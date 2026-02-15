"""
Router Agent
Classifies user tasks and routes to appropriate specialist agent
Uses Google Gemini for fast, cheap classification
"""
import os
from typing import Dict, Any
from loguru import logger
import google.generativeai as genai


class RouterAgent:
    """
    Router Agent - Classifies tasks and routes to specialists
    Uses Google Gemini Flash (fast, cheap, good at classification)
    """
    
    def __init__(self):
        """Initialize router agent with Gemini"""
        api_key = os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            logger.warning("⚠️ GOOGLE_API_KEY not set - router will fail")
        
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash')
        # self.model = genai.GenerativeModel('gemini-1.5-flash-latest')
        logger.info("✅ Router Agent initialized with Gemini Flash")
    
    def classify_task(self, user_message: str) -> Dict[str, Any]:
        """
        Classify user task into categories
        
        Args:
            user_message: User's input message
            
        Returns:
            Classification result with task_type, confidence, reasoning
        """
        
        classification_prompt = f"""You are a task classification expert. Analyze the user's request and classify it into ONE category.

User Request: "{user_message}"

Categories:
1. CODING - User wants to write, generate, execute, debug, or test code
   Examples: "write a script", "create an API", "debug this code", "run this python"
   
2. DESKTOP - User wants to control their computer (open apps, click, type)
   Examples: "open Chrome", "take a screenshot", "click at coordinates"
   
3. WEB - User wants to scrape websites, check weather, or browse
   Examples: "scrape this website", "what's the weather", "get data from URL"
   
4. GENERAL - General questions, conversations, or unclear requests
   Examples: "how are you", "what can you do", "explain quantum physics"

Respond in this EXACT format:
TASK_TYPE: [coding/desktop/web/general]
CONFIDENCE: [0.0-1.0]
REASONING: [Brief explanation]

Example:
TASK_TYPE: coding
CONFIDENCE: 0.95
REASONING: User explicitly asks to "write a Python script" which is code generation.

Now classify the user request above:"""

        try:
            response = self.model.generate_content(classification_prompt)
            result_text = response.text.strip()
            
            # Parse response
            lines = result_text.split('\n')
            task_type = "general"
            confidence = 0.5
            reasoning = "Unable to parse classification"
            
            for line in lines:
                if line.startswith("TASK_TYPE:"):
                    task_type = line.split(":", 1)[1].strip().lower()
                elif line.startswith("CONFIDENCE:"):
                    try:
                        confidence = float(line.split(":", 1)[1].strip())
                    except:
                        confidence = 0.5
                elif line.startswith("REASONING:"):
                    reasoning = line.split(":", 1)[1].strip()
            
            logger.info(f"🎯 Classified as: {task_type} (confidence: {confidence})")
            
            return {
                "task_type": task_type,
                "confidence": confidence,
                "reasoning": reasoning,
                "next_agent": self._get_next_agent(task_type)
            }
        
        except Exception as e:
            logger.error(f"❌ Router classification error: {str(e)}")
            # Fallback: simple keyword matching
            return self._fallback_classification(user_message)
    
    def _get_next_agent(self, task_type: str) -> str:
        """Determine which specialist agent to route to"""
        routing_map = {
            "coding": "code_specialist",
            "desktop": "desktop_specialist",
            "web": "web_specialist",
            "general": "general_assistant"
        }
        return routing_map.get(task_type, "general_assistant")
    
    def _fallback_classification(self, message: str) -> Dict[str, Any]:
        """Simple keyword-based fallback if Gemini fails"""
        message_lower = message.lower()
        
        # Coding keywords
        coding_keywords = [
            "write", "code", "script", "program", "function",
            "python", "javascript", "java", "api", "debug",
            "execute", "run this", "compile", "test"
        ]
        
        # Desktop keywords
        desktop_keywords = [
            "open", "click", "type", "screenshot", "mouse",
            "keyboard", "window", "app", "application", "launch"
        ]
        
        # Web keywords
        web_keywords = [
            "scrape", "website", "url", "weather", "fetch",
            "download", "browse", "web page"
        ]
        
        # Check keywords
        if any(kw in message_lower for kw in coding_keywords):
            return {
                "task_type": "coding",
                "confidence": 0.7,
                "reasoning": "Matched coding keywords (fallback)",
                "next_agent": "code_specialist"
            }
        
        if any(kw in message_lower for kw in desktop_keywords):
            return {
                "task_type": "desktop",
                "confidence": 0.7,
                "reasoning": "Matched desktop keywords (fallback)",
                "next_agent": "desktop_specialist"
            }
        
        if any(kw in message_lower for kw in web_keywords):
            return {
                "task_type": "web",
                "confidence": 0.7,
                "reasoning": "Matched web keywords (fallback)",
                "next_agent": "web_specialist"
            }
        
        return {
            "task_type": "general",
            "confidence": 0.5,
            "reasoning": "No specific keywords matched (fallback)",
            "next_agent": "general_assistant"
        }


# Global router instance
router_agent = RouterAgent()