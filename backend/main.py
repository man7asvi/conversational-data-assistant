from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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

@app.post("/chat")
def chat(message:Message):
    return {"reply":f"You said:{message.text}"}

