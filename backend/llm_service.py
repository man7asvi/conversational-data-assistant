# backend/llm_service.py
"""
LLM Service — generates SQL queries from natural language using Groq.

KEY CHANGE FROM THE HARDCODED VERSION:
Previously, the system prompt was a giant string literal with the Northwind
schema baked in. Now it's built dynamically by build_system_prompt(), which
takes the schema string from SchemaInspector.

The prompt still has the same structure:
  1. Role definition
  2. Schema (now dynamic)
  3. Rules (generic — not database-specific)
  4. Response format
  5. Few-shot examples (generic patterns, not Northwind-specific)

The model sees the same format. It doesn't know or care that the schema
was generated from information_schema rather than typed by hand.
"""

import json
import os
import re
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


# ─── Dynamic system prompt builder ───────────────────────────────────────────
#
# This replaces the old hardcoded SYSTEM_PROMPT.
#
# WHY A FUNCTION INSTEAD OF A STRING?
# Because the schema changes depending on which database is connected.
# The rules stay the same, but the schema block is injected at runtime.
#
# The function is called ONCE at app startup (in main.py) and the result
# is cached. It's not called on every request — that would be wasteful.
#
# The few-shot examples are deliberately generic. They show the JSON format
# and demonstrate common SQL patterns (aggregation, filtering, joins, GROUP BY)
# without referencing specific table or column names. The model learns the
# PATTERN from examples and applies it to whatever schema it sees.
#
# 📖 Read: "Schema-aware prompting" is a technique used by tools like
#    Defog, SQLCoder, and Vanna.ai. The key insight is that the schema IS
#    the main context — examples are secondary.
#    https://defog.ai/blog/open-sourcing-sqlcoder/

def build_system_prompt(schema_str: str, table_names: list) -> str:
    """
    Build the system prompt dynamically from an introspected schema.

    Args:
        schema_str:   The prompt-ready schema string from SchemaInspector.
                      e.g. "customers: customer_id (varchar PK), company_name (varchar)..."
        table_names:  List of all table names (used in the out-of-scope message).

    Returns:
        Complete system prompt string ready to send to the LLM.
    """
    # Format table names for the out-of-scope message
    tables_list = ", ".join(table_names)

    return f"""You are an expert PostgreSQL query generator.
You have access to a database with the schema described below.
You MUST return ONLY a valid JSON object. No explanation. No markdown. No prose.

=== DATABASE SCHEMA ===

{schema_str}

=== RULES ===

1. Only generate SELECT queries. Never INSERT, UPDATE, DELETE, DROP, ALTER.
2. Use %s placeholders for ALL literal values in WHERE clauses. Put those values in params[].
3. GROUP BY must include every non-aggregated column in SELECT — this is a hard PostgreSQL rule.
4. Always ROUND computed numeric values: ROUND(value::numeric, 2)
5. Always alias computed columns (e.g. COUNT(*) as total_count, SUM(x) as total_x).
6. Use short table aliases (first letter or abbreviation) consistently.
7. Default to LIMIT 20 unless the user asks for a specific number.
8. When the user refers to "them", "their", "those" etc., use values from the
   PREVIOUS RESULTS provided in context — put them as params in an IN (%s, %s, ...) clause.
9. NEVER add filters the user did not explicitly ask for. Only filter on what was actually asked.
10. Boolean-like columns stored as smallint (0/1) should be compared to 0 or 1, never true/false.
11. If the user's question cannot be answered from the available database — for example
    questions about weather, news, celebrities, or general knowledge — do NOT generate SQL.
    Instead return: {{"sql": null, "params": [], "out_of_scope": true, "message": "I can only answer questions about the data in this database ({tables_list})."}}
12. Study the schema carefully. Use the correct column names, data types, and foreign key
    relationships shown above. Do not guess column names that are not in the schema.
13. For monetary/revenue calculations, look for columns with price, amount, cost, or value
    in their names. If there's a quantity and unit_price, revenue = SUM(unit_price * quantity).
14. For vague exploration questions like "show me something interesting", "what insights can
    you give me", or "how is business doing" — generate a useful summary query based on the
    schema. Pick the most meaningful aggregation you can find (revenue, counts, averages).
    These are valid data questions, NOT out-of-scope.

=== RESPONSE FORMAT ===

{{"sql": "SELECT ...", "params": []}}

=== EXAMPLES ===

These examples show the expected JSON format and common SQL patterns.
Apply these patterns to whatever tables exist in the schema above.

User: show all records from the first table
{{"sql": "SELECT * FROM <table_name> LIMIT 20", "params": []}}

User: how many records are in [table]
{{"sql": "SELECT COUNT(*) as total_count FROM <table_name>", "params": []}}

User: show the top 5 [items] by [metric]
{{"sql": "SELECT name_col, SUM(value_col) as total FROM table1 t1 JOIN table2 t2 ON t1.id = t2.fk_id GROUP BY name_col ORDER BY total DESC LIMIT 5", "params": []}}

User: show [items] where [column] = [value]
{{"sql": "SELECT col1, col2 FROM table WHERE col = %s LIMIT 20", "params": ["value"]}}

User: which [items] have never been [linked to another table]
{{"sql": "SELECT t1.col1, t1.col2 FROM table1 t1 LEFT JOIN table2 t2 ON t1.id = t2.fk_id WHERE t2.fk_id IS NULL LIMIT 20", "params": []}}

User: compare [A] and [B]
{{"sql": "SELECT group_col, SUM(value_col) as total FROM table WHERE group_col IN (%s, %s) GROUP BY group_col ORDER BY total DESC", "params": ["A", "B"]}}

User: what is the weather today
{{"sql": null, "params": [], "out_of_scope": true, "message": "I can only answer questions about the data in this database ({tables_list})."}}
"""


# ─── Module-level prompt cache ────────────────────────────────────────────────
# Initialized once by main.py at startup via init_prompt()
_system_prompt: str = ""
_table_names: list = []


def init_prompt(schema_str: str, table_names: list):
    """
    Called once at app startup (from main.py) to set the system prompt.
    
    This caches the prompt so it's not rebuilt on every request.
    Think of it as the LLM's "job description" being written once
    and posted on the wall — everyone reads the same one.
    """
    global _system_prompt, _table_names
    _system_prompt = build_system_prompt(schema_str, table_names)
    _table_names = table_names
    print(f"✅ System prompt built: {len(_system_prompt)} chars, {len(table_names)} tables")


def get_system_prompt() -> str:
    """Get the cached system prompt."""
    if not _system_prompt:
        raise RuntimeError(
            "System prompt not initialized. Call init_prompt() at startup. "
            "This usually means SchemaInspector didn't run."
        )
    return _system_prompt


# ─── Context builder ──────────────────────────────────────────────────────────
#
# Unchanged from the previous version. This is database-agnostic — it doesn't
# care what tables exist, it just formats conversation history cleanly.

def _extract_key_values(result_json_str: str, max_values: int = 10) -> list:
    """
    Pull out the most likely 'identifier' values from a stored result blob.
    Prefers columns named *_id, falls back to first column.
    """
    try:
        data = json.loads(result_json_str)
        if not data or not isinstance(data, list):
            return []

        first_row = data[0]
        keys = list(first_row.keys())

        id_col = next((k for k in keys if k.endswith("_id")), None)
        target_col = id_col or keys[0]

        values = [row[target_col] for row in data[:max_values] if target_col in row]
        return values
    except Exception:
        return []


def _build_conversation_history(conversation_state) -> list:
    """
    Convert stored conversation messages into clean LLM message format.
    Returns user/assistant pairs with SQL JSON (not result blobs).
    """
    if not conversation_state or not conversation_state.messages:
        return []

    recent = conversation_state.get_last_n_messages(6)

    history = []
    previous_result_values = []

    for i, msg in enumerate(recent):
        if msg.role == "user":
            content = msg.content

            if previous_result_values:
                values_str = ", ".join(str(v) for v in previous_result_values)
                content += f"\n[CONTEXT: Previous result contained these values: {values_str}]"
                previous_result_values = []

            history.append({"role": "user", "content": content})

        elif msg.role == "assistant":
            if msg.sql_generated:
                history.append({
                    "role": "assistant",
                    "content": json.dumps({"sql": msg.sql_generated, "params": msg.params_used or []})
                })
                previous_result_values = _extract_key_values(msg.content)
            else:
                pass  # Skip error turns

    return history


# ─── Main entry point ─────────────────────────────────────────────────────────

def extract_sql_query(user_text: str, conversation_state=None):
    """
    Generate a SQL query from the user's plain-English question.
    Uses the cached system prompt (which contains the dynamic schema).
    """
    system_prompt = get_system_prompt()
    messages = [{"role": "system", "content": system_prompt}]

    # Inject cleaned conversation history
    history = _build_conversation_history(conversation_state)
    messages.extend(history)

    # Current user question
    messages.append({"role": "user", "content": user_text})

    # Debug logging
    print(f"\n{'='*60}")
    print(f"📤 SENDING TO LLM — {len(messages)} messages")
    for m in messages:
        preview = m['content'][:120].replace('\n', ' ')
        print(f"  [{m['role']}] {preview}...")
    print(f"{'='*60}\n")

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        temperature=0,
        max_tokens=512,
    )

    raw_output = response.choices[0].message.content.strip()
    print(f"🤖 LLM output: {raw_output}")

    # Strip markdown fences
    if raw_output.startswith("```"):
        raw_output = re.sub(r"^```[a-z]*\n?", "", raw_output)
        raw_output = re.sub(r"\n?```$", "", raw_output)
        raw_output = raw_output.strip()

    try:
        result = json.loads(raw_output)
        result.setdefault("params", [])
        result.setdefault("sql", "")
        return result
    except json.JSONDecodeError:
        print(f"❌ JSON parse failed: {raw_output}")
        return {"sql": None, "params": [], "parse_error": raw_output}


# ─── Retry: fix broken SQL ────────────────────────────────────────────────────

def fix_sql_with_error(user_text: str, bad_sql: str, bad_params: list, db_error: str) -> dict:
    """
    Ask the LLM to fix a SQL query that PostgreSQL rejected.
    Uses the same system prompt so the model has the schema context.
    """
    system_prompt = get_system_prompt()
    clean_error = " ".join(db_error.strip().splitlines())

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": json.dumps({"sql": bad_sql, "params": bad_params})},
        {
            "role": "user",
            "content": (
                f"That SQL failed with this PostgreSQL error:\n"
                f"{clean_error}\n\n"
                f"Fix the SQL to resolve this error. "
                f"Return corrected JSON only: {{\"sql\": \"...\", \"params\": [...]}}"
            )
        }
    ]

    print(f"\n{'='*60}")
    print(f"🔄 RETRY — sending error back to LLM for self-correction")
    print(f"   Error: {clean_error[:120]}")
    print(f"{'='*60}\n")

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0,
            max_tokens=512,
        )

        raw_output = response.choices[0].message.content.strip()
        print(f"🔄 Retry LLM output: {raw_output}")

        if raw_output.startswith("```"):
            raw_output = re.sub(r"^```[a-z]*\n?", "", raw_output)
            raw_output = re.sub(r"\n?```$", "", raw_output)
            raw_output = raw_output.strip()

        result = json.loads(raw_output)
        result.setdefault("params", [])
        result.setdefault("sql", "")
        print(f"✅ Retry produced fixed SQL: {result['sql'][:100]}")
        return result

    except Exception as e:
        print(f"❌ Retry also failed: {e}")
        return {"sql": None, "params": []}


# ─── Conversation title generator ─────────────────────────────────────────────

def generate_conversation_title(first_message: str) -> str:
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": "Generate a short 3-5 word title for this data query conversation. Return ONLY the title, no quotes, no punctuation, no explanation."
            },
            {"role": "user", "content": first_message}
        ],
        temperature=0
    )
    return response.choices[0].message.content.strip()