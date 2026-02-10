"""
Conversation State Manager
Handles in-memory conversation history (Phase 1)
Will be replaced with database in Phase 4
"""
from typing import Dict, List, Optional
from datetime import datetime
import uuid
from cachetools import TTLCache
from app.models import Message, MessageRole, ConversationHistory
from app.config import settings
from loguru import logger


class ConversationStateManager:
    """Manages conversation state in memory"""
    
    def __init__(self):
        """Initialize state manager with TTL cache"""
        # Cache conversations for 1 hour (3600 seconds)
        self.conversations: TTLCache = TTLCache(
            maxsize=1000,
            ttl=3600
        )
        logger.info("Initialized ConversationStateManager with TTL cache")
    
    def create_conversation(self, user_id: str) -> str:
        """
        Create a new conversation
        
        Args:
            user_id: User identifier
            
        Returns:
            Conversation ID
        """
        conversation_id = f"conv_{uuid.uuid4().hex[:12]}"
        
        conversation = ConversationHistory(
            conversation_id=conversation_id,
            user_id=user_id,
            messages=[],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        self.conversations[conversation_id] = conversation
        logger.info(f"Created conversation: {conversation_id} for user: {user_id}")
        
        return conversation_id
    
    def get_conversation(self, conversation_id: str) -> Optional[ConversationHistory]:
        """
        Retrieve conversation by ID
        
        Args:
            conversation_id: Conversation identifier
            
        Returns:
            ConversationHistory or None if not found
        """
        return self.conversations.get(conversation_id)
    
    def add_message(
        self, 
        conversation_id: str, 
        role: MessageRole, 
        content: str,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        Add message to conversation
        
        Args:
            conversation_id: Conversation identifier
            role: Message role (user/assistant/system)
            content: Message content
            metadata: Optional metadata
            
        Returns:
            Success boolean
        """
        conversation = self.conversations.get(conversation_id)
        
        if not conversation:
            logger.warning(f"Conversation not found: {conversation_id}")
            return False
        
        message = Message(
            role=role,
            content=content,
            timestamp=datetime.utcnow(),
            metadata=metadata
        )
        
        conversation.messages.append(message)
        conversation.updated_at = datetime.utcnow()
        
        # Keep only last N messages to manage memory
        if len(conversation.messages) > settings.MAX_CONVERSATION_HISTORY:
            # Keep system messages and last N messages
            system_msgs = [m for m in conversation.messages if m.role == MessageRole.SYSTEM]
            recent_msgs = [m for m in conversation.messages if m.role != MessageRole.SYSTEM][-settings.MAX_CONVERSATION_HISTORY:]
            conversation.messages = system_msgs + recent_msgs
        
        logger.debug(f"Added {role.value} message to {conversation_id}")
        return True
    
    def get_messages(
        self, 
        conversation_id: str,
        limit: Optional[int] = None
    ) -> List[Message]:
        """
        Get messages from conversation
        
        Args:
            conversation_id: Conversation identifier
            limit: Optional limit on number of messages
            
        Returns:
            List of messages
        """
        conversation = self.conversations.get(conversation_id)
        
        if not conversation:
            return []
        
        messages = conversation.messages
        
        if limit:
            # Always include system messages
            system_msgs = [m for m in messages if m.role == MessageRole.SYSTEM]
            other_msgs = [m for m in messages if m.role != MessageRole.SYSTEM][-limit:]
            return system_msgs + other_msgs
        
        return messages
    
    def clear_conversation(self, conversation_id: str) -> bool:
        """
        Clear all messages from conversation
        
        Args:
            conversation_id: Conversation identifier
            
        Returns:
            Success boolean
        """
        if conversation_id in self.conversations:
            del self.conversations[conversation_id]
            logger.info(f"Cleared conversation: {conversation_id}")
            return True
        
        return False
    
    def get_stats(self) -> Dict:
        """
        Get statistics about current state
        
        Returns:
            Dict with stats
        """
        total_conversations = len(self.conversations)
        total_messages = sum(
            len(conv.messages) 
            for conv in self.conversations.values()
        )
        
        return {
            "total_conversations": total_conversations,
            "total_messages": total_messages,
            "cache_size": self.conversations.maxsize
        }


# Global state manager instance
state_manager = ConversationStateManager()