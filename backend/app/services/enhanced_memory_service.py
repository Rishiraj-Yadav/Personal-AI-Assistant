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
import re
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from loguru import logger

from app.database.models import (
    User, UserPreference, Conversation, Message,
    TaskHistory, BehavioralPattern, UserProfile, SavedWorkflow
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

            if role == 'user':
                self._learn_identity_from_message(user_id, content)
            
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

    # ============ PERSONALIZATION PROFILE ============

    def get_or_create_user_profile(self, user_id: str) -> UserProfile:
        """Get or initialize the structured user profile."""
        session = self.session_factory()
        try:
            self.ensure_user_exists(user_id)
            profile = session.query(UserProfile).filter_by(user_id=user_id).first()
            if not profile:
                profile = UserProfile(
                    user_id=user_id,
                    favorite_apps=[],
                    common_folders=[],
                    common_contacts=[],
                    named_routines=[],
                    profile_metadata={},
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(profile)
                session.commit()
                session.refresh(profile)
            return profile
        except Exception as e:
            session.rollback()
            logger.error(f"❌ Error getting user profile: {e}")
            raise
        finally:
            session.close()

    def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        """Return a serializable structured user profile."""
        session = self.session_factory()
        try:
            self.ensure_user_exists(user_id)
            profile = session.query(UserProfile).filter_by(user_id=user_id).first()
            if not profile:
                return {
                    "preferred_browser": "",
                    "preferred_editor": "",
                    "preferred_terminal": "",
                    "favorite_apps": [],
                    "common_folders": [],
                    "common_contacts": [],
                    "named_routines": [],
                    "display_name": "",
                    "metadata": {},
                }
            metadata = dict(profile.profile_metadata or {})
            display_name = metadata.get("display_name", "")
            if not display_name:
                inferred_name = self._infer_display_name_from_history(user_id)
                if inferred_name:
                    display_name = inferred_name
                    metadata["display_name"] = inferred_name

            return {
                "preferred_browser": profile.preferred_browser or "",
                "preferred_editor": profile.preferred_editor or "",
                "preferred_terminal": profile.preferred_terminal or "",
                "favorite_apps": list(profile.favorite_apps or []),
                "common_folders": list(profile.common_folders or []),
                "common_contacts": list(profile.common_contacts or []),
                "named_routines": list(profile.named_routines or []),
                "display_name": display_name,
                "metadata": metadata,
                "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
            }
        finally:
            session.close()

    def update_user_profile(self, user_id: str, **updates: Any) -> Dict[str, Any]:
        """Merge structured profile updates into the user's assistant profile."""
        session = self.session_factory()
        try:
            self.ensure_user_exists(user_id)
            profile = session.query(UserProfile).filter_by(user_id=user_id).first()
            if not profile:
                profile = UserProfile(
                    user_id=user_id,
                    favorite_apps=[],
                    common_folders=[],
                    common_contacts=[],
                    named_routines=[],
                    profile_metadata={},
                )
                session.add(profile)
                session.flush()

            for scalar_field in ("preferred_browser", "preferred_editor", "preferred_terminal"):
                value = updates.get(scalar_field)
                if value:
                    setattr(profile, scalar_field, str(value))

            for list_field in ("favorite_apps", "common_folders", "common_contacts", "named_routines"):
                values = updates.get(list_field)
                if values:
                    existing = list(getattr(profile, list_field) or [])
                    merged = existing[:]
                    for value in values:
                        if value and value not in merged:
                            merged.append(value)
                    setattr(profile, list_field, merged[-20:])

            metadata_updates = updates.get("metadata")
            if updates.get("display_name"):
                metadata_updates = {**(metadata_updates or {}), "display_name": str(updates["display_name"]).strip()}
            if isinstance(metadata_updates, dict):
                merged_metadata = dict(profile.profile_metadata or {})
                merged_metadata.update(metadata_updates)
                profile.profile_metadata = merged_metadata

            profile.updated_at = datetime.now(timezone.utc)
            session.commit()
            logger.debug(f"🧠 Updated user profile for {user_id}")
            return self.get_user_profile(user_id)
        except Exception as e:
            session.rollback()
            logger.error(f"❌ Error updating user profile: {e}")
            return self.get_user_profile(user_id)
        finally:
            session.close()

    def _extract_display_name(self, content: str) -> Optional[str]:
        """Extract a stable self-reported display name from direct user statements."""
        normalized = re.sub(r"\s+", " ", content or "").strip()
        if not normalized:
            return None

        patterns = [
            r"\bmy name is\s+([A-Za-z][A-Za-z\s'\-]{0,40})",
            r"\bcall me\s+([A-Za-z][A-Za-z\s'\-]{0,40})",
            r"\bi am\s+([A-Za-z][A-Za-z\s'\-]{0,40})",
            r"\bi'm\s+([A-Za-z][A-Za-z\s'\-]{0,40})",
        ]
        blocked_tokens = {"fine", "good", "okay", "ok", "here", "ready", "working", "trying"}

        for pattern in patterns:
            match = re.search(pattern, normalized, re.IGNORECASE)
            if not match:
                continue
            candidate = match.group(1).strip(" .,!?:;\"'")
            if not candidate:
                continue
            parts = [part for part in candidate.split() if part]
            if not parts or any(part.lower() in blocked_tokens for part in parts):
                continue
            return " ".join(part[:1].upper() + part[1:] for part in parts[:4])
        return None

    def _learn_identity_from_message(self, user_id: str, content: str) -> None:
        """Persist high-confidence personal identity facts from direct statements."""
        display_name = self._extract_display_name(content)
        if display_name:
            self.update_user_profile(user_id, display_name=display_name)

    def _infer_display_name_from_history(self, user_id: str) -> str:
        """Backfill a structured display name from recent stored user messages."""
        try:
            recent_messages = self.get_all_user_messages(user_id, limit=100)
            for message in reversed(recent_messages):
                if message.get("role") != "user":
                    continue
                display_name = self._extract_display_name(message.get("content", ""))
                if display_name:
                    return display_name
        except Exception as e:
            logger.debug(f"Could not infer display name from history for {user_id}: {e}")
        return ""

    def save_workflow(
        self,
        user_id: str,
        workflow_key: str,
        workflow_name: str,
        *,
        description: str = "",
        triggers: Optional[List[str]] = None,
        parameter_defaults: Optional[Dict[str, Any]] = None,
        step_overrides: Optional[List[Dict[str, Any]]] = None,
        is_builtin: bool = False,
    ) -> Dict[str, Any]:
        """Create or update a saved workflow record."""
        session = self.session_factory()
        try:
            self.ensure_user_exists(user_id)
            workflow = (
                session.query(SavedWorkflow)
                .filter_by(user_id=user_id, workflow_key=workflow_key)
                .first()
            )
            if not workflow:
                workflow = SavedWorkflow(
                    user_id=user_id,
                    workflow_key=workflow_key,
                    workflow_name=workflow_name,
                    description=description,
                    triggers=triggers or [],
                    parameter_defaults=parameter_defaults or {},
                    step_overrides=step_overrides or [],
                    is_builtin=is_builtin,
                    use_count=0,
                )
                session.add(workflow)
            else:
                workflow.workflow_name = workflow_name or workflow.workflow_name
                workflow.description = description or workflow.description
                if triggers is not None:
                    workflow.triggers = triggers
                if parameter_defaults is not None:
                    workflow.parameter_defaults = parameter_defaults
                if step_overrides is not None:
                    workflow.step_overrides = step_overrides
                workflow.is_builtin = is_builtin or workflow.is_builtin

            workflow.updated_at = datetime.now(timezone.utc)
            session.commit()
            return {
                "workflow_key": workflow.workflow_key,
                "workflow_name": workflow.workflow_name,
                "is_builtin": workflow.is_builtin,
                "use_count": workflow.use_count,
            }
        except Exception as e:
            session.rollback()
            logger.error(f"❌ Error saving workflow {workflow_key}: {e}")
            return {
                "workflow_key": workflow_key,
                "workflow_name": workflow_name,
                "is_builtin": is_builtin,
                "use_count": 0,
            }
        finally:
            session.close()

    def record_workflow_run(
        self,
        user_id: str,
        workflow_key: str,
        workflow_name: str,
        *,
        success: bool,
        parameters: Optional[Dict[str, Any]] = None,
        description: str = "",
        is_builtin: bool = True,
    ) -> Dict[str, Any]:
        """Increment workflow usage and optionally store personalization hints."""
        workflow = self.save_workflow(
            user_id,
            workflow_key,
            workflow_name,
            description=description,
            parameter_defaults=parameters or {},
            is_builtin=is_builtin,
        )

        session = self.session_factory()
        try:
            record = (
                session.query(SavedWorkflow)
                .filter_by(user_id=user_id, workflow_key=workflow_key)
                .first()
            )
            if record:
                record.use_count = (record.use_count or 0) + 1
                record.last_used = datetime.now(timezone.utc)
                record.updated_at = datetime.now(timezone.utc)
                session.commit()
                workflow["use_count"] = record.use_count
            return workflow
        except Exception as e:
            session.rollback()
            logger.error(f"❌ Error recording workflow run for {workflow_key}: {e}")
            return workflow
        finally:
            session.close()

    def get_saved_workflows(
        self,
        user_id: str,
        *,
        include_builtins: bool = True,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Get saved workflows and routines for this user."""
        session = self.session_factory()
        try:
            query = session.query(SavedWorkflow).filter_by(user_id=user_id)
            if not include_builtins:
                query = query.filter_by(is_builtin=False)
            workflows = (
                query.order_by(desc(SavedWorkflow.use_count), desc(SavedWorkflow.updated_at))
                .limit(limit)
                .all()
            )
            return [
                {
                    "workflow_key": workflow.workflow_key,
                    "workflow_name": workflow.workflow_name,
                    "description": workflow.description or "",
                    "triggers": workflow.triggers or [],
                    "parameter_defaults": workflow.parameter_defaults or {},
                    "step_overrides": workflow.step_overrides or [],
                    "is_builtin": workflow.is_builtin,
                    "use_count": workflow.use_count or 0,
                    "last_used": workflow.last_used.isoformat() if workflow.last_used else None,
                }
                for workflow in workflows
            ]
        finally:
            session.close()

    def get_recent_task_outcomes(
        self,
        user_id: str,
        *,
        task_type: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Return recent successful and failed tasks to help planning and recovery."""
        session = self.session_factory()
        try:
            query = session.query(TaskHistory).filter_by(user_id=user_id)
            if task_type:
                query = query.filter_by(task_type=task_type)
            tasks = query.order_by(desc(TaskHistory.timestamp)).limit(limit).all()
            return [
                {
                    "task_type": task.task_type,
                    "description": task.task_description,
                    "agent_used": task.agent_used,
                    "success": task.success,
                    "skills_used": task.skills_used or [],
                    "timestamp": task.timestamp.isoformat() if task.timestamp else None,
                }
                for task in tasks
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
        if data.get('skills_used') and any(skill in data['skills_used'] for skill in ('app_launcher', 'open_application')):
            app = data.get('actions_performed', {}).get('app') or data.get('app_name')
            if app:
                self._increment_preference(
                    session, user_id,
                    category='desktop',
                    key='frequently_used_apps',
                    value=app
                )

                lower_app = str(app).lower()
                profile_updates: Dict[str, Any] = {"favorite_apps": [app]}
                if any(browser in lower_app for browser in ("chrome", "edge", "firefox", "brave", "opera")):
                    profile_updates["preferred_browser"] = app
                if any(editor in lower_app for editor in ("code", "vscode", "notepad++", "pycharm", "sublime", "vim")):
                    profile_updates["preferred_editor"] = app
                if any(term in lower_app for term in ("powershell", "cmd", "terminal", "wt", "bash")):
                    profile_updates["preferred_terminal"] = app
                self.update_user_profile(user_id, **profile_updates)

        destination_folder = data.get('destination_folder')
        if destination_folder:
            self.update_user_profile(user_id, common_folders=[destination_folder])
    
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
