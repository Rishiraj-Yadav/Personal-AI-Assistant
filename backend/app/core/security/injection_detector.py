"""
Injection Detector

Detects prompt injection and command injection attempts.
Prevents malicious users from bypassing safety rules.

Part of Phase 2: SafeExecutor Security
"""

import re
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum
from loguru import logger


class InjectionType(str, Enum):
    """Types of injection attacks"""
    PROMPT_OVERRIDE = "prompt_override"
    ROLE_MANIPULATION = "role_manipulation"
    JAILBREAK = "jailbreak"
    COMMAND_INJECTION = "command_injection"
    SQL_INJECTION = "sql_injection"
    PATH_INJECTION = "path_injection"


class DetectionAction(str, Enum):
    """Actions to take on detection"""
    ALLOW = "allow"      # Allow the request
    WARN = "warn"        # Allow but log warning
    BLOCK = "block"      # Block the request
    ALERT = "alert"      # Block and send alert


@dataclass
class InjectionDetectionResult:
    """Result of injection detection"""
    is_injection: bool
    action: DetectionAction
    confidence: float  # 0.0 to 1.0
    injection_types: List[InjectionType] = field(default_factory=list)
    patterns_matched: List[str] = field(default_factory=list)
    sanitized_text: Optional[str] = None
    details: str = ""


class InjectionDetector:
    """
    Detects injection attacks in user input.

    Checks for:
    - Prompt injection (override instructions)
    - Role manipulation (pretend to be system)
    - Jailbreak attempts (DAN mode, etc.)
    - Command injection (shell commands)
    - SQL injection
    - Path injection
    """

    # Pattern groups with (pattern, injection_type, weight)
    DETECTION_PATTERNS: List[Tuple[str, InjectionType, float]] = [
        # Prompt override attempts (high priority)
        (r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|rules|prompts)", InjectionType.PROMPT_OVERRIDE, 0.9),
        (r"disregard\s+(all|everything|any)\s+(above|previous|prior)", InjectionType.PROMPT_OVERRIDE, 0.9),
        (r"forget\s+(everything|all|what)\s+(you\s+)?(were|have\s+been)\s+told", InjectionType.PROMPT_OVERRIDE, 0.9),
        (r"from\s+now\s+on[,\s]+(you\s+)?(will|must|should|are)", InjectionType.PROMPT_OVERRIDE, 0.7),
        (r"new\s+instructions?:?\s*", InjectionType.PROMPT_OVERRIDE, 0.6),
        (r"override\s+(previous|system|all)", InjectionType.PROMPT_OVERRIDE, 0.8),

        # Role manipulation
        (r"(you\s+are|act\s+as|pretend\s+to\s+be|behave\s+as)\s+(a\s+)?system", InjectionType.ROLE_MANIPULATION, 0.8),
        (r"(you\s+are|act\s+as)\s+now\s+(a\s+)?(different|new)", InjectionType.ROLE_MANIPULATION, 0.7),
        (r"^(system|admin|root)\s*:", InjectionType.ROLE_MANIPULATION, 0.9),
        (r"\[system\s*(message|prompt)?\]", InjectionType.ROLE_MANIPULATION, 0.8),
        (r"<\s*system\s*>", InjectionType.ROLE_MANIPULATION, 0.8),

        # Jailbreak attempts
        (r"DAN\s+(mode|prompt)", InjectionType.JAILBREAK, 0.95),
        (r"(developer|debug|god|admin)\s+mode", InjectionType.JAILBREAK, 0.85),
        (r"unlock(ed)?\s+(mode|potential|capabilities)", InjectionType.JAILBREAK, 0.8),
        (r"bypass\s+(filter|safety|restriction|rules)", InjectionType.JAILBREAK, 0.9),
        (r"disable\s+(safety|filter|censorship)", InjectionType.JAILBREAK, 0.9),
        (r"no\s+(rules|restrictions|limits|boundaries)", InjectionType.JAILBREAK, 0.7),
        (r"(anything|everything)\s+is\s+(allowed|permitted)", InjectionType.JAILBREAK, 0.75),

        # System prompt extraction
        (r"(show|reveal|display|print|tell)\s+(me\s+)?(your|the)\s+(system\s+)?prompt", InjectionType.PROMPT_OVERRIDE, 0.8),
        (r"what\s+(is|are)\s+your\s+(system\s+)?(instructions|rules|prompt)", InjectionType.PROMPT_OVERRIDE, 0.7),
        (r"(repeat|echo|output)\s+(your|the)\s+(system|initial)\s+(prompt|instructions)", InjectionType.PROMPT_OVERRIDE, 0.85),

        # Command injection patterns
        (r";\s*(rm|del|delete|format)\s+", InjectionType.COMMAND_INJECTION, 0.95),
        (r"\|\s*(bash|sh|cmd|powershell)", InjectionType.COMMAND_INJECTION, 0.95),
        (r"&&\s*(curl|wget|nc|netcat)", InjectionType.COMMAND_INJECTION, 0.9),
        (r"`[^`]*`", InjectionType.COMMAND_INJECTION, 0.5),  # Backtick execution
        (r"\$\([^)]*\)", InjectionType.COMMAND_INJECTION, 0.6),  # $(command)
        (r">\s*/dev/", InjectionType.COMMAND_INJECTION, 0.9),
        (r">\s*[A-Z]:\\", InjectionType.COMMAND_INJECTION, 0.8),

        # SQL injection patterns
        (r"'\s*OR\s*'1'\s*=\s*'1", InjectionType.SQL_INJECTION, 0.95),
        (r"'\s*OR\s+1\s*=\s*1", InjectionType.SQL_INJECTION, 0.9),
        (r";\s*DROP\s+(TABLE|DATABASE)", InjectionType.SQL_INJECTION, 0.95),
        (r";\s*DELETE\s+FROM", InjectionType.SQL_INJECTION, 0.9),
        (r"UNION\s+(ALL\s+)?SELECT", InjectionType.SQL_INJECTION, 0.85),
        (r"--\s*$", InjectionType.SQL_INJECTION, 0.3),  # SQL comment (low weight alone)

        # Path injection patterns
        (r"\.\.[/\\]", InjectionType.PATH_INJECTION, 0.8),
        (r"[/\\](etc|var|sys|proc)[/\\]", InjectionType.PATH_INJECTION, 0.7),
        (r"[A-Z]:\\Windows\\", InjectionType.PATH_INJECTION, 0.8),
        (r"[A-Z]:\\System32\\", InjectionType.PATH_INJECTION, 0.85),
    ]

    def __init__(
        self,
        sensitivity: str = "medium",
        custom_patterns: Optional[List[Tuple[str, InjectionType, float]]] = None
    ):
        """
        Initialize detector.

        Args:
            sensitivity: 'low', 'medium', 'high'
                - low: Only block high-confidence detections
                - medium: Block medium+ confidence, warn on low
                - high: Block on any detection
            custom_patterns: Additional patterns to check
        """
        self.sensitivity = sensitivity
        self.patterns = list(self.DETECTION_PATTERNS)

        if custom_patterns:
            self.patterns.extend(custom_patterns)

        # Compile patterns for efficiency
        self.compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE | re.MULTILINE), itype, weight)
            for pattern, itype, weight in self.patterns
        ]

        # Sensitivity thresholds
        self.thresholds = {
            "low": {"block": 0.9, "warn": 0.7},
            "medium": {"block": 0.6, "warn": 0.4},
            "high": {"block": 0.3, "warn": 0.1}
        }

    def detect(self, text: str) -> InjectionDetectionResult:
        """
        Detect injection attempts in text.

        Args:
            text: User input text to analyze

        Returns:
            InjectionDetectionResult with detection outcome
        """
        if not text or not text.strip():
            return InjectionDetectionResult(
                is_injection=False,
                action=DetectionAction.ALLOW,
                confidence=0.0,
                details="Empty input"
            )

        text_lower = text.lower()
        matched_patterns = []
        injection_types = set()
        total_weight = 0.0
        max_weight = 0.0

        # Check all patterns
        for compiled_pattern, itype, weight in self.compiled_patterns:
            matches = compiled_pattern.findall(text)
            if matches:
                for match in matches:
                    match_str = match if isinstance(match, str) else str(match)
                    matched_patterns.append(match_str)
                    injection_types.add(itype)
                    total_weight += weight
                    max_weight = max(max_weight, weight)

        # No matches found
        if not matched_patterns:
            return InjectionDetectionResult(
                is_injection=False,
                action=DetectionAction.ALLOW,
                confidence=0.0,
                details="No injection patterns detected"
            )

        # Calculate confidence (normalized)
        # Use max weight as base, boost slightly for multiple patterns
        pattern_boost = min(len(matched_patterns) * 0.05, 0.2)
        confidence = min(max_weight + pattern_boost, 1.0)

        # Determine action based on sensitivity
        thresholds = self.thresholds[self.sensitivity]

        if confidence >= thresholds["block"]:
            action = DetectionAction.BLOCK
        elif confidence >= thresholds["warn"]:
            action = DetectionAction.WARN
        else:
            action = DetectionAction.ALLOW

        # Log detection
        if action == DetectionAction.BLOCK:
            logger.warning(
                f"🚨 Injection BLOCKED: {len(matched_patterns)} patterns, "
                f"confidence={confidence:.2f}, types={[t.value for t in injection_types]}"
            )
        elif action == DetectionAction.WARN:
            logger.warning(
                f"⚠️ Injection WARNING: {len(matched_patterns)} patterns, "
                f"confidence={confidence:.2f}"
            )

        return InjectionDetectionResult(
            is_injection=True,
            action=action,
            confidence=confidence,
            injection_types=list(injection_types),
            patterns_matched=matched_patterns[:10],  # Limit to first 10
            details=f"Detected {len(matched_patterns)} suspicious patterns"
        )

    def sanitize(self, text: str) -> str:
        """
        Attempt to sanitize text by removing suspicious patterns.

        Note: This is a best-effort sanitization. For high-risk operations,
        blocking is preferred over sanitization.

        Args:
            text: Text to sanitize

        Returns:
            Sanitized text
        """
        sanitized = text

        for compiled_pattern, _, _ in self.compiled_patterns:
            sanitized = compiled_pattern.sub("[REMOVED]", sanitized)

        return sanitized

    def add_pattern(
        self,
        pattern: str,
        injection_type: InjectionType,
        weight: float = 0.7
    ):
        """Add a custom detection pattern"""
        compiled = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        self.compiled_patterns.append((compiled, injection_type, weight))
        logger.info(f"📝 Added injection pattern: {pattern[:30]}...")


# Global instance
injection_detector = InjectionDetector()
