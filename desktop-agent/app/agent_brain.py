"""
Agent Brain — Orchestrator Agent (OpenClaw Architecture)
The brain of the desktop agent. Takes natural language commands,
routes them via RouterAgent, and manages memory via ContextEngine.
"""
import json
import google.generativeai as genai
from typing import Dict, Any, List, Optional
from loguru import logger
from config import settings
from skill_registry import registry
from context_engine import ContextEngine
from router import RouterAgent

class AgentBrain:
    def __init__(self):
        """Initialize the Orchestrator"""
        if not settings.GOOGLE_API_KEY:
            logger.error("GOOGLE_API_KEY not set! Agent brain will not work.")
            self.model = None
            return

        genai.configure(api_key=settings.GOOGLE_API_KEY)
        # The main reasoning model for the specialized agents
        self.model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=(
                "You are an active sub-agent executing a delegated task. "
                "Use your provided tools to solve the user's request. "
                "If you need to click something, use the screen visual tool to get coordinates first."
            )
        )
        
        # OpenClaw Architecture Components
        self.context = ContextEngine(max_history=20)
        self.router = RouterAgent()
        
        logger.info("🧠 Agent Brain initialized with modular OpenClaw architecture")

    async def process_command(self, command: str) -> Dict[str, Any]:
        if not self.model:
            return {"response": "API Key not set.", "actions_taken": [], "success": False}

        actions_taken = []
        logger.info(f"🧠 Processing command: {command}")

        # 1. Routing phase
        target_agent_name = await self.router.route_command(command, context=str(self.context.get_raw_history()))
        logger.info(f"🚀 Routing handoff to: {target_agent_name}_agent")

        # 2. Get the specific agent and its tools
        target_agent = None
        for name, agent in registry._agents.items():
            if name == target_agent_name or name == f"{target_agent_name}_agent":
                target_agent = agent
                break
                
        # Fallback to all tools if router failed or returned 'system' and system agent isn't found
        gemini_tools = []
        if target_agent:
            tools = target_agent.get_tools()
            for t in tools:
                gemini_tools.append(self._format_tool(t))
            logger.info(f"Loaded {len(tools)} tools exclusively for {target_agent.name}")
        else:
            logger.warning(f"Could not isolate {target_agent_name}, loading fallback global tools")
            for t in registry.get_all_tools():
                gemini_tools.append(self._format_tool(t["function"]))

        # Build tool config
        tools_param = None
        if gemini_tools:
            tools_param = [genai.protos.Tool(function_declarations=gemini_tools)]

        # 3. Execution Phase
        chat = self.model.start_chat(history=self.context.get_gemini_history())

        try:
            response = chat.send_message(command, tools=tools_param)

            max_iterations = 8
            for iteration in range(max_iterations):
                if not response.candidates:
                    break
                    
                candidate = response.candidates[0]
                function_calls = [p for p in candidate.content.parts if p.function_call.name]

                if not function_calls:
                    break

                function_responses = []
                for part in function_calls:
                    fn_call = part.function_call
                    tool_name = fn_call.name
                    tool_args = dict(fn_call.args) if fn_call.args else {}

                    logger.info(f"🔧 Tool call: {tool_name}({tool_args})")

                    # Execute
                    result = registry.execute_tool(tool_name, tool_args)
                    actions_taken.append({
                        "tool": tool_name,
                        "success": result.get("success", False),
                    })

                    function_responses.append(
                        genai.protos.Part(
                            function_response=genai.protos.FunctionResponse(
                                name=tool_name,
                                response={"result": json.dumps(result, default=str)},
                            )
                        )
                    )

                response = chat.send_message(
                    genai.protos.Content(parts=function_responses),
                    tools=tools_param,
                )

            # Final response
            final_text = ""
            if response.candidates:
                final_text = "".join([p.text for p in response.candidates[0].content.parts if p.text])
            if not final_text:
                final_text = "Task completed."

            # Update context engine
            self.context.add_message("user", command)
            self.context.add_message("model", final_text)

            return {"response": final_text, "actions_taken": actions_taken, "success": True}

        except Exception as e:
            logger.error(f"Brain error: {e}")
            return {"response": f"Error: {str(e)}", "actions_taken": actions_taken, "success": False}

    def _format_tool(self, func_def: Dict) -> genai.protos.FunctionDeclaration:
        return genai.protos.FunctionDeclaration(
            name=func_def["name"],
            description=func_def["description"],
            parameters=self._convert_to_proto_schema(func_def.get("parameters", {}))
        )

    def _convert_to_proto_schema(self, schema: Dict) -> Any:
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

            if "enum" in prop_def:
                prop_schema.enum[:] = prop_def["enum"]

            if prop_type == "ARRAY" and "items" in prop_def:
                items_type = prop_def["items"].get("type", "string").upper()
                prop_schema.items = genai.protos.Schema(type=type_map.get(items_type, genai.protos.Type.STRING))

            properties[prop_name] = prop_schema

        return genai.protos.Schema(
            type=genai.protos.Type.OBJECT,
            properties=properties,
            required=schema.get("required", []),
        )

    def clear_history(self):
        self.context.clear()

# Global instance
brain = AgentBrain()
