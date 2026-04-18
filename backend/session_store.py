from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID
from models import ConversationState


class SessionStore(ABC):
    """Abstract interface for conversation storage. Ready for PostgresSessionStore swap."""

    @abstractmethod
    def create_conversation(self, title: str) -> ConversationState:
        """Create a new conversation and return its state."""
        pass

    @abstractmethod
    def get_conversation(self, conversation_id: UUID) -> Optional[ConversationState]:
        """Retrieve a conversation by ID. Return None if not found."""
        pass

    @abstractmethod
    def save_message(self, conversation_id: UUID, role: str, content: str, 
                     sql_generated: Optional[str] = None, params_used: Optional[List] = None) -> ConversationState:
        """Add a message to a conversation and return updated state."""
        pass

    @abstractmethod
    def list_conversations(self) -> List[ConversationState]:
        """List all conversations (summary view: ID, title, created_at, updated_at)."""
        pass

    @abstractmethod
    def delete_conversation(self, conversation_id: UUID) -> bool:
        """Delete a conversation. Return True if successful, False if not found."""
        pass

    @abstractmethod
    def update_conversation_title(self, conversation_id: UUID, title: str) -> Optional[ConversationState]:
        """Update a conversation's title."""
        pass


class InMemorySessionStore(SessionStore):
    """In-memory implementation of SessionStore. For development and testing."""

    def __init__(self):
        self._conversations: dict[UUID, ConversationState] = {}

    def create_conversation(self, title: str) -> ConversationState:
        """Create a new conversation."""
        from uuid import uuid4
        
        conversation_id = uuid4()
        state = ConversationState(
            conversation_id=conversation_id,
            title=title,
        )
        self._conversations[conversation_id] = state
        return state

    def get_conversation(self, conversation_id: UUID) -> Optional[ConversationState]:
        """Retrieve a conversation by ID."""
        return self._conversations.get(conversation_id)

    def save_message(self, conversation_id: UUID, role: str, content: str,
                     sql_generated: Optional[str] = None, params_used: Optional[List] = None) -> ConversationState:
        """Add a message to a conversation."""
        state = self._conversations.get(conversation_id)
        if not state:
            raise ValueError(f"Conversation {conversation_id} not found")
        
        state.add_message(role=role, content=content, sql_generated=sql_generated, params_used=params_used)
        return state

    def list_conversations(self) -> List[ConversationState]:
        """List all conversations."""
        # Sort by updated_at descending (most recent first)
        return sorted(
            self._conversations.values(),
            key=lambda c: c.updated_at,
            reverse=True
        )

    def delete_conversation(self, conversation_id: UUID) -> bool:
        """Delete a conversation."""
        if conversation_id in self._conversations:
            del self._conversations[conversation_id]
            return True
        return False

    def update_conversation_title(self, conversation_id: UUID, title: str) -> Optional[ConversationState]:
        """Update a conversation's title."""
        state = self._conversations.get(conversation_id)
        if state:
            state.title = title
        return state