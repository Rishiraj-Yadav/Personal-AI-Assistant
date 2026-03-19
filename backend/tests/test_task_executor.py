"""
Tests for Phase 1: TaskExecutor Abstraction

Tests the TaskExecutor interface, LocalTaskExecutor, and ExecutorFactory.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.task_executor import (
    TaskExecutor,
    TaskRequest,
    TaskResult,
    TaskType,
    TaskStatus
)
from app.core.local_task_executor import LocalTaskExecutor
from app.core.executor_factory import ExecutorFactory, ExecutorType


class TestTaskRequest:
    """Tests for TaskRequest dataclass"""

    def test_task_request_creation(self):
        """Test basic TaskRequest creation"""
        request = TaskRequest(
            task_type=TaskType.CODE_GENERATION,
            user_id="user_123",
            conversation_id="conv_456",
            message="Write a Python function"
        )

        assert request.task_type == TaskType.CODE_GENERATION
        assert request.user_id == "user_123"
        assert request.conversation_id == "conv_456"
        assert request.message == "Write a Python function"
        assert request.max_iterations == 3  # default

    def test_task_request_with_custom_iterations(self):
        """Test TaskRequest with custom max_iterations"""
        request = TaskRequest(
            task_type=TaskType.GENERAL_QUERY,
            user_id="user_1",
            conversation_id="conv_1",
            message="Hello",
            max_iterations=5
        )

        assert request.max_iterations == 5


class TestTaskResult:
    """Tests for TaskResult dataclass"""

    def test_task_result_success(self):
        """Test successful TaskResult"""
        result = TaskResult(
            success=True,
            task_type=TaskType.CODE_GENERATION,
            confidence=0.95,
            output="Here is your code...",
            code="def hello(): pass",
            agent_path=["router", "code_specialist"]
        )

        assert result.success is True
        assert result.confidence == 0.95
        assert result.code == "def hello(): pass"
        assert len(result.agent_path) == 2

    def test_task_result_failure(self):
        """Test failed TaskResult"""
        result = TaskResult(
            success=False,
            task_type=TaskType.DESKTOP_AUTOMATION,
            confidence=0.8,
            output="",
            error="Desktop agent not available"
        )

        assert result.success is False
        assert result.error == "Desktop agent not available"


class TestTaskType:
    """Tests for TaskType enum"""

    def test_task_types_exist(self):
        """Test all expected task types exist"""
        assert TaskType.CODE_GENERATION
        assert TaskType.DESKTOP_AUTOMATION
        assert TaskType.WEB_AUTOMATION
        assert TaskType.GENERAL_QUERY

    def test_task_type_values(self):
        """Test task type string values"""
        assert TaskType.CODE_GENERATION.value == "code_generation"
        assert TaskType.DESKTOP_AUTOMATION.value == "desktop_automation"


class TestLocalTaskExecutor:
    """Tests for LocalTaskExecutor"""

    @pytest.fixture
    def executor(self):
        """Create LocalTaskExecutor for testing"""
        return LocalTaskExecutor()

    @pytest.mark.asyncio
    async def test_health_check(self, executor):
        """Test health check returns correct structure"""
        health = await executor.health_check()

        assert "status" in health
        assert "executor_type" in health
        assert health["executor_type"] == "local"

    @pytest.mark.asyncio
    async def test_execute_with_mock_orchestrator(self, executor):
        """Test execute method with mocked orchestrator"""
        request = TaskRequest(
            task_type=TaskType.GENERAL_QUERY,
            user_id="test_user",
            conversation_id="test_conv",
            message="Hello world"
        )

        # Mock the orchestrator
        mock_result = {
            "success": True,
            "task_type": "general",
            "confidence": 0.9,
            "output": "Hello! How can I help?",
            "agent_path": ["router", "general_assistant"],
            "metadata": {}
        }

        with patch.object(
            executor.orchestrator, 'process',
            new_callable=AsyncMock, return_value=mock_result
        ):
            result = await executor.execute(request)

            assert result.success is True
            assert "Hello" in result.output

    def test_get_status_unknown_task(self, executor):
        """Test get_status for unknown task"""
        status = executor.get_status("unknown_task_id")
        assert status == TaskStatus.UNKNOWN


class TestExecutorFactory:
    """Tests for ExecutorFactory"""

    def test_get_local_executor(self):
        """Test getting local executor"""
        with patch.dict('os.environ', {'SONARBOT_EXECUTOR_TYPE': 'local'}):
            executor = ExecutorFactory.get_executor()
            assert isinstance(executor, LocalTaskExecutor)

    def test_get_executor_default(self):
        """Test default executor is local"""
        with patch.dict('os.environ', {}, clear=True):
            executor = ExecutorFactory.get_executor()
            assert isinstance(executor, LocalTaskExecutor)

    def test_executor_singleton(self):
        """Test factory returns same instance"""
        # Reset singleton
        ExecutorFactory._instance = None

        executor1 = ExecutorFactory.get_executor()
        executor2 = ExecutorFactory.get_executor()

        assert executor1 is executor2

    def test_reset_executor(self):
        """Test reset creates new instance"""
        executor1 = ExecutorFactory.get_executor()
        ExecutorFactory.reset()
        executor2 = ExecutorFactory.get_executor()

        assert executor1 is not executor2


class TestTaskTypeDetection:
    """Tests for task type detection logic"""

    def test_code_keywords(self):
        """Test code-related keywords are detected"""
        from app.api.routes.multi_agent import _determine_task_type

        assert _determine_task_type("write python code") == TaskType.CODE_GENERATION
        assert _determine_task_type("create a react component") == TaskType.CODE_GENERATION
        assert _determine_task_type("fix this bug") == TaskType.CODE_GENERATION

    def test_desktop_keywords(self):
        """Test desktop-related keywords are detected"""
        from app.api.routes.multi_agent import _determine_task_type

        assert _determine_task_type("click the button") == TaskType.DESKTOP_AUTOMATION
        assert _determine_task_type("open the file manager") == TaskType.DESKTOP_AUTOMATION
        assert _determine_task_type("take a screenshot") == TaskType.DESKTOP_AUTOMATION

    def test_web_keywords(self):
        """Test web-related keywords are detected"""
        from app.api.routes.multi_agent import _determine_task_type

        assert _determine_task_type("browse to google.com") == TaskType.WEB_AUTOMATION
        assert _determine_task_type("search online for python") == TaskType.WEB_AUTOMATION
        assert _determine_task_type("scrape the website") == TaskType.WEB_AUTOMATION

    def test_general_query(self):
        """Test general queries default correctly"""
        from app.api.routes.multi_agent import _determine_task_type

        assert _determine_task_type("what is the weather?") == TaskType.GENERAL_QUERY
        assert _determine_task_type("hello") == TaskType.GENERAL_QUERY


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
