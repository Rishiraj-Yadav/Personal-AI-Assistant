"""
Core Module Exports

Provides unified access to core functionality:
- Task execution abstraction (Phase 1)
- Security layer (Phase 2)
- LLM adapter
- Agent definitions
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
]
