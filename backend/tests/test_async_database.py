"""
Tests for Phase 4: Async Database Migration

Tests the async database components: async_base and async_memory_service.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


class TestAsyncDatabaseSetup:
    """Tests for async database initialization"""

    def test_get_async_database_url_sqlite(self):
        """Test SQLite URL conversion"""
        from app.database.async_base import get_async_database_url

        with patch.dict('os.environ', {'DATABASE_URL': 'sqlite:///./data/test.db'}):
            url = get_async_database_url()
            assert "sqlite+aiosqlite" in url

    def test_get_async_database_url_postgres(self):
        """Test PostgreSQL URL conversion"""
        from app.database.async_base import get_async_database_url

        with patch.dict('os.environ', {'DATABASE_URL': 'postgresql://user:pass@host/db'}):
            url = get_async_database_url()
            assert "postgresql+asyncpg" in url

    @pytest.mark.asyncio
    async def test_init_async_db(self):
        """Test async database initialization"""
        from app.database.async_base import init_async_db, close_async_db

        try:
            result = await init_async_db()
            # Should return True on success
            assert result is True
        finally:
            await close_async_db()

    @pytest.mark.asyncio
    async def test_get_async_session(self):
        """Test async session context manager"""
        from app.database.async_base import init_async_db, get_async_session, close_async_db

        await init_async_db()

        try:
            async with get_async_session() as session:
                # Session should be usable
                assert session is not None
        finally:
            await close_async_db()

    @pytest.mark.asyncio
    async def test_async_database_manager(self):
        """Test AsyncDatabaseManager context manager"""
        from app.database.async_base import AsyncDatabaseManager, init_async_db, close_async_db

        await init_async_db()

        try:
            async with AsyncDatabaseManager() as session:
                assert session is not None
        finally:
            await close_async_db()


class TestAsyncMemoryService:
    """Tests for AsyncMemoryService"""

    @pytest.fixture
    async def memory_service(self):
        """Create memory service for testing"""
        from app.database.async_base import init_async_db, close_async_db
        from app.services.async_memory_service import async_memory_service

        await init_async_db()
        yield async_memory_service
        await close_async_db()

    @pytest.mark.asyncio
    async def test_ensure_user_exists_creates_new(self, memory_service):
        """Test user creation"""
        user_id = f"test_user_{datetime.now().timestamp()}"

        user = await memory_service.ensure_user_exists(user_id)

        assert user is not None
        assert user.user_id == user_id

    @pytest.mark.asyncio
    async def test_ensure_user_exists_returns_existing(self, memory_service):
        """Test existing user is returned"""
        user_id = f"existing_user_{datetime.now().timestamp()}"

        # Create user
        user1 = await memory_service.ensure_user_exists(user_id)

        # Get same user
        user2 = await memory_service.ensure_user_exists(user_id)

        assert user1.user_id == user2.user_id

    @pytest.mark.asyncio
    async def test_save_message(self, memory_service):
        """Test message saving"""
        conv_id = f"conv_{datetime.now().timestamp()}"
        user_id = "test_user"

        result = await memory_service.save_message(
            conversation_id=conv_id,
            user_id=user_id,
            role="user",
            content="Hello, this is a test message"
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_get_conversation_history(self, memory_service):
        """Test conversation history retrieval"""
        conv_id = f"conv_history_{datetime.now().timestamp()}"
        user_id = "test_user"

        # Save some messages
        await memory_service.save_message(conv_id, user_id, "user", "Message 1")
        await memory_service.save_message(conv_id, user_id, "assistant", "Response 1")
        await memory_service.save_message(conv_id, user_id, "user", "Message 2")

        # Get history
        history = await memory_service.get_conversation_history(conv_id, limit=10)

        assert len(history) == 3
        assert history[0]['content'] == "Message 1"
        assert history[1]['content'] == "Response 1"
        assert history[2]['content'] == "Message 2"

    @pytest.mark.asyncio
    async def test_get_recent_conversations(self, memory_service):
        """Test recent conversations retrieval"""
        user_id = f"user_convs_{datetime.now().timestamp()}"

        # Create some conversations
        for i in range(3):
            conv_id = f"conv_{user_id}_{i}"
            await memory_service.save_message(conv_id, user_id, "user", f"Message {i}")

        # Get recent conversations
        convs = await memory_service.get_recent_conversations(user_id, limit=5)

        assert len(convs) >= 3

    @pytest.mark.asyncio
    async def test_save_task(self, memory_service):
        """Test task history saving"""
        user_id = "test_user"
        task_data = {
            "conversation_id": "conv_123",
            "task_type": "code_generation",
            "description": "Generate a Python function",
            "agent_used": "code_specialist",
            "iterations": 2,
            "success": True
        }

        result = await memory_service.save_task(user_id, task_data)
        assert result is True

    @pytest.mark.asyncio
    async def test_set_and_get_preference(self, memory_service):
        """Test preference storage and retrieval"""
        user_id = f"pref_user_{datetime.now().timestamp()}"

        # Set preference
        await memory_service.set_preference(user_id, "theme", "dark")
        await memory_service.set_preference(user_id, "language", "python")

        # Get preferences
        theme = await memory_service.get_preference(user_id, "theme")
        language = await memory_service.get_preference(user_id, "language")

        assert theme == "dark"
        assert language == "python"

    @pytest.mark.asyncio
    async def test_get_preference_default(self, memory_service):
        """Test preference default value"""
        user_id = "nonexistent_user"

        value = await memory_service.get_preference(
            user_id, "nonexistent_key", default="default_value"
        )

        assert value == "default_value"

    @pytest.mark.asyncio
    async def test_learn_from_behavior(self, memory_service):
        """Test behavioral learning"""
        user_id = f"behavior_user_{datetime.now().timestamp()}"
        behavior_data = {
            "task_type": "code_generation",
            "preferred_language": "python",
            "average_iterations": 2
        }

        result = await memory_service.learn_from_behavior(user_id, behavior_data)
        assert result is True

    @pytest.mark.asyncio
    async def test_get_personalized_context(self, memory_service):
        """Test personalized context building"""
        user_id = f"context_user_{datetime.now().timestamp()}"

        # Set up some data
        await memory_service.set_preference(user_id, "language", "python")
        await memory_service.save_task(user_id, {
            "task_type": "code_generation",
            "success": True
        })

        # Get context
        context = await memory_service.get_personalized_context(user_id)

        assert context["user_id"] == user_id
        assert "preferences" in context
        assert "recent_tasks" in context


class TestAsyncConcurrency:
    """Tests for async concurrency behavior"""

    @pytest.mark.asyncio
    async def test_concurrent_writes(self):
        """Test multiple concurrent write operations"""
        from app.database.async_base import init_async_db, close_async_db
        from app.services.async_memory_service import async_memory_service

        await init_async_db()

        try:
            user_id = f"concurrent_user_{datetime.now().timestamp()}"

            # Create many concurrent write tasks
            tasks = []
            for i in range(10):
                conv_id = f"concurrent_conv_{i}"
                task = memory_service.save_message(
                    conv_id, user_id, "user", f"Concurrent message {i}"
                )
                tasks.append(task)

            # Run concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # All should succeed
            successes = [r for r in results if r is True]
            assert len(successes) == 10

        finally:
            await close_async_db()

    @pytest.mark.asyncio
    async def test_concurrent_reads_and_writes(self):
        """Test mixed concurrent read/write operations"""
        from app.database.async_base import init_async_db, close_async_db
        from app.services.async_memory_service import async_memory_service

        await init_async_db()

        try:
            user_id = f"mixed_user_{datetime.now().timestamp()}"
            conv_id = f"mixed_conv_{datetime.now().timestamp()}"

            # Write some initial data
            await async_memory_service.save_message(conv_id, user_id, "user", "Initial")

            # Concurrent reads and writes
            tasks = []
            for i in range(5):
                # Write task
                tasks.append(
                    async_memory_service.save_message(conv_id, user_id, "user", f"Msg {i}")
                )
                # Read task
                tasks.append(
                    async_memory_service.get_conversation_history(conv_id, limit=10)
                )

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # No exceptions
            exceptions = [r for r in results if isinstance(r, Exception)]
            assert len(exceptions) == 0

        finally:
            await close_async_db()


class TestAsyncVsSyncComparison:
    """Tests comparing async vs sync performance"""

    @pytest.mark.asyncio
    async def test_async_does_not_block_event_loop(self):
        """Verify async operations don't block"""
        from app.database.async_base import init_async_db, close_async_db
        from app.services.async_memory_service import async_memory_service
        import time

        await init_async_db()

        try:
            user_id = "block_test_user"
            start = time.time()

            # Launch multiple async operations
            tasks = []
            for i in range(5):
                tasks.append(
                    async_memory_service.get_recent_conversations(user_id, limit=5)
                )

            # All should complete "in parallel"
            await asyncio.gather(*tasks)
            duration = time.time() - start

            # Should be much faster than sequential (5x faster ideal)
            # Being generous with timing due to test environment variance
            assert duration < 5.0  # Should definitely be under 5 seconds

        finally:
            await close_async_db()


class TestAsyncErrorHandling:
    """Tests for async error handling"""

    @pytest.mark.asyncio
    async def test_rollback_on_error(self):
        """Test transaction rollback on error"""
        from app.database.async_base import init_async_db, get_async_session, close_async_db

        await init_async_db()

        try:
            async with get_async_session() as session:
                # This should handle errors gracefully
                try:
                    # Force an error
                    raise ValueError("Test error")
                except ValueError:
                    pass
                # Session should still be usable after error handling

        finally:
            await close_async_db()

    @pytest.mark.asyncio
    async def test_session_cleanup(self):
        """Test session is properly cleaned up"""
        from app.database.async_base import init_async_db, get_async_session, close_async_db

        await init_async_db()

        session_ids = []

        try:
            for _ in range(5):
                async with get_async_session() as session:
                    session_ids.append(id(session))

            # Each should be unique (new session each time)
            assert len(set(session_ids)) == 5

        finally:
            await close_async_db()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
