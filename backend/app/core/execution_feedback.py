"""
Execution Feedback Loop - Phase 6 Pillar 6
============================================

Structured feedback after action execution:
- Execute → Verify (Process spawned?) → Update Context → Log Success
- Returns structured JSON to backend for persona layer
"""

import os
import subprocess
import time
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Callable
from loguru import logger


class FeedbackStatus(str, Enum):
    """Execution feedback status."""
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    NEEDS_FALLBACK = "needs_fallback"
    VERIFICATION_FAILED = "verification_failed"


class ActionCategory(str, Enum):
    """Categories of actions for verification strategies."""
    FILE_SYSTEM = "file_system"
    APP_LAUNCH = "app_launch"
    WEB_OPEN = "web_open"
    SCREEN_CAPTURE = "screen_capture"
    WINDOW_CONTROL = "window_control"
    SYSTEM = "system"


@dataclass
class ExecutionFeedback:
    """
    Structured feedback from action execution.
    
    Contains all information needed for:
    - Context updates
    - Persona response generation
    - Fallback decisions
    """
    # Core result
    status: FeedbackStatus
    action: str
    target: Optional[str] = None
    
    # Verification
    verified: bool = False
    verification_method: Optional[str] = None
    verification_details: Dict[str, Any] = field(default_factory=dict)
    
    # Timing
    execution_time_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    # Result data
    result: Dict[str, Any] = field(default_factory=dict)
    
    # Error info (if failed)
    error: Optional[str] = None
    error_code: Optional[str] = None
    recoverable: bool = True
    
    # Fallback info
    fallback_reason: Optional[str] = None
    fallback_suggested_action: Optional[str] = None
    
    # Context updates to apply
    context_updates: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "action": self.action,
            "target": self.target,
            "verified": self.verified,
            "verification_method": self.verification_method,
            "verification_details": self.verification_details,
            "execution_time_ms": self.execution_time_ms,
            "timestamp": self.timestamp,
            "result": self.result,
            "error": self.error,
            "error_code": self.error_code,
            "recoverable": self.recoverable,
            "fallback_reason": self.fallback_reason,
            "context_updates": self.context_updates,
        }
    
    @property
    def needs_fallback(self) -> bool:
        """Check if this feedback indicates fallback is needed."""
        return self.status == FeedbackStatus.NEEDS_FALLBACK
    
    @property
    def is_success(self) -> bool:
        """Check if execution was successful."""
        return self.status in [FeedbackStatus.SUCCESS, FeedbackStatus.PARTIAL_SUCCESS]


class FeedbackLoop:
    """
    Phase 6 Execution Feedback Loop
    
    Implements: Execute → Verify → Update Context → Log → Return
    
    Each action type has specific verification strategies:
    - fs.open: Check if path exists, verify explorer/app launched
    - app.launch: Check if process is running
    - web.open: Check if browser process spawned
    - screen.capture: Check if screenshot file was created
    """
    
    def __init__(
        self,
        context_updater: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_fallback: Optional[Callable[[ExecutionFeedback], None]] = None
    ):
        """
        Initialize the Feedback Loop.
        
        Args:
            context_updater: Callback to update predictive context
            on_fallback: Callback when fallback is needed
        """
        self.context_updater = context_updater
        self.on_fallback = on_fallback
        
        # Verification strategies by action category
        self._verifiers: Dict[ActionCategory, Callable] = {
            ActionCategory.FILE_SYSTEM: self._verify_file_system,
            ActionCategory.APP_LAUNCH: self._verify_app_launch,
            ActionCategory.WEB_OPEN: self._verify_web_open,
            ActionCategory.SCREEN_CAPTURE: self._verify_screen_capture,
            ActionCategory.WINDOW_CONTROL: self._verify_window_control,
        }
        
        logger.info("✅ FeedbackLoop initialized")
    
    def process(
        self,
        action: str,
        target: Optional[str],
        execution_result: Dict[str, Any],
        execution_time_ms: float
    ) -> ExecutionFeedback:
        """
        Process execution result and create structured feedback.
        
        Args:
            action: The action that was executed (e.g., "fs.open")
            target: The target of the action
            execution_result: Raw result from executor
            execution_time_ms: Time taken to execute
            
        Returns:
            ExecutionFeedback with verification and context updates
        """
        start_time = time.time()
        
        # Determine action category
        category = self._get_action_category(action)
        
        # Check basic success
        raw_success = execution_result.get("success", False)
        error = execution_result.get("error")
        
        if not raw_success:
            feedback = ExecutionFeedback(
                status=FeedbackStatus.FAILED,
                action=action,
                target=target,
                execution_time_ms=execution_time_ms,
                error=error,
                error_code=self._classify_error(error),
                recoverable=self._is_recoverable(error),
                fallback_reason=error,
            )
            
            # Check if fallback is needed
            if self._should_fallback(error, action):
                feedback.status = FeedbackStatus.NEEDS_FALLBACK
                feedback.fallback_suggested_action = self._suggest_fallback(action, error)
                if self.on_fallback:
                    self.on_fallback(feedback)
            
            logger.warning(f"❌ Action failed: {action} → {error}")
            return feedback
        
        # Run verification
        verified, verification_details = self._verify_execution(category, action, target, execution_result)
        
        # Build context updates
        context_updates = self._build_context_updates(action, target, execution_result)
        
        # Determine final status
        if verified:
            status = FeedbackStatus.SUCCESS
        elif raw_success:
            status = FeedbackStatus.PARTIAL_SUCCESS
        else:
            status = FeedbackStatus.VERIFICATION_FAILED
        
        feedback = ExecutionFeedback(
            status=status,
            action=action,
            target=target,
            verified=verified,
            verification_method=category.value if category else "none",
            verification_details=verification_details,
            execution_time_ms=execution_time_ms,
            result=execution_result,
            context_updates=context_updates,
        )
        
        # Apply context updates
        if self.context_updater and context_updates:
            try:
                self.context_updater(context_updates)
            except Exception as e:
                logger.error(f"❌ Context update failed: {e}")
        
        verification_time = (time.time() - start_time) * 1000
        logger.info(
            f"✅ Feedback: {action} → {status.value} "
            f"(verified={verified}, +{verification_time:.0f}ms)"
        )
        
        return feedback
    
    def _get_action_category(self, action: str) -> Optional[ActionCategory]:
        """Map action to category for verification strategy."""
        action_lower = action.lower()
        
        if action_lower.startswith("fs."):
            return ActionCategory.FILE_SYSTEM
        elif action_lower.startswith("app."):
            return ActionCategory.APP_LAUNCH
        elif action_lower.startswith("web."):
            return ActionCategory.WEB_OPEN
        elif action_lower.startswith("screen."):
            return ActionCategory.SCREEN_CAPTURE
        elif action_lower.startswith("window."):
            return ActionCategory.WINDOW_CONTROL
        
        return None
    
    def _verify_execution(
        self,
        category: Optional[ActionCategory],
        action: str,
        target: Optional[str],
        result: Dict[str, Any]
    ) -> tuple[bool, Dict[str, Any]]:
        """Run verification for the action."""
        if category is None:
            return True, {"method": "no_verification", "reason": "unknown_category"}
        
        verifier = self._verifiers.get(category)
        if verifier:
            try:
                return verifier(action, target, result)
            except Exception as e:
                logger.error(f"❌ Verification error: {e}")
                return False, {"method": category.value, "error": str(e)}
        
        return True, {"method": "default", "reason": "no_verifier"}
    
    def _verify_file_system(
        self,
        action: str,
        target: Optional[str],
        result: Dict[str, Any]
    ) -> tuple[bool, Dict[str, Any]]:
        """Verify file system operations."""
        details = {"method": "file_system"}
        
        if action == "fs.open" and target:
            # Check if path exists
            exists = os.path.exists(target)
            details["path_exists"] = exists
            details["path"] = target
            
            if exists:
                details["is_dir"] = os.path.isdir(target)
                details["is_file"] = os.path.isfile(target)
            
            return exists, details
        
        return True, details
    
    def _verify_app_launch(
        self,
        action: str,
        target: Optional[str],
        result: Dict[str, Any]
    ) -> tuple[bool, Dict[str, Any]]:
        """Verify application launch."""
        details = {"method": "app_launch", "target": target}
        
        if not target:
            return True, details
        
        # Map common app names to process names
        process_map = {
            "vscode": ["code.exe", "Code.exe"],
            "notepad": ["notepad.exe"],
            "chrome": ["chrome.exe"],
            "firefox": ["firefox.exe"],
            "explorer": ["explorer.exe"],
        }
        
        target_lower = target.lower()
        process_names = process_map.get(target_lower, [f"{target}.exe"])
        
        # Check if any matching process is running (Windows)
        try:
            # Use tasklist on Windows
            result_proc = subprocess.run(
                ["tasklist", "/FO", "CSV"],
                capture_output=True,
                text=True,
                timeout=5
            )
            running_processes = result_proc.stdout.lower()
            
            for proc in process_names:
                if proc.lower() in running_processes:
                    details["process_found"] = proc
                    details["running"] = True
                    return True, details
            
            details["running"] = False
            return False, details
            
        except Exception as e:
            details["error"] = str(e)
            # Assume success if we can't verify
            return True, details
    
    def _verify_web_open(
        self,
        action: str,
        target: Optional[str],
        result: Dict[str, Any]
    ) -> tuple[bool, Dict[str, Any]]:
        """Verify web browser opened."""
        details = {"method": "web_open", "url": target}
        
        # Check for browser processes
        browsers = ["chrome.exe", "firefox.exe", "msedge.exe", "brave.exe"]
        
        try:
            result_proc = subprocess.run(
                ["tasklist", "/FO", "CSV"],
                capture_output=True,
                text=True,
                timeout=5
            )
            running = result_proc.stdout.lower()
            
            for browser in browsers:
                if browser in running:
                    details["browser_found"] = browser
                    details["running"] = True
                    return True, details
            
            details["running"] = False
            return False, details
            
        except Exception as e:
            details["error"] = str(e)
            return True, details
    
    def _verify_screen_capture(
        self,
        action: str,
        target: Optional[str],
        result: Dict[str, Any]
    ) -> tuple[bool, Dict[str, Any]]:
        """Verify screenshot was captured."""
        details = {"method": "screen_capture"}
        
        screenshot_path = result.get("path") or target
        if screenshot_path and os.path.exists(screenshot_path):
            details["path"] = screenshot_path
            details["exists"] = True
            details["size_bytes"] = os.path.getsize(screenshot_path)
            return True, details
        
        details["exists"] = False
        return False, details
    
    def _verify_window_control(
        self,
        action: str,
        target: Optional[str],
        result: Dict[str, Any]
    ) -> tuple[bool, Dict[str, Any]]:
        """Verify window control operation."""
        # Window control is hard to verify, assume success if no error
        return True, {"method": "window_control", "assumed": True}
    
    def _build_context_updates(
        self,
        action: str,
        target: Optional[str],
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build context updates based on successful action."""
        updates = {}
        
        if action == "fs.open" and target:
            if os.path.isdir(target):
                updates["last_folder"] = target
                updates["add_recent_path"] = target
                
                # Try to detect project
                if any(f in os.listdir(target) for f in ["package.json", "requirements.txt", "setup.py", ".git"]):
                    updates["active_project"] = target
                    
            elif os.path.isfile(target):
                updates["last_file"] = target
                updates["add_recent_path"] = os.path.dirname(target)
        
        elif action == "app.launch":
            updates["last_app"] = target
        
        elif action == "web.open":
            updates["last_url"] = target
        
        return updates
    
    def _classify_error(self, error: Optional[str]) -> Optional[str]:
        """Classify error into a standard error code."""
        if not error:
            return None
        
        error_lower = error.lower()
        
        if "not found" in error_lower or "does not exist" in error_lower:
            return "NOT_FOUND"
        elif "permission" in error_lower or "access denied" in error_lower:
            return "PERMISSION_DENIED"
        elif "timeout" in error_lower:
            return "TIMEOUT"
        elif "invalid" in error_lower:
            return "INVALID_TARGET"
        
        return "UNKNOWN"
    
    def _is_recoverable(self, error: Optional[str]) -> bool:
        """Determine if error is recoverable."""
        if not error:
            return True
        
        error_lower = error.lower()
        unrecoverable = ["permission denied", "access denied", "critical", "fatal"]
        
        return not any(term in error_lower for term in unrecoverable)
    
    def _should_fallback(self, error: Optional[str], action: str) -> bool:
        """Determine if fallback to backend intelligence is needed."""
        if not error:
            return False
        
        error_code = self._classify_error(error)
        
        # These errors benefit from LLM reasoning
        fallback_codes = ["NOT_FOUND", "INVALID_TARGET"]
        
        return error_code in fallback_codes
    
    def _suggest_fallback(self, action: str, error: Optional[str]) -> Optional[str]:
        """Suggest a fallback action."""
        error_code = self._classify_error(error)
        
        if error_code == "NOT_FOUND":
            if action.startswith("fs."):
                return "search_file_system"
            elif action.startswith("app."):
                return "search_installed_apps"
        
        return "llm_reasoning"


# Global instance
_feedback_loop: Optional[FeedbackLoop] = None


def get_feedback_loop(
    context_updater: Optional[Callable] = None,
    on_fallback: Optional[Callable] = None
) -> FeedbackLoop:
    """Get or create the global FeedbackLoop instance."""
    global _feedback_loop
    if _feedback_loop is None:
        _feedback_loop = FeedbackLoop(
            context_updater=context_updater,
            on_fallback=on_fallback
        )
    return _feedback_loop
