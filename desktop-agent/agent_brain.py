"""
Agent Brain — Orchestrator Agent
The brain of the desktop agent. Takes natural language commands,
plans multi-step execution, dispatches to specialist agents via the SkillRegistry.
Uses Gemini Flash for reasoning (ReAct pattern: Think → Act → Observe → Repeat).
"""
import json
import google.generativeai as genai
from typing import Dict, Any, List, Optional
from loguru import logger
from config import settings
from skill_registry import registry


class AgentBrain:
    """
    Orchestrator Agent — the brain of the desktop agent.
    Receives NL commands and executes them using specialist agents.
    """

    SYSTEM_PROMPT = """You are a powerful desktop assistant running on the user's Windows PC.
You can control their computer by calling tools. You have access to these specialist capabilities:
- Launch/close applications, open folders and URLs
- Run PowerShell/CMD commands safely
- Manage files and folders (create, delete, move, copy, search, read)
- Control mouse, keyboard, take screenshots, read screen text via OCR
- Get system info (CPU, RAM, battery, network, processes)
- Manage clipboard (get/set text)
- Fetch web pages, search the web, download files
- Schedule tasks and reminders for later
- Send desktop notifications and speak text aloud

RULES:
1. Always use the available tools to accomplish tasks. Do NOT just describe what you would do.
2. For multi-step tasks, execute them one step at a time. After each tool call, observe the result before deciding the next step.
3. If a tool call fails, try an alternative approach instead of giving up.
4. Be concise in your final response — tell the user what you DID, not what you WOULD do.
5. If the user asks something that doesn't require a tool (like a question), just answer directly.
6. For potentially dangerous operations (deleting files, killing processes), explain what you're about to do before doing it.
7. When dealing with file paths on Windows, use backslashes (\\).
8. Current user's home directory can be found in system environment variables.
"""

    def __init__(self):
        """Initialize the Orchestrator with Gemini Flash"""
        if not settings.GOOGLE_API_KEY:
            logger.error("GOOGLE_API_KEY not set in .env.desktop or .env. Agent brain will not work.")
            self.model = None
            return

        genai.configure(api_key=settings.GOOGLE_API_KEY)
        self.model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=self.SYSTEM_PROMPT,
        )
        self._conversation_history: List[Dict] = []
        self._max_history = 20  # Keep last 20 messages for context
        logger.info("🧠 Agent Brain (Orchestrator) initialized with Gemini Flash")

    def _build_tools(self) -> List[Dict]:
        """Get all tools from the registry formatted for Gemini"""
        tools = registry.get_all_tools()
        if not tools:
            logger.warning("No tools registered in the skill registry!")
            return []

        # Convert to Gemini function declarations
        gemini_tools = []
        for tool in tools:
            func = tool["function"]
            declaration = {
                "name": func["name"],
                "description": func["description"],
                "parameters": func.get("parameters", {"type": "object", "properties": {}}),
            }
            gemini_tools.append(declaration)

        return gemini_tools

    async def process_command(self, command: str) -> Dict[str, Any]:
        """
        Process a natural language command through the ReAct loop.

        Args:
            command: Natural language command from the user

        Returns:
            Dict with:
            - response: str — final text response
            - actions_taken: list — tools that were called
            - success: bool
        """
        if not self.model:
            return {
                "response": "Agent brain not initialized. Please set GOOGLE_API_KEY in .env.desktop or .env",
                "actions_taken": [],
                "success": False,
            }

        actions_taken = []
        gemini_tools = self._build_tools()

        logger.info(f"🧠 Processing command: {command}")
        logger.info(f"📦 Available tools: {len(gemini_tools)}")

        # Build tool config for Gemini
        tool_config = None
        tools_param = None
        if gemini_tools:
            tools_param = [genai.protos.Tool(
                function_declarations=[
                    genai.protos.FunctionDeclaration(
                        name=t["name"],
                        description=t["description"],
                        parameters=self._convert_to_proto_schema(t["parameters"]),
                    )
                    for t in gemini_tools
                ]
            )]

        # Start a chat with history
        chat = self.model.start_chat(history=self._get_chat_history())

        try:
            # Send the user's message
            response = chat.send_message(
                command,
                tools=tools_param,
            )

            # ReAct loop — keep executing tool calls until the model gives a text response
            max_iterations = 10
            iteration = 0

            while iteration < max_iterations:
                iteration += 1

                # Check if the model wants to call tools
                if not response.candidates:
                    break

                candidate = response.candidates[0]
                parts = candidate.content.parts

                # Collect all function calls from this response
                function_calls = [p for p in parts if p.function_call.name]

                if not function_calls:
                    # No more tool calls — we have the final text response
                    break

                # Execute each function call
                function_responses = []
                for part in function_calls:
                    fn_call = part.function_call
                    tool_name = fn_call.name
                    tool_args = dict(fn_call.args) if fn_call.args else {}

                    logger.info(f"🔧 Tool call [{iteration}]: {tool_name}({tool_args})")

                    # Execute via registry
                    result = registry.execute_tool(tool_name, tool_args)
                    actions_taken.append({
                        "tool": tool_name,
                        "args": tool_args,
                        "success": result.get("success", False),
                        "result_preview": str(result.get("result", ""))[:200],
                    })

                    logger.info(
                        f"{'✅' if result.get('success') else '❌'} "
                        f"{tool_name} → {str(result)[:100]}"
                    )

                    # Build function response for Gemini
                    function_responses.append(
                        genai.protos.Part(
                            function_response=genai.protos.FunctionResponse(
                                name=tool_name,
                                response={"result": json.dumps(result, default=str)},
                            )
                        )
                    )

                # Send tool results back to the model
                response = chat.send_message(
                    genai.protos.Content(parts=function_responses),
                    tools=tools_param,
                )

            # Extract final text response
            final_text = ""
            if response.candidates:
                for part in response.candidates[0].content.parts:
                    if part.text:
                        final_text += part.text

            if not final_text:
                final_text = "Done." if actions_taken else "I couldn't understand that command."

            # Update conversation history
            self._add_to_history("user", command)
            self._add_to_history("assistant", final_text)

            logger.info(f"🧠 Response: {final_text[:100]}...")
            return {
                "response": final_text,
                "actions_taken": actions_taken,
                "success": True,
            }

        except Exception as e:
            logger.error(f"🧠 Brain error: {e}")
            return {
                "response": f"I encountered an error: {str(e)}",
                "actions_taken": actions_taken,
                "success": False,
            }

    def _convert_to_proto_schema(self, schema: Dict) -> Any:
        """Convert JSON Schema to Gemini proto Schema"""
        if not schema or not schema.get("properties"):
            return genai.protos.Schema(type=genai.protos.Type.OBJECT)

        properties = {}
        for prop_name, prop_def in schema.get("properties", {}).items():
            prop_type = prop_def.get("type", "string").upper()
            type_map = {
                "STRING": genai.protos.Type.STRING,
                "INTEGER": genai.protos.Type.INTEGER,
                "NUMBER": genai.protos.Type.NUMBER,
                "BOOLEAN": genai.protos.Type.BOOLEAN,
                "ARRAY": genai.protos.Type.ARRAY,
                "OBJECT": genai.protos.Type.OBJECT,
            }
            proto_type = type_map.get(prop_type, genai.protos.Type.STRING)

            prop_schema = genai.protos.Schema(
                type=proto_type,
                description=prop_def.get("description", ""),
            )

            # Handle enum values
            if "enum" in prop_def:
                prop_schema.enum[:] = prop_def["enum"]

            # Handle array items
            if prop_type == "ARRAY" and "items" in prop_def:
                items_type = prop_def["items"].get("type", "string").upper()
                item_proto_type = type_map.get(items_type, genai.protos.Type.STRING)
                prop_schema.items = genai.protos.Schema(type=item_proto_type)

            properties[prop_name] = prop_schema

        return genai.protos.Schema(
            type=genai.protos.Type.OBJECT,
            properties=properties,
            required=schema.get("required", []),
        )

    def _get_chat_history(self) -> list:
        """Get recent conversation history for context"""
        history = []
        for msg in self._conversation_history[-self._max_history:]:
            history.append(
                genai.protos.Content(
                    role=msg["role"],
                    parts=[genai.protos.Part(text=msg["content"])],
                )
            )
        return history

    def _add_to_history(self, role: str, content: str):
        """Add a message to conversation history"""
        self._conversation_history.append({"role": role, "content": content})
        # Trim old messages
        if len(self._conversation_history) > self._max_history * 2:
            self._conversation_history = self._conversation_history[-self._max_history:]

    def clear_history(self):
        """Clear conversation history"""
        self._conversation_history = []
        logger.info("🧠 Conversation history cleared")


# Global instance
brain = AgentBrain()
