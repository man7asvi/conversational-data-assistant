from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional
from uuid import UUID
import json


@dataclass
class MessageRecord:
    """Single message in a conversation — shaped like a future SQL row."""
    role: str  # 'user' | 'assistant'
    content: str
    sql_generated: Optional[str] = None
    params_used: Optional[List] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self):
        """Convert to dict for JSON serialization."""
        return {
            "role": self.role,
            "content": self.content,
            "sql_generated": self.sql_generated,
            "params_used": self.params_used,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict):
        """Reconstruct from dict."""
        return cls(
            role=data["role"],
            content=data["content"],
            sql_generated=data.get("sql_generated"),
            params_used=data.get("params_used"),
            timestamp=datetime.fromisoformat(data.get("timestamp", datetime.utcnow().isoformat())),
        )


@dataclass
class ConversationState:
    """Full conversation state — shaped like a future SQL row."""
    conversation_id: UUID
    title: str
    messages: List[MessageRecord] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    # Context hints for the LLM (updated as conversation progresses)
    last_sql_generated: Optional[str] = None
    tables_used: List[str] = field(default_factory=list)
    filters_applied: List[str] = field(default_factory=list)

    def add_message(self, role: str, content: str, sql_generated: Optional[str] = None, params_used: Optional[List] = None):
        """Add a message and update context hints."""
        msg = MessageRecord(role=role, content=content, sql_generated=sql_generated, params_used=params_used)
        self.messages.append(msg)
        self.updated_at = datetime.utcnow()
        
        # Update context hints if SQL was generated
        if sql_generated:
            self.last_sql_generated = sql_generated
            # Simple extraction: find table names in FROM/JOIN clauses
            # (This is a naive implementation; enhance as needed)
            sql_upper = sql_generated.upper()
            for table in ["customers", "orders", "order_details", "products", "employees", "categories", "suppliers", "shippers"]:
                if table.upper() in sql_upper:
                    if table not in self.tables_used:
                        self.tables_used.append(table)

    def get_last_n_messages(self, n: int = 4) -> List[MessageRecord]:
        """Get the last n messages for context."""
        return self.messages[-n:]

    def to_dict(self):
        """Convert to dict for JSON serialization."""
        return {
            "conversation_id": str(self.conversation_id),
            "title": self.title,
            "messages": [msg.to_dict() for msg in self.messages],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_sql_generated": self.last_sql_generated,
            "tables_used": self.tables_used,
            "filters_applied": self.filters_applied,
        }

    @classmethod
    def from_dict(cls, data: dict):
        """Reconstruct from dict."""
        return cls(
            conversation_id=UUID(data["conversation_id"]),
            title=data["title"],
            messages=[MessageRecord.from_dict(msg) for msg in data.get("messages", [])],
            created_at=datetime.fromisoformat(data.get("created_at", datetime.utcnow().isoformat())),
            updated_at=datetime.fromisoformat(data.get("updated_at", datetime.utcnow().isoformat())),
            last_sql_generated=data.get("last_sql_generated"),
            tables_used=data.get("tables_used", []),
            filters_applied=data.get("filters_applied", []),
        )