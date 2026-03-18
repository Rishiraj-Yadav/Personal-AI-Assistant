"""
Built-in tools for the gateway
"""
from __future__ import annotations
import time
from typing import Any, Dict
from gateway.app.tools.registry import ToolRegistry


def register_builtin_tools(registry: ToolRegistry):
    """Register the default gateway tools."""

    def ping() -> Dict[str, Any]:
        return {"pong": True, "timestamp": time.time()}

    def get_current_datetime() -> Dict[str, Any]:
        return {"datetime": time.strftime("%Y-%m-%d %H:%M:%S")}

    registry.register("ping", "Ping the gateway", ping)
    registry.register("get_current_datetime", "Get the current date and time", get_current_datetime)
