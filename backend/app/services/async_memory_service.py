"""
Async Memory Service

Non-blocking alternative to MemoryService.
Uses async SQLAlchemy for all database operations.

Part of Phase 4: Async Database Migration

Usage:
    from app.services.async_memory_service import async_memory_service

    # Save message (non-blocking)
    await async_memory_service.save_message(
        conversation_id="conv_123",
        user_id="user_1",
        role="user",
        content="Hello!"
    )

    # Get history (non-blocking)
    history = await async_memory_service.get_conversation_history("conv_123")

Migration:
    1. Import async_memory_service alongside memory_service
    2. Replace sync calls with async calls in routes
    3. Eventually remove sync memory_service
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from loguru import logger

# Try to import async SQLAlchemy
try:
    from sqlalchemy import select, desc, func, update, delete
    from sqlalchemy.ext.asyncio import AsyncSession
    ASYNC_AVAILABLE = True
except ImportError:
    ASYNC_AVAILABLE = False
    logger.warning("⚠️ Async SQLAlchemy not available for AsyncMemoryService")

from app.database.models import (
    User, UserPreference, Conversation, Message,
    TaskHistory, BehavioralPattern
)


class AsyncMemoryService:
    """
    Async memory service - non-blocking database operations.

    Drop-in replacement for MemoryService with async/await.
    """

    def __init__(self):
        """Initialize async memory service"""
        self._initialized = False
        logger.info("✅ AsyncMemoryService created")

    async def _get_session(self) -> "AsyncSession":
        """Get async database session"""
        from app.database.async_base import get_async_session
        return get_async_session()

    # ============ USER MANAGEMENT ============

    async def ensure_user_exists(self, user_id: str) -> User:
        """
        Create user if doesn't exist (NON-BLOCKING).

        Args:
            user_id: User identifier

        Returns:
            User instance
        """
        from app.database.async_base import get_async_session

        async with get_async_session() as session:
            try:
                # Non-blocking query
                result = await session.execute(
                    select(User).where(User.user_id == user_id)
                )
                user = result.scalar_one_or_none()

                if not user:
                    user = User(
                        user_id=user_id,
                        created_at=datetime.now(timezone.utc),
                        last_active=datetime.now(timezone.utc)
                    )
                    session.add(user)
                    await session.flush()
                    logger.info(f"✅ Created new user: {user_id}")
                else:
                    # Update last active
                    user.last_active = datetime.now(timezone.utc)

                await session.commit()
                return user

            except Exception as e:
                await session.rollback()
                logger.error(f"❌ Error ensuring user exists: {e}")
                raise

    # ============ CONVERSATION MANAGEMENT ============

    async def save_message(
        self,
        conversation_id: str,
        user_id: str,
        role: str,
        content: str,
        metadata: Dict = None
    ) -> bool:
        """
        Save message to conversation (NON-BLOCKING).

        Args:
            conversation_id: Conversation ID
            user_id: User ID
            role: 'user' or 'assistant'
            content: Message content
            metadata: Optional metadata dict

        Returns:
            True if saved successfully
        """
        from app.database.async_base import get_async_session

        async with get_async_session() as session:
            try:
                # Ensure user exists (inline to avoid nested transactions)
                result = await session.execute(
                    select(User).where(User.user_id == user_id)
                )
                user = result.scalar_one_or_none()

                if not user:
                    user = User(
                        user_id=user_id,
                        created_at=datetime.now(timezone.utc),
                        last_active=datetime.now(timezone.utc)
                    )
                    session.add(user)
                    await session.flush()

                # Get or create conversation
                result = await session.execute(
                    select(Conversation).where(
                        Conversation.conversation_id == conversation_id
                    )
                )
                conv = result.scalar_one_or_none()

                if not conv:
                    conv = Conversation(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        title=content[:100] if content else "New Conversation",
                        created_at=datetime.now(timezone.utc),
                        last_message_at=datetime.now(timezone.utc),
                        message_count=0
                    )
                    session.add(conv)
                    await session.flush()

                # Create message
                message = Message(
                    conversation_id=conversation_id,
                    role=role,
                    content=content,
                    message_metadata=metadata or {},
                    timestamp=datetime.now(timezone.utc)
                )
                session.add(message)

                # Update conversation metadata
                if conv.message_count is None:
                    conv.message_count = 0
                conv.message_count += 1
                conv.last_message_at = datetime.now(timezone.utc)

                await session.commit()
                logger.debug(f"💾 Message saved: {role} in {conversation_id}")
                return True

            except Exception as e:
                await session.rollback()
                logger.error(f"❌ Error saving message: {e}")
                return False

    async def get_conversation_history(
        self,
        conversation_id: str,
        limit: int = 20
    ) -> List[Dict]:
        """
        Get conversation messages (NON-BLOCKING).

        Args:
            conversation_id: Conversation ID
            limit: Maximum messages to return

        Returns:
            List of message dicts
        """
        from app.database.async_base import get_async_session

        async with get_async_session() as session:
            try:
                result = await session.execute(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(desc(Message.timestamp))
                    .limit(limit)
                )
                messages = result.scalars().all()

                return [
                    {
                        'role': msg.role,
                        'content': msg.content,
                        'metadata': msg.message_metadata or {},
                        'timestamp': msg.timestamp.isoformat() if msg.timestamp else None
                    }
                    for msg in reversed(messages)
                ]

            except Exception as e:
                logger.error(f"❌ Error getting conversation history: {e}")
                return []

    async def get_recent_conversations(
        self,
        user_id: str,
        limit: int = 10
    ) -> List[Dict]:
        """
        Get user's recent conversations (NON-BLOCKING).

        Args:
            user_id: User ID
            limit: Maximum conversations to return

        Returns:
            List of conversation dicts
        """
        from app.database.async_base import get_async_session

        async with get_async_session() as session:
            try:
                result = await session.execute(
                    select(Conversation)
                    .where(Conversation.user_id == user_id)
                    .order_by(desc(Conversation.last_message_at))
                    .limit(limit)
                )
                convs = result.scalars().all()

                return [
                    {
                        'conversation_id': conv.conversation_id,
                        'title': conv.title,
                        'message_count': conv.message_count or 0,
                        'created_at': conv.created_at.isoformat() if conv.created_at else None,
                        'last_message_at': conv.last_message_at.isoformat() if conv.last_message_at else None
                    }
                    for conv in convs
                ]

            except Exception as e:
                logger.error(f"❌ Error getting recent conversations: {e}")
                return []

    # ============ CONTEXT BUILDING ============

    async def get_personalized_context(
        self,
        user_id: str,
        task_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get user context for personalization (NON-BLOCKING).

        Args:
            user_id: User ID
            task_type: Optional task type filter

        Returns:
            Context dict with preferences and history
        """
        from app.database.async_base import get_async_session

        async with get_async_session() as session:
            try:
                # Get user preferences
                result = await session.execute(
                    select(UserPreference).where(UserPreference.user_id == user_id)
                )
                prefs = result.scalars().all()

                # Get recent task history
                query = select(TaskHistory).where(TaskHistory.user_id == user_id)
                if task_type:
                    query = query.where(TaskHistory.task_type == task_type)
                query = query.order_by(desc(TaskHistory.timestamp)).limit(10)

                result = await session.execute(query)
                tasks = result.scalars().all()

                # Get behavioral patterns
                result = await session.execute(
                    select(BehavioralPattern).where(BehavioralPattern.user_id == user_id)
                )
                patterns = result.scalars().all()

                return {
                    "user_id": user_id,
                    "preferences": {p.key: p.value for p in prefs},
                    "recent_tasks": [
                        {
                            "task_type": t.task_type,
                            "success": t.success,
                            "timestamp": t.timestamp.isoformat() if t.timestamp else None
                        }
                        for t in tasks
                    ],
                    "patterns": {p.pattern_type: p.pattern_data for p in patterns},
                    "task_type_filter": task_type
                }

            except Exception as e:
                logger.error(f"❌ Error getting personalized context: {e}")
                return {"user_id": user_id, "preferences": {}}

    # ============ LEARNING ============

    async def save_task(self, user_id: str, task_data: Dict) -> bool:
        """
        Save task history for learning (NON-BLOCKING).

        Args:
            user_id: User ID
            task_data: Task data dict

        Returns:
            True if saved successfully
        """
        from app.database.async_base import get_async_session

        async with get_async_session() as session:
            try:
                task = TaskHistory(
                    user_id=user_id,
                    conversation_id=task_data.get('conversation_id'),
                    task_type=task_data.get('task_type'),
                    description=task_data.get('description', ''),
                    agent_used=task_data.get('agent_used'),
                    iterations=task_data.get('iterations', 1),
                    success=task_data.get('success', False),
                    error_message=task_data.get('error'),
                    timestamp=datetime.now(timezone.utc)
                )
                session.add(task)
                await session.commit()

                logger.debug(f"📊 Task saved: {task_data.get('task_type')} for {user_id}")
                return True

            except Exception as e:
                await session.rollback()
                logger.error(f"❌ Error saving task: {e}")
                return False

    async def learn_from_behavior(self, user_id: str, behavior_data: Dict) -> bool:
        """
        Learn from user behavior (NON-BLOCKING).

        Args:
            user_id: User ID
            behavior_data: Behavior data dict

        Returns:
            True if saved successfully
        """
        from app.database.async_base import get_async_session

        async with get_async_session() as session:
            try:
                pattern_type = behavior_data.get('task_type', 'general')

                # Get existing pattern
                result = await session.execute(
                    select(BehavioralPattern).where(
                        BehavioralPattern.user_id == user_id,
                        BehavioralPattern.pattern_type == pattern_type
                    )
                )
                existing = result.scalar_one_or_none()

                if existing:
                    # Update existing pattern
                    current_data = existing.pattern_data or {}
                    # Merge new data
                    for key, value in behavior_data.items():
                        if key in current_data and isinstance(current_data[key], int):
                            current_data[key] = current_data[key] + 1
                        else:
                            current_data[key] = value
                    existing.pattern_data = current_data
                    existing.updated_at = datetime.now(timezone.utc)
                else:
                    # Create new pattern
                    pattern = BehavioralPattern(
                        user_id=user_id,
                        pattern_type=pattern_type,
                        pattern_data=behavior_data,
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc)
                    )
                    session.add(pattern)

                await session.commit()
                logger.debug(f"🧠 Behavior learned: {pattern_type} for {user_id}")
                return True

            except Exception as e:
                await session.rollback()
                logger.error(f"❌ Error learning behavior: {e}")
                return False

    # ============ PREFERENCES ============

    async def set_preference(self, user_id: str, key: str, value: Any) -> bool:
        """
        Set user preference (NON-BLOCKING).

        Args:
            user_id: User ID
            key: Preference key
            value: Preference value

        Returns:
            True if saved successfully
        """
        from app.database.async_base import get_async_session

        async with get_async_session() as session:
            try:
                # Check if preference exists
                result = await session.execute(
                    select(UserPreference).where(
                        UserPreference.user_id == user_id,
                        UserPreference.key == key
                    )
                )
                existing = result.scalar_one_or_none()

                if existing:
                    existing.value = str(value)
                    existing.updated_at = datetime.now(timezone.utc)
                else:
                    pref = UserPreference(
                        user_id=user_id,
                        key=key,
                        value=str(value),
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc)
                    )
                    session.add(pref)

                await session.commit()
                return True

            except Exception as e:
                await session.rollback()
                logger.error(f"❌ Error setting preference: {e}")
                return False

    async def get_preference(self, user_id: str, key: str, default: Any = None) -> Any:
        """
        Get user preference (NON-BLOCKING).

        Args:
            user_id: User ID
            key: Preference key
            default: Default value if not found

        Returns:
            Preference value or default
        """
        from app.database.async_base import get_async_session

        async with get_async_session() as session:
            try:
                result = await session.execute(
                    select(UserPreference).where(
                        UserPreference.user_id == user_id,
                        UserPreference.key == key
                    )
                )
                pref = result.scalar_one_or_none()

                return pref.value if pref else default

            except Exception as e:
                logger.error(f"❌ Error getting preference: {e}")
                return default


# Global instance
async_memory_service = AsyncMemoryService()
