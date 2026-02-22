"""
Context Builder - Combines Structured + Semantic Memory
Builds rich context for AI agents
"""
from typing import Dict, List, Optional
from loguru import logger

from app.services.memory_service import memory_service
from app.services.vector_memory_service import vector_memory


class ContextBuilder:
    """
    Builds comprehensive context from multiple memory sources
    """
    
    def __init__(self):
        self.sql_memory = memory_service
        self.vector_memory = vector_memory
        logger.info("✅ Context Builder initialized")
    
    def build_user_context(
        self,
        user_id: str,
        current_message: str,
        conversation_id: str,
        task_type: Optional[str] = None
    ) -> str:
        """
        Build complete context for agent
        
        Combines:
        - User profile (SQL)
        - Learned preferences (SQL)
        - Recent conversation (SQL)
        - Semantically similar past conversations (Vector)
        - Relevant insights (Vector)
        
        Args:
            user_id: User identifier
            current_message: Current user message
            conversation_id: Current conversation
            task_type: Optional task type for filtering
            
        Returns:
            Formatted context string for LLM system prompt
        """
        context_parts = []
        
        # === 1. USER PROFILE (Structured) ===
        profile_context = self._build_profile_context(user_id)
        if profile_context:
            context_parts.append(profile_context)
        
        # === 2. LEARNED PREFERENCES (Structured) ===
        preferences_context = self._build_preferences_context(user_id, task_type)
        if preferences_context:
            context_parts.append(preferences_context)
        
        # === 3. SEMANTIC MEMORY (Vector) ===
        semantic_context = self._build_semantic_context(user_id, current_message)
        if semantic_context:
            context_parts.append(semantic_context)
        
        # === 4. RECENT CONVERSATION (Structured) ===
        # This will be added separately as message history
        # We just note it exists
        recent_messages = self.sql_memory.get_conversation_history(
            conversation_id, limit=5
        )
        if recent_messages:
            context_parts.append(
                f"\n# CURRENT CONVERSATION:\n"
                f"- This conversation has {len(recent_messages)} recent messages\n"
                f"- Continue naturally from this context"
            )
        
        # Combine all context
        if context_parts:
            full_context = "\n\n".join(context_parts)
            return f"""# PERSONALIZED CONTEXT FOR THIS USER

{full_context}

Use this context to provide personalized, contextaware responses.
Reference past discussions when relevant.
Build on user's known preferences.
"""
        else:
            return ""
    
    def _build_profile_context(self, user_id: str) -> str:
        """Build user profile context"""
        try:
            # Get user stats from SQL
            recent_convs = self.sql_memory.get_recent_conversations(user_id, limit=5)
            
            # Get vector memory stats
            vector_stats = self.vector_memory.get_stats(user_id)
            
            if not recent_convs and vector_stats['total_messages'] == 0:
                return ""
            
            context = "# USER PROFILE:\n"
            
            if recent_convs:
                total_messages = sum(c['message_count'] for c in recent_convs)
                context += f"- Total conversations: {len(recent_convs)}\n"
                context += f"- Total messages exchanged: {total_messages}\n"
            
            if vector_stats['total_insights'] > 0:
                context += f"- Learned insights: {vector_stats['total_insights']}\n"
            
            return context
        
        except Exception as e:
            logger.error(f"Error building profile context: {e}")
            return ""
    
    def _build_preferences_context(
        self,
        user_id: str,
        task_type: Optional[str] = None
    ) -> str:
        """Build structured preferences context from SQL"""
        try:
            prefs = self.sql_memory.get_user_preferences(user_id)
            
            if not prefs:
                return ""
            
            context = "# LEARNED PREFERENCES:\n"
            
            # Filter by task type if specified
            if task_type:
                category = task_type.split('_')[0]
                prefs = {category: prefs.get(category, {})}
            
            # Build context
            for category, items in prefs.items():
                if not items:
                    continue
                
                context += f"\n## {category.title()}:\n"
                
                for key, values in items.items():
                    if not values:
                        continue
                    
                    top_pref = values[0]
                    confidence_pct = int(top_pref['confidence'] * 100)
                    
                    context += (
                        f"- {key.replace('_', ' ').title()}: "
                        f"{top_pref['value']} "
                        f"({confidence_pct}% confidence, "
                        f"observed {top_pref['occurrences']} times)\n"
                    )
            
            return context
        
        except Exception as e:
            logger.error(f"Error building preferences context: {e}")
            return ""
    
    def _build_semantic_context(
        self,
        user_id: str,
        current_message: str
    ) -> str:
        """Build semantic context from vector memory"""
        try:
            # Get semantic context
            semantic_data = self.vector_memory.get_user_context(
                user_id=user_id,
                current_query=current_message,
                include_messages=True,
                include_insights=True
            )
            
            context_parts = []
            
            # Add similar past messages
            if semantic_data['similar_messages']:
                context_parts.append("# RELEVANT PAST DISCUSSIONS:")
                for msg in semantic_data['similar_messages'][:3]:
                    similarity = int(msg['similarity_score'] * 100)
                    content_preview = msg['content'][:80] + "..."
                    context_parts.append(
                        f"- ({similarity}% similar) \"{content_preview}\""
                    )
            
            # Add relevant insights
            if semantic_data['insights']:
                context_parts.append("\n# RELEVANT INSIGHTS:")
                for insight in semantic_data['insights']:
                    similarity = int(insight['similarity_score'] * 100)
                    context_parts.append(
                        f"- ({similarity}% relevant) {insight['content']}"
                    )
            
            if context_parts:
                return "\n".join(context_parts)
            else:
                return ""
        
        except Exception as e:
            logger.error(f"Error building semantic context: {e}")
            return ""
    
    def save_message_with_context(
        self,
        user_id: str,
        message_id: int,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Dict = None
    ):
        """
        Save message to both SQL and vector databases
        
        Args:
            user_id: User identifier
            message_id: Message ID from SQL database
            conversation_id: Conversation ID
            role: 'user' or 'assistant'
            content: Message content
            metadata: Additional metadata
        """
        # Save to vector memory
        self.vector_memory.store_message(
            user_id=user_id,
            message_id=message_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            metadata=metadata
        )
    
    def extract_and_save_insights(
        self,
        user_id: str,
        conversation_id: str
    ):
        """
        Extract insights from recent conversation
        
        Should be called periodically (e.g., every 5 messages)
        
        Args:
            user_id: User identifier
            conversation_id: Conversation to analyze
        """
        try:
            # Get recent messages
            messages = self.sql_memory.get_conversation_history(
                conversation_id, limit=10
            )
            
            if not messages:
                return
            
            # Extract and store insights
            self.vector_memory.extract_and_store_insights(
                user_id=user_id,
                conversation_messages=messages
            )
            
            logger.debug(f"🧠 Extracted insights from conversation {conversation_id}")
        
        except Exception as e:
            logger.error(f"Error extracting insights: {e}")
    
    def get_memory_summary(self, user_id: str) -> Dict:
        """Get summary of all memory for user"""
        try:
            # SQL memory stats
            prefs = self.sql_memory.get_user_preferences(user_id)
            recent_convs = self.sql_memory.get_recent_conversations(user_id, limit=10)
            
            # Vector memory stats
            vector_stats = self.vector_memory.get_stats(user_id)
            
            return {
                'sql_memory': {
                    'total_preferences': sum(
                        len(items) for items in prefs.values()
                    ) if prefs else 0,
                    'total_conversations': len(recent_convs),
                    'total_messages': sum(
                        c['message_count'] for c in recent_convs
                    )
                },
                'vector_memory': vector_stats,
                'total_memory_items': (
                    vector_stats['total_messages'] + 
                    vector_stats['total_insights']
                )
            }
        
        except Exception as e:
            logger.error(f"Error getting memory summary: {e}")
            return {}


# Global instance
context_builder = ContextBuilder()