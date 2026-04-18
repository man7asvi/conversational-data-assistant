# backend/llm_service.py
import json
import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def build_prompt(user_text: str) -> str:
    return f"""
You are a SQL generation assistant for the Northwind database.

You MUST return ONLY valid JSON.
No explanation. No markdown.

Database schema (PostgreSQL):

Table: customers
- customer_id (varchar) PRIMARY KEY
- company_name (varchar)
- contact_name (varchar)
- contact_title (varchar)
- city (varchar)
- country (varchar)

Table: orders
- order_id (integer) PRIMARY KEY
- customer_id (varchar) FK -> customers
- employee_id (integer) FK -> employees
- order_date (date)
- shipped_date (date)
- ship_country (varchar)
- ship_city (varchar)
- freight (real)

Table: order_details
- order_id (integer) FK -> orders
- product_id (integer) FK -> products
- unit_price (real)
- quantity (smallint)
- discount (real)

Table: products
- product_id (integer) PRIMARY KEY
- product_name (varchar)
- supplier_id (integer) FK -> suppliers
- category_id (integer) FK -> categories
- unit_price (real)
- units_in_stock (smallint)
- discontinued (boolean)

Table: employees
- employee_id (integer) PRIMARY KEY
- first_name (varchar)
- last_name (varchar)
- title (varchar)
- city (varchar)
- country (varchar)

Table: categories
- category_id (integer) PRIMARY KEY
- category_name (varchar)
- description (text)

Table: suppliers
- supplier_id (integer) PRIMARY KEY
- company_name (varchar)
- country (varchar)
- city (varchar)

Table: shippers
- shipper_id (integer) PRIMARY KEY
- company_name (varchar)

Rules:
- Only generate SELECT queries
- NEVER generate INSERT, UPDATE, DELETE, DROP
- Use %s placeholders for parameters
- Always return params as a list
- For revenue calculations use: SUM(od.unit_price * od.quantity * (1 - od.discount))
- Always alias calculated columns

Format:
{{
  "sql": "SELECT ...",
  "params": []
}}

Examples:

User: show top 5 customers by total orders
Response:
{{
  "sql": "SELECT c.company_name, COUNT(o.order_id) as total_orders FROM customers c JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.company_name ORDER BY total_orders DESC LIMIT 5",
  "params": []
}}

User: show products low in stock
Response:
{{
  "sql": "SELECT product_name, units_in_stock, unit_price FROM products WHERE units_in_stock < %s ORDER BY units_in_stock ASC LIMIT 20",
  "params": [10]
}}

User: revenue by country
Response:
{{
  "sql": "SELECT o.ship_country, ROUND(SUM(od.unit_price * od.quantity * (1 - od.discount))::numeric, 2) as revenue FROM orders o JOIN order_details od ON o.order_id = od.order_id GROUP BY o.ship_country ORDER BY revenue DESC LIMIT 20",
  "params": []
}}

User:
{user_text}
"""

def extract_sql_query(user_text: str, conversation_state=None):
    """Generate SQL query from user text."""
    prompt = build_prompt(user_text)

    messages = [{"role": "system", "content": "Return only JSON"}]
    
    # Build context from conversation state if provided
    if conversation_state:
        context_block = _build_context_block(conversation_state)
        if context_block:
            print(f"\n{'='*60}")
            print(f"📋 CONTEXT BEING SENT TO LLM:")
            print(f"{'='*60}")
            print(context_block)
            print(f"{'='*60}\n")
            messages.append({"role": "system", "content": context_block})
    
    # Add last 3-4 messages from conversation for context
    if conversation_state and conversation_state.messages:
        print(f"📜 CONVERSATION HISTORY ({len(conversation_state.messages)} messages total):")
        for msg in conversation_state.get_last_n_messages(4):
            print(f"   {msg.role}: {msg.content[:100]}...")
        for msg in conversation_state.get_last_n_messages(4):
            messages.append({"role": msg.role, "content": msg.content})
    
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
            "sql": "SELECT * FROM products LIMIT 10",
            "params": []
        }


def _build_context_block(conversation_state) -> str:
    """
    Build a system context block from conversation state.
    Includes last SQL, tables used, and PREVIOUS RESULTS for context.
    """
    lines = ["--- CONVERSATION CONTEXT ---"]
    
    if conversation_state.last_sql_generated:
        lines.append(f"Last SQL generated: {conversation_state.last_sql_generated}")
    
    if conversation_state.tables_used:
        lines.append(f"Tables referenced so far: {', '.join(conversation_state.tables_used)}")
    
    # Add previous messages with ACTUAL RESULTS for better context
    if conversation_state.messages:
        lines.append("\n--- CONVERSATION HISTORY WITH RESULTS ---")
        for msg in conversation_state.get_last_n_messages(3):
            if msg.role == "user":
                lines.append(f"\nUser asked: {msg.content}")
            else:
                # Show what the assistant replied with
                if msg.sql_generated:
                    lines.append(f"Assistant generated SQL: {msg.sql_generated[:150]}...")
                    # Include the summary which hints at results
                    lines.append(f"Result summary: {msg.content}")
    
    if conversation_state.filters_applied:
        lines.append(f"\nFilters applied: {', '.join(conversation_state.filters_applied)}")
    
    lines.append("\n--- END CONTEXT ---")
    lines.append("\nIMPORTANT: When user refers to 'their', 'those', 'them', build queries that reference entities from previous results using IN (...) or subqueries.")
    
    return "\n".join(lines) if len(lines) > 2 else ""