from typing import Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from uuid import UUID
import re

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
from session_store import InMemorySessionStore


# python3 -m uvicorn main:app --reload
app = FastAPI()

# Initialize the session store (in-memory for now, swap for PostgresSessionStore later)
session_store = InMemorySessionStore()

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
    }

# Request models
class ChatRequest(BaseModel):
    conversation_id: str  # UUID as string
    text: str

class CreateConversationRequest(BaseModel):
    title: str = "New Conversation"


def query_db(query: str, params: tuple = ()):
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        options=f"-c search_path={os.getenv('DB_SCHEMA')}"
    )
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ============= CONVERSATION MANAGEMENT ENDPOINTS =============

@app.post("/conversations")
def create_conversation(request: CreateConversationRequest):
    """Create a new conversation."""
    state = session_store.create_conversation(request.title)
    return {
        "conversation_id": str(state.conversation_id),
        "title": state.title,
        "created_at": state.created_at.isoformat(),
    }


@app.get("/conversations")
def list_conversations():
    """List all conversations (for sidebar)."""
    conversations = session_store.list_conversations()
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

@app.post("/chat")
def chat(request: ChatRequest):
    """Chat endpoint. Backend owns all conversation state."""
    try:
        conversation_id = UUID(request.conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation_id format")
    
    text = request.text.strip()
    
    state = session_store.get_conversation(conversation_id)
    if not state:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    print(f"Chat in conversation {conversation_id}: '{text}'")

    dangerous_words = ["delete", "drop", "remove", "truncate", "update", "insert"]

    if any(word in text.lower() for word in dangerous_words):
        session_store.save_message(conversation_id, "user", text)
        session_store.save_message(conversation_id, "assistant", "This operation is not allowed.")
        return {"reply": "This operation is not allowed.", "type": "text"}

    try:
        llm_output = extract_sql_query(text, state)
        print("LLM output:", llm_output)

        sql = llm_output.get("sql")
        params = tuple(llm_output.get("params", []))

        if not sql:
            session_store.save_message(conversation_id, "user", text)
            session_store.save_message(conversation_id, "assistant", "Could not generate SQL.")
            return {"reply": "Could not generate SQL.", "type": "text"}

        # FIX: Replace single %s with correct number of placeholders for IN clauses
        param_count = len(params)
        if param_count > 0:
            # Replace IN (%s) with IN (%s, %s, ...) for lists
            import re
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

        result = query_db(safe_sql, params)
        print(f"Database result: {result}")

        session_store.save_message(conversation_id, "user", text)
        session_store.save_message(
            conversation_id, 
            "assistant",
            f"Returned {len(result)} rows",
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
        return {"reply": f"Query blocked: {str(e)}", "type": "text"}

    except Exception as e:
        print("Error:", e)
        session_store.save_message(conversation_id, "user", text)
        session_store.save_message(conversation_id, "assistant", f"Something went wrong: {str(e)}")
        return {"reply": f"Something went wrong: {str(e)}", "type": "text"}