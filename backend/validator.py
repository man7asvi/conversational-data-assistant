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


def extract_table_names(sql: str):
    """
    Very simple table extractor.
    Works for basic queries like:
    SELECT * FROM sales
    SELECT SUM(amount) FROM sales
    """
    tables = set()

    # FROM table_name
    from_matches = re.findall(r"\bfrom\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql, re.IGNORECASE)
    tables.update(from_matches)

    # JOIN table_name
    join_matches = re.findall(r"\bjoin\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql, re.IGNORECASE)
    tables.update(join_matches)

    return list(tables) 