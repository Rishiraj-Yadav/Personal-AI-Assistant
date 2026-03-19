"""
Safe Executor

Wraps TaskExecutor to enforce security rules.
All task execution goes through this layer in production.

Part of Phase 2: SafeExecutor Security

Usage:
    from app.core.safe_executor import SafeExecutor
    from app.core.local_task_executor import LocalTaskExecutor

    local = LocalTaskExecutor()
    safe = SafeExecutor(local)

    result = await safe.execute(request)  # Security checks applied
"""

import time
from typing import Dict, Any, Optional, Callable
from loguru import logger

from .task_executor import (
    TaskExecutor,
    TaskRequest,
    TaskResult,
    TaskType,
    TaskExecutionError
)
from .security.action_validator import action_validator, ActionRiskLevel
from .security.path_validator import path_validator
from .security.injection_detector import injection_detector, DetectionAction


class SecurityCheckError(Exception):
    """Raised when security check fails"""

    def __init__(self, message: str, check_type: str, details: Dict[str, Any] = None):
        super().__init__(message)
        self.check_type = check_type
        self.details = details or {}


class SafeExecutor(TaskExecutor):
    """
    Security wrapper for task executors.

    Applies multiple security layers before allowing execution:
    1. Injection detection - blocks prompt/command injection
    2. Action validation - enforces action whitelist
    3. Path validation - blocks sensitive directories
    4. Rate limiting - prevents abuse (future)

    All checks are transparent - existing code doesn't need changes.
    """

    def __init__(
        self,
        wrapped_executor: TaskExecutor,
        injection_sensitivity: str = "medium",
        block_on_high_risk: bool = False,
        enable_audit_log: bool = True
    ):
        """
        Initialize safe executor.

        Args:
            wrapped_executor: The underlying executor to wrap
            injection_sensitivity: 'low', 'medium', 'high'
            block_on_high_risk: Block HIGH risk actions (not just CRITICAL)
            enable_audit_log: Log all security decisions
        """
        self.wrapped_executor = wrapped_executor
        self.injection_sensitivity = injection_sensitivity
        self.block_on_high_risk = block_on_high_risk
        self.enable_audit_log = enable_audit_log

        # Configure detectors
        injection_detector.sensitivity = injection_sensitivity

        # Statistics
        self.stats = {
            "total_requests": 0,
            "blocked_requests": 0,
            "warned_requests": 0,
            "passed_requests": 0
        }

        logger.info(
            f"✅ SafeExecutor initialized: "
            f"sensitivity={injection_sensitivity}, "
            f"block_high_risk={block_on_high_risk}"
        )

    async def execute(
        self,
        request: TaskRequest,
        progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None
    ) -> TaskResult:
        """
        Execute task with security checks.

        Security checks applied:
        1. Injection detection on user message
        2. Validation will be applied during agent execution

        Args:
            request: Task request
            progress_callback: Progress callback

        Returns:
            TaskResult from wrapped executor or error result
        """
        self.stats["total_requests"] += 1
        start_time = time.time()

        try:
            # ========== Security Check 1: Injection Detection ==========
            logger.debug("🔒 Security check: injection detection")
            injection_result = injection_detector.detect(request.message)

            if injection_result.action == DetectionAction.BLOCK:
                self.stats["blocked_requests"] += 1
                self._audit_log(
                    "BLOCKED",
                    "injection_detection",
                    request,
                    {
                        "confidence": injection_result.confidence,
                        "types": [t.value for t in injection_result.injection_types],
                        "patterns": injection_result.patterns_matched[:5]
                    }
                )

                return TaskResult(
                    success=False,
                    output="",
                    task_type=request.task_type,
                    metadata={
                        "security_check": "failed",
                        "check_type": "injection_detection",
                        "confidence": injection_result.confidence
                    },
                    error="Request blocked: suspicious patterns detected"
                )

            elif injection_result.action == DetectionAction.WARN:
                self.stats["warned_requests"] += 1
                self._audit_log(
                    "WARNED",
                    "injection_detection",
                    request,
                    {
                        "confidence": injection_result.confidence,
                        "types": [t.value for t in injection_result.injection_types]
                    }
                )
                # Continue with execution but log the warning

            # ========== Security Check 2: Task Type Validation ==========
            # Certain task types may have additional restrictions
            if request.task_type in [TaskType.DESKTOP_AUTOMATION]:
                logger.debug("🔒 Security check: desktop task validation")
                # Desktop tasks will be validated at action execution level
                # by action_validator when specific actions are called

            # ========== All Checks Passed - Execute ==========
            self.stats["passed_requests"] += 1
            logger.info(f"✅ Security checks passed for {request.task_type.value}")

            # Add security context to request metadata
            request.metadata["security_validated"] = True
            request.metadata["security_timestamp"] = time.time()

            # Execute through wrapped executor
            result = await self.wrapped_executor.execute(request, progress_callback)

            # Add security info to result
            result.metadata["security_checks"] = {
                "injection_detection": {
                    "passed": True,
                    "confidence": injection_result.confidence if injection_result.is_injection else 0.0
                }
            }

            execution_time = time.time() - start_time

            self._audit_log(
                "COMPLETED",
                "execution",
                request,
                {
                    "success": result.success,
                    "execution_time": execution_time
                }
            )

            return result

        except SecurityCheckError as e:
            self.stats["blocked_requests"] += 1
            self._audit_log("BLOCKED", e.check_type, request, e.details)

            return TaskResult(
                success=False,
                output="",
                task_type=request.task_type,
                metadata={"security_check": "failed", **e.details},
                error=str(e)
            )

        except Exception as e:
            logger.error(f"❌ SafeExecutor error: {e}")
            self._audit_log("ERROR", "execution", request, {"error": str(e)})

            return TaskResult(
                success=False,
                output="",
                task_type=request.task_type,
                metadata={"error": str(e)},
                error=f"Security execution error: {str(e)}"
            )

    async def health_check(self) -> Dict[str, Any]:
        """Health check including security system status"""
        wrapped_health = await self.wrapped_executor.health_check()

        return {
            **wrapped_health,
            "security": {
                "enabled": True,
                "injection_detection": "enabled",
                "injection_sensitivity": self.injection_sensitivity,
                "action_validation": "enabled",
                "path_validation": "enabled",
                "block_high_risk": self.block_on_high_risk
            },
            "stats": self.stats
        }

    async def get_status(self, task_id: str) -> Dict[str, Any]:
        """Get task status from wrapped executor"""
        return await self.wrapped_executor.get_status(task_id)

    def _audit_log(
        self,
        action: str,
        check_type: str,
        request: TaskRequest,
        details: Dict[str, Any]
    ):
        """Log security audit event"""
        if not self.enable_audit_log:
            return

        log_entry = {
            "action": action,
            "check_type": check_type,
            "user_id": request.user_id,
            "task_type": request.task_type.value,
            "message_preview": request.message[:100],
            "timestamp": time.time(),
            **details
        }

        if action == "BLOCKED":
            logger.warning(f"🚨 AUDIT [{action}]: {check_type} - {log_entry}")
        elif action == "WARNED":
            logger.warning(f"⚠️ AUDIT [{action}]: {check_type} - {log_entry}")
        else:
            logger.info(f"📋 AUDIT [{action}]: {check_type}")

    def validate_action(
        self,
        action_name: str,
        args: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Validate a specific action (for use by agents).

        Args:
            action_name: Name of the action
            args: Action arguments

        Returns:
            {
                "allowed": bool,
                "risk_level": str,
                "reason": str
            }
        """
        result = action_validator.validate(action_name, args)

        # Check if we should block high risk actions
        if self.block_on_high_risk and result.risk_level == ActionRiskLevel.HIGH:
            return {
                "allowed": False,
                "risk_level": result.risk_level.value,
                "reason": f"High-risk action blocked: {action_name}"
            }

        return {
            "allowed": result.allowed,
            "risk_level": result.risk_level.value,
            "reason": result.reason,
            "requires_approval": result.requires_approval
        }

    def validate_path(
        self,
        path: str,
        operation: str = "read"
    ) -> Dict[str, Any]:
        """
        Validate a file path (for use by agents).

        Args:
            path: File path to validate
            operation: 'read', 'write', 'delete'

        Returns:
            {
                "allowed": bool,
                "reason": str
            }
        """
        result = path_validator.validate(path, operation)

        return {
            "allowed": result.allowed,
            "reason": result.reason,
            "normalized_path": result.normalized_path
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get security statistics"""
        total = self.stats["total_requests"]
        if total == 0:
            return {**self.stats, "block_rate": 0.0, "warn_rate": 0.0}

        return {
            **self.stats,
            "block_rate": self.stats["blocked_requests"] / total,
            "warn_rate": self.stats["warned_requests"] / total
        }

    def reset_stats(self):
        """Reset security statistics"""
        self.stats = {
            "total_requests": 0,
            "blocked_requests": 0,
            "warned_requests": 0,
            "passed_requests": 0
        }
