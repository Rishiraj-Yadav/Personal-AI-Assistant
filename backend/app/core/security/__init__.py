"""
Security Module

Provides security validation for task execution:
- Action validation (whitelist, risk levels)
- Path validation (block sensitive directories)
- Injection detection (prompt injection, command injection)

Part of Phase 2: SafeExecutor Security
"""

from .action_validator import (
    ActionValidator,
    ActionRiskLevel,
    ActionValidationResult,
    action_validator
)

from .path_validator import (
    PathValidator,
    PathValidationResult,
    path_validator
)

from .injection_detector import (
    InjectionDetector,
    InjectionType,
    DetectionAction,
    InjectionDetectionResult,
    injection_detector
)

__all__ = [
    # Action Validator
    "ActionValidator",
    "ActionRiskLevel",
    "ActionValidationResult",
    "action_validator",
    # Path Validator
    "PathValidator",
    "PathValidationResult",
    "path_validator",
    # Injection Detector
    "InjectionDetector",
    "InjectionType",
    "DetectionAction",
    "InjectionDetectionResult",
    "injection_detector",
]
