"""
Memory Service - FIXED VERSION
Proper NULL handling and conversation management
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


class MemoryService:
    """Manages user memory and learning"""
    
    def __init__(self):
        self.session_factory = SessionLocal
    
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
                session.refresh(user)  # ✅ Refresh to get defaults
                logger.info(f"✅ Created new user: {user_id}")
            else:
                # Update last active
                user.last_active = datetime.now(timezone.utc)
                session.commit()
            
            return user
        except Exception as e:
            session.rollback()
            logger.error(f"❌ Error ensuring user exists: {e}")
            raise
        finally:
            session.close()
    
    # ============ CONVERSATION MANAGEMENT ============
    
    def save_message(
        self,
        conversation_id: str,
        user_id: str,
        role: str,
        content: str,
        metadata: Dict = None
    ):
        """Save message to conversation - FIXED NULL handling"""
        session = self.session_factory()
        try:
            # Ensure user exists
            self.ensure_user_exists(user_id)
            
            # Get or create conversation
            conv = session.query(Conversation).filter_by(
                conversation_id=conversation_id
            ).first()
            
            if not conv:
                conv = Conversation(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    title=content[:100],  # First message as title
                    created_at=datetime.now(timezone.utc),
                    last_message_at=datetime.now(timezone.utc),
                    message_count=0  # ✅ Initialize to 0
                )
                session.add(conv)
                session.flush()  # ✅ Get ID without committing
            
            # Create message
            message = Message(
                conversation_id=conversation_id,
                role=role,
                content=content,
                message_metadata=metadata or {},
                timestamp=datetime.now(timezone.utc)
            )
            session.add(message)
            
            # ✅ FIX: Ensure message_count is not NULL before incrementing
            if conv.message_count is None:
                conv.message_count = 0
            
            # Update conversation
            conv.last_message_at = datetime.now(timezone.utc)
            conv.message_count = conv.message_count + 1  # ✅ Safe increment
            
            session.commit()
            logger.debug(f"💾 Saved message: {role} in {conversation_id}")
        
        except Exception as e:
            session.rollback()
            logger.error(f"❌ Error saving message: {e}")
        finally:
            session.close()
    
    def get_conversation_history(
        self,
        conversation_id: str,
        limit: int = 20
    ) -> List[Dict]:
        """Get conversation messages"""
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
    
    def _learn_coding_preferences(
        self,
        session: Session,
        user_id: str,
        data: Dict
    ):
        """Learn coding preferences"""
        
        # Language preference
        if data.get('language'):
            self._increment_preference(
                session, user_id,
                category='coding',
                key='preferred_language',
                value=data['language']
            )
        
        # Framework preference
        if data.get('framework'):
            self._increment_preference(
                session, user_id,
                category='coding',
                key=f"{data['language']}_framework",
                value=data['framework']
            )
        
        # Project type
        if data.get('project_type'):
            self._increment_preference(
                session, user_id,
                category='coding',
                key='project_type',
                value=data['project_type']
            )
    
    def _learn_desktop_preferences(
        self,
        session: Session,
        user_id: str,
        data: Dict
    ):
        """Learn desktop preferences"""
        
        # Track app usage
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
        
        # Find existing preference
        pref = session.query(UserPreference).filter_by(
            user_id=user_id,
            category=category,
            preference_key=key,
            preference_value=value
        ).first()
        
        if pref:
            # Increment
            pref.occurrences += 1
            pref.last_updated = datetime.now(timezone.utc)
        else:
            # Create new
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
        
        # Calculate confidence based on frequency
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
        """Get user preferences"""
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
            
            # Sort by confidence
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
        
        # Filter by task type
        if task_type:
            category = task_type.split('_')[0]  # 'coding', 'desktop', etc.
            prefs = {category: prefs.get(category, {})}
        
        # Build context
        for category, items in prefs.items():
            if not items:
                continue
                
            context_parts.append(f"\n## {category.title()}:")
            
            for key, values in items.items():
                if not values:
                    continue
                
                top_pref = values[0]  # Highest confidence
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
memory_service = MemoryService()