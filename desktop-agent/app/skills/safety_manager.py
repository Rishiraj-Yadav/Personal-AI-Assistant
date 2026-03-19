"""
Safety Manager
Validates actions, requires confirmations, prevents dangerous operations
"""
import re
from typing import Dict, Any, Optional, List
from loguru import logger
from config import settings
import json
from datetime import datetime


class SafetyManager:
    """Manages safety checks and confirmations"""
    
    def __init__(self):
        """Initialize safety manager"""
        self.pending_confirmations: Dict[str, Dict] = {}
        self.action_history: List[Dict] = []
        logger.info("SafetyManager initialized")
    
    def validate_action(self, skill: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate if action is safe to execute
        
        Returns:
            {
                "safe": bool,
                "reason": str,
                "requires_confirmation": bool,
                "confirmation_message": str
            }
        """
        # Check if in safe mode
        if settings.SAFE_MODE:
            return {
                "safe": False,
                "reason": "Safe mode is enabled. Actions will only be logged.",
                "requires_confirmation": False,
                "safe_mode": True
            }
        
        # Check for dangerous keywords
        args_str = json.dumps(args).lower()
        for keyword in settings.DANGER_KEYWORDS:
            if keyword in args_str:
                return {
                    "safe": False,
                    "reason": f"Dangerous keyword detected: {keyword}",
                    "requires_confirmation": True,
                    "confirmation_message": f"⚠️ WARNING: This action contains '{keyword}'. Type 'CONFIRM {keyword.upper()}' to proceed."
                }
        
        # Check app launcher for blocked apps
        if skill == "app_launcher":
            app_name = args.get("app", "").lower()
            
            # Check blocklist
            for blocked in settings.BLOCKED_APPS:
                if blocked in app_name:
                    return {
                        "safe": False,
                        "reason": f"Application '{app_name}' is blocked for security",
                        "requires_confirmation": False,
                        "blocked": True
                    }
            
            # Check whitelist (if not in whitelist, needs confirmation)
            if not any(allowed in app_name for allowed in settings.ALLOWED_APPS):
                return {
                    "safe": False,
                    "reason": f"Application '{app_name}' not in whitelist",
                    "requires_confirmation": True,
                    "confirmation_message": f"⚠️ '{app_name}' is not in the safe apps list. Type 'CONFIRM LAUNCH' to proceed."
                }
        
        # Check keyboard control for dangerous commands
        if skill == "keyboard_control":
            text = args.get("text", "").lower()
            
            # Check for shell commands
            dangerous_patterns = [
                r'rm\s+-rf',
                r'format\s+[a-z]:',
                r'del\s+/f\s+/q',
                r'sudo\s+rm',
                r'shutdown',
                r'restart'
            ]
            
            for pattern in dangerous_patterns:
                if re.search(pattern, text):
                    return {
                        "safe": False,
                        "reason": "Potentially dangerous command detected",
                        "requires_confirmation": True,
                        "confirmation_message": f"⚠️ DANGER: This command could harm your system. Type 'I UNDERSTAND THE RISK' to proceed."
                    }
        
        # Check mouse clicks near screen edges (could close important windows)
        if skill == "mouse_control" and args.get("action") == "click":
            x = args.get("x", 0)
            y = args.get("y", 0)
            
            # Near top-right (close buttons)
            if x > settings.MAX_SCREEN_WIDTH * 0.95 and y < 50:
                return {
                    "safe": True,  # Allow but warn
                    "reason": "Clicking near close button",
                    "requires_confirmation": False,
                    "warning": "This click is near window close buttons"
                }
        
        # All checks passed
        return {
            "safe": True,
            "reason": "Action validated",
            "requires_confirmation": False
        }
    
    def log_action(self, skill: str, args: Dict[str, Any], result: Any, success: bool):
        """
        Log action for audit trail
        
        Args:
            skill: Skill name
            args: Action arguments
            result: Action result
            success: Whether action succeeded
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "skill": skill,
            "args": args,
            "result": str(result)[:200],  # Limit result length
            "success": success
        }
        
        self.action_history.append(log_entry)
        
        # Write to log file
        if settings.LOG_ALL_ACTIONS:
            logger.info(f"ACTION: {skill} | {args} | Success: {success}")
        
        # Keep only last 1000 actions in memory
        if len(self.action_history) > 1000:
            self.action_history = self.action_history[-1000:]
    
    def get_action_history(self, limit: int = 100) -> List[Dict]:
        """Get recent action history"""
        return self.action_history[-limit:]
    
    def create_confirmation_request(self, skill: str, args: Dict[str, Any], message: str) -> str:
        """
        Create a confirmation request
        
        Returns:
            Confirmation ID
        """
        import uuid
        conf_id = f"conf_{uuid.uuid4().hex[:8]}"
        
        self.pending_confirmations[conf_id] = {
            "skill": skill,
            "args": args,
            "message": message,
            "created_at": datetime.now().isoformat()
        }
        
        logger.warning(f"Confirmation required: {conf_id} | {message}")
        return conf_id
    
    def check_confirmation(self, conf_id: str, user_input: str) -> bool:
        """
        Check if user confirmation matches requirement
        
        Args:
            conf_id: Confirmation ID
            user_input: User's confirmation text
            
        Returns:
            True if confirmed correctly
        """
        if conf_id not in self.pending_confirmations:
            return False
        
        # For now, simple confirmation
        # In production, implement proper confirmation matching
        confirmation_phrases = [
            "CONFIRM", "YES", "I UNDERSTAND THE RISK",
            "CONFIRM DELETE", "CONFIRM LAUNCH"
        ]
        
        return any(phrase in user_input.upper() for phrase in confirmation_phrases)
    
    def clear_confirmation(self, conf_id: str):
        """Remove confirmation after processing"""
        if conf_id in self.pending_confirmations:
            del self.pending_confirmations[conf_id]


# Global safety manager
safety_manager = SafetyManager()