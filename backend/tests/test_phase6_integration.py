"""
Phase 6 Integration Tests
=========================

Tests for the production-grade OpenClaw architecture:
- Master Intent Router with confidence thresholds
- Task State Machine transitions
- Execution Feedback Loop
- Predictive Context Manager
- Fast Path Handler integration
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Phase 6 Core Components
from app.core.master_router import (
    MasterIntentRouter,
    RoutingDecision,
    RoutingPath,
    TaskType,
    get_master_router,
)

from app.core.task_state_machine import (
    TaskStateMachine,
    TaskState,
    TaskTransition,
    TaskContext,
    get_task_state_machine,
)

from app.core.execution_feedback import (
    ExecutionFeedback,
    FeedbackStatus,
    FeedbackLoop,
    get_feedback_loop,
)

from app.core.predictive_context import (
    PredictiveContextManager,
    PredictiveContext,
    get_predictive_context_manager,
)


class TestMasterIntentRouter:
    """Tests for the Master Intent Router."""
    
    def test_router_initialization(self):
        """Test router initializes correctly."""
        router = MasterIntentRouter()
        assert router is not None
        assert router.FAST_PATH_THRESHOLD == 0.8
        assert router.DISAMBIGUATION_THRESHOLD == 0.5
    
    def test_fast_path_open_folder(self):
        """Test fast path matching for 'open folder' commands."""
        router = MasterIntentRouter()
        
        decision = router.route("open my python project folder")
        
        assert decision.task_type == TaskType.DESKTOP_ACTION
        assert decision.confidence >= 0.9
        assert decision.routing_path == RoutingPath.FAST_DESKTOP
        assert decision.action == "fs.open"
        assert "python" in decision.target.lower()
    
    def test_fast_path_app_launch(self):
        """Test fast path matching for app launch commands."""
        router = MasterIntentRouter()
        
        decision = router.route("launch vs code")
        
        assert decision.task_type == TaskType.DESKTOP_ACTION
        assert decision.confidence >= 0.9
        assert decision.action == "app.launch"
        assert "vscode" in decision.target.lower() or "code" in decision.target.lower()
    
    def test_fast_path_website(self):
        """Test fast path matching for website opening."""
        router = MasterIntentRouter()
        
        decision = router.route("open youtube")
        
        assert decision.task_type == TaskType.DESKTOP_ACTION
        assert decision.confidence >= 0.9
        assert decision.action == "web.open"
        assert "youtube" in decision.target.lower()
    
    def test_fast_path_screenshot(self):
        """Test fast path matching for screenshot."""
        router = MasterIntentRouter()
        
        decision = router.route("take a screenshot")
        
        assert decision.task_type == TaskType.DESKTOP_ACTION
        assert decision.confidence >= 0.95
        assert decision.action == "screen.capture"
    
    def test_disambiguation_path(self):
        """Test disambiguation for ambiguous queries."""
        router = MasterIntentRouter()
        
        # Fallback classification with medium confidence
        decision = router.route("do something with files")
        
        # Should fall into disambiguation or full orchestration
        assert decision.confidence < 0.8
    
    def test_context_based_resolution(self):
        """Test target resolution using context."""
        router = MasterIntentRouter()
        
        context = {
            "active_project": "/Users/dev/MyPythonApp",
            "recent_paths": ["/Users/dev/MyPythonApp", "/Users/dev/Documents"],
        }
        
        decision = router.route("open my project", context=context)
        
        # Should resolve "project" to active_project from context
        if decision.routing_path == RoutingPath.FAST_DESKTOP:
            assert decision.target == "/Users/dev/MyPythonApp"


class TestTaskStateMachine:
    """Tests for the Task State Machine."""
    
    def test_create_task(self):
        """Test task creation."""
        machine = TaskStateMachine()
        
        task = machine.create_task(
            user_message="open folder",
            session_id="test-session",
            conversation_id="test-conv"
        )
        
        assert task.task_id is not None
        assert task.current_state == TaskState.PENDING
        assert task.user_message == "open folder"
    
    def test_task_transitions(self):
        """Test valid state transitions."""
        machine = TaskStateMachine()
        
        task = machine.create_task("test message")
        
        # PENDING → VALIDATING
        assert machine.transition(task.task_id, TaskTransition.START)
        assert machine.get_task(task.task_id).current_state == TaskState.VALIDATING
        
        # VALIDATING → ROUTING
        assert machine.transition(task.task_id, TaskTransition.VALIDATE)
        assert machine.get_task(task.task_id).current_state == TaskState.ROUTING
        
        # ROUTING → EXECUTING
        assert machine.transition(task.task_id, TaskTransition.ROUTE)
        assert machine.get_task(task.task_id).current_state == TaskState.EXECUTING
        
        # EXECUTING → VERIFYING
        assert machine.transition(task.task_id, TaskTransition.EXECUTE)
        assert machine.get_task(task.task_id).current_state == TaskState.VERIFYING
        
        # VERIFYING → COMPLETED
        assert machine.transition(task.task_id, TaskTransition.VERIFY)
        assert machine.get_task(task.task_id).current_state == TaskState.COMPLETED
    
    def test_invalid_transition(self):
        """Test invalid state transitions are rejected."""
        machine = TaskStateMachine()
        
        task = machine.create_task("test message")
        
        # Cannot COMPLETE directly from PENDING
        assert not machine.transition(task.task_id, TaskTransition.COMPLETE)
        assert machine.get_task(task.task_id).current_state == TaskState.PENDING
    
    def test_task_failure(self):
        """Test task failure path."""
        machine = TaskStateMachine()
        
        task = machine.create_task("test message")
        
        machine.transition(task.task_id, TaskTransition.START)
        machine.transition(task.task_id, TaskTransition.VALIDATE)
        
        # Fail from ROUTING
        assert machine.transition(task.task_id, TaskTransition.FAIL, {"error": "test error"})
        
        task = machine.get_task(task.task_id)
        assert task.current_state == TaskState.FAILED
        assert task.error == "test error"
    
    def test_task_chain(self):
        """Test chained tasks for continuity."""
        machine = TaskStateMachine()
        
        # Parent task
        parent = machine.create_task("create file")
        
        # Child task
        child = machine.create_task(
            "edit file",
            parent_task_id=parent.task_id
        )
        
        assert child.parent_task_id == parent.task_id
        
        # Get chain
        chain = machine.get_task_chain(child.task_id)
        assert len(chain) == 2


class TestExecutionFeedback:
    """Tests for the Execution Feedback Loop."""
    
    def test_successful_execution(self):
        """Test feedback for successful execution."""
        loop = FeedbackLoop()
        
        feedback = loop.process(
            action="fs.open",
            target="/test/path",
            execution_result={"success": True},
            execution_time_ms=50.0
        )
        
        assert feedback.status == FeedbackStatus.SUCCESS
        assert feedback.action == "fs.open"
        assert feedback.is_success
    
    def test_failed_execution(self):
        """Test feedback for failed execution."""
        loop = FeedbackLoop()
        
        feedback = loop.process(
            action="fs.open",
            target="/nonexistent",
            execution_result={"success": False, "error": "Path not found"},
            execution_time_ms=10.0
        )
        
        assert feedback.status in [FeedbackStatus.FAILED, FeedbackStatus.NEEDS_FALLBACK]
        assert not feedback.is_success
        assert feedback.error == "Path not found"
    
    def test_context_updates(self):
        """Test context updates from successful actions."""
        updates_received = []
        
        def capture_updates(updates):
            updates_received.append(updates)
        
        loop = FeedbackLoop(context_updater=capture_updates)
        
        # Mock the file existence check
        with patch('os.path.isdir', return_value=True):
            with patch('os.listdir', return_value=['file.py']):
                feedback = loop.process(
                    action="fs.open",
                    target="/Users/dev/project",
                    execution_result={"success": True},
                    execution_time_ms=30.0
                )
        
        # Should have called context updater
        assert len(updates_received) > 0
    
    def test_fallback_trigger(self):
        """Test fallback callback when action fails."""
        fallback_triggered = []
        
        def on_fallback(feedback):
            fallback_triggered.append(feedback)
        
        loop = FeedbackLoop(on_fallback=on_fallback)
        
        feedback = loop.process(
            action="fs.open",
            target="/nonexistent",
            execution_result={"success": False, "error": "File not found"},
            execution_time_ms=5.0
        )
        
        if feedback.needs_fallback:
            assert len(fallback_triggered) > 0


class TestPredictiveContext:
    """Tests for the Predictive Context Manager."""
    
    def test_context_initialization(self):
        """Test context manager initializes correctly."""
        manager = PredictiveContextManager()
        
        context = manager.get_context()
        assert "recent_paths" in context
        assert "frequent_paths" in context
    
    def test_context_update(self):
        """Test context updates."""
        manager = PredictiveContextManager()
        
        manager.update({
            "last_folder": "/Users/dev/project",
            "add_recent_path": "/Users/dev/project"
        })
        
        context = manager.get_context()
        assert context["last_folder"] == "/Users/dev/project"
        assert "/Users/dev/project" in context["recent_paths"]
    
    def test_path_frequency(self):
        """Test path frequency tracking."""
        manager = PredictiveContextManager()
        
        # Access same path multiple times
        for _ in range(5):
            manager.update({"last_folder": "/Users/dev/frequently-used"})
        
        context = manager.get_context()
        assert "/Users/dev/frequently-used" in context["frequent_paths"]
    
    def test_path_suggestions(self):
        """Test path suggestions based on query."""
        manager = PredictiveContextManager()
        
        manager.update({"add_recent_path": "/Users/dev/python-project"})
        manager.update({"add_recent_path": "/Users/dev/node-project"})
        
        suggestions = manager.suggest_paths("python", limit=5)
        
        # Should suggest paths containing "python"
        assert any("python" in s.lower() for s in suggestions)
    
    def test_current_task(self):
        """Test current task tracking."""
        manager = PredictiveContextManager()
        
        manager.set_current_task("Debugging API endpoint")
        
        context = manager.get_context()
        assert context["current_task"] == "Debugging API endpoint"
        
        manager.clear_current_task()
        context = manager.get_context()
        assert context["current_task"] is None


class TestEndToEndFlow:
    """End-to-end integration tests."""
    
    @pytest.mark.asyncio
    async def test_fast_path_desktop_command(self):
        """Test the full flow for a fast-path desktop command."""
        # This would require mocking the HTTP client
        # For now, just test the routing logic
        
        router = MasterIntentRouter()
        machine = TaskStateMachine()
        context_manager = PredictiveContextManager()
        
        # 1. Classify
        decision = router.route(
            "open my downloads folder",
            context=context_manager.get_context_for_resolution()
        )
        
        # 2. Create task
        task = machine.create_task("open my downloads folder")
        
        # 3. Run through state machine
        machine.transition(task.task_id, TaskTransition.START)
        machine.transition(task.task_id, TaskTransition.VALIDATE)
        machine.transition(task.task_id, TaskTransition.ROUTE, {
            "routing_decision": decision.to_dict()
        })
        
        # Verify routing
        assert decision.routing_path == RoutingPath.FAST_DESKTOP
        assert machine.get_task(task.task_id).current_state == TaskState.EXECUTING


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
