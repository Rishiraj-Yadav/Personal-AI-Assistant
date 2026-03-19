"""
Observability Module

Provides production monitoring capabilities:
- Distributed tracing (OpenTelemetry)
- Prometheus metrics
- Structured logging

Part of Phase 3: Observability Layer

Setup at application start:
    from app.observability import setup_observability

    setup_observability()
"""

from .tracing import (
    setup_tracing,
    get_tracer,
    trace_async,
    trace_sync,
    trace_block,
    TracingConfig
)

from .metrics import (
    metrics,
    MetricsCollector
)

from .logging import (
    setup_logging,
    get_logger,
    log_context,
    LogConfig,
    RequestIdMiddleware
)


def setup_observability(
    service_name: str = "sonarbot",
    log_level: str = "INFO",
    json_logs: bool = False,
    enable_tracing: bool = True,
    jaeger_enabled: bool = False
) -> bool:
    """
    Setup all observability components.

    Args:
        service_name: Service name for tracing
        log_level: Logging level
        json_logs: Enable JSON log output
        enable_tracing: Enable distributed tracing
        jaeger_enabled: Enable Jaeger export

    Returns:
        True if all components initialized
    """
    success = True

    # Setup logging first
    log_config = LogConfig(level=log_level, json_output=json_logs)
    if not setup_logging(log_config):
        success = False

    # Setup tracing
    if enable_tracing:
        tracing_config = TracingConfig(
            service_name=service_name,
            jaeger_enabled=jaeger_enabled
        )
        if not setup_tracing(tracing_config):
            success = False

    # Metrics are initialized on import

    return success


__all__ = [
    # Setup
    "setup_observability",
    # Tracing
    "setup_tracing",
    "get_tracer",
    "trace_async",
    "trace_sync",
    "trace_block",
    "TracingConfig",
    # Metrics
    "metrics",
    "MetricsCollector",
    # Logging
    "setup_logging",
    "get_logger",
    "log_context",
    "LogConfig",
    "RequestIdMiddleware",
]
