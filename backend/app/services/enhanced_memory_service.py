"""
Enhanced Memory Service - SonarBot Dual-Layer Memory
Integrates SQL (structured) + Qdrant Vector (semantic) memory.

KEY DESIGN: Every message is saved to BOTH databases.
- SQL: Conversation structure, user profiles, preferences
- Qdrant: Semantic embeddings for cross-conversation retrieval

Memory persists across:
- New chats (same user_id, different conversation_id)
- System restarts (SQLite file + Qdrant storage on disk)
"""
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from loguru import logger

from app.database.models import (
    User, UserPreference, Conversation, Message,
    TaskHistory, BehavioralPattern
)
from app.database.base import SessionLocal


class EnhancedMemoryService:
    """
    Dual-layer memory service:
    - SQL for structured data (users, conversations, messages, preferences)
    - Qdrant for semantic search (embeddings, insights, cross-conversation retrieval)
    """
    
    def __init__(self):
        self.session_factory = SessionLocal
        self._vector_memory = None
    
    @property
    def vector_memory(self):
        """Lazy load vector memory to avoid circular import"""
        if self._vector_memory is None:
            try:
                from app.services.vector_memory_service import vector_memory
                self._vector_memory = vector_memory
            except Exception as e:
                logger.warning(f"Vector memory not available: {e}")
        return self._vector_memory
    
    # ============ USER MANAGEMENT ============
    
    def ensure_user_exists(self, user_id: str) -> User:
        """Create user if doesn't exist"""
        session = self.session_factory()
        try:
            user = session.query(User).filter_by(user_id=user_id).first()
            
            if not user:
                user = User(
                    user_id=user_id,
                    created_at=datetime.now(timezone.utc),
                    last_active=datetime.now(timezone.utc)
                )
                session.add(user)
                session.commit()
                session.refresh(user)
                logger.info(f"✅ Created new user: {user_id}")
            else:
                user.last_active = datetime.now(timezone.utc)
                session.commit()
            
            return user
        except Exception as e:
            session.rollback()
            logger.error(f"❌ Error ensuring user exists: {e}")
            raise
        finally:
            session.close()
    
    # ============ CONVERSATION MANAGEMENT (Dual-Layer) ============
    
    def save_message(
        self,
        conversation_id: str,
        user_id: str,
        role: str,
        content: str,
        metadata: Dict = None
    ):
        """
        Save message to BOTH SQL and Vector databases.
        
        SQL: Structured storage for conversation history retrieval
        Qdrant: Semantic embedding for cross-conversation search
        """
        session = self.session_factory()
        try:
            # Ensure user exists
            self.ensure_user_exists(user_id)
            
            # Get or create conversation in SQL
            conv = session.query(Conversation).filter_by(
                conversation_id=conversation_id
            ).first()
            
            if not conv:
                conv = Conversation(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    title=content[:100] if role == 'user' else 'New conversation',
                    created_at=datetime.now(timezone.utc),
                    last_message_at=datetime.now(timezone.utc),
                    message_count=0
                )
                session.add(conv)
                session.flush()
            
            # Create message in SQL
            message = Message(
                conversation_id=conversation_id,
                role=role,
                content=content,
                message_metadata=metadata or {},
                timestamp=datetime.now(timezone.utc)
            )
            session.add(message)
            session.flush()
            
            # Update conversation stats
            if conv.message_count is None:
                conv.message_count = 0
            conv.last_message_at = datetime.now(timezone.utc)
            conv.message_count = conv.message_count + 1
            
            session.commit()
            
            # Save to Vector database (BOTH user and assistant messages)
            if self.vector_memory:
                self.vector_memory.store_message(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    role=role,
                    content=content,
                    metadata=metadata
                )
            
            logger.debug(f"💾 Saved {role} message to SQL + Vector")
        
        except Exception as e:
            session.rollback()
            logger.error(f"❌ Error saving message: {e}")
        finally:
            session.close()
    
    def save_conversation_exchange(
        self,
        conversation_id: str,
        user_id: str,
        user_message: str,
        assistant_response: str,
        metadata: Dict = None
    ):
        """
        Save a complete user+assistant exchange to vector DB as a pair.
        This creates a combined embedding that captures the full context.
        Also extracts facts/preferences from the exchange.
        """
        if self.vector_memory:
            # Store the combined exchange for better semantic retrieval
            self.vector_memory.store_conversation_pair(
                user_id=user_id,
                conversation_id=conversation_id,
                user_message=user_message,
                assistant_response=assistant_response,
                metadata=metadata
            )
            
            # Extract and store facts/preferences from user message
            self.vector_memory.extract_and_store_facts(
                user_id=user_id,
                user_message=user_message,
                assistant_response=assistant_response
            )
    
    def get_conversation_history(
        self,
        conversation_id: str,
        limit: int = 20
    ) -> List[Dict]:
        """Get conversation messages from SQL"""
        session = self.session_factory()
        try:
            messages = session.query(Message).filter_by(
                conversation_id=conversation_id
            ).order_by(Message.timestamp.desc()).limit(limit).all()
            
            return [
                {
                    'role': msg.role,
                    'content': msg.content,
                    'metadata': msg.message_metadata,
                    'timestamp': msg.timestamp.isoformat()
                }
                for msg in reversed(messages)
            ]
        finally:
            session.close()
    
    def get_recent_conversations(
        self,
        user_id: str,
        limit: int = 10
    ) -> List[Dict]:
        """Get user's recent conversations"""
        session = self.session_factory()
        try:
            convs = session.query(Conversation).filter_by(
                user_id=user_id
            ).order_by(desc(Conversation.last_message_at)).limit(limit).all()
            
            return [
                {
                    'conversation_id': conv.conversation_id,
                    'title': conv.title,
                    'message_count': conv.message_count or 0,
                    'last_message_at': conv.last_message_at.isoformat()
                }
                for conv in convs
            ]
        finally:
            session.close()
    
    def get_all_user_messages(
        self,
        user_id: str,
        limit: int = 50
    ) -> List[Dict]:
        """Get recent messages across ALL conversations for a user"""
        session = self.session_factory()
        try:
            # Join Message with Conversation to filter by user_id
            messages = (
                session.query(Message)
                .join(Conversation, Message.conversation_id == Conversation.conversation_id)
                .filter(Conversation.user_id == user_id)
                .order_by(Message.timestamp.desc())
                .limit(limit)
                .all()
            )
            
            return [
                {
                    'role': msg.role,
                    'content': msg.content,
                    'conversation_id': msg.conversation_id,
                    'timestamp': msg.timestamp.isoformat()
                }
                for msg in reversed(messages)
            ]
        finally:
            session.close()
    
    # ============ PREFERENCE LEARNING ============
    
    def learn_from_behavior(
        self,
        user_id: str,
        task_data: Dict
    ):
        """Learn preferences from user behavior"""
        session = self.session_factory()
        try:
            self.ensure_user_exists(user_id)
            
            if task_data.get('task_type') == 'coding':
                self._learn_coding_preferences(session, user_id, task_data)
            elif task_data.get('task_type') == 'desktop':
                self._learn_desktop_preferences(session, user_id, task_data)
            
            session.commit()
            logger.debug(f"🧠 Learned from behavior: {user_id}")
        
        except Exception as e:
            session.rollback()
            logger.error(f"❌ Error learning behavior: {e}")
        finally:
            session.close()
    
    def _learn_coding_preferences(self, session: Session, user_id: str, data: Dict):
        """Learn coding preferences"""
        if data.get('language'):
            self._increment_preference(
                session, user_id,
                category='coding',
                key='preferred_language',
                value=data['language']
            )
        
        if data.get('framework'):
            self._increment_preference(
                session, user_id,
                category='coding',
                key=f"{data['language']}_framework",
                value=data['framework']
            )
        
        if data.get('project_type'):
            self._increment_preference(
                session, user_id,
                category='coding',
                key='project_type',
                value=data['project_type']
            )
    
    def _learn_desktop_preferences(self, session: Session, user_id: str, data: Dict):
        """Learn desktop preferences"""
        if data.get('skills_used') and 'app_launcher' in data['skills_used']:
            app = data.get('actions_performed', {}).get('app')
            if app:
                self._increment_preference(
                    session, user_id,
                    category='desktop',
                    key='frequently_used_apps',
                    value=app
                )
    
    def _increment_preference(
        self,
        session: Session,
        user_id: str,
        category: str,
        key: str,
        value: Any
    ):
        """Increment preference count and update confidence"""
        pref = session.query(UserPreference).filter_by(
            user_id=user_id,
            category=category,
            preference_key=key,
            preference_value=value
        ).first()
        
        if pref:
            pref.occurrences += 1
            pref.last_updated = datetime.now(timezone.utc)
        else:
            pref = UserPreference(
                user_id=user_id,
                category=category,
                preference_key=key,
                preference_value=value,
                occurrences=1,
                learned_from='behavior',
                created_at=datetime.now(timezone.utc),
                last_updated=datetime.now(timezone.utc)
            )
            session.add(pref)
        
        total = session.query(func.sum(UserPreference.occurrences)).filter_by(
            user_id=user_id,
            category=category,
            preference_key=key
        ).scalar() or 1
        
        pref.confidence_score = pref.occurrences / total
    
    def get_user_preferences(
        self,
        user_id: str,
        category: str = None
    ) -> Dict:
        """Get user preferences from SQL"""
        session = self.session_factory()
        try:
            query = session.query(UserPreference).filter_by(user_id=user_id)
            
            if category:
                query = query.filter_by(category=category)
            
            prefs = query.all()
            
            result = {}
            for pref in prefs:
                if pref.category not in result:
                    result[pref.category] = {}
                
                if pref.preference_key not in result[pref.category]:
                    result[pref.category][pref.preference_key] = []
                
                result[pref.category][pref.preference_key].append({
                    'value': pref.preference_value,
                    'confidence': pref.confidence_score,
                    'occurrences': pref.occurrences
                })
            
            for category_data in result.values():
                for key in category_data:
                    category_data[key].sort(
                        key=lambda x: x['confidence'],
                        reverse=True
                    )
            
            return result
        finally:
            session.close()
    
    def get_personalized_context(
        self,
        user_id: str,
        task_type: str = None
    ) -> str:
        """Generate context string for AI prompts"""
        prefs = self.get_user_preferences(user_id)
        
        if not prefs:
            return ""
        
        context_parts = ["# USER PREFERENCES (learned from behavior):"]
        
        if task_type:
            category = task_type.split('_')[0]
            prefs = {category: prefs.get(category, {})}
        
        for category, items in prefs.items():
            if not items:
                continue
                
            context_parts.append(f"\n## {category.title()}:")
            
            for key, values in items.items():
                if not values:
                    continue
                
                top_pref = values[0]
                confidence_pct = int(top_pref['confidence'] * 100)
                
                context_parts.append(
                    f"- {key.replace('_', ' ').title()}: "
                    f"{top_pref['value']} "
                    f"({confidence_pct}% confident, used {top_pref['occurrences']} times)"
                )
        
        return "\n".join(context_parts) if len(context_parts) > 1 else ""
    
    # ============ TASK HISTORY ============
    
    def save_task(
        self,
        user_id: str,
        task_data: Dict
    ):
        """Save task to history"""
        session = self.session_factory()
        try:
            self.ensure_user_exists(user_id)
            
            task = TaskHistory(
                user_id=user_id,
                conversation_id=task_data.get('conversation_id'),
                task_type=task_data.get('task_type'),
                task_description=task_data.get('description'),
                agent_used=task_data.get('agent_used'),
                iterations=task_data.get('iterations', 1),
                success=task_data.get('success', False),
                execution_time=task_data.get('execution_time', 0),
                language=task_data.get('language'),
                framework=task_data.get('framework'),
                project_type=task_data.get('project_type'),
                skills_used=task_data.get('skills_used'),
                timestamp=datetime.now(timezone.utc)
            )
            
            session.add(task)
            session.commit()
            logger.debug(f"📝 Saved task: {task_data.get('task_type')}")
        
        except Exception as e:
            session.rollback()
            logger.error(f"❌ Error saving task: {e}")
        finally:
            session.close()


# Global instance
enhanced_memory_service = EnhancedMemoryService()
