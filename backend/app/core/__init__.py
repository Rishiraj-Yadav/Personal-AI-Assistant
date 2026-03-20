"""
Core Module Exports

Provides unified access to core functionality:
- Task execution abstraction (Phase 1)
- Security layer (Phase 2)
- LLM adapter
- Agent definitions
- Phase 6: Production-grade routing and orchestration
"""

# Task Executor Abstraction (Phase 1)
from .task_executor import (
    TaskExecutor,
    TaskRequest,
    TaskResult,
    TaskType,
    TaskStatus,
    TaskExecutionError
)

from .local_task_executor import LocalTaskExecutor

from .executor_factory import (
    ExecutorFactory,
    ExecutorType,
    get_task_executor,
    task_executor
)

# Existing core modules
from .llm import llm_adapter

# Phase 6: Production-grade routing and orchestration
from .master_router import (
    MasterIntentRouter,
    RoutingDecision,
    RoutingPath,
    TaskType as Phase6TaskType,
    get_master_router,
)

from .task_state_machine import (
    TaskStateMachine,
    TaskState,
    TaskTransition,
    TaskContext,
    get_task_state_machine,
)

from .execution_feedback import (
    ExecutionFeedback,
    FeedbackStatus,
    FeedbackLoop,
    ActionCategory,
    get_feedback_loop,
)

from .predictive_context import (
    PredictiveContextManager,
    PredictiveContext,
    get_predictive_context_manager,
)

__all__ = [
    # Task Executor
    "TaskExecutor",
    "TaskRequest",
    "TaskResult",
    "TaskType",
    "TaskStatus",
    "TaskExecutionError",
    "LocalTaskExecutor",
    "ExecutorFactory",
    "ExecutorType",
    "get_task_executor",
    "task_executor",
    # LLM
    "llm_adapter",
    # Phase 6: Master Router
    "MasterIntentRouter",
    "RoutingDecision",
    "RoutingPath",
    "Phase6TaskType",
    "get_master_router",
    # Phase 6: Task State Machine
    "TaskStateMachine",
    "TaskState",
    "TaskTransition",
    "TaskContext",
    "get_task_state_machine",
    # Phase 6: Execution Feedback
    "ExecutionFeedback",
    "FeedbackStatus",
    "FeedbackLoop",
    "ActionCategory",
    "get_feedback_loop",
    # Phase 6: Predictive Context
    "PredictiveContextManager",
    "PredictiveContext",
    "get_predictive_context_manager",
]
