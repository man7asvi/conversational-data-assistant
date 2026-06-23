# backend/db_manager.py
"""
DatabaseManager handles connections to multiple data sources.
Allows the app to switch between different databases dynamically.
"""

from dataclasses import dataclass
from typing import Optional, List, Dict
import psycopg2
from psycopg2.extras import RealDictCursor
import os


@dataclass
class DatabaseConfig:
    """Configuration for a single database connection."""
    name: str
    host: str
    port: int
    dbname: str
    username: str
    password: Optional[str] = None
    schema_name: str = "public"
    description: Optional[str] = None

    def get_connection_string(self) -> Dict:
        """Return psycopg2 connection params."""
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.dbname,
            "user": self.username,
            "password": self.password or "",
            "options": f"-c search_path={self.schema_name}"
        }


class DatabaseManager:
    """
    Manages connections and metadata for multiple databases.
    Stores database configs in PostgreSQL 'databases' table.
    """

    def __init__(self, storage_db_config: DatabaseConfig):
        """
        Initialize DatabaseManager.
        
        Args:
            storage_db_config: Config for the storage database (where conversations are stored)
        """
        self.storage_db = storage_db_config
        self._cache: Dict[str, DatabaseConfig] = {}
        self._load_databases()

    def _load_databases(self):
        """Load all database configs from the storage database."""
        try:
            conn = psycopg2.connect(**self.storage_db.get_connection_string())
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Check if the databases table exists first — it won't on fresh setups
            cursor.execute("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_name = 'databases' AND table_schema = 'public'
                )
            """)
            if not cursor.fetchone()[0]:
                # Table doesn't exist — this is normal for fresh setups
                cursor.close()
                conn.close()
                self._cache = {}
                return
            
            cursor.execute(
                "SELECT name, host, port, dbname, username, password, schema_name, description FROM databases WHERE enabled = true"
            )
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            self._cache.clear()
            for row in rows:
                config = DatabaseConfig(
                    name=row["name"],
                    host=row["host"],
                    port=row["port"],
                    dbname=row["dbname"],
                    username=row["username"],
                    password=row.get("password"),
                    schema_name=row.get("schema_name", "public"),
                    description=row.get("description")
                )
                self._cache[row["name"]] = config
            
            if self._cache:
                print(f"✅ Loaded {len(self._cache)} databases from storage")
        except Exception as e:
            print(f"⚠️  Could not load databases table (this is fine for fresh setups): {e}")
            self._cache = {}

    def get_database(self, name: str) -> Optional[DatabaseConfig]:
        """Get database config by name."""
        return self._cache.get(name)

    def list_databases(self) -> List[Dict]:
        """List all available databases."""
        return [
            {
                "name": db.name,
                "dbname": db.dbname,
                "host": db.host,
                "description": db.description or ""
            }
            for db in self._cache.values()
        ]

    def test_connection(self, name: str) -> bool:
        """Test if a database connection works."""
        config = self.get_database(name)
        if not config:
            print(f"❌ Database '{name}' not found")
            return False

        try:
            conn = psycopg2.connect(**config.get_connection_string())
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            conn.close()
            print(f"✅ Connection to '{name}' successful")
            return True
        except Exception as e:
            print(f"❌ Connection to '{name}' failed: {e}")
            return False

    def add_database(self, config: DatabaseConfig) -> bool:
        """
        Add a new database config to storage.
        
        Args:
            config: DatabaseConfig to add
            
        Returns:
            True if successful, False otherwise
        """
        try:
            conn = psycopg2.connect(**self.storage_db.get_connection_string())
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO databases (name, host, port, dbname, username, password, schema_name, description, enabled)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true)
                ON CONFLICT (name) DO UPDATE SET
                  host = EXCLUDED.host,
                  port = EXCLUDED.port,
                  dbname = EXCLUDED.dbname,
                  username = EXCLUDED.username,
                  password = EXCLUDED.password,
                  schema_name = EXCLUDED.schema_name,
                  description = EXCLUDED.description
                """,
                (config.name, config.host, config.port, config.dbname, config.username,
                 config.password, config.schema_name, config.description)
            )
            conn.commit()
            cursor.close()
            conn.close()
            
            self._load_databases()
            print(f"✅ Added/updated database '{config.name}'")
            return True
        except Exception as e:
            print(f"❌ Error adding database: {e}")
            return False

    def delete_database(self, name: str) -> bool:
        """Delete a database from the system."""
        try:
            conn = psycopg2.connect(**self.storage_db.get_connection_string())
            cursor = conn.cursor()
            cursor.execute("DELETE FROM databases WHERE name = %s", (name,))
            conn.commit()
            cursor.close()
            conn.close()
            
            self._load_databases()
            print(f"✅ Deleted database '{name}'")
            return True
        except Exception as e:
            print(f"❌ Error deleting database: {e}")
            return False


# ==============================================================================
# DATABASE CONFIG LOADERS
# ==============================================================================
# Two databases, two purposes, two functions.
# Each reads from its own set of .env variables.
#
#   get_target_db_config()   →  TARGET_DB_*   →  the database users query (READ ONLY)
#   get_storage_db_config()  →  STORAGE_DB_*  →  where chat history is saved (READ + WRITE)
# ==============================================================================


def get_target_db_config() -> DatabaseConfig:
    """
    The database users ask questions about. READ ONLY.
    
    The app will:
      - Inspect this database's schema at startup
      - Run SELECT queries against it
      - NEVER write to it (no INSERT, UPDATE, DELETE)
    
    .env variables: TARGET_DB_HOST, TARGET_DB_PORT, TARGET_DB_NAME,
                    TARGET_DB_USER, TARGET_DB_PASSWORD, TARGET_DB_SCHEMA
    """
    db_name = os.getenv("TARGET_DB_NAME", "postgres")
    return DatabaseConfig(
        name=db_name,
        host=os.getenv("TARGET_DB_HOST", "localhost"),
        port=int(os.getenv("TARGET_DB_PORT", "5432")),
        dbname=db_name,
        username=os.getenv("TARGET_DB_USER", "postgres"),
        password=os.getenv("TARGET_DB_PASSWORD", ""),
        schema_name=os.getenv("TARGET_DB_SCHEMA", "public"),
        description="Target database (read-only queries)"
    )


def get_storage_db_config() -> DatabaseConfig:
    """
    Where conversations and messages are saved. READ + WRITE.
    
    Requires 'conversations' and 'messages' tables to exist.
    Run migrations/setup.sql before first use.
    
    .env variables: STORAGE_DB_HOST, STORAGE_DB_PORT, STORAGE_DB_NAME,
                    STORAGE_DB_USER, STORAGE_DB_PASSWORD, STORAGE_DB_SCHEMA
    """
    return DatabaseConfig(
        name="storage",
        host=os.getenv("STORAGE_DB_HOST", "localhost"),
        port=int(os.getenv("STORAGE_DB_PORT", "5432")),
        dbname=os.getenv("STORAGE_DB_NAME", "datachat_storage"),
        username=os.getenv("STORAGE_DB_USER", "postgres"),
        password=os.getenv("STORAGE_DB_PASSWORD", ""),
        schema_name=os.getenv("STORAGE_DB_SCHEMA", "public")
    )