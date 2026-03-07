"""
Context Builder - Combines Structured (SQL) + Semantic (Qdrant) Memory
Builds rich, cross-conversation context for AI agents in SonarBot

KEY FIX: Loads context across ALL conversations, not just the current one.
This ensures memory persists across new chats and system restarts.
"""
from typing import Dict, List, Optional
from loguru import logger

from app.services.enhanced_memory_service import enhanced_memory_service
from app.services.vector_memory_service import vector_memory


class ContextBuilder:
    """
    Builds comprehensive context from multiple memory sources:
    1. SQL: User profile, preferences, conversation history
    2. Qdrant: Semantic search across ALL past conversations + user insights
    """
    
    def __init__(self):
        self.sql_memory = enhanced_memory_service
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
        Build complete context for agent from ALL memory sources.
        
        This context persists across:
        - New chats (via vector search across all conversations)
        - System restarts (Qdrant + SQLite both persist to disk)
        
        Returns:
            Formatted context string for LLM system prompt
        """
        context_parts = []
        
        # === 1. USER FACTS FROM QDRANT (persistent across all chats) ===
        facts_context = self._build_user_facts_context(user_id)
        if facts_context:
            context_parts.append(facts_context)
        
        # === 2. USER PROFILE & STATS (SQL) ===
        profile_context = self._build_profile_context(user_id)
        if profile_context:
            context_parts.append(profile_context)
        
        # === 3. LEARNED PREFERENCES (SQL) ===
        preferences_context = self._build_preferences_context(user_id, task_type)
        if preferences_context:
            context_parts.append(preferences_context)
        
        # === 4. SEMANTIC MEMORY - Similar past conversations (Qdrant) ===
        semantic_context = self._build_semantic_context(user_id, current_message)
        if semantic_context:
            context_parts.append(semantic_context)
        
        # === 5. CURRENT CONVERSATION HISTORY (SQL) ===
        recent_messages = self.sql_memory.get_conversation_history(
            conversation_id, limit=5
        )
        if recent_messages:
            context_parts.append(
                f"\n# CURRENT CONVERSATION:\n"
                f"- This conversation has {len(recent_messages)} recent messages\n"
                f"- Continue naturally from this context"
            )
        
        # === 6. CROSS-CONVERSATION RECENT HISTORY ===
        cross_conv_context = self._build_cross_conversation_context(user_id, conversation_id)
        if cross_conv_context:
            context_parts.append(cross_conv_context)
        
        # Combine all context
        if context_parts:
            full_context = "\n\n".join(context_parts)
            return f"""# PERSONALIZED CONTEXT FOR THIS USER

{full_context}

IMPORTANT INSTRUCTIONS:
- Use this context to provide personalized, context-aware responses.
- Reference past discussions and known facts when relevant.
- Build on user's known preferences.
- If you know the user's name, use it naturally.
- All context above persists across conversations - the user expects you to remember.
"""
        else:
            return ""
    
    def _build_user_facts_context(self, user_id: str) -> str:
        """Build context from extracted user facts (from Qdrant insights)"""
        try:
            all_insights = self.vector_memory.get_all_user_insights(user_id, limit=30)
            
            if not all_insights:
                return ""
            
            # Deduplicate and organize insights
            user_facts = []
            preferences = []
            seen_content = set()
            
            for insight in all_insights:
                content = insight.get('content', '')
                # Simple dedup by content similarity
                content_key = content.lower().strip()[:80]
                if content_key in seen_content:
                    continue
                seen_content.add(content_key)
                
                itype = insight.get('type', '')
                if itype == 'user_fact':
                    user_facts.append(content)
                elif itype == 'preference':
                    preferences.append(content)
            
            context_parts = []
            
            if user_facts:
                context_parts.append("# KNOWN FACTS ABOUT THIS USER:")
                for fact in user_facts[:10]:
                    context_parts.append(f"- {fact}")
            
            if preferences:
                context_parts.append("\n# USER PREFERENCES (from past conversations):")
                for pref in preferences[:10]:
                    context_parts.append(f"- {pref}")
            
            if context_parts:
                return "\n".join(context_parts)
            return ""
        
        except Exception as e:
            logger.error(f"Error building user facts context: {e}")
            return ""
    
    def _build_profile_context(self, user_id: str) -> str:
        """Build user profile context from SQL"""
        try:
            recent_convs = self.sql_memory.get_recent_conversations(user_id, limit=10)
            vector_stats = self.vector_memory.get_stats(user_id)
            
            if not recent_convs and vector_stats['total_messages'] == 0:
                return ""
            
            context = "# USER PROFILE:\n"
            
            if recent_convs:
                total_messages = sum(c['message_count'] for c in recent_convs)
                context += f"- Total conversations: {len(recent_convs)}\n"
                context += f"- Total messages exchanged: {total_messages}\n"
            
            if vector_stats['total_messages'] > 0:
                context += f"- Semantic memories stored: {vector_stats['total_messages']}\n"
            
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
            
            context = "# LEARNED PREFERENCES (SQL):\n"
            
            if task_type:
                category = task_type.split('_')[0]
                prefs = {category: prefs.get(category, {})}
            
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
        """Build semantic context from vector memory (cross-conversation)"""
        try:
            semantic_data = self.vector_memory.get_user_context(
                user_id=user_id,
                current_query=current_message,
                include_messages=True,
                include_insights=True
            )
            
            context_parts = []
            
            # Add similar past messages/exchanges
            if semantic_data['similar_messages']:
                context_parts.append("# RELEVANT PAST DISCUSSIONS (from any conversation):")
                for msg in semantic_data['similar_messages'][:5]:
                    similarity = int(msg['similarity_score'] * 100)
                    role = msg.get('role', 'user')
                    
                    if role == 'exchange':
                        # This is a full exchange pair - most useful
                        user_msg = msg.get('user_message', '')
                        asst_resp = msg.get('assistant_response', '')
                        if user_msg and asst_resp:
                            context_parts.append(
                                f"- ({similarity}% relevant) Previous exchange:\n"
                                f"  User: \"{user_msg[:100]}\"\n"
                                f"  Assistant: \"{asst_resp[:150]}\""
                            )
                    else:
                        content_preview = msg['content'][:120]
                        context_parts.append(
                            f"- ({similarity}% similar, {role}) \"{content_preview}\""
                        )
            
            # Add relevant insights
            if semantic_data['insights']:
                context_parts.append("\n# QUERY-RELEVANT INSIGHTS:")
                for insight in semantic_data['insights'][:5]:
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
    
    def _build_cross_conversation_context(
        self,
        user_id: str,
        current_conversation_id: str
    ) -> str:
        """Build context from recent messages across OTHER conversations"""
        try:
            recent_convs = self.sql_memory.get_recent_conversations(user_id, limit=5)
            
            if not recent_convs:
                return ""
            
            other_convs = [
                c for c in recent_convs 
                if c['conversation_id'] != current_conversation_id
            ]
            
            if not other_convs:
                return ""
            
            context_parts = ["# RECENT CONVERSATION TOPICS:"]
            for conv in other_convs[:3]:
                title = conv.get('title', 'Unknown topic')[:80]
                msg_count = conv.get('message_count', 0)
                context_parts.append(f"- \"{title}\" ({msg_count} messages)")
            
            return "\n".join(context_parts)
        
        except Exception as e:
            logger.error(f"Error building cross-conversation context: {e}")
            return ""
    
    def get_memory_summary(self, user_id: str) -> Dict:
        """Get summary of all memory for user"""
        try:
            prefs = self.sql_memory.get_user_preferences(user_id)
            recent_convs = self.sql_memory.get_recent_conversations(user_id, limit=10)
            vector_stats = self.vector_memory.get_stats(user_id)
            
            return {
                'sql_memory': {
                    'total_preferences': sum(
                        len(items) for category_items in prefs.values() 
                        for items in category_items.values()
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
