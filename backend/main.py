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

try:
    from nlu import parse
except ImportError:
    parse = None

try:
    from validator import validate_sql, SQLValidationError
except ImportError:
    validate_sql = None
    SQLValidationError = None

from llm_service import extract_sql_query
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
    conversations = session_store.list_conversations(database_name)
    return [
        {
            "conversation_id": str(c.conversation_id),
            "title": c.title,
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat(),
            "message_count": len(c.messages),
        }
        for c in conversations
    ]


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

        if not sql:
            session_store.save_message(conversation_id, "user", text)
            session_store.save_message(conversation_id, "assistant", "Could not generate SQL.")
            return {
                "reply": "Could not generate SQL.",
                "type": "text"
            }

        # FIX: Replace single %s with correct number of placeholders for IN clauses
        param_count = len(params)
        if param_count > 0:
            in_pattern = r'IN \(%s\)'
            if re.search(in_pattern, sql):
                placeholders = ', '.join(['%s'] * param_count)
                sql = re.sub(in_pattern, f'IN ({placeholders})', sql)

        safe_sql = validate_sql(
            sql,
            allowed_tables=["customers", "orders", "order_details", "products", 
                            "employees", "categories", "suppliers", "shippers",
                            "territories", "region", "us_states"],
            require_limit=True
        )

        result = query_db(safe_sql, params, database_name)
        print(f"Database result: {result}")

        # Save conversation: user message, SQL, and result summary
        session_store.save_message(
            conversation_id, 
            "user", 
            text
        )
        result_summary = f"Returned {len(result)} rows with data: {json.dumps(result[:3], default=str)}" if result else "Returned 0 rows"
        session_store.save_message(
            conversation_id, 
            "assistant",
            result_summary,
            sql_generated=safe_sql,
            params_used=list(params)
        )

        return {
            "reply": result,
            "type": "table",
            "sql": safe_sql,
            "params": list(params)
        }

    except SQLValidationError as e:
        session_store.save_message(conversation_id, "user", text)
        session_store.save_message(conversation_id, "assistant", f"Query blocked: {str(e)}")
        return {
            "reply": f"Query blocked: {str(e)}",
            "type": "text"
        }

    except Exception as e:
        print("Error:", e)
        session_store.save_message(conversation_id, "user", text)
        session_store.save_message(conversation_id, "assistant", f"Something went wrong: {str(e)}")
        return {
            "reply": f"Something went wrong: {str(e)}",
            "type": "text"
        }