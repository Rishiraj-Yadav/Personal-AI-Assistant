"""
Structured Logging Setup

Configures loguru for structured, queryable logging.
Supports JSON output for log aggregation systems.

Part of Phase 3: Observability Layer

Usage:
    from app.observability.logging import setup_logging, get_logger

    # Setup at application start
    setup_logging(level="INFO", json_output=True)

    # Get contextual logger
    logger = get_logger(__name__)
    logger.info("Processing task", task_id="123", user_id="user_1")
"""

import sys
import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Callable
from pathlib import Path
from loguru import logger


class LogConfig:
    """Logging configuration"""

    def __init__(
        self,
        level: str = "INFO",
        json_output: bool = False,
        log_file: Optional[str] = None,
        rotation: str = "10 MB",
        retention: str = "7 days",
        include_trace_id: bool = True,
        include_request_id: bool = True
    ):
        self.level = level.upper()
        self.json_output = json_output
        self.log_file = log_file
        self.rotation = rotation
        self.retention = retention
        self.include_trace_id = include_trace_id
        self.include_request_id = include_request_id


class StructuredLogger:
    """Wrapper for structured logging with context"""

    def __init__(self, name: str):
        self.name = name
        self._context: Dict[str, Any] = {}

    def bind(self, **kwargs) -> "StructuredLogger":
        """Bind context that will be included in all logs"""
        new_logger = StructuredLogger(self.name)
        new_logger._context = {**self._context, **kwargs}
        return new_logger

    def _log(self, level: str, message: str, **kwargs):
        """Internal log method"""
        extra = {
            "logger_name": self.name,
            **self._context,
            **kwargs
        }
        getattr(logger.bind(**extra), level)(message)

    def debug(self, message: str, **kwargs):
        self._log("debug", message, **kwargs)

    def info(self, message: str, **kwargs):
        self._log("info", message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._log("warning", message, **kwargs)

    def error(self, message: str, **kwargs):
        self._log("error", message, **kwargs)

    def critical(self, message: str, **kwargs):
        self._log("critical", message, **kwargs)

    def exception(self, message: str, **kwargs):
        """Log with exception info"""
        extra = {
            "logger_name": self.name,
            **self._context,
            **kwargs
        }
        logger.bind(**extra).exception(message)


def json_serializer(record: Dict[str, Any]) -> str:
    """
    Serialize log record to JSON.

    Formats log output for log aggregation systems (ELK, Loki, etc.)
    """
    subset = {
        "timestamp": record["time"].strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        "level": record["level"].name,
        "message": record["message"],
        "logger": record.get("extra", {}).get("logger_name", record["name"]),
        "module": record["module"],
        "function": record["function"],
        "line": record["line"],
    }

    # Add extra fields (structured data)
    extra = record.get("extra", {})
    for key, value in extra.items():
        if key != "logger_name" and not key.startswith("_"):
            # Handle non-serializable values
            try:
                json.dumps(value)
                subset[key] = value
            except (TypeError, ValueError):
                subset[key] = str(value)

    # Add exception info if present
    if record.get("exception"):
        exc = record["exception"]
        if exc.type:
            subset["exception"] = {
                "type": exc.type.__name__,
                "value": str(exc.value),
                "traceback": exc.traceback.split("\n") if exc.traceback else []
            }

    return json.dumps(subset, default=str)


def json_sink(message):
    """Write JSON log to stdout"""
    record = message.record
    serialized = json_serializer(record)
    sys.stdout.write(serialized + "\n")
    sys.stdout.flush()


def human_format(record: Dict[str, Any]) -> str:
    """
    Format log for human-readable console output.

    Includes colors and structured extra data.
    """
    # Base format
    base = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    # Add extra fields if present
    extra = record.get("extra", {})
    extra_fields = {k: v for k, v in extra.items()
                   if not k.startswith("_") and k != "logger_name"}

    if extra_fields:
        extra_str = " | " + " ".join(f"{k}={v}" for k, v in extra_fields.items())
        return base + extra_str + "\n"

    return base + "\n"


_logging_initialized = False


def setup_logging(config: LogConfig = None) -> bool:
    """
    Setup structured logging.

    Args:
        config: Logging configuration

    Returns:
        True if setup successful
    """
    global _logging_initialized

    if _logging_initialized:
        return True

    config = config or LogConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        json_output=os.getenv("LOG_JSON", "false").lower() == "true",
        log_file=os.getenv("LOG_FILE")
    )

    try:
        # Remove default handler
        logger.remove()

        # Add console handler
        if config.json_output:
            # JSON format for production
            logger.add(
                json_sink,
                level=config.level,
                colorize=False,
                serialize=False
            )
            logger.info("📋 JSON logging enabled")
        else:
            # Human-readable format for development
            logger.add(
                sys.stdout,
                format=human_format,
                level=config.level,
                colorize=True,
                diagnose=True
            )

        # Add file handler if configured
        if config.log_file:
            log_path = Path(config.log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            logger.add(
                str(log_path),
                format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
                level=config.level,
                rotation=config.rotation,
                retention=config.retention,
                compression="gz",
                serialize=config.json_output
            )
            logger.info(f"📁 File logging enabled: {log_path}")

        _logging_initialized = True
        logger.info(f"✅ Logging initialized: level={config.level}")

        return True

    except Exception as e:
        print(f"Failed to setup logging: {e}")
        return False


def get_logger(name: str) -> StructuredLogger:
    """
    Get a structured logger instance.

    Args:
        name: Logger name (usually __name__)

    Returns:
        StructuredLogger instance
    """
    return StructuredLogger(name)


def log_context(**context) -> Callable:
    """
    Decorator to add context to all logs within a function.

    Usage:
        @log_context(user_id="123", task_type="coding")
        async def process_task():
            logger.info("Processing...")  # Will include user_id and task_type

    Note: This uses loguru's contextvars support.
    """
    def decorator(func):
        import functools

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            with logger.contextualize(**context):
                return await func(*args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            with logger.contextualize(**context):
                return func(*args, **kwargs)

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


class RequestIdMiddleware:
    """
    Middleware to add request ID to logs.

    Usage (FastAPI):
        app.add_middleware(RequestIdMiddleware)
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        import uuid
        request_id = str(uuid.uuid4())[:8]

        # Add to scope for access in routes
        scope["request_id"] = request_id

        # Add to log context
        with logger.contextualize(request_id=request_id):
            await self.app(scope, receive, send)
