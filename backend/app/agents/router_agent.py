"""
Router Agent - SMART VERSION
Automatically detects task type without user needing to toggle
"""
import os
import re
from typing import Dict, Any
from loguru import logger
import google.generativeai as genai


class RouterAgent:
    """
    Smart Router - Classifies ANY task automatically
    User never needs to pick mode - it just works!
    """
    
    # Pre-compiled patterns for fast-path routing (catches typos too)
    _WEB_FAST_PATTERNS = re.compile(
        r'brows|open\s+.{0,6}brows|'             # browser / broswer / browsr etc.
        r'leetcode|amazon|flipkart|github|'
        r'stackoverflow|wikipedia|reddit|twitter|'
        r'linkedin|facebook|instagram|netflix|'
        r'\.com\b|\.org\b|\.io\b|\.net\b|\.dev\b|'
        r'https?://|www\.',
        re.IGNORECASE
    )
    
    def __init__(self):
        api_key = os.getenv("GOOGLE_API_KEY", "")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash')
        logger.info("✅ Smart Router Agent initialized")
    
    def classify_task(
        self,
        user_message: str,
        user_context: str = "",
        conversation_history: list = None
    ) -> Dict[str, Any]:
        """
        Classify task with user context and conversation history.
        """
        
        # ── Fast-path: if message mentions browser/website, skip LLM ──
        if self._WEB_FAST_PATTERNS.search(user_message):
            logger.info("🎯 Fast-path: detected browser/website → web_autonomous")
            return {
                "task_type": "web_autonomous",
                "confidence": 0.95,
                "reasoning": "Detected browser or website reference",
                "next_agent": "web_autonomous_agent"
            }
        
        # Build recent conversation context for the classifier
        history_block = ""
        if conversation_history:
            recent = conversation_history[-6:]  # last 3 exchanges
            lines = []
            for msg in recent:
                role = msg.get('role', 'user') if isinstance(msg, dict) else 'user'
                content = (msg.get('content', '') if isinstance(msg, dict) else str(msg))[:120]
                lines.append(f"  {role}: {content}")
            history_block = "Recent conversation:\n" + "\n".join(lines) + "\n"
        
        classification_prompt = f"""You are an expert task classifier for a multi-agent AI system.

{user_context}

{history_block}User Request: "{user_message}"

Analyze this request and classify it into ONE category:

1. CODING - Write, generate, debug, test, or execute code
   Triggers: "write", "create", "build", "generate", "code", "script", "API", "app", "function"
   Examples: "write a Python script", "create React app", "debug this code", "make calculator"
   
2. DESKTOP - Control the HOST computer (open local desktop apps, click, type, screenshot, mouse)
   Triggers: "click", "type on keyboard", "screenshot", "mouse", "window", "minimize", "move window"
   Examples: "take screenshot", "click at 100,200", "launch VS Code", "minimize all windows"
   NOTE: DESKTOP is ONLY for controlling the user's physical computer. Do NOT use DESKTOP when the user wants to visit a website or browse the web.
   
3. WEB_AUTONOMOUS - Autonomously browse the web, research topics, interact with web pages, fill forms, compare products, book things, perform multi-step web tasks
   Triggers: "browse", "browser", "open browser", "search the web", "go to", "visit", "look up", "research", "compare", "book", "check price", "find flights", "order", "search for", "find me", "show me", "look for", "web search", "google", "browse to", "open website", "fill form", "sign up on", "buy", "purchase", "leetcode", "amazon", "wikipedia", "github"
   Examples: "open browser on leetcode", "search the web for best laptops 2026", "go to amazon and find AirPods price", "research AI news", "compare flights to NYC", "visit wikipedia and summarize the page about Mars", "open browser and go to github"

4. WEB - Simple scrape/weather/data fetch (no browsing needed)
   Triggers: "scrape", "weather", "fetch data", "download file", "get HTML"
   Examples: "scrape example.com", "what's the weather", "get data from URL"

5. EMAIL - Gmail operations: read, send, compose, search, draft emails
   Triggers: "email", "mail", "inbox", "send email", "compose", "unread", "gmail"
   Examples: "check my email", "send email to john", "read my inbox"

6. CALENDAR - Google Calendar: events, schedule, meetings, reminders
   Triggers: "calendar", "schedule", "meeting", "event", "appointment", "remind", "reminder"
   Examples: "what's on my calendar today", "schedule a meeting", "set a reminder"

7. GENERAL - Questions, conversations, explanations, unclear requests
   Triggers: Everything else
   Examples: "how are you", "explain quantum physics", "what can you do"

IMPORTANT RULES:
- If user mentions code/programming/app/API → CODING
- If user mentions file paths like "R:/..." → CODING
- If user says "create", "make", "build" + tech term → CODING
- "open browser", "browser", or any mention of a website name (leetcode, amazon, google, github, etc.) → WEB_AUTONOMOUS (NOT desktop!)
- If the user asks to open or search YouTube → DESKTOP (so it opens locally on host)
- If user wants to browse, search, research, visit a website, or do anything involving web pages → WEB_AUTONOMOUS
- If user just wants a simple scrape or weather check → WEB
- If user mentions email/mail/inbox → EMAIL
- If user mentions calendar/schedule/meeting → CALENDAR
- If in doubt between DESKTOP and WEB_AUTONOMOUS, choose WEB_AUTONOMOUS
- If in doubt between WEB and WEB_AUTONOMOUS, choose WEB_AUTONOMOUS

Respond EXACTLY in this format:
TASK_TYPE: [coding/desktop/web_autonomous/web/email/calendar/general]
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
            "web_autonomous": "web_autonomous_agent",
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
        
        # Desktop keywords — only physical desktop-control verbs (NOT "open" — too ambiguous)
        desktop_keywords = [
            "click", "screenshot", "mouse",
            "keyboard", "window", "minimize", "maximize",
            "launch app", "launch vs", "launch notepad",
            "take screenshot", "move mouse", "press key",
            "youtube", "open youtube"
        ]
        
        # Web autonomous keywords (browsing, research, interaction)
        web_auto_keywords = [
            "browse", "browser", "open browser", "search the web",
            "find on", "go to", "visit", "look up", "research",
            "compare", "book", "check price", "find flights", "order",
            "search for", "find me", "google", "web search", "browse to",
            "open website", "fill form", "show me", "look for",
            "buy online", "purchase online"
        ]
        
        website_names = [
            "leetcode", "amazon", "flipkart", "github",
            "stackoverflow", "wikipedia", "reddit", "twitter",
            "linkedin", "facebook", "instagram", "netflix",
            ".com", ".org", ".io", ".net", ".dev", "http"
        ]

        # Web keywords (simple scrape/fetch)
        web_keywords = [
            "scrape", "weather", "fetch", "download"
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
        
        # Check keywords — order matters: web_auto + website names first
        # Website names always → web_autonomous
        if any(kw in message_lower for kw in website_names):
            return {
                "task_type": "web_autonomous",
                "confidence": 0.90,
                "reasoning": "Detected website name — autonomous browsing",
                "next_agent": "web_autonomous_agent"
            }
        
        if any(kw in message_lower for kw in web_auto_keywords):
            return {
                "task_type": "web_autonomous",
                "confidence": 0.80,
                "reasoning": "Matched web autonomous keywords — autonomous browsing",
                "next_agent": "web_autonomous_agent"
            }
        
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