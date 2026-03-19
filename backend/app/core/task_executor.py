"""
Abstract Task Executor Interface

This is the foundation for architecture flexibility.
- Currently: runs tasks locally (LocalTaskExecutor)
- Later: can swap to Celery without changing agent code

Part of Phase 1: TaskExecutor Abstraction
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class TaskType(str, Enum):
    """Task classifications matching router agent categories"""
    CODE_GENERATION = "coding"
    DESKTOP_AUTOMATION = "desktop"
    WEB_AUTOMATION = "web"
    GENERAL_QUERY = "general"
    SLASH_COMMAND = "slash_command"


class TaskStatus(str, Enum):
    """Task execution status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskRequest:
    """
    Unified task request format.

    All agents receive tasks in this format, regardless of
    where they execute (local, Celery, cloud function).
    """
    task_type: TaskType
    user_id: str
    conversation_id: str
    message: str
    context: Optional[Dict[str, Any]] = None
    max_iterations: int = 5
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Tracking
    created_at: datetime = field(default_factory=datetime.now)
    request_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "task_type": self.task_type.value,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "message": self.message,
            "context": self.context,
            "max_iterations": self.max_iterations,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "request_id": self.request_id
        }


@dataclass
class TaskResult:
    """
    Unified task result format.

    All agents return results in this format.
    """
    success: bool
    output: str
    task_type: TaskType
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    # Code generation specific
    code: Optional[str] = None
    files: Optional[Dict[str, str]] = None
    project_structure: Optional[Dict[str, Any]] = None
    project_path: Optional[str] = None

    # Server specific
    server_running: bool = False
    server_url: Optional[str] = None
    server_port: Optional[int] = None

    # Web agent specific
    web_screenshots: List[str] = field(default_factory=list)
    web_current_url: Optional[str] = None

    # Tracking
    agent_path: List[str] = field(default_factory=list)
    confidence: float = 0.0
    execution_time: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response"""
        return {
            "success": self.success,
            "output": self.output,
            "task_type": self.task_type.value,
            "metadata": self.metadata,
            "error": self.error,
            "code": self.code,
            "files": self.files,
            "project_structure": self.project_structure,
            "project_path": self.project_path,
            "server_running": self.server_running,
            "server_url": self.server_url,
            "server_port": self.server_port,
            "web_screenshots": self.web_screenshots,
            "web_current_url": self.web_current_url,
            "agent_path": self.agent_path,
            "confidence": self.confidence,
            "execution_time": self.execution_time
        }


class TaskExecutor(ABC):
    """
    Abstract base class for task execution.

    Abstracts WHERE tasks run:
    - LocalTaskExecutor: Same process (current implementation)
    - CeleryTaskExecutor: Distributed workers (future)
    - CloudTaskExecutor: Cloud functions (future)

    All implementations must follow this interface.
    """

    @abstractmethod
    async def execute(
        self,
        request: TaskRequest,
        progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None
    ) -> TaskResult:
        """
        Execute a task.

        Args:
            request: TaskRequest with all context needed
            progress_callback: Optional async callback for streaming updates
                              Signature: async def callback(data: dict) -> None

        Returns:
            TaskResult with execution outcome

        Raises:
            TaskExecutionError: If execution fails critically
        """
        pass

    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """
        Check executor health status.

        Returns:
            {
                "status": "healthy" | "degraded" | "unhealthy",
                "type": str,  # executor type
                "workers": int,  # number of workers
                "details": {...}  # additional info
            }
        """
        pass

    @abstractmethod
    async def get_status(self, task_id: str) -> Dict[str, Any]:
        """
        Get status of a specific task.

        Args:
            task_id: The task identifier

        Returns:
            {
                "status": TaskStatus,
                "progress": float,  # 0.0 to 1.0
                "current_step": str,
                "error": str | None
            }
        """
        pass


class TaskExecutionError(Exception):
    """Raised when task execution fails critically"""

    def __init__(self, message: str, task_type: TaskType, details: Dict[str, Any] = None):
        super().__init__(message)
        self.task_type = task_type
        self.details = details or {}
