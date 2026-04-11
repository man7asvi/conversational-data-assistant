from typing import Optional, List
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
import os
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
        llm_output = extract_sql_query(text)
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
        allowed_tables=["customers", "orders", "order_details", "products", 
                        "employees", "categories", "suppliers", "shippers",
                        "territories", "region", "us_states"],
        require_limit=True
        )

        result = query_db(safe_sql, params)
        print(f"Database result: {result}")

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