"""
Distributed Tracing Setup

Uses OpenTelemetry for distributed tracing.
Can export to Jaeger, Zipkin, Datadog, etc.

Part of Phase 3: Observability Layer

Usage:
    from app.observability.tracing import get_tracer, trace_async

    tracer = get_tracer(__name__)

    @trace_async("my_operation")
    async def my_function():
        ...

    # Or manual spans:
    with tracer.start_as_current_span("operation"):
        ...
"""

import os
import functools
from typing import Dict, Any, Optional, Callable, TypeVar
from contextlib import contextmanager
from loguru import logger

# Type variable for generic decorator
F = TypeVar('F', bound=Callable)

# Try to import OpenTelemetry, gracefully degrade if not installed
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.trace import Status, StatusCode
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    logger.warning("⚠️ OpenTelemetry not installed. Tracing disabled. Install with: pip install opentelemetry-sdk")

# Try to import Jaeger exporter
try:
    from opentelemetry.exporter.jaeger.thrift import JaegerExporter
    JAEGER_AVAILABLE = True
except ImportError:
    JAEGER_AVAILABLE = False


class TracingConfig:
    """Tracing configuration"""

    def __init__(
        self,
        service_name: str = "sonarbot",
        jaeger_enabled: bool = None,
        jaeger_host: str = None,
        jaeger_port: int = None,
        console_enabled: bool = False
    ):
        self.service_name = service_name
        self.jaeger_enabled = jaeger_enabled if jaeger_enabled is not None else \
            os.getenv("JAEGER_ENABLED", "false").lower() == "true"
        self.jaeger_host = jaeger_host or os.getenv("JAEGER_HOST", "localhost")
        self.jaeger_port = jaeger_port or int(os.getenv("JAEGER_PORT", "6831"))
        self.console_enabled = console_enabled


class TracingManager:
    """Manages tracing setup and tracer instances"""

    _instance: Optional["TracingManager"] = None
    _provider: Optional[Any] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def setup(self, config: TracingConfig = None) -> bool:
        """
        Setup tracing infrastructure.

        Args:
            config: Tracing configuration

        Returns:
            True if setup successful, False otherwise
        """
        if self._initialized:
            return True

        if not OTEL_AVAILABLE:
            logger.warning("⚠️ OpenTelemetry not available. Tracing disabled.")
            return False

        config = config or TracingConfig()

        try:
            # Create resource
            resource = Resource(attributes={
                SERVICE_NAME: config.service_name
            })

            # Create provider
            self._provider = TracerProvider(resource=resource)

            # Add Jaeger exporter if enabled
            if config.jaeger_enabled:
                if not JAEGER_AVAILABLE:
                    logger.warning("⚠️ Jaeger exporter not installed. Install with: pip install opentelemetry-exporter-jaeger")
                else:
                    jaeger_exporter = JaegerExporter(
                        agent_host_name=config.jaeger_host,
                        agent_port=config.jaeger_port
                    )
                    self._provider.add_span_processor(
                        BatchSpanProcessor(jaeger_exporter)
                    )
                    logger.info(f"📊 Jaeger tracing enabled: {config.jaeger_host}:{config.jaeger_port}")

            # Add console exporter if enabled (for debugging)
            if config.console_enabled:
                self._provider.add_span_processor(
                    BatchSpanProcessor(ConsoleSpanExporter())
                )
                logger.info("📊 Console tracing enabled")

            # Set global provider
            trace.set_tracer_provider(self._provider)

            self._initialized = True
            logger.info(f"✅ Tracing initialized for service: {config.service_name}")

            return True

        except Exception as e:
            logger.error(f"❌ Failed to setup tracing: {e}")
            return False

    def get_tracer(self, name: str):
        """Get a tracer instance"""
        if not OTEL_AVAILABLE:
            return NoOpTracer()

        if not self._initialized:
            self.setup()

        return trace.get_tracer(name)

    def shutdown(self):
        """Shutdown tracing"""
        if self._provider and hasattr(self._provider, 'shutdown'):
            self._provider.shutdown()
            logger.info("📊 Tracing shutdown complete")


class NoOpTracer:
    """No-op tracer for when OpenTelemetry is not available"""

    def start_as_current_span(self, name: str, **kwargs):
        return NoOpSpan()

    def start_span(self, name: str, **kwargs):
        return NoOpSpan()


class NoOpSpan:
    """No-op span context manager"""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def set_attribute(self, key: str, value: Any):
        pass

    def set_status(self, status: Any):
        pass

    def record_exception(self, exception: Exception):
        pass

    def end(self):
        pass


# Global manager instance
_tracing_manager = TracingManager()


def setup_tracing(config: TracingConfig = None) -> bool:
    """Setup tracing infrastructure"""
    return _tracing_manager.setup(config)


def get_tracer(name: str):
    """
    Get a tracer instance.

    Args:
        name: Tracer name (usually __name__)

    Returns:
        Tracer instance
    """
    return _tracing_manager.get_tracer(name)


def trace_async(span_name: str = None, attributes: Dict[str, Any] = None):
    """
    Decorator for tracing async functions.

    Args:
        span_name: Name for the span (defaults to function name)
        attributes: Additional span attributes

    Usage:
        @trace_async("process_task")
        async def process_task(request):
            ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            tracer = get_tracer(func.__module__)
            name = span_name or func.__name__

            if not OTEL_AVAILABLE:
                return await func(*args, **kwargs)

            with tracer.start_as_current_span(name) as span:
                # Set attributes
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)

                # Set function info
                span.set_attribute("function.name", func.__name__)
                span.set_attribute("function.module", func.__module__)

                try:
                    result = await func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    return result

                except Exception as e:
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.record_exception(e)
                    raise

        return wrapper
    return decorator


def trace_sync(span_name: str = None, attributes: Dict[str, Any] = None):
    """
    Decorator for tracing sync functions.

    Args:
        span_name: Name for the span (defaults to function name)
        attributes: Additional span attributes
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            tracer = get_tracer(func.__module__)
            name = span_name or func.__name__

            if not OTEL_AVAILABLE:
                return func(*args, **kwargs)

            with tracer.start_as_current_span(name) as span:
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)

                span.set_attribute("function.name", func.__name__)

                try:
                    result = func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    return result

                except Exception as e:
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.record_exception(e)
                    raise

        return wrapper
    return decorator


@contextmanager
def trace_block(name: str, attributes: Dict[str, Any] = None):
    """
    Context manager for tracing a block of code.

    Usage:
        with trace_block("database_query", {"table": "users"}):
            result = db.query(...)
    """
    tracer = get_tracer(__name__)

    if not OTEL_AVAILABLE:
        yield
        return

    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)

        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise
