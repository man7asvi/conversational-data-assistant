# backend/llm_service.py
import json
import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def build_prompt(user_text: str) -> str:
    return f"""
You are a SQL generation assistant.

You MUST return ONLY valid JSON.
No explanation. No markdown.

Database schema:
Table: sales
Columns:
- id (integer)
- date (text, format YYYY-MM-DD)
- region (NY, LA, CH)
- product (Laptop, Phone, Tablet)
- amount (number)

Rules:
- Only generate SELECT queries
- NEVER generate INSERT, UPDATE, DELETE, DROP
- Use ? placeholders for parameters
- Always return params as a list

Format:
{{
  "sql": "SELECT ...",
  "params": []
}}

Examples:

User: show sales in ny
Response:
{{
  "sql": "SELECT * FROM sales WHERE region = ? LIMIT 10",
  "params": ["NY"]
}}

User: show total sales in march
Response:
{{
  "sql": "SELECT SUM(amount) FROM sales WHERE date LIKE ?",
  "params": ["2026-03-%"]
}}

User:
{user_text}
"""

def extract_sql_query(user_text: str, history: list = []):
    prompt = build_prompt(user_text)

    messages=[{"role": "system", "content": "Return only JSON"}]
    for msg in history[-4:]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=messages,
        temperature=0
    )

    raw_output = response.choices[0].message.content.strip()
    print("🤖 LLM SQL output:", raw_output)

    if raw_output.startswith("```"):
        raw_output = raw_output.split("```")[1].strip()

    try:
        return json.loads(raw_output)
    except:
        print("❌ Bad SQL JSON:", raw_output)
        return {
            "sql": "SELECT * FROM sales LIMIT 10",
            "params": []
        }