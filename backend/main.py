from typing import Optional, List
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
from nlu import parse
from validator import validate_sql, SQLValidationError
from llm_service import extract_sql_query


# python3 -m uvicorn main:app --reload
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class ConversationMessage(BaseModel):
    role: str
    content: str

class Message(BaseModel):
    text:str
    history: Optional[List[ConversationMessage]] = []


def query_db(query:str, params:tuple=()):
    conn=sqlite3.connect("sales.db")
    conn.row_factory=sqlite3.Row
    cursor=conn.cursor()
    cursor.execute(query,params)
    rows=cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.post("/chat")
def chat(message: Message):
    text = message.text.strip()
    history= [m.dict() for m in message.history]
    print(f"Received: '{text}'")

    dangerous_words = ["delete", "drop", "remove", "truncate", "update", "insert"]

    if any(word in text.lower() for word in dangerous_words):
        return {
            "reply": "This operation is not allowed.",
            "type": "text"
        }

    try:
        llm_output = extract_sql_query(text, history)
        print("LLM output:", llm_output)

        sql = llm_output.get("sql")
        params = tuple(llm_output.get("params", []))

        if not sql:
            return {
                "reply": "Could not generate SQL.",
                "type": "text"
            }

        safe_sql = validate_sql(
            sql,
            allowed_tables=["sales"],
            require_limit=True
        )

        result = query_db(safe_sql, params)

        return {
            "reply": result,
            "type": "table",
            "sql": safe_sql,
            "params": params
        }

    except SQLValidationError as e:
        return {
            "reply": f"Query blocked: {str(e)}",
            "type": "text"
        }

    except Exception as e:
        print("Error:", e)
        return {
            "reply": f"Something went wrong: {str(e)}",
            "type": "text"
        }