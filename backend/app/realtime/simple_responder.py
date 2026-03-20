"""
Simple Responder - Phase 3
==========================

Handles simple conversational responses without tool execution.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from loguru import logger


@dataclass
class SimpleResponse:
    """Simple response result."""
    response: str
    intent_type: str
    confidence: float


class SimpleResponder:
    """
    Handles simple responses that don't require tool execution.
    
    For greetings, thanks, help requests, etc.
    """
    
    GREETINGS = {
        "hi": "Hello! How can I help you today?",
        "hello": "Hi there! What would you like me to do?",
        "hey": "Hey! I'm ready to help. What do you need?",
        "good morning": "Good morning! How can I assist you today?",
        "good afternoon": "Good afternoon! What can I help you with?",
        "good evening": "Good evening! How may I assist you?",
    }
    
    FAREWELLS = {
        "bye": "Goodbye! Have a great day!",
        "goodbye": "Take care! See you next time.",
        "see you": "See you later! Feel free to come back anytime.",
        "thanks bye": "You're welcome! Goodbye!",
    }
    
    THANKS = {
        "thanks": "You're welcome! Let me know if you need anything else.",
        "thank you": "Happy to help! Anything else I can do for you?",
        "thx": "No problem! Need anything else?",
    }
    
    CAPABILITIES = """I'm your AI desktop assistant. I can help you with:

**Desktop Control:**
- Open applications (VS Code, Chrome, Notepad, etc.)
- Take screenshots
- Control mouse and keyboard
- Manage windows

**Development:**
- Write and generate code
- Create projects (React, Python, Node.js)
- Debug and fix code

**Web:**
- Browse and research topics
- Search the web autonomously

**Productivity:**
- Manage emails (read, send, compose)
- Schedule calendar events

Just tell me what you need!"""
    
    def __init__(self):
        logger.info("✅ SimpleResponder initialized")
    
    def respond(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[SimpleResponse]:
        """
        Generate a simple response if applicable.
        
        Args:
            message: User's message
            context: Optional context
            
        Returns:
            SimpleResponse if handled, None otherwise
        """
        message_lower = message.lower().strip()
        
        # Check greetings
        for pattern, response in self.GREETINGS.items():
            if message_lower.startswith(pattern):
                return SimpleResponse(
                    response=response,
                    intent_type="greeting",
                    confidence=0.95
                )
        
        # Check farewells
        for pattern, response in self.FAREWELLS.items():
            if pattern in message_lower:
                return SimpleResponse(
                    response=response,
                    intent_type="farewell",
                    confidence=0.95
                )
        
        # Check thanks
        for pattern, response in self.THANKS.items():
            if message_lower.startswith(pattern):
                return SimpleResponse(
                    response=response,
                    intent_type="thanks",
                    confidence=0.95
                )
        
        # Check capability questions
        if any(phrase in message_lower for phrase in [
            "what can you do", "what are you", "who are you",
            "your capabilities", "help", "how do i"
        ]):
            return SimpleResponse(
                response=self.CAPABILITIES,
                intent_type="capabilities",
                confidence=0.90
            )
        
        return None


# Global instance
simple_responder = SimpleResponder()
