from typing import Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from uuid import UUID
import re
import json


#python3 -m uvicorn main:app --reload
try:
    from nlu import parse
except ImportError:
    parse = None

try:
    from validator import validate_sql, SQLValidationError
except ImportError:
    validate_sql = None
    SQLValidationError = None

from llm_service import extract_sql_query, fix_sql_with_error, generate_conversation_title
from models import ConversationState
from db_manager import DatabaseManager, get_storage_db_config
from postgres_session_store import PostgresSessionStore

# ============================================================================
# Initialize FastAPI and Session Store
# ============================================================================
app = FastAPI()

# Initialize the PostgreSQL session store for conversation persistence
storage_db_config = get_storage_db_config()
session_store = PostgresSessionStore(storage_db_config)

# Initialize database manager for multi-database support
db_manager = DatabaseManager(storage_db_config)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check endpoint
@app.get("/health")
def health():
    """Check if backend is alive."""
    return {
        "status": "ok",
        "session_store_type": type(session_store).__name__,
        "databases_loaded": len(db_manager.list_databases()),
    }

# Request models
class ChatRequest(BaseModel):
    conversation_id: str  # UUID as string
    text: str
    database_name: Optional[str] = "northwind"  # Default to northwind

class CreateConversationRequest(BaseModel):
    title: str = "New Conversation"
    database_name: str = "northwind"


def query_db(query: str, params: tuple = (), database_name: str = "northwind"):
    """Execute query against a specific database."""
    db_config = db_manager.get_database(database_name)
    if not db_config:
        raise ValueError(f"Database '{database_name}' not found")
    
    conn = psycopg2.connect(**db_config.get_connection_string())
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ============================================================================
# DATABASE MANAGEMENT ENDPOINTS
# ============================================================================

@app.get("/databases")
def list_databases():
    """List all available databases."""
    databases = db_manager.list_databases()
    return {"databases": databases}


@app.get("/databases/{name}/test")
def test_database_connection(name: str):
    """Test connection to a database."""
    success = db_manager.test_connection(name)
    return {
        "database": name,
        "connected": success
    }


# ============================================================================
# CONVERSATION MANAGEMENT ENDPOINTS
# ============================================================================

@app.post("/conversations")
def create_conversation(request: CreateConversationRequest):
    """Create a new conversation."""
    state = session_store.create_conversation(
        request.title, 
        request.database_name
    )
    return {
        "conversation_id": str(state.conversation_id),
        "title": state.title,
        "database_name": request.database_name,
        "created_at": state.created_at.isoformat(),
    }


@app.get("/conversations")
def list_conversations(database_name: Optional[str] = None):
    """List all conversations, optionally filtered by database."""
    try:
        storage_db_config = get_storage_db_config()
        conn = psycopg2.connect(**storage_db_config.get_connection_string())
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        if database_name:
            cursor.execute(
                """
                SELECT c.id, c.title, c.created_at, c.updated_at, c.database_name, COUNT(m.id) as message_count
                FROM conversations c
                LEFT JOIN messages m ON c.id = m.conversation_id
                WHERE c.database_name = %s
                GROUP BY c.id, c.title, c.created_at, c.updated_at, c.database_name
                ORDER BY c.updated_at DESC
                """,
                (database_name,)
            )
        else:
            cursor.execute(
                """
                SELECT c.id, c.title, c.created_at, c.updated_at, c.database_name, COUNT(m.id) as message_count
                FROM conversations c
                LEFT JOIN messages m ON c.id = m.conversation_id
                GROUP BY c.id, c.title, c.created_at, c.updated_at, c.database_name
                ORDER BY c.updated_at DESC
                """
            )
        
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        
        return [
            {
                "conversation_id": str(row["id"]),
                "title": row["title"],
                "created_at": row["created_at"].isoformat(),
                "updated_at": row["updated_at"].isoformat(),
                "message_count": row["message_count"],
            }
            for row in rows
        ]
    except Exception as e:
        print(f"❌ Error listing conversations: {e}")
        return []


@app.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str):
    """Retrieve a full conversation by ID."""
    try:
        cid = UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation_id format")
    
    state = session_store.get_conversation(cid)
    if not state:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    return state.to_dict()


@app.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str):
    """Delete a conversation."""
    try:
        cid = UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation_id format")
    
    success = session_store.delete_conversation(cid)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    return {"status": "deleted", "conversation_id": conversation_id}


# ============================================================================
# CHAT ENDPOINT
# ============================================================================

@app.post("/chat")
def chat(request: ChatRequest):
    """
    Chat endpoint. Backend owns all conversation state.
    Frontend sends: conversation_id + text (no history)
    """
    try:
        conversation_id = UUID(request.conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation_id format")
    
    text = request.text.strip()
    database_name = request.database_name or "northwind"
    
    # Retrieve conversation state
    state = session_store.get_conversation(conversation_id)
    if not state:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    print(f"Chat in conversation {conversation_id}: '{text}' (database: {database_name})")

    dangerous_words = ["delete", "drop", "remove", "truncate", "update", "insert"]

    if any(word in text.lower() for word in dangerous_words):
        # Save user message and error response
        session_store.save_message(conversation_id, "user", text)
        session_store.save_message(conversation_id, "assistant", "This operation is not allowed.")
        return {
            "reply": "This operation is not allowed.",
            "type": "text"
        }

    try:
        # Extract SQL using conversation state for rich context
        llm_output = extract_sql_query(text, state)
        print("LLM output:", llm_output)

        sql = llm_output.get("sql")
        params = tuple(llm_output.get("params", []))
        safe_sql = None  # will be set after validation — retry handler needs this in scope

        if not sql:
            # Check if the model explicitly flagged this as out of scope
            if llm_output.get("out_of_scope"):
                reply = llm_output.get(
                    "message",
                    "I can only answer questions about the Northwind database (customers, orders, products, employees, suppliers)."
                )
            else:
                # LLM returned bad JSON or couldn't understand the question
                parse_err = llm_output.get("parse_error", "")
                reply = "I couldn't understand that question well enough to generate a query. Could you rephrase it?"
                if parse_err:
                    print(f"LLM parse error detail: {parse_err}")
            session_store.save_message(conversation_id, "user", text)
            session_store.save_message(conversation_id, "assistant", reply)
            return {"reply": reply, "type": "text"}

        # Fix IN clause placeholders.
        # The LLM generates IN (%s, %s, %s) with the right count now,
        # but as a safety net we also handle the single-placeholder case.
        in_pattern = r'IN\s*\(%s\)'
        if re.search(in_pattern, sql, re.IGNORECASE):
            param_count = len(params)
            if param_count > 1:
                placeholders = ', '.join(['%s'] * param_count)
                sql = re.sub(in_pattern, f'IN ({placeholders})', sql, flags=re.IGNORECASE)

        safe_sql = validate_sql(
            sql,
            allowed_tables=["customers", "orders", "order_details", "products", 
                            "employees", "categories", "suppliers", "shippers",
                            "territories", "region", "us_states"],
            require_limit=True
        )

        result = query_db(safe_sql, params, database_name)
        print(f"Database result: {len(result)} rows")

        # Save conversation: user message, then assistant message with actual result data
        session_store.save_message(
            conversation_id,
            "user",
            text
        )

        # Store actual result data as JSON (complete snapshot for conversation history)
        result_json = json.dumps(result, default=str) if result else "[]"
        session_store.save_message(
            conversation_id,
            "assistant",
            result_json,
            sql_generated=safe_sql,
            params_used=list(params)
        )

         # ── Auto-title on first message ───────────────────────────────────
        # state.messages was loaded BEFORE we saved this turn, so if it was
        # empty then this is the first ever message in the conversation.
        # We generate a short title and update the DB immediately.
        new_title = None
        if len(state.messages) == 0:
            try:
                new_title = generate_conversation_title(text)
                session_store.update_conversation_title(conversation_id, new_title)
                print(f"✅ Auto-title set: '{new_title}'")
            except Exception as title_err:
                print(f"⚠️  Title generation failed (non-fatal): {title_err}")

        # When the query ran fine but returned nothing, tell the user clearly.
        # "type: empty" lets the frontend show the SQL (so the user can see what
        # ran) alongside a human-readable explanation instead of just blank space.
        if not result:
            return {
                "reply": "The query ran successfully but returned no results. The data matching your question may not exist in the database.",
                "type": "empty",
                "sql": safe_sql,
                "params": list(params),
                "title": new_title      # ← add this
            }

        return {
            "reply": result,
            "type": "table",
            "sql": safe_sql,
            "params": list(params),
            "title": new_title          # ← add this
        }

    except SQLValidationError as e:
        msg = f"Query blocked: {str(e)}"
        session_store.save_message(conversation_id, "user", text)
        session_store.save_message(conversation_id, "assistant", msg)
        return {"reply": msg, "type": "error"}

    except Exception as e:
        # ── Retry loop ────────────────────────────────────────────────────────
        # The database rejected the SQL. Before giving up, send the error back
        # to the LLM and ask it to fix the query. We only attempt this once —
        # if the retry also fails, we show the original error to the user.
        #
        # We only retry on actual DB execution errors — not on validation errors
        # (those are caught above) and not when sql was None (LLM parse failure,
        # caught earlier). By the time we reach here, we always have a real sql
        # string that made it past the validator but failed in Postgres.
        raw_error = str(e).strip()
        print(f"⚠️  DB error, attempting retry: {raw_error[:100]}")

        # Only retry if we actually got past validation — if safe_sql is still
        # None it means the error happened before the DB call (e.g. in validate_sql
        # itself), and we should just surface it directly.
        if not safe_sql:
            msg = f"Something went wrong: {raw_error}"
            session_store.save_message(conversation_id, "user", text)
            session_store.save_message(conversation_id, "assistant", msg)
            return {"reply": msg, "type": "error"}

        try:
            # Ask the LLM to self-correct
            retry_output = fix_sql_with_error(
                user_text=text,
                bad_sql=safe_sql,   # the validated SQL that postgres rejected
                bad_params=list(params),
                db_error=raw_error
            )

            retry_sql = retry_output.get("sql")
            retry_params = tuple(retry_output.get("params", []))

            if not retry_sql:
                raise ValueError("Retry returned no SQL")

            # Validate the fixed SQL through the same security layer
            safe_retry_sql = validate_sql(
                retry_sql,
                allowed_tables=["customers", "orders", "order_details", "products",
                                "employees", "categories", "suppliers", "shippers",
                                "territories", "region", "us_states"],
                require_limit=True
            )

            # Execute the fixed query
            result = query_db(safe_retry_sql, retry_params, database_name)
            print(f"✅ Retry succeeded: {len(result)} rows")

            result_json = json.dumps(result, default=str) if result else "[]"
            session_store.save_message(conversation_id, "user", text)
            session_store.save_message(
                conversation_id,
                "assistant",
                result_json,
                sql_generated=safe_retry_sql,
                params_used=list(retry_params)
            )

            if not result:
                return {
                    "reply": "The query ran successfully but returned no results. The data matching your question may not exist in the database.",
                    "type": "empty",
                    "sql": safe_retry_sql,
                    "params": list(retry_params)
                }

            return {
                "reply": result,
                "type": "table",
                "sql": safe_retry_sql,
                "params": list(retry_params)
            }

        except Exception as retry_e:
            # Retry also failed — now we give up and show the original error.
            # We show the ORIGINAL error (not the retry error) because it's
            # more meaningful to the user and useful for debugging.
            msg = f"Something went wrong: {raw_error}"
            print(f"❌ Retry also failed: {str(retry_e)}")
            session_store.save_message(conversation_id, "user", text)
            session_store.save_message(conversation_id, "assistant", msg)
            return {"reply": msg, "type": "error"}