"""
Router Agent - smart task classification for the backend orchestrator.
"""
import os
import re
from typing import Any, Dict, Optional

import google.generativeai as genai
from loguru import logger

from app.config import settings


class RouterAgent:
    """
    Smart Router - classifies incoming tasks without user mode selection.
    """

    _WEB_FAST_PATTERNS = re.compile(
        r"brows|open\s+.{0,6}brows|"
        r"leetcode|amazon|flipkart|youtube|github|"
        r"stackoverflow|wikipedia|reddit|twitter|"
        r"linkedin|facebook|instagram|netflix|"
        r"\.com\b|\.org\b|\.io\b|\.net\b|\.dev\b|"
        r"https?://|www\.",
        re.IGNORECASE,
    )
    _EMAIL_FAST_PATTERNS = re.compile(
        r"\b(gmail|email|mail|inbox|draft|unread|send email|send mail|compose email|compose mail|cc|bcc)\b",
        re.IGNORECASE,
    )
    _CALENDAR_FAST_PATTERNS = re.compile(
        r"\b(calendar|google calendar|schedule|scheduled|meeting|event|appointment|remind|reminder|availability)\b",
        re.IGNORECASE,
    )
    _EMAIL_FOLLOWUP_PATTERNS = re.compile(
        r"^\s*(send it|yes send|send the email|send the draft|go ahead|go ahead and send)\s*[.!]*\s*$",
        re.IGNORECASE,
    )

    def __init__(self):
        api_key = os.getenv("GOOGLE_API_KEY", "")
        genai.configure(api_key=api_key)
        model_name = settings.GEMINI_MODEL if api_key else "gemini-2.5-flash"
        self.model = genai.GenerativeModel(model_name)
        logger.info("Smart Router Agent initialized")

    def _history_text(self, conversation_history: Optional[list] = None) -> str:
        """Flatten recent conversation history for fast-path checks."""
        if not conversation_history:
            return ""

        chunks = []
        for msg in conversation_history[-6:]:
            if isinstance(msg, dict):
                chunks.append(str(msg.get("content", "")))
            else:
                chunks.append(str(msg))
        return "\n".join(chunks).lower()

    def _fast_specialist_route(
        self,
        user_message: str,
        conversation_history: Optional[list] = None,
    ) -> Optional[Dict[str, Any]]:
        """Short-circuit obvious Gmail and Calendar requests before web routing."""
        message_lower = user_message.lower()
        history_text = self._history_text(conversation_history)

        if self._EMAIL_FAST_PATTERNS.search(user_message):
            return {
                "task_type": "email",
                "confidence": 0.98,
                "reasoning": "Detected Gmail or email intent.",
                "next_agent": "email_specialist",
            }

        if self._EMAIL_FOLLOWUP_PATTERNS.match(user_message) and (
            "draft id:" in history_text or "email draft created" in history_text
        ):
            return {
                "task_type": "email",
                "confidence": 0.98,
                "reasoning": "Detected a send confirmation for a previously drafted email.",
                "next_agent": "email_specialist",
            }

        if self._CALENDAR_FAST_PATTERNS.search(user_message) or any(
            phrase in message_lower
            for phrase in [
                "add it to calendar",
                "schedule it",
                "set a reminder",
                "list reminders",
                "what's on my calendar",
                "what is on my calendar",
                "today's schedule",
            ]
        ):
            return {
                "task_type": "calendar",
                "confidence": 0.98,
                "reasoning": "Detected Google Calendar or scheduling intent.",
                "next_agent": "calendar_specialist",
            }

        return None

    def classify_task(
        self,
        user_message: str,
        user_context: str = "",
        conversation_history: list = None,
    ) -> Dict[str, Any]:
        """
        Classify task with user context and conversation history.
        """
        specialist_route = self._fast_specialist_route(user_message, conversation_history)
        if specialist_route:
            logger.info(f"Fast-path classified as {specialist_route['task_type']}")
            return specialist_route

        if self._WEB_FAST_PATTERNS.search(user_message):
            logger.info("Fast-path classified as web_autonomous")
            return {
                "task_type": "web_autonomous",
                "confidence": 0.95,
                "reasoning": "Detected browser or website reference.",
                "next_agent": "web_autonomous_agent",
            }

        history_block = ""
        if conversation_history:
            recent = conversation_history[-6:]
            lines = []
            for msg in recent:
                role = msg.get("role", "user") if isinstance(msg, dict) else "user"
                content = (msg.get("content", "") if isinstance(msg, dict) else str(msg))[:120]
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
   Triggers: "browse", "browser", "open browser", "search the web", "go to", "visit", "look up", "research", "compare", "book", "check price", "find flights", "order", "search for", "find me", "show me", "look for", "web search", "search google", "google search", "browse to", "open website", "fill form", "sign up on", "buy", "purchase", "leetcode", "amazon", "wikipedia", "youtube", "github"
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
- If user mentions code/programming/app/API -> CODING
- If user mentions file paths like "R:/..." -> CODING
- If user says "create", "make", "build" + tech term -> CODING
- "open browser", "browser", or any mention of a website name (leetcode, amazon, youtube, github, etc.) -> WEB_AUTONOMOUS (NOT desktop)
- If user wants to browse, search, research, visit a website, or do anything involving web pages -> WEB_AUTONOMOUS
- If user just wants a simple scrape or weather check -> WEB
- If user mentions gmail/email/mail/inbox -> EMAIL even though it is a Google product
- If user mentions Google Calendar/calendar/schedule/meeting/reminder -> CALENDAR, not WEB_AUTONOMOUS
- If user says "send it" after an email draft was created -> EMAIL
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

            task_type = "general"
            confidence = 0.5
            reasoning = ""

            for line in result_text.split("\n"):
                if line.startswith("TASK_TYPE:"):
                    task_type = line.split(":", 1)[1].strip().lower()
                elif line.startswith("CONFIDENCE:"):
                    try:
                        confidence = float(line.split(":", 1)[1].strip())
                    except Exception:
                        confidence = 0.7
                elif line.startswith("REASONING:"):
                    reasoning = line.split(":", 1)[1].strip()

            logger.info(f"Classified: {task_type} ({confidence:.0%} confidence)")

            return {
                "task_type": task_type,
                "confidence": confidence,
                "reasoning": reasoning,
                "next_agent": self._get_next_agent(task_type),
            }

        except Exception as exc:
            logger.error(f"Classification error: {exc}")
            return self._fallback_classification(user_message)

    def _get_next_agent(self, task_type: str) -> str:
        """Route to appropriate agent."""
        routing_map = {
            "coding": "code_specialist",
            "desktop": "desktop_specialist",
            "web_autonomous": "web_autonomous_agent",
            "web": "web_specialist",
            "email": "email_specialist",
            "calendar": "calendar_specialist",
            "general": "general_assistant",
        }
        return routing_map.get(task_type, "general_assistant")

    def _fallback_classification(self, message: str) -> Dict[str, Any]:
        """Keyword-based fallback."""
        message_lower = message.lower()

        coding_keywords = [
            "write",
            "code",
            "script",
            "program",
            "function",
            "class",
            "python",
            "javascript",
            "react",
            "flask",
            "api",
            "app",
            "create",
            "build",
            "make",
            "generate",
            "develop",
            "debug",
            "fix",
            "test",
            "compile",
            "execute",
            "run",
        ]

        desktop_keywords = [
            "click",
            "screenshot",
            "mouse",
            "keyboard",
            "window",
            "minimize",
            "maximize",
            "launch app",
            "launch vs",
            "launch notepad",
            "take screenshot",
            "move mouse",
            "press key",
        ]

        email_keywords = [
            "email",
            "mail",
            "inbox",
            "compose",
            "send email",
            "draft",
            "unread",
            "gmail",
            "send mail",
        ]

        calendar_keywords = [
            "calendar",
            "google calendar",
            "schedule",
            "meeting",
            "event",
            "appointment",
            "remind",
            "reminder",
            "what's on",
        ]

        web_auto_keywords = [
            "browse",
            "browser",
            "open browser",
            "search the web",
            "find on",
            "go to",
            "visit",
            "look up",
            "research",
            "compare",
            "book",
            "check price",
            "find flights",
            "order",
            "search for",
            "find me",
            "search google",
            "google search",
            "web search",
            "browse to",
            "open website",
            "fill form",
            "show me",
            "look for",
            "buy online",
            "purchase online",
        ]

        website_names = [
            "leetcode",
            "amazon",
            "flipkart",
            "youtube",
            "github",
            "stackoverflow",
            "wikipedia",
            "reddit",
            "twitter",
            "linkedin",
            "facebook",
            "instagram",
            "netflix",
            ".com",
            ".org",
            ".io",
            ".net",
            ".dev",
            "http",
        ]

        web_keywords = [
            "scrape",
            "weather",
            "fetch",
            "download",
        ]

        if any(keyword in message_lower for keyword in coding_keywords):
            return {
                "task_type": "coding",
                "confidence": 0.75,
                "reasoning": "Matched coding keywords.",
                "next_agent": "code_specialist",
            }

        if any(keyword in message_lower for keyword in email_keywords):
            return {
                "task_type": "email",
                "confidence": 0.80,
                "reasoning": "Matched email keywords.",
                "next_agent": "email_specialist",
            }

        if any(keyword in message_lower for keyword in calendar_keywords):
            return {
                "task_type": "calendar",
                "confidence": 0.80,
                "reasoning": "Matched calendar keywords.",
                "next_agent": "calendar_specialist",
            }

        if any(keyword in message_lower for keyword in website_names):
            return {
                "task_type": "web_autonomous",
                "confidence": 0.90,
                "reasoning": "Detected website name - autonomous browsing.",
                "next_agent": "web_autonomous_agent",
            }

        if any(keyword in message_lower for keyword in web_auto_keywords):
            return {
                "task_type": "web_autonomous",
                "confidence": 0.80,
                "reasoning": "Matched web autonomous keywords - autonomous browsing.",
                "next_agent": "web_autonomous_agent",
            }

        if any(keyword in message_lower for keyword in desktop_keywords):
            return {
                "task_type": "desktop",
                "confidence": 0.75,
                "reasoning": "Matched desktop keywords.",
                "next_agent": "desktop_specialist",
            }

        if any(keyword in message_lower for keyword in web_keywords):
            return {
                "task_type": "web",
                "confidence": 0.75,
                "reasoning": "Matched web keywords.",
                "next_agent": "web_specialist",
            }

        return {
            "task_type": "general",
            "confidence": 0.5,
            "reasoning": "No specific keywords matched.",
            "next_agent": "general_assistant",
        }


router_agent = RouterAgent()
