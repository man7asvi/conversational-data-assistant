# backend/postgres_session_store.py
"""
PostgreSQL implementation of SessionStore.
Replaces InMemorySessionStore for production use.
Conversations persist across server restarts.
"""

from typing import List, Optional
from uuid import UUID
import psycopg2
from psycopg2.extras import RealDictCursor
import json
from datetime import datetime

from session_store import SessionStore
from models import ConversationState, MessageRecord
from db_manager import DatabaseConfig


class PostgresSessionStore(SessionStore):
    """
    PostgreSQL backend for conversation storage.
    Implements the SessionStore interface with database persistence.
    """

    def __init__(self, db_config: DatabaseConfig):
        """
        Initialize PostgresSessionStore.
        
        Args:
            db_config: DatabaseConfig for the storage database
        """
        self.db_config = db_config
        self._verify_tables()

    def _get_connection(self):
        """Get a database connection."""
        return psycopg2.connect(**self.db_config.get_connection_string())

    def _verify_tables(self):
        """Verify that required tables exist."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_name = 'conversations'
                )
                """
            )
            if not cursor.fetchone()[0]:
                print("⚠️  conversations table not found. Run phase2_schema.sql first.")
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"⚠️  Warning: Could not verify tables: {e}")

    def create_conversation(self, title: str, database_name: str = "default") -> ConversationState:
        """
        Create a new conversation.
        
        Args:
            title: Conversation title
            database_name: Name of the database to query
            
        Returns:
            ConversationState with new conversation_id
        """
        from uuid import uuid4
        
        conversation_id = uuid4()
        now = datetime.utcnow()
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
    """
    INSERT INTO conversations (id, database_name, title, created_at, updated_at)
    VALUES (%s, %s, %s, %s, %s)
    """,
    (str(conversation_id), database_name, title, now, now)
)
            conn.commit()
            cursor.close()
            conn.close()
            
            state = ConversationState(
                conversation_id=conversation_id,
                title=title,
            )
            print(f"✅ Created conversation {conversation_id}")
            return state
        except Exception as e:
            print(f"❌ Error creating conversation: {e}")
            raise

    def get_conversation(self, conversation_id: UUID) -> Optional[ConversationState]:
        """
        Retrieve a conversation by ID.
        
        Args:
            conversation_id: UUID of conversation
            
        Returns:
            ConversationState with all messages, or None if not found
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Get conversation metadata
            cursor.execute(
    """
    SELECT id, title, created_at, updated_at, database_name
    FROM conversations WHERE id = %s
    """,
    (str(conversation_id),)
)
            conv_row = cursor.fetchone()
            
            if not conv_row:
                cursor.close()
                conn.close()
                return None
            
            # Get all messages for this conversation
            cursor.execute(
                """
                SELECT role, content, sql_generated, params_used, timestamp
                FROM messages
                WHERE conversation_id = %s
                ORDER BY timestamp ASC
                """,
                (str(conversation_id),)
            )
            message_rows = cursor.fetchall()
            cursor.close()
            conn.close()
            
            # Build ConversationState
            messages = []
            for row in message_rows:
                msg = MessageRecord(
                    role=row["role"],
                    content=row["content"],
                    sql_generated=row.get("sql_generated"),
                    params_used=row.get("params_used"),
                    timestamp=row["timestamp"]
                )
                messages.append(msg)
            
            state = ConversationState(
                conversation_id=conversation_id,
                title=conv_row["title"],
                messages=messages,
                created_at=conv_row["created_at"],
                updated_at=conv_row["updated_at"]
            )
            
            return state
        except Exception as e:
            print(f"❌ Error retrieving conversation: {e}")
            return None

    def save_message(
        self,
        conversation_id: UUID,
        role: str,
        content: str,
        sql_generated: Optional[str] = None,
        params_used: Optional[List] = None
    ) -> ConversationState:
        """
        Add a message to a conversation.
        
        Args:
            conversation_id: UUID of conversation
            role: 'user' or 'assistant'
            content: Message text
            sql_generated: Optional SQL query
            params_used: Optional list of parameters
            
        Returns:
            Updated ConversationState
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Insert message
            cursor.execute(
                """
                INSERT INTO messages (conversation_id, role, content, sql_generated, params_used, timestamp)
                VALUES (%s, %s, %s, %s, %s, NOW())
                """,
                (str(conversation_id), role, content, sql_generated, json.dumps(params_used) if params_used else None)
            )
            
            # Update conversation updated_at
            cursor.execute(
                "UPDATE conversations SET updated_at = NOW() WHERE id = %s",
                (str(conversation_id),)
            )
            
            conn.commit()
            cursor.close()
            conn.close()
            
            # Return updated state
            return self.get_conversation(conversation_id)
        except Exception as e:
            print(f"❌ Error saving message: {e}")
            raise

    def list_conversations(self, database_name: Optional[str] = None) -> List[ConversationState]:
        """
        List all conversations.
        
        Args:
            database_name: Optional filter by database name
            
        Returns:
            List of ConversationState objects (summary, no messages)
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            if database_name:
                cursor.execute(
                    """
                    SELECT c.id, c.title, c.created_at, c.updated_at, c.database_name, COUNT(m.id) as message_count
                    FROM conversations c
                    LEFT JOIN messages m ON c.id = m.conversation_id
                    WHERE c.database_name = %s
                    GROUP BY c.id, c.title, c.created_at, c.updated_at, c.database_name
                    ORDER BY c.updated_at DESC
                    """,
                    (database_name,)
                )
            else:
                cursor.execute(
                    """
                    SELECT c.id, c.title, c.created_at, c.updated_at, c.database_name, COUNT(m.id) as message_count
                    FROM conversations c
                    LEFT JOIN messages m ON c.id = m.conversation_id
                    GROUP BY c.id, c.title, c.created_at, c.updated_at, c.database_name
                    ORDER BY c.updated_at DESC
                    """
                )
            
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            
            conversations = []
            for row in rows:
                state = ConversationState(
                    conversation_id=row["id"],
                    title=row["title"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"]
                )
                # Manually add message_count to the state for frontend
                state.message_count = row["message_count"]
                conversations.append(state)
            
            return conversations
        except Exception as e:
            print(f"❌ Error listing conversations: {e}")
            return []

    def delete_conversation(self, conversation_id: UUID) -> bool:
        """Delete a conversation and all its messages."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM conversations WHERE id = %s", (str(conversation_id),))
            success = cursor.rowcount > 0
            conn.commit()
            cursor.close()
            conn.close()
            
            if success:
                print(f"✅ Deleted conversation {conversation_id}")
            return success
        except Exception as e:
            print(f"❌ Error deleting conversation: {e}")
            return False

    def update_conversation_title(self, conversation_id: UUID, title: str) -> Optional[ConversationState]:
        """Update a conversation's title."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE conversations SET title = %s, updated_at = NOW() WHERE id = %s",
                (title, str(conversation_id))
            )
            conn.commit()
            cursor.close()
            conn.close()
            
            return self.get_conversation(conversation_id)
        except Exception as e:
            print(f"❌ Error updating conversation title: {e}")
            return None