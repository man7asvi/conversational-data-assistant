# backend/validator.py
import re

class SQLValidationError(Exception):
    pass

FORBIDDEN_PATTERNS = [
    r"\binsert\b",
    r"\bupdate\b",
    r"\bdelete\b",
    r"\bdrop\b",
    r"\balter\b",
    r"\btruncate\b",
    r"\bcreate\b",
    r"\breplace\b",
    r"\battach\b",
    r"\bdetach\b",
    r";\s*\w+",      # multiple statements
    r"--",           # single-line comment
    r"/\*",          # block comment start
    r"\*/",          # block comment end
]


def validate_sql(sql: str, allowed_tables=None, require_limit: bool = False) -> str:
    if not sql or not sql.strip():
        raise SQLValidationError("Empty SQL query")

    normalized = sql.strip().lower()

    # Must start with SELECT
    if not normalized.startswith("select"):
        raise SQLValidationError("Only SELECT queries are allowed")

    # Block dangerous keywords and patterns
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            raise SQLValidationError(f"Forbidden SQL pattern detected: {pattern}")

    # Optional table whitelist
    if allowed_tables:
        tables_found = extract_table_names(normalized)
        for table in tables_found:
            if table not in allowed_tables:
                raise SQLValidationError(f"Table '{table}' is not allowed")

    # Optional LIMIT enforcement
    if require_limit and "limit" not in normalized:
        sql = sql.rstrip(";") + " LIMIT 100"

    return sql


def extract_table_names(sql: str) -> list:
    """
    Extract real table names from a SQL query, correctly ignoring:
      - Table aliases    e.g. FROM orders o       → only 'orders', not 'o'
      - Function FROM    e.g. EXTRACT(YEAR FROM x) → 'x' is a column, not a table
      - Subquery aliases e.g. FROM (SELECT ...) sub → 'sub' is an alias, not a table
      - CTEs             e.g. WITH cte AS (SELECT ...) → 'cte' is not a real table

    Strategy:
      1. Strip CTE definitions so their names don't get picked up as tables.
      2. Remove EXTRACT(... FROM ...) patterns so that FROM inside a function
         doesn't get treated as a table reference.
      3. Remove subqueries (parenthesised blocks) — we still recurse into them
         but we don't want the alias after ')' to be treated as a table.
      4. Match FROM/JOIN followed by a word, then check whether the next token
         is a keyword (which means the word IS the table) or another word
         (which means the first word is the table and the second is its alias).

    The key insight: in "FROM orders o", 'orders' is followed by 'o' (an alias).
    In "FROM orders WHERE", 'orders' is followed by a keyword — no alias.
    In both cases we want 'orders'. We never want the alias token.
    """
    tables = set()

    # SQL keywords that can follow a table name — if we see one of these
    # after the table name, it confirms the preceding word was the table.
    # This set is used to distinguish aliases from keywords.
    SQL_KEYWORDS = {
        'where', 'on', 'join', 'inner', 'left', 'right', 'full', 'outer',
        'cross', 'group', 'order', 'having', 'limit', 'offset', 'union',
        'except', 'intersect', 'set', 'select', 'from', 'as', 'with',
        'and', 'or', 'not', 'in', 'exists', 'between', 'like', 'is',
        'null', 'true', 'false', 'case', 'when', 'then', 'else', 'end',
    }

    # ── Step 1: strip CTEs ────────────────────────────────────────────────
    # WITH cte_name AS (SELECT ...) — remove so 'cte_name' isn't seen as a table
    # We just remove the WITH ... AS portion; the inner SELECT is still parsed.
    sql = re.sub(r'\bwith\b.+?\bas\b\s*\(', '(', sql, flags=re.IGNORECASE | re.DOTALL)

    # ── Step 2: remove EXTRACT(... FROM ...) ──────────────────────────────
    # EXTRACT(YEAR FROM order_date) — the FROM here is not a table reference
    sql = re.sub(r'\bextract\s*\([^)]+\)', 'EXTRACT_REMOVED', sql, flags=re.IGNORECASE)

    # ── Step 3: recursively extract from subqueries ───────────────────────
    # Find top-level parenthesised blocks, extract table names from inside them,
    # then replace the whole block (including the alias after it) with a placeholder.
    # This prevents the subquery alias from being treated as a table name.
    # We do this iteratively until no more parenthesised blocks remain.
    max_passes = 10
    for _ in range(max_passes):
        # Match innermost parenthesised block (no nested parens inside)
        inner = re.search(r'\(([^()]+)\)', sql)
        if not inner:
            break
        # Recursively extract tables from the inner SQL
        inner_tables = extract_table_names(inner.group(1))
        tables.update(inner_tables)
        # Replace the whole block + optional alias with a placeholder
        # e.g. "(SELECT ...) sub" → "SUBQUERY_REMOVED"
        sql = sql[:inner.start()] + ' SUBQUERY_REMOVED ' + sql[inner.end():]
        # Remove the alias that follows the subquery if present
        sql = re.sub(r'\bSUBQUERY_REMOVED\s+([a-zA-Z_][a-zA-Z0-9_]*)\b', 'SUBQUERY_REMOVED', sql)

    # ── Step 4: match FROM/JOIN <table> [optional_alias] ─────────────────
    # Pattern: (FROM|JOIN) <word1> [<word2>]
    # - word1 is always the table name
    # - word2, if present and not a keyword, is an alias — we ignore it
    # - word2, if a keyword, means there's no alias
    pattern = re.compile(
        r'\b(?:from|join)\s+'          # FROM or JOIN
        r'([a-zA-Z_][a-zA-Z0-9_]*)'   # table name (captured)
        r'(?:\s+([a-zA-Z_][a-zA-Z0-9_]*))?',  # optional alias (captured)
        re.IGNORECASE
    )

    for match in pattern.finditer(sql):
        table_name = match.group(1).lower()
        alias_or_next = match.group(2).lower() if match.group(2) else None

        # Skip placeholders we injected
        if table_name in ('subquery_removed', 'extract_removed'):
            continue

        # Skip SQL keywords mistakenly captured as table names
        # This catches cases like "FROM (subquery) WHERE" where our
        # subquery removal left edge cases
        if table_name in SQL_KEYWORDS:
            continue

        tables.add(table_name)
        # We deliberately do NOT add alias_or_next — that's the alias, not a table

    return list(tables)