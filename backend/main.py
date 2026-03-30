from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3

# python3 -m uvicorn main:app --reload
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage for todos
todos = []

class Message(BaseModel):
    text:str

def query_db(query:str, params:tuple=()):
    conn=sqlite3.connect("sales.db")
    conn.row_factory=sqlite3.Row
    cursor=conn.cursor()
    cursor.execute(query,params)
    rows=cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.post("/chat")
def chat(message:Message):
    text=message.text.lower()
    print(f"Received: '{text}'")

    if "all sales" in text:
        result =  query_db("SELECT * FROM sales LIMIT 10")
        return {"reply":result, "type":"table"}
    
    if "new york" in text or "ny" in text:
        result = query_db("SELECT * FROM sales WHERE region = ?", ("NY",))
        return {"reply":result, "type":"table"}
    
    if "total" in text:
        results = query_db("SELECT region, SUM(amount) as total FROM sales GROUP BY region")
        return {"reply": results, "type": "table"}

    return {"reply": "I can answer: 'show all sales', 'show NY sales', 'show totals'", "type": "text"}

