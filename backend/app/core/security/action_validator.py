"""
Action Validator

Validates that LLM-generated actions are safe to execute.
Prevents prompt injection and dangerous operations.

Part of Phase 2: SafeExecutor Security
"""

from enum import Enum
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from loguru import logger


class ActionRiskLevel(str, Enum):
    """Risk classification for actions"""
    LOW = "low"              # Safe, no approval needed
    MEDIUM = "medium"        # Moderately risky, can warn
    HIGH = "high"            # Dangerous, require approval
    CRITICAL = "critical"    # Never allow


@dataclass
class ActionValidationResult:
    """Result of action validation"""
    allowed: bool
    risk_level: ActionRiskLevel
    reason: str
    requires_approval: bool = False
    suggested_alternative: Optional[str] = None


class ActionValidator:
    """
    Validates action safety before execution.

    Provides whitelist-based validation with risk levels.
    High-risk actions can be blocked or require user approval.
    """

    # Define all allowed actions and their risk levels
    ACTION_REGISTRY: Dict[str, Dict[str, Any]] = {
        # Desktop - low risk (visual/read operations)
        "click": {"risk": ActionRiskLevel.LOW, "category": "desktop"},
        "double_click": {"risk": ActionRiskLevel.LOW, "category": "desktop"},
        "right_click": {"risk": ActionRiskLevel.LOW, "category": "desktop"},
        "type_text": {"risk": ActionRiskLevel.LOW, "category": "desktop"},
        "press_key": {"risk": ActionRiskLevel.LOW, "category": "desktop"},
        "screenshot": {"risk": ActionRiskLevel.LOW, "category": "desktop"},
        "get_cursor_position": {"risk": ActionRiskLevel.LOW, "category": "desktop"},
        "move_mouse": {"risk": ActionRiskLevel.LOW, "category": "desktop"},
        "get_screen_size": {"risk": ActionRiskLevel.LOW, "category": "desktop"},
        "get_active_window": {"risk": ActionRiskLevel.LOW, "category": "desktop"},

        # Desktop - medium risk (app control)
        "open_app": {"risk": ActionRiskLevel.MEDIUM, "category": "desktop"},
        "close_app": {"risk": ActionRiskLevel.MEDIUM, "category": "desktop"},
        "scroll": {"risk": ActionRiskLevel.MEDIUM, "category": "desktop"},
        "scroll_up": {"risk": ActionRiskLevel.MEDIUM, "category": "desktop"},
        "scroll_down": {"risk": ActionRiskLevel.MEDIUM, "category": "desktop"},
        "hotkey": {"risk": ActionRiskLevel.MEDIUM, "category": "desktop"},
        "maximize_window": {"risk": ActionRiskLevel.MEDIUM, "category": "desktop"},
        "minimize_window": {"risk": ActionRiskLevel.MEDIUM, "category": "desktop"},

        # File operations - high risk (require approval)
        "read_file": {"risk": ActionRiskLevel.MEDIUM, "category": "file"},
        "list_directory": {"risk": ActionRiskLevel.LOW, "category": "file"},
        "create_file": {"risk": ActionRiskLevel.HIGH, "category": "file"},
        "write_file": {"risk": ActionRiskLevel.HIGH, "category": "file"},
        "delete_file": {"risk": ActionRiskLevel.HIGH, "category": "file"},
        "move_file": {"risk": ActionRiskLevel.HIGH, "category": "file"},
        "copy_file": {"risk": ActionRiskLevel.HIGH, "category": "file"},
        "rename_file": {"risk": ActionRiskLevel.HIGH, "category": "file"},

        # Web operations - medium risk
        "navigate_to": {"risk": ActionRiskLevel.MEDIUM, "category": "web"},
        "web_click": {"risk": ActionRiskLevel.LOW, "category": "web"},
        "web_type": {"risk": ActionRiskLevel.LOW, "category": "web"},
        "web_screenshot": {"risk": ActionRiskLevel.LOW, "category": "web"},
        "web_scroll": {"risk": ActionRiskLevel.LOW, "category": "web"},
        "web_wait": {"risk": ActionRiskLevel.LOW, "category": "web"},

        # System - CRITICAL (never allow)
        "run_command": {"risk": ActionRiskLevel.CRITICAL, "category": "system"},
        "execute_shell": {"risk": ActionRiskLevel.CRITICAL, "category": "system"},
        "run_script": {"risk": ActionRiskLevel.CRITICAL, "category": "system"},
        "shutdown": {"risk": ActionRiskLevel.CRITICAL, "category": "system"},
        "restart": {"risk": ActionRiskLevel.CRITICAL, "category": "system"},
        "sleep_system": {"risk": ActionRiskLevel.CRITICAL, "category": "system"},
        "install_software": {"risk": ActionRiskLevel.CRITICAL, "category": "system"},
        "uninstall_software": {"risk": ActionRiskLevel.CRITICAL, "category": "system"},
        "modify_registry": {"risk": ActionRiskLevel.CRITICAL, "category": "system"},
        "modify_system_settings": {"risk": ActionRiskLevel.CRITICAL, "category": "system"},
        "kill_process": {"risk": ActionRiskLevel.CRITICAL, "category": "system"},
        "start_service": {"risk": ActionRiskLevel.CRITICAL, "category": "system"},
        "stop_service": {"risk": ActionRiskLevel.CRITICAL, "category": "system"},
    }

    def __init__(
        self,
        require_approval_for_high: bool = True,
        block_unknown_actions: bool = True,
        custom_registry: Optional[Dict[str, Dict[str, Any]]] = None
    ):
        """
        Initialize validator.

        Args:
            require_approval_for_high: If True, HIGH risk actions need user approval
            block_unknown_actions: If True, unknown actions are blocked
            custom_registry: Additional actions to register
        """
        self.require_approval_for_high = require_approval_for_high
        self.block_unknown_actions = block_unknown_actions

        # Merge custom registry
        self.registry = {**self.ACTION_REGISTRY}
        if custom_registry:
            self.registry.update(custom_registry)

    def validate(self, action_name: str, args: Optional[Dict] = None) -> ActionValidationResult:
        """
        Validate an action.

        Args:
            action_name: Name of the action to validate
            args: Optional action arguments (for context-aware validation)

        Returns:
            ActionValidationResult with validation outcome
        """
        action_name_lower = action_name.lower()

        # Check if action exists in registry
        if action_name_lower not in self.registry:
            if self.block_unknown_actions:
                logger.warning(f"🚫 Blocked unknown action: {action_name}")
                return ActionValidationResult(
                    allowed=False,
                    risk_level=ActionRiskLevel.CRITICAL,
                    reason=f"Unknown action '{action_name}' is not in the allowed list",
                    requires_approval=False
                )
            else:
                # Allow with warning
                logger.warning(f"⚠️ Unknown action allowed: {action_name}")
                return ActionValidationResult(
                    allowed=True,
                    risk_level=ActionRiskLevel.HIGH,
                    reason=f"Unknown action '{action_name}' allowed (block_unknown_actions=False)",
                    requires_approval=True
                )

        action_info = self.registry[action_name_lower]
        risk_level = action_info["risk"]

        # Never allow critical actions
        if risk_level == ActionRiskLevel.CRITICAL:
            logger.warning(f"🚫 Blocked critical action: {action_name}")
            return ActionValidationResult(
                allowed=False,
                risk_level=risk_level,
                reason=f"Action '{action_name}' is blocked for security reasons",
                requires_approval=False
            )

        # Check if high-risk needs approval
        requires_approval = (
            self.require_approval_for_high and
            risk_level == ActionRiskLevel.HIGH
        )

        if requires_approval:
            logger.info(f"⚠️ High-risk action requires approval: {action_name}")

        return ActionValidationResult(
            allowed=True,
            risk_level=risk_level,
            reason=f"Action '{action_name}' allowed ({risk_level.value} risk)",
            requires_approval=requires_approval
        )

    def validate_batch(self, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate multiple actions at once.

        Args:
            actions: List of {name: str, args: dict} action definitions

        Returns:
            {
                "all_allowed": bool,
                "any_requires_approval": bool,
                "blocked_actions": [...],
                "results": [...]
            }
        """
        results = []
        blocked = []
        needs_approval = False

        for action in actions:
            name = action.get("name") or action.get("action")
            args = action.get("args", {})

            validation = self.validate(name, args)
            results.append({
                "action": name,
                "result": validation
            })

            if not validation.allowed:
                blocked.append(name)

            if validation.requires_approval:
                needs_approval = True

        return {
            "all_allowed": len(blocked) == 0,
            "any_requires_approval": needs_approval,
            "blocked_actions": blocked,
            "results": results
        }

    def get_allowed_actions(self, category: Optional[str] = None) -> List[str]:
        """
        Get list of allowed actions.

        Args:
            category: Filter by category (desktop, file, web, system)

        Returns:
            List of action names
        """
        actions = []
        for name, info in self.registry.items():
            if info["risk"] != ActionRiskLevel.CRITICAL:
                if category is None or info.get("category") == category:
                    actions.append(name)
        return sorted(actions)

    def register_action(
        self,
        name: str,
        risk: ActionRiskLevel,
        category: str = "custom"
    ):
        """
        Register a new action.

        Args:
            name: Action name
            risk: Risk level
            category: Action category
        """
        self.registry[name.lower()] = {
            "risk": risk,
            "category": category
        }
        logger.info(f"📝 Registered action: {name} ({risk.value} risk)")


# Global instance
action_validator = ActionValidator()
