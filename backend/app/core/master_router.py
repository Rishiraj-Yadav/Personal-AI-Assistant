"""
Master Intent Router - Phase 6 Pillar 1 & 2
============================================

Centralized routing with confidence threshold system:
- Score > 0.8: Fast path → Direct to Desktop Agent
- 0.5 < Score < 0.8: Ambiguous → Trigger disambiguation
- Score < 0.5: Complex → Full LangGraph orchestration
"""

import re
import uuid
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Callable
from loguru import logger


class RoutingPath(str, Enum):
    """Routing destination based on confidence."""
    FAST_DESKTOP = "fast_desktop"      # Direct to desktop agent (confidence > 0.8)
    DISAMBIGUATE = "disambiguate"       # Needs user clarification (0.5 - 0.8)
    FULL_ORCHESTRATION = "full_orchestration"  # LangGraph flow (confidence < 0.5)
    FALLBACK = "fallback"               # Error recovery path


class TaskType(str, Enum):
    """Task classification types."""
    DESKTOP_ACTION = "desktop_action"
    CODING = "coding"
    WEB_AUTONOMOUS = "web_autonomous"
    WEB = "web"
    EMAIL = "email"
    CALENDAR = "calendar"
    GENERAL = "general"


@dataclass
class RoutingDecision:
    """Result of the Master Intent Router's classification."""
    task_id: str
    task_type: TaskType
    confidence: float
    routing_path: RoutingPath
    reasoning: str
    
    # Action details for fast path
    action: Optional[str] = None
    target: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    # Disambiguation options (if routing_path == DISAMBIGUATE)
    disambiguation_options: List[Dict[str, Any]] = field(default_factory=list)
    
    # Metadata
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    requires_confirmation: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type.value,
            "confidence": self.confidence,
            "routing_path": self.routing_path.value,
            "reasoning": self.reasoning,
            "action": self.action,
            "target": self.target,
            "parameters": self.parameters,
            "disambiguation_options": self.disambiguation_options,
            "timestamp": self.timestamp,
            "requires_confirmation": self.requires_confirmation,
        }


class MasterIntentRouter:
    """
    Phase 6 Master Intent Router
    
    The central brain that classifies every query and decides:
    - Fast Path (direct desktop execution)
    - Disambiguation (ask user for clarification)
    - Full Orchestration (LangGraph multi-step)
    """
    
    # Confidence thresholds
    FAST_PATH_THRESHOLD = 0.8
    DISAMBIGUATION_THRESHOLD = 0.5
    
    # Fast-path patterns for desktop actions
    DESKTOP_FAST_PATTERNS = {
        # File/folder operations
        r'open\s+(?:my\s+)?(?:the\s+)?(.+?)\s*(?:folder|directory|project)': {
            'action': 'fs.open',
            'confidence': 0.92,
            'extract_target': True
        },
        r'open\s+(?:the\s+)?file\s+(.+)': {
            'action': 'fs.open',
            'confidence': 0.90,
            'extract_target': True
        },
        # App launch
        r'(?:launch|start|open)\s+(?:the\s+)?(?:app\s+)?(?:vs\s*code|vscode|visual\s*studio\s*code)': {
            'action': 'app.launch',
            'confidence': 0.95,
            'target': 'vscode'
        },
        r'(?:launch|start|open)\s+(?:the\s+)?(?:app\s+)?(notepad|chrome|firefox|explorer|terminal|cmd|powershell)': {
            'action': 'app.launch',
            'confidence': 0.95,
            'extract_target': True
        },
        # Website opening (physical browser)
        r'open\s+(?:the\s+)?(youtube|google|github|gmail|reddit|twitter|linkedin|amazon|netflix|spotify)': {
            'action': 'web.open',
            'confidence': 0.95,
            'extract_target': True
        },
        # Screenshot
        r'(?:take|capture)\s+(?:a\s+)?screenshot': {
            'action': 'screen.capture',
            'confidence': 0.98,
            'target': 'screenshot'
        },
        # Window control
        r'(?:minimize|maximize|close)\s+(?:the\s+)?(?:current\s+)?window': {
            'action': 'window.control',
            'confidence': 0.90,
            'extract_target': True
        },
    }
    
    def __init__(self, llm_classifier: Optional[Callable] = None):
        """
        Initialize the Master Intent Router.
        
        Args:
            llm_classifier: Optional LLM-based classifier for complex cases
        """
        self.llm_classifier = llm_classifier
        self._compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), config)
            for pattern, config in self.DESKTOP_FAST_PATTERNS.items()
        ]
        logger.info("✅ MasterIntentRouter initialized with Phase 6 routing")
    
    def route(
        self,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[List[Dict]] = None
    ) -> RoutingDecision:
        """
        Main routing entry point. Classifies the message and returns routing decision.
        
        Args:
            user_message: The user's input message
            context: Optional context (active_project, recent_paths, etc.)
            conversation_history: Optional conversation history
            
        Returns:
            RoutingDecision with routing path and action details
        """
        task_id = str(uuid.uuid4())[:8]
        context = context or {}
        
        # Step 1: Try fast-path pattern matching for desktop actions
        fast_result = self._try_fast_path(user_message, context)
        if fast_result:
            fast_result.task_id = task_id
            logger.info(f"🚀 Fast path: {fast_result.action} → {fast_result.routing_path.value}")
            return fast_result
        
        # Step 2: Use LLM classifier if available
        if self.llm_classifier:
            llm_result = self._classify_with_llm(user_message, context, conversation_history)
            llm_result.task_id = task_id
            return llm_result
        
        # Step 3: Fallback to keyword-based classification
        fallback_result = self._fallback_classify(user_message, context)
        fallback_result.task_id = task_id
        return fallback_result
    
    def _try_fast_path(
        self,
        message: str,
        context: Dict[str, Any]
    ) -> Optional[RoutingDecision]:
        """
        Attempt fast-path pattern matching for high-confidence desktop actions.
        """
        for pattern, config in self._compiled_patterns:
            match = pattern.search(message)
            if match:
                # Extract target from regex group if needed
                target = config.get('target')
                if config.get('extract_target') and match.groups():
                    target = match.group(1).strip()
                
                # Resolve target using context (e.g., "python project" → actual path)
                resolved_target = self._resolve_target(target, context)
                
                confidence = config['confidence']
                routing_path = self._get_routing_path(confidence)
                
                return RoutingDecision(
                    task_id="",
                    task_type=TaskType.DESKTOP_ACTION,
                    confidence=confidence,
                    routing_path=routing_path,
                    reasoning=f"Fast-path match: {config['action']}",
                    action=config['action'],
                    target=resolved_target or target,
                    parameters={"raw_target": target, "resolved": resolved_target is not None},
                    requires_confirmation=self._requires_confirmation(config['action'])
                )
        
        return None
    
    def _classify_with_llm(
        self,
        message: str,
        context: Dict[str, Any],
        conversation_history: Optional[List[Dict]]
    ) -> RoutingDecision:
        """
        Use LLM for complex classification when fast-path doesn't match.
        """
        try:
            result = self.llm_classifier(
                user_message=message,
                user_context=str(context),
                conversation_history=conversation_history
            )
            
            task_type = TaskType(result.get("task_type", "general"))
            confidence = result.get("confidence", 0.5)
            routing_path = self._get_routing_path(confidence, task_type)
            
            return RoutingDecision(
                task_id="",
                task_type=task_type,
                confidence=confidence,
                routing_path=routing_path,
                reasoning=result.get("reasoning", "LLM classification"),
                disambiguation_options=self._get_disambiguation_options(message, confidence)
                    if routing_path == RoutingPath.DISAMBIGUATE else []
            )
        except Exception as e:
            logger.error(f"❌ LLM classification failed: {e}")
            return self._fallback_classify(message, context)
    
    def _fallback_classify(
        self,
        message: str,
        context: Dict[str, Any]
    ) -> RoutingDecision:
        """
        Keyword-based fallback classification.
        """
        message_lower = message.lower()
        
        # Desktop keywords
        if any(kw in message_lower for kw in ["click", "screenshot", "mouse", "window", "launch", "open app"]):
            return RoutingDecision(
                task_id="",
                task_type=TaskType.DESKTOP_ACTION,
                confidence=0.6,
                routing_path=RoutingPath.DISAMBIGUATE,
                reasoning="Matched desktop keywords but needs clarification",
                disambiguation_options=self._get_disambiguation_options(message, 0.6)
            )
        
        # Coding keywords
        if any(kw in message_lower for kw in ["code", "write", "script", "function", "program", "debug"]):
            return RoutingDecision(
                task_id="",
                task_type=TaskType.CODING,
                confidence=0.7,
                routing_path=RoutingPath.DISAMBIGUATE,
                reasoning="Matched coding keywords"
            )
        
        # Web keywords
        if any(kw in message_lower for kw in ["browse", "search", "website", "google"]):
            return RoutingDecision(
                task_id="",
                task_type=TaskType.WEB_AUTONOMOUS,
                confidence=0.65,
                routing_path=RoutingPath.DISAMBIGUATE,
                reasoning="Matched web keywords"
            )
        
        # Default: general with low confidence
        return RoutingDecision(
            task_id="",
            task_type=TaskType.GENERAL,
            confidence=0.3,
            routing_path=RoutingPath.FULL_ORCHESTRATION,
            reasoning="No specific patterns matched, using full orchestration"
        )
    
    def _get_routing_path(
        self,
        confidence: float,
        task_type: Optional[TaskType] = None
    ) -> RoutingPath:
        """
        Determine routing path based on confidence thresholds.
        
        - > 0.8: Fast path (direct execution)
        - 0.5 - 0.8: Disambiguation needed
        - < 0.5: Full orchestration
        """
        # Desktop actions can use fast path if confidence is high
        if task_type == TaskType.DESKTOP_ACTION and confidence >= self.FAST_PATH_THRESHOLD:
            return RoutingPath.FAST_DESKTOP
        
        if confidence >= self.FAST_PATH_THRESHOLD:
            return RoutingPath.FAST_DESKTOP
        elif confidence >= self.DISAMBIGUATION_THRESHOLD:
            return RoutingPath.DISAMBIGUATE
        else:
            return RoutingPath.FULL_ORCHESTRATION
    
    def _resolve_target(
        self,
        target: Optional[str],
        context: Dict[str, Any]
    ) -> Optional[str]:
        """
        Resolve ambiguous targets using context.
        
        e.g., "python project" → "/Projects/MyPythonApp" from recent_paths
        """
        if not target:
            return None
        
        target_lower = target.lower()
        
        # Check active_project
        if "project" in target_lower and context.get("active_project"):
            return context["active_project"]
        
        # Check recent_paths for matching keywords
        recent_paths = context.get("recent_paths", [])
        for path in recent_paths:
            path_lower = path.lower()
            if target_lower in path_lower:
                return path
        
        # Check frequent_paths
        frequent_paths = context.get("frequent_paths", [])
        for path in frequent_paths:
            path_lower = path.lower()
            if target_lower in path_lower:
                return path
        
        return None
    
    def _requires_confirmation(self, action: str) -> bool:
        """
        Determine if action requires user confirmation.
        """
        destructive_actions = ["fs.delete", "sys.reboot", "sys.shutdown", "app.kill"]
        return action in destructive_actions
    
    def _get_disambiguation_options(
        self,
        message: str,
        confidence: float
    ) -> List[Dict[str, Any]]:
        """
        Generate disambiguation options for ambiguous queries.
        """
        message_lower = message.lower()
        options = []
        
        if "open" in message_lower:
            options = [
                {"label": "Open in file explorer", "action": "fs.open", "type": "desktop"},
                {"label": "Open in VS Code", "action": "app.launch", "params": {"app": "vscode"}},
                {"label": "Search on the web", "action": "web.search", "type": "web_autonomous"},
            ]
        elif "project" in message_lower:
            options = [
                {"label": "Open project folder", "action": "fs.open", "type": "desktop"},
                {"label": "Create new project", "action": "code.create", "type": "coding"},
                {"label": "Search project online", "action": "web.search", "type": "web_autonomous"},
            ]
        
        return options


# Global instance (lazy initialization)
_master_router: Optional[MasterIntentRouter] = None


def get_master_router(llm_classifier: Optional[Callable] = None) -> MasterIntentRouter:
    """Get or create the global MasterIntentRouter instance."""
    global _master_router
    if _master_router is None:
        _master_router = MasterIntentRouter(llm_classifier=llm_classifier)
    return _master_router
