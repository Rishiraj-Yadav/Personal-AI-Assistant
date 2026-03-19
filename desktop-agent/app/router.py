"""
Router Agent
Analyzes the user's natural language command and routes it
to the most appropriate specialist agent in the registry.
This mirrors OpenClaw's modular orchestration approach.
"""
from typing import Optional
import json
import re
import google.generativeai as genai
from loguru import logger
from config import settings
from skill_registry import registry

class RouterAgent:
    def __init__(self):
        if not settings.GOOGLE_API_KEY:
            self.model = None
            return

        genai.configure(api_key=settings.GOOGLE_API_KEY)
        self.model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=(
                "You are an intelligent routing engine. Your job is to classify "
                "the user's command and map it to exactly ONE of the available agents.\n"
                "If the command requires tools from multiple different agents (like launching an app AND clicking inside it), return 'system'.\n"
                "You MUST output raw JSON containing a single key 'agent_name'."
            )
        )
        logger.info("🚦 Router Agent initialized")

    async def route_command(self, command: str, context: Optional[str] = None) -> str:
        """
        Route the command to an agent name.
        Returns the agent name (e.g., 'app', 'web', 'gui').
        If uncertain, returns 'system' or None.
        """
        if not self.model:
            logger.error("Router has no API key.")
            return "system"

        # Build list of available agents
        agents_info = []
        for agent in registry.list_agents():
            agents_info.append(f"- {agent['name']}: {agent['description']}")
        
        agents_list = "\n".join(agents_info)

        prompt = f"""
Available Agents:
{agents_list}

User Command: {command}
Context: {context or 'None'}

IMPORTANT routing rules:
- If the user wants to OPEN a website (youtube, google, github, etc.) → use "app" (it has the open_url tool)
- If the command involves BOTH opening an app/website AND interacting with it (clicking, typing, searching inside it) → use "system" (to get all tools)
- If the command is purely about GUI interaction (clicking, typing, screenshots) on an already-open app → use "gui"

Determine the best agent to handle this command.
Return ONLY JSON format: {{"agent_name": "<name>"}}
"""
        try:
            response = await self.model.generate_content_async(prompt)
            text = response.text.strip()
            
            # Clean up JSON formatting using regex
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                text = match.group(0)

            parsed = json.loads(text)
            selected_agent = parsed.get("agent_name", "system")
            logger.info(f"🚦 Router selected agent: {selected_agent}")
            return selected_agent

        except Exception as e:
            logger.error(f"Router failed to parse response: {e}")
            return "system"  # Fallback gracefully
