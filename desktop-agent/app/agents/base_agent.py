"""
Base Agent — Abstract base class for all specialist agents
All 8 specialist agents inherit from this.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List
from loguru import logger


class BaseAgent(ABC):
    """
    Base class for all specialist agents.
    Each agent owns a set of skills and exposes tool definitions for the Orchestrator.
    """

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        logger.info(f"Initialized agent: {name}")

    @abstractmethod
    def get_tools(self) -> List[Dict[str, Any]]:
        """
        Return a list of tool definitions for the LLM.
        Each tool dict has: name, description, parameters (JSON Schema)
        """
        pass

    @abstractmethod
    def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a specific tool with given arguments.

        Returns:
            Dict with at minimum:
            - success: bool
            - result: Any (the output)
            - error: str | None
        """
        pass

    def _success(self, result: Any, message: str = "") -> Dict[str, Any]:
        """Helper to build a success response"""
        return {
            "success": True,
            "result": result,
            "message": message,
            "error": None,
        }

    def _error(self, error: str) -> Dict[str, Any]:
        """Helper to build an error response"""
        logger.error(f"[{self.name}] {error}")
        return {
            "success": False,
            "result": None,
            "message": "",
            "error": error,
        }
