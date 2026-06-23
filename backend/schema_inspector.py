# backend/schema_inspector.py
"""
Schema Inspector — automatically discovers the structure of any PostgreSQL database.

This is the core piece that makes the project database-agnostic.
Instead of hardcoding "customers has customer_id, company_name...",
we ASK the database itself what it contains.

HOW IT WORKS:
PostgreSQL maintains a set of system tables collectively called
"information_schema". These are standardized in SQL specification —
meaning MySQL, SQL Server, and others have them too. The key ones:

  information_schema.tables    → lists all tables
  information_schema.columns   → lists all columns, their types, nullability
  information_schema.table_constraints     → lists primary keys, foreign keys
  information_schema.key_column_usage      → which columns are in those keys
  information_schema.referential_constraints → what foreign keys reference

By querying these, we get a complete picture of any database's structure
without knowing anything about it in advance.

USAGE:
  from schema_inspector import SchemaInspector
  from db_manager import DatabaseConfig

  config = DatabaseConfig(name="mydb", host="localhost", ...)
  inspector = SchemaInspector(config)
  schema = inspector.inspect()

  # schema is a dict:
  # {
  #   "tables": {
  #     "customers": {
  #       "columns": [
  #         {"name": "customer_id", "type": "varchar", "pk": True, "fk": None},
  #         {"name": "company_name", "type": "varchar", "pk": False, "fk": None},
  #         ...
  #       ]
  #     },
  #     ...
  #   },
  #   "table_names": ["customers", "orders", ...],
  #   "prompt_schema": "customers: customer_id (varchar PK), company_name (varchar)..."
  # }
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import psycopg2
from psycopg2.extras import RealDictCursor


@dataclass
class ColumnInfo:
    """Represents a single column in a table."""
    name: str
    data_type: str
    is_nullable: bool
    is_primary_key: bool
    foreign_key: Optional[str] = None  # "referenced_table.referenced_column"
    character_max_length: Optional[int] = None

    def to_prompt_string(self) -> str:
        """
        Format this column for inclusion in the LLM prompt.
        
        Examples:
          customer_id (varchar PK)
          order_id (integer PK)
          customer_id (varchar FK → customers.customer_id)
          product_name (varchar)
          unit_price (numeric)
          discontinued (smallint)
        
        We keep it compact because every token counts.
        The model needs to know: name, type, and relationships.
        """
        # Simplify verbose PostgreSQL type names into what the model
        # actually needs. "character varying" → "varchar" is clearer
        # and uses fewer tokens.
        type_map = {
            "character varying": "varchar",
            "character": "char",
            "double precision": "float",
            "timestamp without time zone": "timestamp",
            "timestamp with time zone": "timestamptz",
            "boolean": "boolean",
            "smallint": "smallint",
            "integer": "integer",
            "bigint": "bigint",
            "numeric": "numeric",
            "real": "real",
            "text": "text",
            "date": "date",
            "bytea": "bytea",
            "uuid": "uuid",
            "json": "json",
            "jsonb": "jsonb",
        }
        short_type = type_map.get(self.data_type, self.data_type)

        parts = [f"{self.name} ({short_type}"]

        if self.is_primary_key:
            parts.append(" PK")
        if self.foreign_key:
            parts.append(f" FK → {self.foreign_key}")

        parts.append(")")
        return "".join(parts)


@dataclass
class TableInfo:
    """Represents a single table and all its columns."""
    name: str
    columns: List[ColumnInfo]

    def to_prompt_string(self) -> str:
        """
        Format this table for the LLM prompt.
        
        Example output:
          customers: customer_id (varchar PK), company_name (varchar), city (varchar), country (varchar)
        
        This is the same compact format we were using in the hardcoded prompt,
        but now generated automatically.
        """
        col_strings = [col.to_prompt_string() for col in self.columns]
        return f"{self.name}: {', '.join(col_strings)}"


class SchemaInspector:
    """
    Connects to a PostgreSQL database and discovers its complete schema.
    
    This class does THREE things:
      1. Discovers all tables and columns (with types)
      2. Identifies primary keys and foreign key relationships
      3. Formats everything into a prompt-ready string
    
    The result is cached — introspection only happens once at startup,
    not on every query. Database schemas rarely change at runtime.
    """

    # Default tables to exclude — these are the app's own internal tables
    # used for conversation storage, not user data.
    DEFAULT_EXCLUDE = {"conversations", "messages", "databases"}

    def __init__(self, db_config, exclude_tables: set = None):
        """
        Args:
            db_config: A DatabaseConfig object with connection details
            exclude_tables: Set of table names to exclude from discovery.
                           Defaults to the app's internal tables (conversations,
                           messages, databases). Pass an empty set to include everything.
        """
        self.db_config = db_config
        self.exclude_tables = exclude_tables if exclude_tables is not None else self.DEFAULT_EXCLUDE
        self._schema: Optional[Dict] = None

    def inspect(self) -> Dict[str, Any]:
        """
        Main entry point. Inspects the database and returns a complete
        schema description.
        
        Returns:
            {
                "tables": {"table_name": TableInfo, ...},
                "table_names": ["table1", "table2", ...],
                "prompt_schema": "table1: col1 (type), col2 (type)...\ntable2: ...",
                "column_count": 42,
                "table_count": 8
            }
        
        The result is cached. Calling inspect() twice returns the same object
        without hitting the database again.
        """
        if self._schema is not None:
            return self._schema

        print(f"🔍 Inspecting database schema: {self.db_config.dbname}...")

        conn = psycopg2.connect(**self.db_config.get_connection_string())
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # ── Step 1: Get all tables ────────────────────────────────────
            tables_info = self._get_tables_and_columns(cursor)

            # ── Step 2: Get primary keys ──────────────────────────────────
            primary_keys = self._get_primary_keys(cursor)

            # ── Step 3: Get foreign keys ──────────────────────────────────
            foreign_keys = self._get_foreign_keys(cursor)

            # ── Step 4: Assemble everything ───────────────────────────────
            # Filter out excluded tables (app internals like conversations, messages)
            tables = {}
            for table_name, columns_raw in tables_info.items():
                if table_name in self.exclude_tables:
                    print(f"   ⏭️  Skipping internal table: {table_name}")
                    continue
                columns = []
                for col in columns_raw:
                    col_name = col["column_name"]
                    columns.append(ColumnInfo(
                        name=col_name,
                        data_type=col["data_type"],
                        is_nullable=col["is_nullable"] == "YES",
                        is_primary_key=col_name in primary_keys.get(table_name, set()),
                        foreign_key=foreign_keys.get(table_name, {}).get(col_name),
                        character_max_length=col.get("character_maximum_length"),
                    ))
                tables[table_name] = TableInfo(name=table_name, columns=columns)

            # ── Step 5: Build prompt-ready schema string ──────────────────
            prompt_lines = []
            for table_name in sorted(tables.keys()):
                prompt_lines.append(tables[table_name].to_prompt_string())
            prompt_schema = "\n".join(prompt_lines)

            # Count totals
            total_columns = sum(len(t.columns) for t in tables.values())

            self._schema = {
                "tables": tables,
                "table_names": sorted(tables.keys()),
                "prompt_schema": prompt_schema,
                "table_count": len(tables),
                "column_count": total_columns,
            }

            print(f"✅ Schema discovered: {len(tables)} tables, {total_columns} columns")
            for table_name in sorted(tables.keys()):
                col_count = len(tables[table_name].columns)
                pk_count = sum(1 for c in tables[table_name].columns if c.is_primary_key)
                fk_count = sum(1 for c in tables[table_name].columns if c.foreign_key)
                print(f"   📋 {table_name}: {col_count} columns, {pk_count} PK, {fk_count} FK")

            return self._schema

        finally:
            cursor.close()
            conn.close()

    def _get_tables_and_columns(self, cursor) -> Dict[str, List[Dict]]:
        """
        Query information_schema.columns to get all tables and their columns.
        
        WHY information_schema.columns AND NOT information_schema.tables?
        Because columns gives us both — the table names AND the column details
        in a single query. We filter by table_schema to only get user tables
        (not PostgreSQL's internal system tables).
        
        The table_type = 'BASE TABLE' filter excludes views. We only want
        real tables that contain data.
        """
        schema_name = self.db_config.schema_name or "public"

        cursor.execute("""
            SELECT 
                c.table_name,
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.character_maximum_length,
                c.ordinal_position
            FROM information_schema.columns c
            JOIN information_schema.tables t 
                ON c.table_name = t.table_name 
                AND c.table_schema = t.table_schema
            WHERE c.table_schema = %s
                AND t.table_type = 'BASE TABLE'
            ORDER BY c.table_name, c.ordinal_position
        """, (schema_name,))

        rows = cursor.fetchall()

        # Group columns by table name
        tables: Dict[str, List[Dict]] = {}
        for row in rows:
            table_name = row["table_name"]
            if table_name not in tables:
                tables[table_name] = []
            tables[table_name].append(dict(row))

        return tables

    def _get_primary_keys(self, cursor) -> Dict[str, set]:
        """
        Find all primary key columns.
        
        We join table_constraints (which knows WHICH tables have PKs)
        with key_column_usage (which knows WHICH COLUMNS are in those PKs).
        
        Returns: {"customers": {"customer_id"}, "orders": {"order_id"}, ...}
        """
        schema_name = self.db_config.schema_name or "public"

        cursor.execute("""
            SELECT
                tc.table_name,
                kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_schema = %s
        """, (schema_name,))

        rows = cursor.fetchall()

        pks: Dict[str, set] = {}
        for row in rows:
            table = row["table_name"]
            if table not in pks:
                pks[table] = set()
            pks[table].add(row["column_name"])

        return pks

    def _get_foreign_keys(self, cursor) -> Dict[str, Dict[str, str]]:
        """
        Find all foreign key relationships.
        
        This is the most complex query because we need to join THREE tables:
          - table_constraints: tells us which constraints are FOREIGN KEYs
          - key_column_usage: tells us which column in OUR table has the FK
          - referential_constraints + key_column_usage (again): tells us
            which table+column the FK POINTS TO
        
        Returns: {
            "orders": {
                "customer_id": "customers.customer_id",
                "employee_id": "employees.employee_id"
            },
            ...
        }
        
        This is crucial for the LLM — it needs to know that orders.customer_id
        connects to customers.customer_id, otherwise it can't write JOINs.
        """
        schema_name = self.db_config.schema_name or "public"

        cursor.execute("""
            SELECT
                kcu.table_name AS from_table,
                kcu.column_name AS from_column,
                ccu.table_name AS to_table,
                ccu.column_name AS to_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
                AND tc.table_schema = ccu.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_schema = %s
        """, (schema_name,))

        rows = cursor.fetchall()

        fks: Dict[str, Dict[str, str]] = {}
        for row in rows:
            from_table = row["from_table"]
            if from_table not in fks:
                fks[from_table] = {}
            fks[from_table][row["from_column"]] = f"{row['to_table']}.{row['to_column']}"

        return fks

    def get_table_names(self) -> List[str]:
        """Convenience method — returns just the table names."""
        schema = self.inspect()
        return schema["table_names"]

    def get_prompt_schema(self) -> str:
        """Convenience method — returns the prompt-ready schema string."""
        schema = self.inspect()
        return schema["prompt_schema"]

    def refresh(self):
        """
        Force re-inspection on next call.
        
        Useful if someone adds a table and wants the app to pick it up
        without restarting. Normally you'd restart the server, but this
        gives a programmatic option.
        """
        self._schema = None
        print("🔄 Schema cache cleared — will re-inspect on next query")