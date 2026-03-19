"""
Prometheus Metrics

Custom metrics for system monitoring.
Exported via /metrics endpoint.

Part of Phase 3: Observability Layer

Usage:
    from app.observability.metrics import metrics

    # Record task execution
    metrics.record_task("coding", success=True, duration=5.2)

    # Record agent execution
    metrics.record_agent("code_specialist")

    # Record security event
    metrics.record_security_block("injection_detected")

Metrics exposed:
    - sonarbot_tasks_total: Task counter by type and status
    - sonarbot_task_duration_seconds: Task duration histogram
    - sonarbot_agent_executions_total: Agent execution counter
    - sonarbot_security_blocks_total: Security block counter
    - sonarbot_llm_api_calls_total: LLM API call counter
    - sonarbot_llm_tokens_total: Token usage counter
    - sonarbot_active_tasks: Active task gauge
"""

import time
import os
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from loguru import logger

# Try to import prometheus_client, gracefully degrade if not installed
try:
    from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest, REGISTRY
    from prometheus_client import CONTENT_TYPE_LATEST
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning("⚠️ prometheus_client not installed. Metrics disabled. Install with: pip install prometheus-client")


@dataclass
class MetricValue:
    """In-memory metric value for fallback"""
    name: str
    value: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class MetricsCollector:
    """
    Collects and exposes Prometheus metrics.

    Falls back to in-memory counters if prometheus_client not available.
    """

    def __init__(self, prefix: str = "sonarbot"):
        """
        Initialize metrics collector.

        Args:
            prefix: Metric name prefix
        """
        self.prefix = prefix
        self._initialized = False

        # In-memory fallback storage
        self._fallback_metrics: Dict[str, MetricValue] = {}

        if PROMETHEUS_AVAILABLE:
            self._init_prometheus_metrics()
        else:
            logger.warning("📊 Using in-memory metrics fallback")

    def _init_prometheus_metrics(self):
        """Initialize Prometheus metrics"""
        try:
            # Task metrics
            self.task_counter = Counter(
                f"{self.prefix}_tasks_total",
                "Total tasks executed",
                ["task_type", "status"]
            )

            self.task_duration = Histogram(
                f"{self.prefix}_task_duration_seconds",
                "Task execution duration in seconds",
                ["task_type"],
                buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0]
            )

            self.task_errors = Counter(
                f"{self.prefix}_task_errors_total",
                "Total task errors",
                ["task_type", "error_type"]
            )

            self.active_tasks = Gauge(
                f"{self.prefix}_active_tasks",
                "Currently active tasks",
                ["task_type"]
            )

            # Agent metrics
            self.agent_executions = Counter(
                f"{self.prefix}_agent_executions_total",
                "Agent executions by type",
                ["agent"]
            )

            self.agent_duration = Histogram(
                f"{self.prefix}_agent_duration_seconds",
                "Agent execution duration",
                ["agent"],
                buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
            )

            # Security metrics
            self.security_blocks = Counter(
                f"{self.prefix}_security_blocks_total",
                "Security check blocks",
                ["reason"]
            )

            self.security_warnings = Counter(
                f"{self.prefix}_security_warnings_total",
                "Security check warnings",
                ["reason"]
            )

            self.injection_attempts = Counter(
                f"{self.prefix}_injection_attempts_total",
                "Injection attack attempts detected",
                ["injection_type"]
            )

            # LLM metrics
            self.llm_api_calls = Counter(
                f"{self.prefix}_llm_api_calls_total",
                "LLM API calls",
                ["provider", "model"]
            )

            self.llm_tokens = Counter(
                f"{self.prefix}_llm_tokens_total",
                "LLM tokens consumed",
                ["provider", "token_type"]
            )

            self.llm_latency = Histogram(
                f"{self.prefix}_llm_latency_seconds",
                "LLM API latency",
                ["provider"],
                buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0]
            )

            self.llm_errors = Counter(
                f"{self.prefix}_llm_errors_total",
                "LLM API errors",
                ["provider", "error_type"]
            )

            # System info
            self.system_info = Info(
                f"{self.prefix}_system",
                "System information"
            )
            self.system_info.info({
                "version": os.getenv("SONARBOT_VERSION", "0.4.0"),
                "environment": os.getenv("ENVIRONMENT", "development")
            })

            self._initialized = True
            logger.info("✅ Prometheus metrics initialized")

        except Exception as e:
            logger.error(f"❌ Failed to initialize Prometheus metrics: {e}")
            self._initialized = False

    def record_task(
        self,
        task_type: str,
        success: bool,
        duration: float,
        error_type: Optional[str] = None
    ):
        """
        Record task execution.

        Args:
            task_type: Type of task (coding, desktop, web, general)
            success: Whether task succeeded
            duration: Execution duration in seconds
            error_type: Error type if failed
        """
        status = "success" if success else "failure"

        if PROMETHEUS_AVAILABLE and self._initialized:
            self.task_counter.labels(task_type=task_type, status=status).inc()
            self.task_duration.labels(task_type=task_type).observe(duration)

            if not success and error_type:
                self.task_errors.labels(task_type=task_type, error_type=error_type).inc()
        else:
            # Fallback
            key = f"task_{task_type}_{status}"
            self._increment_fallback(key)

    def record_agent(self, agent_name: str, duration: Optional[float] = None):
        """
        Record agent execution.

        Args:
            agent_name: Name of the agent
            duration: Execution duration in seconds
        """
        if PROMETHEUS_AVAILABLE and self._initialized:
            self.agent_executions.labels(agent=agent_name).inc()
            if duration is not None:
                self.agent_duration.labels(agent=agent_name).observe(duration)
        else:
            key = f"agent_{agent_name}"
            self._increment_fallback(key)

    def record_security_block(self, reason: str):
        """Record security block event"""
        if PROMETHEUS_AVAILABLE and self._initialized:
            self.security_blocks.labels(reason=reason).inc()
        else:
            self._increment_fallback(f"security_block_{reason}")

    def record_security_warning(self, reason: str):
        """Record security warning event"""
        if PROMETHEUS_AVAILABLE and self._initialized:
            self.security_warnings.labels(reason=reason).inc()
        else:
            self._increment_fallback(f"security_warning_{reason}")

    def record_injection_attempt(self, injection_type: str):
        """Record injection attempt"""
        if PROMETHEUS_AVAILABLE and self._initialized:
            self.injection_attempts.labels(injection_type=injection_type).inc()
        else:
            self._increment_fallback(f"injection_{injection_type}")

    def record_llm_call(
        self,
        provider: str,
        model: str,
        latency: float,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        error: Optional[str] = None
    ):
        """
        Record LLM API call.

        Args:
            provider: LLM provider (groq, gemini, openai)
            model: Model name
            latency: API latency in seconds
            input_tokens: Input token count
            output_tokens: Output token count
            error: Error type if failed
        """
        if PROMETHEUS_AVAILABLE and self._initialized:
            self.llm_api_calls.labels(provider=provider, model=model).inc()
            self.llm_latency.labels(provider=provider).observe(latency)

            if input_tokens:
                self.llm_tokens.labels(provider=provider, token_type="input").inc(input_tokens)
            if output_tokens:
                self.llm_tokens.labels(provider=provider, token_type="output").inc(output_tokens)
            if error:
                self.llm_errors.labels(provider=provider, error_type=error).inc()
        else:
            self._increment_fallback(f"llm_{provider}")

    def set_active_tasks(self, task_type: str, count: int):
        """Set active task count"""
        if PROMETHEUS_AVAILABLE and self._initialized:
            self.active_tasks.labels(task_type=task_type).set(count)

    def _increment_fallback(self, key: str, value: float = 1.0):
        """Increment fallback metric"""
        if key not in self._fallback_metrics:
            self._fallback_metrics[key] = MetricValue(name=key)
        self._fallback_metrics[key].value += value
        self._fallback_metrics[key].timestamp = time.time()

    def get_metrics(self) -> bytes:
        """
        Get metrics in Prometheus format.

        Returns:
            Metrics as bytes (for HTTP response)
        """
        if PROMETHEUS_AVAILABLE:
            return generate_latest(REGISTRY)
        else:
            # Generate simple text format for fallback
            lines = []
            for key, metric in self._fallback_metrics.items():
                lines.append(f"# HELP {key} Fallback metric")
                lines.append(f"# TYPE {key} counter")
                lines.append(f"{key} {metric.value}")
            return "\n".join(lines).encode()

    def get_content_type(self) -> str:
        """Get metrics content type"""
        if PROMETHEUS_AVAILABLE:
            return CONTENT_TYPE_LATEST
        else:
            return "text/plain; charset=utf-8"

    def get_stats(self) -> Dict[str, Any]:
        """Get metrics as dictionary (for health check)"""
        if not PROMETHEUS_AVAILABLE:
            return {
                "available": False,
                "fallback_metrics": {
                    k: v.value for k, v in self._fallback_metrics.items()
                }
            }

        # Prometheus metrics are exposed via /metrics endpoint
        return {
            "available": True,
            "initialized": self._initialized,
            "prefix": self.prefix
        }


# Global metrics instance
metrics = MetricsCollector()
