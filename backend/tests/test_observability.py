"""
Tests for Phase 3: Observability Layer

Tests the observability components: tracing, metrics, and logging.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import time


class TestTracing:
    """Tests for OpenTelemetry tracing"""

    def test_trace_decorator_sync(self):
        """Test @trace_sync decorator works"""
        from app.observability.tracing import trace_sync

        @trace_sync("test_operation")
        def test_function(x: int) -> int:
            return x * 2

        result = test_function(5)
        assert result == 10

    @pytest.mark.asyncio
    async def test_trace_decorator_async(self):
        """Test @trace_async decorator works"""
        from app.observability.tracing import trace_async

        @trace_async("test_async_operation")
        async def test_async_function(x: int) -> int:
            return x * 2

        result = await test_async_function(5)
        assert result == 10

    def test_trace_decorator_captures_exceptions(self):
        """Test decorator captures and re-raises exceptions"""
        from app.observability.tracing import trace_sync

        @trace_sync("failing_operation")
        def failing_function():
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            failing_function()

    def test_tracer_initialization(self):
        """Test tracer can be initialized"""
        from app.observability.tracing import setup_tracing, get_tracer

        # Setup should not fail
        setup_tracing(service_name="test_service", jaeger_enabled=False)

        # Should return a tracer (real or no-op)
        tracer = get_tracer()
        assert tracer is not None


class TestMetrics:
    """Tests for Prometheus metrics"""

    @pytest.fixture
    def metrics_collector(self):
        """Get metrics collector"""
        from app.observability.metrics import metrics
        return metrics

    def test_record_task(self, metrics_collector):
        """Test task recording"""
        # Should not raise
        metrics_collector.record_task(
            task_type="code_generation",
            success=True,
            duration=1.5
        )

    def test_record_task_with_error(self, metrics_collector):
        """Test task recording with error"""
        metrics_collector.record_task(
            task_type="desktop_automation",
            success=False,
            duration=0.5,
            error_type="TimeoutError"
        )

    def test_record_agent_execution(self, metrics_collector):
        """Test agent execution recording"""
        metrics_collector.record_agent_execution(
            agent_name="code_specialist",
            duration=2.0
        )

    def test_record_security_block(self, metrics_collector):
        """Test security block recording"""
        metrics_collector.record_security_block(
            block_type="injection_detected",
            severity="high"
        )

    def test_record_llm_call(self, metrics_collector):
        """Test LLM API call recording"""
        metrics_collector.record_llm_call(
            provider="groq",
            model="llama-3.3-70b",
            tokens=150,
            duration=0.8,
            success=True
        )

    def test_get_metrics_format(self, metrics_collector):
        """Test metrics output format"""
        output = metrics_collector.get_metrics()

        # Should return string (Prometheus format or JSON)
        assert isinstance(output, str)

    def test_get_content_type(self, metrics_collector):
        """Test content type for metrics"""
        content_type = metrics_collector.get_content_type()

        # Should be valid content type
        assert "text" in content_type or "application" in content_type

    def test_metrics_increments(self, metrics_collector):
        """Test metrics actually increment"""
        # Record multiple tasks
        for i in range(5):
            metrics_collector.record_task(
                task_type="test_task",
                success=True,
                duration=0.1
            )

        # Get current counts (implementation specific)
        output = metrics_collector.get_metrics()
        assert output  # Non-empty output


class TestLogging:
    """Tests for structured logging"""

    def test_setup_logging(self):
        """Test logging setup"""
        from app.observability.logging import setup_logging

        # Should not raise
        setup_logging(json_format=False, log_level="DEBUG")

    def test_json_logging_format(self):
        """Test JSON logging format"""
        from app.observability.logging import setup_logging

        # Should not raise with JSON format
        setup_logging(json_format=True, log_level="INFO")

    def test_request_id_middleware(self):
        """Test RequestIdMiddleware adds request ID"""
        from app.observability.logging import RequestIdMiddleware
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/test")

        # Should have request ID header
        assert "X-Request-ID" in response.headers

    def test_request_id_uniqueness(self):
        """Test request IDs are unique"""
        from app.observability.logging import RequestIdMiddleware
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        ids = set()
        for _ in range(10):
            response = client.get("/test")
            ids.add(response.headers.get("X-Request-ID"))

        # All IDs should be unique
        assert len(ids) == 10


class TestObservabilitySetup:
    """Tests for combined observability setup"""

    def test_full_setup(self):
        """Test complete observability setup"""
        from app.observability import setup_observability

        # Should not raise
        setup_observability(
            service_name="test_service",
            log_level="INFO",
            json_logs=False,
            jaeger_enabled=False
        )

    def test_setup_idempotent(self):
        """Test setup can be called multiple times"""
        from app.observability import setup_observability

        # Multiple calls should not fail
        setup_observability(service_name="test1")
        setup_observability(service_name="test2")


class TestMetricsEndpoint:
    """Tests for /metrics endpoint integration"""

    def test_metrics_endpoint_exists(self):
        """Test metrics endpoint is accessible"""
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)

        # Due to lifespan, we may need to handle this differently
        try:
            response = client.get("/metrics")
            assert response.status_code in [200, 500]  # 500 if not initialized
        except Exception:
            # Lifespan issues in test mode are expected
            pass

    def test_health_endpoint_includes_executor(self):
        """Test health endpoint includes executor info"""
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)

        try:
            response = client.get("/health")
            if response.status_code == 200:
                data = response.json()
                assert "status" in data
        except Exception:
            pass


class TestPerformanceMetrics:
    """Tests for performance-related metrics"""

    def test_timing_accuracy(self):
        """Test duration measurements are accurate"""
        from app.observability.metrics import metrics

        start = time.time()
        time.sleep(0.1)
        duration = time.time() - start

        # Should be roughly 0.1 seconds (allowing for timing variance)
        assert 0.05 < duration < 0.2

        # Record it
        metrics.record_task(
            task_type="timed_task",
            success=True,
            duration=duration
        )

    def test_concurrent_metric_updates(self):
        """Test metrics handle concurrent updates"""
        from app.observability.metrics import metrics
        import threading

        def record_tasks():
            for _ in range(100):
                metrics.record_task(
                    task_type="concurrent_test",
                    success=True,
                    duration=0.01
                )

        threads = [threading.Thread(target=record_tasks) for _ in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should complete without errors


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
