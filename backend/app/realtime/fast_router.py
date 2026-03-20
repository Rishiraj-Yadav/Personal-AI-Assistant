"""
Fast Router - Phase 3
=====================

Routes intents to appropriate handlers based on confidence thresholds.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any
from loguru import logger

from .fast_intent_classifier import IntentResult, IntentType


class RoutingPath(str, Enum):
    """Where to route the request."""
    FAST_DESKTOP = "fast_desktop"        # Direct desktop execution
    FAST_RESPONSE = "fast_response"       # Simple response (no tools)
    FULL_ORCHESTRATION = "full_orchestration"  # LangGraph flow
    DISAMBIGUATE = "disambiguate"         # Ask user for clarification


@dataclass
class RoutingDecision:
    """Routing decision result."""
    path: RoutingPath
    intent_result: IntentResult
    handler: str
    needs_confirmation: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path.value,
            "intent_type": self.intent_result.intent_type.value,
            "confidence": self.intent_result.confidence,
            "handler": self.handler,
            "action": self.intent_result.action,
            "target": self.intent_result.target,
            "needs_confirmation": self.needs_confirmation,
        }


class FastRouter:
    """
    Routes intents based on confidence thresholds.
    
    Thresholds:
    - > 0.8: Fast path (direct execution)
    - 0.5 - 0.8: May need disambiguation
    - < 0.5: Full orchestration
    """
    
    FAST_PATH_THRESHOLD = 0.8
    DISAMBIGUATION_THRESHOLD = 0.5
    
    # Handlers for each intent type
    HANDLERS = {
        IntentType.DESKTOP_ACTION: "desktop_handler",
        IntentType.CODING: "code_handler",
        IntentType.WEB_AUTONOMOUS: "web_handler",
        IntentType.WEB_SIMPLE: "web_simple_handler",
        IntentType.EMAIL: "email_handler",
        IntentType.CALENDAR: "calendar_handler",
        IntentType.CONVERSATION: "simple_responder",
        IntentType.GENERAL: "langgraph_orchestrator",
    }
    
    # Actions that require confirmation
    CONFIRMATION_REQUIRED = [
        "fs.delete", "sys.reboot", "sys.shutdown", "app.kill",
        "file.delete", "folder.delete"
    ]
    
    def __init__(self):
        logger.info("✅ FastRouter initialized")
    
    def route(self, intent_result: IntentResult) -> RoutingDecision:
        """
        Route an intent to the appropriate handler.
        
        Args:
            intent_result: Result from FastIntentClassifier
            
        Returns:
            RoutingDecision with path and handler info
        """
        confidence = intent_result.confidence
        intent_type = intent_result.intent_type
        action = intent_result.action
        
        # Determine routing path
        if confidence >= self.FAST_PATH_THRESHOLD:
            # High confidence - can use fast path
            if intent_type == IntentType.DESKTOP_ACTION:
                path = RoutingPath.FAST_DESKTOP
            elif intent_type == IntentType.CONVERSATION:
                path = RoutingPath.FAST_RESPONSE
            else:
                # Other intents with high confidence still go to orchestration
                # but with priority flag
                path = RoutingPath.FULL_ORCHESTRATION
                
        elif confidence >= self.DISAMBIGUATION_THRESHOLD:
            # Medium confidence - may need clarification
            path = RoutingPath.DISAMBIGUATE
            
        else:
            # Low confidence - full orchestration
            path = RoutingPath.FULL_ORCHESTRATION
        
        # Check if action requires confirmation
        needs_confirmation = action in self.CONFIRMATION_REQUIRED if action else False
        
        # Get handler
        handler = self.HANDLERS.get(intent_type, "langgraph_orchestrator")
        
        decision = RoutingDecision(
            path=path,
            intent_result=intent_result,
            handler=handler,
            needs_confirmation=needs_confirmation
        )
        
        logger.info(
            f"🚦 Route: {intent_type.value} → {path.value} "
            f"(conf={confidence:.2f}, handler={handler})"
        )
        
        return decision


# Global instance
fast_router = FastRouter()
