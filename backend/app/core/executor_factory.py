"""
Task Executor Factory

Factory pattern for creating task executors.
Allows switching implementations without changing application code.

Part of Phase 1: TaskExecutor Abstraction

Usage:
    # Get default executor (based on configuration)
    executor = ExecutorFactory.get_executor()

    # Or specify type explicitly
    ExecutorFactory.set_type(ExecutorType.SAFE)
    executor = ExecutorFactory.get_executor()
"""

import os
from enum import Enum
from typing import Optional
from loguru import logger

from .task_executor import TaskExecutor


class ExecutorType(str, Enum):
    """Available executor implementations"""
    LOCAL = "local"         # Direct execution in process
    SAFE = "safe"           # With security wrapper (Phase 2)
    CELERY = "celery"       # Distributed workers (future)


class ExecutorFactory:
    """
    Factory for creating task executors.

    Singleton pattern ensures consistent executor usage across application.
    """

    _instance: Optional[TaskExecutor] = None
    _executor_type: ExecutorType = ExecutorType.LOCAL
    _initialized: bool = False

    @classmethod
    def set_type(cls, executor_type: ExecutorType):
        """
        Configure which executor to use.

        Must be called before first get_executor() call,
        or after reset() to change executor type.

        Args:
            executor_type: The type of executor to create
        """
        if cls._initialized and cls._executor_type != executor_type:
            logger.warning(
                f"⚠️ Changing executor type from {cls._executor_type} to {executor_type}. "
                "Call reset() first to apply changes."
            )
        cls._executor_type = executor_type
        logger.info(f"📋 Executor type set to: {executor_type}")

    @classmethod
    def get_executor(cls) -> TaskExecutor:
        """
        Get or create executor instance.

        Returns the singleton executor instance.
        Creates it on first call based on configured type.

        Returns:
            TaskExecutor implementation
        """
        if cls._instance is None:
            cls._instance = cls._create_executor()
            cls._initialized = True

        return cls._instance

    @classmethod
    def _create_executor(cls) -> TaskExecutor:
        """Create executor based on configured type"""
        logger.info(f"🏭 Creating {cls._executor_type} executor...")

        if cls._executor_type == ExecutorType.LOCAL:
            from .local_task_executor import LocalTaskExecutor
            return LocalTaskExecutor()

        elif cls._executor_type == ExecutorType.SAFE:
            # Phase 2: SafeExecutor wraps LocalTaskExecutor
            try:
                from .safe_executor import SafeExecutor
                from .local_task_executor import LocalTaskExecutor

                local = LocalTaskExecutor()
                return SafeExecutor(local)
            except ImportError:
                # SafeExecutor not yet implemented, fall back to local
                logger.warning(
                    "⚠️ SafeExecutor not available, falling back to LocalTaskExecutor"
                )
                from .local_task_executor import LocalTaskExecutor
                return LocalTaskExecutor()

        elif cls._executor_type == ExecutorType.CELERY:
            # Future: CeleryTaskExecutor
            raise NotImplementedError(
                "Celery executor not yet implemented. "
                "Use LOCAL or SAFE executor type."
            )

        else:
            raise ValueError(f"Unknown executor type: {cls._executor_type}")

    @classmethod
    def reset(cls):
        """
        Reset factory state.

        Call this to recreate executor with new configuration.
        Useful for testing or runtime reconfiguration.
        """
        cls._instance = None
        cls._initialized = False
        logger.info("🔄 ExecutorFactory reset")

    @classmethod
    def get_type(cls) -> ExecutorType:
        """Get current executor type"""
        return cls._executor_type


def get_executor_from_env() -> ExecutorType:
    """
    Determine executor type from environment.

    Environment variable: SONARBOT_EXECUTOR_TYPE
    Values: local, safe, celery

    Defaults to SAFE for production safety.
    """
    env_type = os.getenv("SONARBOT_EXECUTOR_TYPE", "local").lower()

    type_map = {
        "local": ExecutorType.LOCAL,
        "safe": ExecutorType.SAFE,
        "celery": ExecutorType.CELERY,
    }

    return type_map.get(env_type, ExecutorType.LOCAL)


# Configure from environment on module load
_env_executor_type = get_executor_from_env()
ExecutorFactory.set_type(_env_executor_type)


# Convenience function for getting executor
def get_task_executor() -> TaskExecutor:
    """
    Get the configured task executor.

    Convenience wrapper around ExecutorFactory.get_executor().
    """
    return ExecutorFactory.get_executor()


# Create singleton instance for import
# Usage: from app.core.executor_factory import task_executor
task_executor = ExecutorFactory.get_executor()
