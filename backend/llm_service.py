# backend/llm_service.py
import json
import os
import re
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ─── System prompt ────────────────────────────────────────────────────────────
#
# This is sent as the very first [system] message on EVERY call.
# Think of it as the LLM's "job description + rulebook + reference manual."
#
# Key design decisions:
#   1. Schema comes first — the model needs to see table/column names before
#      it sees any examples or the user's question.
#   2. Rules are explicit and numbered — LLMs follow numbered lists more
#      reliably than prose paragraphs.
#   3. Examples are in the exact JSON format we expect back — this is called
#      "few-shot prompting." Each example is a mini-demonstration.
#   4. The GROUP BY rule is called out explicitly because it's the single most
#      common SQL mistake small models make.
#
# 📖 Read more on system prompts:
#    https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview
#    (sections: "System prompts", "Be specific", "Use examples")

SYSTEM_PROMPT = """You are a expert PostgreSQL query generator for the Northwind database.
You MUST return ONLY a valid JSON object. No explanation. No markdown. No prose.

=== DATABASE SCHEMA ===

customers:        customer_id (varchar PK), company_name, contact_name, contact_title, city, country
orders:           order_id (int PK), customer_id (FK), employee_id (FK), order_date, shipped_date, ship_city, ship_country, freight
order_details:    order_id (FK), product_id (FK), unit_price, quantity (smallint), discount (real)
products:         product_id (int PK), product_name, supplier_id (FK), category_id (FK), unit_price, units_in_stock (smallint), discontinued (smallint: 0=active 1=discontinued)
employees:        employee_id (int PK), first_name, last_name, title, city, country
categories:       category_id (int PK), category_name, description
suppliers:        supplier_id (int PK), company_name, city, country
shippers:         shipper_id (int PK), company_name

=== RULES ===

1. Only generate SELECT queries. Never INSERT, UPDATE, DELETE, DROP, ALTER.
2. Use %s placeholders for ALL literal values in WHERE clauses. Put those values in params[].
3. GROUP BY must include every non-aggregated column in SELECT — this is a hard PostgreSQL rule.
4. For revenue use: SUM(od.unit_price * od.quantity * (1 - od.discount))
5. Always ROUND revenue/averages: ROUND(value::numeric, 2)
6. Always alias computed columns (e.g. COUNT(*) as total_orders)
7. Use table aliases (c, o, od, p, e) consistently.
8. Default to LIMIT 20 unless the user asks for a specific number.
9. When the user refers to "them", "their", "those", "that customer" etc., use values
   from the PREVIOUS RESULTS provided in context — put them as params in an IN (%s, %s, ...) clause.
10. The discontinued column is a smallint (0 or 1), NEVER compare it to true/false/boolean.
    Always use: discontinued = 0 (active) or discontinued = 1 (discontinued).
11. NEVER add filters the user did not explicitly ask for. If the user asks for "products
    that have never been ordered", do not add WHERE discontinued = 0 unless they said so.
    Only filter on what the user actually asked.
12. If the user's question cannot be answered from the Northwind database — for example
    questions about weather, news, people outside the dataset, or general knowledge —
    do NOT generate a SQL query. Instead return this exact JSON:
    {"sql": null, "params": [], "out_of_scope": true, "message": "I can only answer questions about the Northwind database (customers, orders, products, employees, suppliers)."}


=== RESPONSE FORMAT ===

{"sql": "SELECT ...", "params": []}

=== EXAMPLES ===

User: show top 5 customers by revenue
{"sql": "SELECT c.company_name, ROUND(SUM(od.unit_price * od.quantity * (1 - od.discount))::numeric, 2) as revenue FROM customers c JOIN orders o ON c.customer_id = o.customer_id JOIN order_details od ON o.order_id = od.order_id GROUP BY c.company_name ORDER BY revenue DESC LIMIT 5", "params": []}

User: which products are low in stock
{"sql": "SELECT product_name, units_in_stock, unit_price FROM products WHERE units_in_stock < %s AND discontinued = 0 ORDER BY units_in_stock ASC LIMIT 20", "params": [10]}

User: show me discontinued products
{"sql": "SELECT product_name, unit_price, units_in_stock FROM products WHERE discontinued = 1 ORDER BY product_name LIMIT 20", "params": []}

User: revenue by country
{"sql": "SELECT o.ship_country, ROUND(SUM(od.unit_price * od.quantity * (1 - od.discount))::numeric, 2) as revenue FROM orders o JOIN order_details od ON o.order_id = od.order_id GROUP BY o.ship_country ORDER BY revenue DESC LIMIT 20", "params": []}

User: show me all orders from QUICK-Stop
{"sql": "SELECT o.order_id, o.order_date, o.shipped_date, o.freight, o.ship_country FROM orders o WHERE o.customer_id = %s ORDER BY o.order_date DESC LIMIT 20", "params": ["QUICK"]}

User: what products did Ernst Handel order
{"sql": "SELECT DISTINCT p.product_name, p.unit_price, cat.category_name FROM products p JOIN order_details od ON p.product_id = od.product_id JOIN orders o ON od.order_id = o.order_id JOIN categories cat ON p.category_id = cat.category_id WHERE o.customer_id = %s ORDER BY p.product_name LIMIT 20", "params": ["ERNSH"]}

User: show employees and how many orders they handled
{"sql": "SELECT e.first_name || ' ' || e.last_name as employee_name, e.title, COUNT(o.order_id) as total_orders FROM employees e LEFT JOIN orders o ON e.employee_id = o.employee_id GROUP BY e.employee_id, e.first_name, e.last_name, e.title ORDER BY total_orders DESC", "params": []}

User: what is the weather today
{"sql": null, "params": [], "out_of_scope": true, "message": "I can only answer questions about the Northwind database (customers, orders, products, employees, suppliers)."}

User: who is the CEO of Apple
{"sql": null, "params": [], "out_of_scope": true, "message": "I can only answer questions about the Northwind database (customers, orders, products, employees, suppliers)."}
"""


# ─── Context builder ──────────────────────────────────────────────────────────
#
# This is the key fix. Instead of dumping raw message blobs, we build a clean
# structured summary of what happened in the conversation so far.
#
# The two things the LLM needs from prior turns:
#   1. What the user actually asked (plain English)
#   2. What SQL was generated — NOT the results, just the SQL
#
# For follow-up queries like "show me their orders", we also need to inject
# the actual KEY VALUES from the previous result (e.g. customer IDs).
# That way the model can write: WHERE customer_id IN (%s, %s) with real params.
#
# Why not send the full result? Two reasons:
#   - A 50-row result is ~2000 tokens. At 4 turns that's 8000 tokens of noise.
#   - The model doesn't need the data, it needs the identifiers (IDs / names).
#
# 📖 Read: "Context window management" and "Conversation history"
#    https://platform.openai.com/docs/guides/conversation-state
#    Also a great practical post on prompt context design:
#    https://www.promptingguide.ai/techniques/fewshot

def _extract_key_values(result_json_str: str, max_values: int = 10) -> list:
    """
    Pull out the most likely 'identifier' values from a stored result blob.
    We use these to help the model write IN (...) clauses on follow-up queries.

    For example, if the last result was:
      [{"customer_id": "QUICK", "company_name": "QUICK-Stop"}, ...]
    We return: ["QUICK", "ERNSH", ...]

    We prefer columns named *_id or the first column if no ID column exists.
    """
    try:
        data = json.loads(result_json_str)
        if not data or not isinstance(data, list):
            return []

        first_row = data[0]
        keys = list(first_row.keys())

        # Prefer explicit ID columns
        id_col = next((k for k in keys if k.endswith("_id")), None)
        # Fall back to first column
        target_col = id_col or keys[0]

        values = [row[target_col] for row in data[:max_values] if target_col in row]
        return values
    except Exception:
        return []


def _build_conversation_history(conversation_state) -> list:
    """
    Convert stored conversation messages into clean LLM message format.

    Returns a list of {"role": ..., "content": ...} dicts.

    The pattern we produce for each prior turn:
      [user]      "show top 5 customers by revenue"
      [assistant] '{"sql": "SELECT c.company_name...", "params": []}'

    This teaches the model through example: user speaks English,
    assistant responds with SQL JSON. Clean, consistent, unambiguous.

    We also append a CONTEXT note to the last user message if the previous
    result had extractable key values — this helps with "show me their orders"
    style follow-up questions.
    """
    if not conversation_state or not conversation_state.messages:
        return []

    # Take the last 3 full turns (6 messages: 3 user + 3 assistant)
    # Going further back gives diminishing returns and adds token cost.
    recent = conversation_state.get_last_n_messages(6)

    history = []
    previous_result_values = []

    for i, msg in enumerate(recent):
        if msg.role == "user":
            content = msg.content

            # If we have key values from the previous assistant turn,
            # append them as a hint so the model can resolve "them"/"their"
            if previous_result_values:
                values_str = ", ".join(str(v) for v in previous_result_values)
                content += f"\n[CONTEXT: Previous result contained these values: {values_str}]"
                previous_result_values = []  # consume — only relevant for next turn

            history.append({"role": "user", "content": content})

        elif msg.role == "assistant":
            # Only send the SQL back, not the result blob.
            # The model needs to see what SQL pattern it generated,
            # so it can build on it (e.g. same tables, same aliases).
            if msg.sql_generated:
                history.append({
                    "role": "assistant",
                    "content": json.dumps({"sql": msg.sql_generated, "params": msg.params_used or []})
                })

                # Try to extract key values from the result for the NEXT turn's context hint
                previous_result_values = _extract_key_values(msg.content)
            else:
                # Error turn — skip it entirely. We don't want the model to
                # "learn" from failed queries.
                pass

    return history


# ─── Main entry point ─────────────────────────────────────────────────────────

def extract_sql_query(user_text: str, conversation_state=None):
    """
    Generate a SQL query from the user's plain-English question.

    Message structure sent to the LLM:
      [system]       SYSTEM_PROMPT (schema + rules + examples)
      [user]         prior turn 1 question
      [assistant]    prior turn 1 SQL JSON
      [user]         prior turn 2 question  ← may include [CONTEXT: ...] hint
      [assistant]    prior turn 2 SQL JSON
      ...
      [user]         current question

    This is a standard "multi-turn prompting" pattern. The model sees the
    full back-and-forth and generates the next assistant turn.
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Inject cleaned conversation history (user questions + SQL only)
    history = _build_conversation_history(conversation_state)
    messages.extend(history)

    # Current user question is the final message
    messages.append({"role": "user", "content": user_text})

    # ── Debug logging ──────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"📤 SENDING TO LLM — {len(messages)} messages")
    for m in messages:
        preview = m['content'][:120].replace('\n', ' ')
        print(f"  [{m['role']}] {preview}...")
    print(f"{'='*60}\n")

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        temperature=0,       # 0 = deterministic, no creativity. We want exact SQL.
        max_tokens=512,      # SQL rarely needs more than this. Caps runaway responses.
    )

    raw_output = response.choices[0].message.content.strip()
    print(f"🤖 LLM output: {raw_output}")

    # Strip markdown fences if the model wraps the JSON anyway
    if raw_output.startswith("```"):
        raw_output = re.sub(r"^```[a-z]*\n?", "", raw_output)
        raw_output = re.sub(r"\n?```$", "", raw_output)
        raw_output = raw_output.strip()

    try:
        result = json.loads(raw_output)
        # Normalise — ensure both keys exist
        result.setdefault("params", [])
        result.setdefault("sql", "")
        return result
    except json.JSONDecodeError:
        print(f"❌ JSON parse failed: {raw_output}")
        # Return None sql so main.py can return a clean "I didn't understand" message
        return {"sql": None, "params": [], "parse_error": raw_output}


# ─── Retry: fix broken SQL ────────────────────────────────────────────────────
#
# Called by main.py when PostgreSQL rejects the generated SQL.
# We send the model its own bad SQL + the exact Postgres error and ask it
# to return a corrected JSON object.
#
# Why a separate function and not just a loop inside extract_sql_query?
# Because the caller (main.py) is the one who knows the DB error — it only
# exists after actually running the query. The LLM call and DB call live in
# different layers, so the fix has to cross that boundary explicitly.
#
# The message structure for the retry call:
#   [system]    SYSTEM_PROMPT  (same rules, same schema)
#   [user]      original user question
#   [assistant] the bad SQL JSON the model generated
#   [user]      "That SQL failed: <postgres error>. Fix it."
#
# This is called "error-driven self-correction" — a standard pattern for
# agentic LLM systems. The model acts as its own debugger.
#
# 📖 Read: "Self-refine" prompting paper (Madaan et al. 2023)
#    https://arxiv.org/abs/2303.17651
#    Also: "ReAct" pattern for LLM tool use + error recovery
#    https://arxiv.org/abs/2210.03629

def fix_sql_with_error(user_text: str, bad_sql: str, bad_params: list, db_error: str) -> dict:
    """
    Ask the LLM to fix a SQL query that PostgreSQL rejected.

    Args:
        user_text:  The original user question (so the model remembers the intent)
        bad_sql:    The SQL that failed
        bad_params: The params that were used
        db_error:   The raw PostgreSQL error string

    Returns:
        Same shape as extract_sql_query: {"sql": ..., "params": [...]}
        Returns {"sql": None} if the retry also fails to parse.
    """
    # Clean the postgres error — strip the trailing newline + caret line
    # e.g. "operator does not exist: integer = boolean\nLINE 1: ...^\n"
    # becomes "operator does not exist: integer = boolean LINE 1: ..."
    clean_error = " ".join(db_error.strip().splitlines())

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        # Show the original question so the model knows what it was trying to do
        {"role": "user", "content": user_text},
        # Show the bad SQL it generated
        {"role": "assistant", "content": json.dumps({"sql": bad_sql, "params": bad_params})},
        # Tell it exactly what went wrong and ask for a fix
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

        # Strip markdown fences
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