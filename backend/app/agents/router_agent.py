"""
Router Agent - SMART VERSION
Automatically detects task type without user needing to toggle
"""
import os
from typing import Dict, Any
from loguru import logger
import google.generativeai as genai


class RouterAgent:
    """
    Smart Router - Classifies ANY task automatically
    User never needs to pick mode - it just works!
    """
    
    def __init__(self):
        api_key = os.getenv("GOOGLE_API_KEY", "")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash')
        logger.info("✅ Smart Router Agent initialized")
    
    def classify_task(
        self,
        user_message: str,
        user_context: str = ""  # NEW - User preferences
    ) -> Dict[str, Any]:
        """
        Classify task with user context
        
        Args:
            user_message: What user asked
            user_context: User's learned preferences
        """
        
        classification_prompt = f"""You are an expert task classifier for a multi-agent AI system.

{user_context}

User Request: "{user_message}"

Analyze this request and classify it into ONE category:

1. CODING - Write, generate, debug, test, or execute code
   Triggers: "write", "create", "build", "generate", "code", "script", "API", "app", "function"
   Examples: "write a Python script", "create React app", "debug this code", "make calculator"
   
2. DESKTOP - Control computer (open apps, click, type, screenshot)
   Triggers: "open", "click", "type", "screenshot", "mouse", "window", "launch", "close"
   Examples: "open Chrome", "take screenshot", "click at 100,200", "launch VS Code"
   
3. WEB - Scrape websites, get weather, fetch data
   Triggers: "scrape", "website", "URL", "weather", "fetch", "download", "browse"
   Examples: "scrape example.com", "what's the weather", "get data from URL"

4. EMAIL - Gmail operations: read, send, compose, search, draft emails
   Triggers: "email", "mail", "inbox", "send email", "compose", "unread", "gmail"
   Examples: "check my email", "send email to john", "read my inbox", "search emails from boss", "any unread emails?"

5. CALENDAR - Google Calendar: events, schedule, meetings, reminders
   Triggers: "calendar", "schedule", "meeting", "event", "appointment", "remind", "reminder", "what's on"
   Examples: "what's on my calendar today", "schedule a meeting", "set a reminder", "create event tomorrow 3pm"

6. GENERAL - Questions, conversations, explanations, unclear requests
   Triggers: Everything else
   Examples: "how are you", "explain quantum physics", "what can you do"

IMPORTANT RULES:
- If user mentions code/programming/app/API → CODING
- If user mentions file paths like "R:/..." → CODING (they want to work with files)
- If user says "create", "make", "build" + tech term → CODING
- If user mentions email/mail/inbox/compose/send email → EMAIL
- If user mentions calendar/schedule/meeting/event/reminder → CALENDAR
- Be decisive! Coding is the most common task.

Respond EXACTLY in this format:
TASK_TYPE: [coding/desktop/web/email/calendar/general]
CONFIDENCE: [0.0-1.0]
REASONING: [Brief explanation]

Classify now:"""

        try:
            response = self.model.generate_content(classification_prompt)
            result_text = response.text.strip()
            
            # Parse response
            task_type = "general"
            confidence = 0.5
            reasoning = ""
            
            for line in result_text.split('\n'):
                if line.startswith("TASK_TYPE:"):
                    task_type = line.split(":", 1)[1].strip().lower()
                elif line.startswith("CONFIDENCE:"):
                    try:
                        confidence = float(line.split(":", 1)[1].strip())
                    except:
                        confidence = 0.7
                elif line.startswith("REASONING:"):
                    reasoning = line.split(":", 1)[1].strip()
            
            logger.info(f"🎯 Classified: {task_type} ({confidence:.0%} confidence)")
            
            return {
                "task_type": task_type,
                "confidence": confidence,
                "reasoning": reasoning,
                "next_agent": self._get_next_agent(task_type)
            }
        
        except Exception as e:
            logger.error(f"❌ Classification error: {e}")
            # Fallback to keyword matching
            return self._fallback_classification(user_message)
    
    def _get_next_agent(self, task_type: str) -> str:
        """Route to appropriate agent"""
        routing_map = {
            "coding": "code_specialist",
            "desktop": "desktop_specialist",
            "web": "web_specialist",
            "email": "email_specialist",
            "calendar": "calendar_specialist",
            "general": "general_assistant"
        }
        return routing_map.get(task_type, "general_assistant")
    
    def _fallback_classification(self, message: str) -> Dict[str, Any]:
        """Keyword-based fallback"""
        message_lower = message.lower()
        
        # Coding keywords (expanded!)
        coding_keywords = [
            "write", "code", "script", "program", "function", "class",
            "python", "javascript", "react", "flask", "api", "app",
            "create", "build", "make", "generate", "develop",
            "debug", "fix", "test", "compile", "execute", "run"
        ]
        
        # Desktop keywords
        desktop_keywords = [
            "open", "click", "type", "screenshot", "mouse",
            "keyboard", "window", "close", "minimize"
        ]
        
        # Web keywords
        web_keywords = [
            "scrape", "website", "url", "weather", "fetch", "download"
        ]
        
        # Email keywords
        email_keywords = [
            "email", "mail", "inbox", "compose", "send email", "draft",
            "unread", "gmail", "send mail"
        ]
        
        # Calendar keywords
        calendar_keywords = [
            "calendar", "schedule", "meeting", "event", "appointment",
            "remind", "reminder", "what's on"
        ]
        
        # Check keywords
        if any(kw in message_lower for kw in coding_keywords):
            return {
                "task_type": "coding",
                "confidence": 0.75,
                "reasoning": "Matched coding keywords",
                "next_agent": "code_specialist"
            }
        
        if any(kw in message_lower for kw in email_keywords):
            return {
                "task_type": "email",
                "confidence": 0.80,
                "reasoning": "Matched email keywords",
                "next_agent": "email_specialist"
            }
        
        if any(kw in message_lower for kw in calendar_keywords):
            return {
                "task_type": "calendar",
                "confidence": 0.80,
                "reasoning": "Matched calendar keywords",
                "next_agent": "calendar_specialist"
            }
        
        if any(kw in message_lower for kw in desktop_keywords):
            return {
                "task_type": "desktop",
                "confidence": 0.75,
                "reasoning": "Matched desktop keywords",
                "next_agent": "desktop_specialist"
            }
        
        if any(kw in message_lower for kw in web_keywords):
            return {
                "task_type": "web",
                "confidence": 0.75,
                "reasoning": "Matched web keywords",
                "next_agent": "web_specialist"
            }
        
        return {
            "task_type": "general",
            "confidence": 0.5,
            "reasoning": "No specific keywords matched",
            "next_agent": "general_assistant"
        }


# Global instance
router_agent = RouterAgent()