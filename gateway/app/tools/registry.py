"""
Tool Registry — stores registered tools for the gateway
"""
from __future__ import annotations
import time
from typing import Any, Callable, Dict, List, Optional


ToolFn = Callable[..., Any]


class ToolSpec:
    def __init__(self, name: str, description: str, fn: ToolFn, parameters: Optional[Dict] = None):
        self.name = name
        self.description = description
        self.fn = fn
        self.parameters = parameters or {}


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, name: str, description: str, fn: ToolFn, parameters: Optional[Dict] = None):
        self._tools[name] = ToolSpec(name, description, fn, parameters)

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in self._tools.values()
        ]

    def execute(self, name: str, args: Dict[str, Any] = {}) -> Any:
        spec = self._tools.get(name)
        if not spec:
            raise ValueError(f"Tool not found: {name}")
        return spec.fn(**args)
