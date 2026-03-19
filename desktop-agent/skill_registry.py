"""
Skill Registry — Auto-discovers all specialist agents and builds tool catalog
The Orchestrator uses this to know what tools are available.
"""
from typing import Dict, Any, List, Optional
from loguru import logger
from agents.base_agent import BaseAgent


class SkillRegistry:
    """
    Central registry that collects tools from all specialist agents.
    Maps tool names → agent instances for dispatch.
    """

    def __init__(self):
        self._agents: Dict[str, BaseAgent] = {}
        self._tool_map: Dict[str, str] = {}  # tool_name → agent_name
        self._tools_cache: List[Dict[str, Any]] = []
        logger.info("SkillRegistry initialized")

    def register_agent(self, agent: BaseAgent):
        """Register a specialist agent and index its tools"""
        self._agents[agent.name] = agent
        for tool in agent.get_tools():
            tool_name = tool["name"]
            self._tool_map[tool_name] = agent.name
            logger.debug(f"Registered tool: {tool_name} → {agent.name}")

        # Invalidate cache
        self._tools_cache = []
        logger.info(
            f"Registered agent '{agent.name}' with "
            f"{len(agent.get_tools())} tools"
        )

    def get_all_tools(self) -> List[Dict[str, Any]]:
        """Get all tool definitions for the LLM (cached)"""
        if not self._tools_cache:
            for agent in self._agents.values():
                for tool in agent.get_tools():
                    self._tools_cache.append({
                        "type": "function",
                        "function": tool,
                    })
        return self._tools_cache

    def get_agent_for_tool(self, tool_name: str) -> Optional[BaseAgent]:
        """Get the agent that owns a specific tool"""
        agent_name = self._tool_map.get(tool_name)
        if agent_name:
            return self._agents.get(agent_name)
        return None

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool by name — dispatches to the owning agent"""
        agent = self.get_agent_for_tool(tool_name)
        if not agent:
            return {
                "success": False,
                "result": None,
                "error": f"Unknown tool: {tool_name}. Available: {list(self._tool_map.keys())}",
            }

        try:
            logger.info(f"Executing {tool_name} via {agent.name}")
            result = agent.execute(tool_name, args)
            return result
        except Exception as e:
            logger.error(f"Tool execution error [{tool_name}]: {e}")
            return {
                "success": False,
                "result": None,
                "error": f"Execution failed: {str(e)}",
            }

    def list_agents(self) -> List[Dict[str, Any]]:
        """List all registered agents and their tools"""
        result = []
        for name, agent in self._agents.items():
            result.append({
                "name": name,
                "description": agent.description,
                "tools": [t["name"] for t in agent.get_tools()],
            })
        return result

    @property
    def tool_count(self) -> int:
        return len(self._tool_map)

    @property
    def agent_count(self) -> int:
        return len(self._agents)


# Global instance
registry = SkillRegistry()
