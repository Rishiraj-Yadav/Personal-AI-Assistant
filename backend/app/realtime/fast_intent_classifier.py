"""
Fast Intent Classifier - Phase 3
================================

Classifies user intents quickly using pattern matching and heuristics.
Falls back to LLM only when confidence is low.
"""

import re
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from loguru import logger


class IntentType(str, Enum):
    """Types of user intents."""
    DESKTOP_ACTION = "desktop_action"
    CODING = "coding"
    WEB_AUTONOMOUS = "web_autonomous"
    WEB_SIMPLE = "web_simple"
    EMAIL = "email"
    CALENDAR = "calendar"
    CONVERSATION = "conversation"
    GENERAL = "general"


@dataclass
class IntentResult:
    """Result of intent classification."""
    intent_type: IntentType
    confidence: float
    reasoning: str
    action: Optional[str] = None
    target: Optional[str] = None
    parameters: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.parameters is None:
            self.parameters = {}


class FastIntentClassifier:
    """
    Fast rule-based intent classifier.
    
    Uses pattern matching for high-confidence classification.
    Falls back to LLM for ambiguous cases.
    """
    
    # Desktop action patterns (high confidence)
    DESKTOP_PATTERNS = [
        # File/folder operations
        (r'open\s+(?:my\s+)?(?:the\s+)?(.+?)\s*(?:folder|directory|project)', 'fs.open', 0.92),
        (r'open\s+(?:the\s+)?file\s+(.+)', 'fs.open', 0.90),
        
        # App launch
        (r'(?:launch|start|open)\s+(?:the\s+)?(?:app\s+)?(?:vs\s*code|vscode|visual\s*studio\s*code)', 'app.launch', 0.95),
        (r'(?:launch|start|open)\s+(?:the\s+)?(?:app\s+)?(notepad|chrome|firefox|explorer|terminal|cmd|powershell)', 'app.launch', 0.95),
        
        # Website opening (physical browser) - simple open commands
        (r'open\s+(?:the\s+)?(youtube|google|github|gmail|reddit|twitter|linkedin|amazon|netflix|spotify|facebook|instagram|whatsapp)', 'web.open', 0.95),
        (r'(?:go to|visit)\s+(?:the\s+)?(youtube|google|github|gmail|reddit|twitter|linkedin|amazon|netflix|spotify)', 'web.open', 0.93),
        
        # Screenshot
        (r'(?:take|capture)\s+(?:a\s+)?screenshot', 'screen.capture', 0.98),
        
        # Window control
        (r'(?:minimize|maximize|close)\s+(?:the\s+)?(?:current\s+)?window', 'window.control', 0.90),
        
        # Mouse/keyboard
        (r'click\s+(?:at\s+)?(\d+)\s*,?\s*(\d+)', 'mouse.click', 0.95),
        (r'type\s+(.+)', 'keyboard.type', 0.90),
        (r'press\s+(.+)', 'keyboard.press', 0.92),
        
        # Ensure browser (for web tasks)
        (r'(?:open|start|launch)\s+(?:the\s+)?(?:default\s+)?browser', 'browser.ensure', 0.95),
    ]
    
    # Web interaction patterns (needs browser + GUI interaction - falls back to full orchestration)
    WEB_INTERACTION_PATTERNS = [
        (r'search\s+(?:for\s+)?(.+?)\s+on\s+(youtube|google|amazon)', 'web.search', 0.70),  # Low confidence → needs full orchestration
        (r'play\s+(.+?)\s+on\s+(youtube|spotify|netflix)', 'web.play', 0.70),
        (r'(?:find|look for)\s+(.+?)\s+(?:on|in)\s+(youtube|amazon|google)', 'web.search', 0.70),
    ]
    
    # Coding patterns
    CODING_PATTERNS = [
        (r'(?:write|create|build|make|generate)\s+(?:a\s+)?(?:python|javascript|react|node|flask)\s+', 0.85),
        (r'(?:write|create|generate)\s+(?:a\s+)?(?:script|program|function|class|app|api)', 0.80),
        (r'(?:debug|fix|refactor)\s+(?:the\s+)?(?:code|error|bug)', 0.85),
        (r'(?:code|program|script)\s+(?:that|to|for)', 0.75),
    ]
    
    # Web autonomous patterns
    WEB_PATTERNS = [
        (r'(?:browse|search|find|research|look up)\s+(?:for\s+)?(?:on\s+)?(?:the\s+)?(?:web|internet|google)', 0.85),
        (r'(?:go to|visit|navigate to)\s+(?:the\s+)?(?:website|page|site)', 0.80),
        (r'(?:search|find|look for)\s+(.+?)\s+on\s+(amazon|ebay|google|youtube)', 0.90),
    ]
    
    # Email patterns
    EMAIL_PATTERNS = [
        (r'(?:check|read|send|compose|write)\s+(?:my\s+)?(?:an?\s+)?email', 0.90),
        (r'(?:inbox|unread|mail)', 0.85),
    ]
    
    # Calendar patterns
    CALENDAR_PATTERNS = [
        (r'(?:schedule|create|add|set)\s+(?:a\s+)?(?:meeting|event|appointment|reminder)', 0.90),
        (r'(?:what.+?my\s+)?calendar', 0.85),
        (r'(?:meetings?|events?)\s+(?:today|tomorrow|this week)', 0.85),
    ]
    
    def __init__(self):
        """Initialize the classifier with compiled patterns."""
        self._desktop_patterns = [
            (re.compile(pattern, re.IGNORECASE), action, conf)
            for pattern, action, conf in self.DESKTOP_PATTERNS
        ]
        self._coding_patterns = [
            (re.compile(pattern, re.IGNORECASE), conf)
            for pattern, conf in self.CODING_PATTERNS
        ]
        self._web_patterns = [
            (re.compile(pattern, re.IGNORECASE), conf)
            for pattern, conf in self.WEB_PATTERNS
        ]
        self._email_patterns = [
            (re.compile(pattern, re.IGNORECASE), conf)
            for pattern, conf in self.EMAIL_PATTERNS
        ]
        self._calendar_patterns = [
            (re.compile(pattern, re.IGNORECASE), conf)
            for pattern, conf in self.CALENDAR_PATTERNS
        ]
        
        logger.info("✅ FastIntentClassifier initialized")
    
    def classify(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None
    ) -> IntentResult:
        """
        Classify the user's intent.
        
        Args:
            message: User's message
            context: Optional context for better classification
            
        Returns:
            IntentResult with classification details
        """
        message = message.strip()
        
        # Try desktop patterns first (highest priority for desktop actions)
        for pattern, action, confidence in self._desktop_patterns:
            match = pattern.search(message)
            if match:
                target = match.group(1) if match.groups() else None
                return IntentResult(
                    intent_type=IntentType.DESKTOP_ACTION,
                    confidence=confidence,
                    reasoning=f"Matched desktop pattern: {action}",
                    action=action,
                    target=target
                )
        
        # Try coding patterns
        for pattern, confidence in self._coding_patterns:
            if pattern.search(message):
                return IntentResult(
                    intent_type=IntentType.CODING,
                    confidence=confidence,
                    reasoning="Matched coding pattern"
                )
        
        # Try web patterns
        for pattern, confidence in self._web_patterns:
            if pattern.search(message):
                return IntentResult(
                    intent_type=IntentType.WEB_AUTONOMOUS,
                    confidence=confidence,
                    reasoning="Matched web autonomous pattern"
                )
        
        # Try email patterns
        for pattern, confidence in self._email_patterns:
            if pattern.search(message):
                return IntentResult(
                    intent_type=IntentType.EMAIL,
                    confidence=confidence,
                    reasoning="Matched email pattern"
                )
        
        # Try calendar patterns
        for pattern, confidence in self._calendar_patterns:
            if pattern.search(message):
                return IntentResult(
                    intent_type=IntentType.CALENDAR,
                    confidence=confidence,
                    reasoning="Matched calendar pattern"
                )
        
        # Check for conversational patterns
        if self._is_conversational(message):
            return IntentResult(
                intent_type=IntentType.CONVERSATION,
                confidence=0.70,
                reasoning="Appears to be conversational"
            )
        
        # Default: general with low confidence
        return IntentResult(
            intent_type=IntentType.GENERAL,
            confidence=0.40,
            reasoning="No specific patterns matched"
        )
    
    def _is_conversational(self, message: str) -> bool:
        """Check if message is conversational."""
        conversational_starts = [
            "hi", "hello", "hey", "how are you",
            "what can you", "who are you",
            "thanks", "thank you", "bye", "goodbye"
        ]
        message_lower = message.lower()
        return any(message_lower.startswith(s) for s in conversational_starts)


# Global instance
fast_intent_classifier = FastIntentClassifier()
