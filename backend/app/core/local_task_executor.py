"""
Local Task Executor

Runs tasks in the same process (current behavior).
Wraps existing LangGraph orchestrator code.

Part of Phase 1: TaskExecutor Abstraction
"""

import time
import uuid
from typing import Dict, Any, Optional, Callable
from loguru import logger

from .task_executor import (
    TaskExecutor,
    TaskRequest,
    TaskResult,
    TaskType,
    TaskStatus,
    TaskExecutionError
)


class LocalTaskExecutor(TaskExecutor):
    """
    Execute tasks locally in FastAPI process.

    This wraps the existing LangGraph orchestrator,
    allowing future migration to Celery without changing agent code.
    """

    def __init__(self):
        """Initialize local executor"""
        # Lazy import to avoid circular dependencies
        self._orchestrator = None
        self._task_status: Dict[str, Dict[str, Any]] = {}
        logger.info("✅ LocalTaskExecutor initialized")

    @property
    def orchestrator(self):
        """Lazy load orchestrator to avoid import issues"""
        if self._orchestrator is None:
            from app.agents.langgraph_orchestrator import langgraph_orchestrator
            self._orchestrator = langgraph_orchestrator
        return self._orchestrator

    async def execute(
        self,
        request: TaskRequest,
        progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None
    ) -> TaskResult:
        """
        Execute task using existing LangGraph orchestrator.

        Maps TaskRequest → orchestrator.process() → TaskResult
        """
        # Generate task ID for tracking
        task_id = request.request_id or str(uuid.uuid4())
        start_time = time.time()

        # Track task status
        self._task_status[task_id] = {
            "status": TaskStatus.RUNNING,
            "progress": 0.0,
            "current_step": "starting",
            "error": None
        }

        try:
            logger.info(f"🚀 LocalTaskExecutor: {request.task_type.value} [task_id={task_id}]")

            # Update status
            self._task_status[task_id]["current_step"] = "calling_orchestrator"
            self._task_status[task_id]["progress"] = 0.1

            # Call existing LangGraph orchestrator
            orchestrator_result = await self.orchestrator.process(
                user_message=request.message,
                user_id=request.user_id,
                conversation_id=request.conversation_id,
                max_iterations=request.max_iterations,
                message_callback=progress_callback
            )

            # Update status
            self._task_status[task_id]["progress"] = 0.9
            self._task_status[task_id]["current_step"] = "building_result"

            # Calculate execution time
            execution_time = time.time() - start_time

            # Map orchestrator response to TaskResult
            result = TaskResult(
                success=orchestrator_result.get("success", False),
                output=orchestrator_result.get("output", ""),
                task_type=request.task_type,
                metadata=orchestrator_result.get("metadata", {}),
                error=orchestrator_result.get("metadata", {}).get("error"),

                # Code generation specific
                code=orchestrator_result.get("code"),
                files=orchestrator_result.get("files"),
                project_structure=orchestrator_result.get("project_structure"),
                project_path=orchestrator_result.get("file_path"),

                # Server specific
                server_running=orchestrator_result.get("server_running", False),
                server_url=orchestrator_result.get("server_url"),
                server_port=orchestrator_result.get("server_port"),

                # Web agent specific
                web_screenshots=orchestrator_result.get("metadata", {}).get("web_screenshots", []),
                web_current_url=orchestrator_result.get("metadata", {}).get("web_current_url"),

                # Tracking
                agent_path=orchestrator_result.get("agent_path", []),
                confidence=orchestrator_result.get("confidence", 0.0),
                execution_time=execution_time
            )

            # Update final status
            self._task_status[task_id] = {
                "status": TaskStatus.COMPLETED,
                "progress": 1.0,
                "current_step": "completed",
                "error": None
            }

            logger.info(
                f"✅ Task completed: {request.task_type.value} "
                f"[success={result.success}, time={execution_time:.2f}s]"
            )

            return result

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = str(e)

            # Update error status
            self._task_status[task_id] = {
                "status": TaskStatus.FAILED,
                "progress": 0.0,
                "current_step": "failed",
                "error": error_msg
            }

            logger.error(f"❌ LocalTaskExecutor failed: {error_msg}")

            return TaskResult(
                success=False,
                output="",
                task_type=request.task_type,
                metadata={"error": error_msg},
                error=error_msg,
                execution_time=execution_time
            )

    async def health_check(self) -> Dict[str, Any]:
        """
        Health check - always OK for local execution.

        In future, could check:
        - Memory usage
        - CPU usage
        - Active task count
        """
        active_tasks = sum(
            1 for status in self._task_status.values()
            if status["status"] == TaskStatus.RUNNING
        )

        return {
            "status": "healthy",
            "type": "local",
            "workers": 1,
            "active_tasks": active_tasks,
            "details": {
                "orchestrator": "langgraph",
                "execution_mode": "in_process"
            }
        }

    async def get_status(self, task_id: str) -> Dict[str, Any]:
        """Get status of a specific task"""
        if task_id not in self._task_status:
            return {
                "status": TaskStatus.PENDING,
                "progress": 0.0,
                "current_step": "unknown",
                "error": "Task not found"
            }

        return self._task_status[task_id]

    def clear_completed_tasks(self, max_age_seconds: int = 3600):
        """
        Clean up old completed/failed task statuses.

        Call periodically to prevent memory leaks.
        """
        # Note: Would need timestamps to implement properly
        # For now, clear all completed/failed tasks
        to_remove = [
            task_id for task_id, status in self._task_status.items()
            if status["status"] in [TaskStatus.COMPLETED, TaskStatus.FAILED]
        ]

        for task_id in to_remove:
            del self._task_status[task_id]

        if to_remove:
            logger.info(f"🧹 Cleared {len(to_remove)} completed task statuses")
