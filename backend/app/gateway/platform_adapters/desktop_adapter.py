"""
Desktop Platform Adapter - Phase 4

Handles communication between Gateway and Desktop Agent.

Supports:
- Bidirectional WebSocket connection to desktop agent
- HTTP fallback for simple commands
- Real-time context updates from desktop
- Command execution with feedback
"""

import asyncio
import aiohttp
from typing import Any, Dict, Optional
from loguru import logger
from fastapi import WebSocket

from app.gateway.message_protocol import (
    UnifiedMessage,
    Platform,
    MessageType,
    create_desktop_result,
    create_error_message
)
from app.config import settings


class DesktopAdapter:
    """
    Adapter for desktop agent platform.

    Manages:
    - WebSocket connection to desktop agent (if available)
    - HTTP fallback for commands
    - Context synchronization
    - Command result handling
    """

    def __init__(self):
        # Desktop agent WebSocket connection
        self._desktop_websocket: Optional[WebSocket] = None
        self._desktop_connected = False

        # HTTP client for fallback
        self._http_session: Optional[aiohttp.ClientSession] = None

        # Pending requests: {request_id: asyncio.Future}
        self._pending_requests: Dict[str, asyncio.Future] = {}

        # Lock for connection management
        self._lock = asyncio.Lock()

        # Desktop agent URL (default matches desktop-agent config)
        self._desktop_url = getattr(settings, 'DESKTOP_AGENT_URL', 'http://localhost:7777')

        logger.info("DesktopAdapter initialized")

    async def initialize(self):
        """Initialize HTTP session."""
        if not self._http_session:
            self._http_session = aiohttp.ClientSession()

    async def shutdown(self):
        """Shutdown adapter and cleanup resources."""
        if self._http_session:
            await self._http_session.close()
        if self._desktop_websocket:
            await self._desktop_websocket.close()

    async def register_desktop_connection(self, websocket: WebSocket):
        """Register desktop agent WebSocket connection."""
        async with self._lock:
            self._desktop_websocket = websocket
            self._desktop_connected = True
        logger.info("Desktop agent WebSocket connected")

    async def unregister_desktop_connection(self):
        """Unregister desktop agent connection."""
        async with self._lock:
            self._desktop_websocket = None
            self._desktop_connected = False
        logger.info("Desktop agent WebSocket disconnected")

    async def handle_message(self, message: UnifiedMessage) -> Optional[UnifiedMessage]:
        """
        Handle incoming message from gateway.

        Routes desktop commands to agent and returns results.
        """
        if message.type == MessageType.DESKTOP_COMMAND:
            return await self._execute_desktop_command(message)

        # Other message types are informational only
        return None

    async def _execute_desktop_command(
        self,
        message: UnifiedMessage
    ) -> UnifiedMessage:
        """Execute a desktop command and return result."""
        payload = message.payload
        command = payload.get("command")
        parameters = payload.get("parameters", {})
        timeout = payload.get("timeout", 30)

        logger.info(f"Executing desktop command: {command}")

        try:
            # Try WebSocket first if connected
            if self._desktop_connected and self._desktop_websocket:
                result = await self._execute_via_websocket(
                    command, parameters, timeout, message.request_id
                )
            else:
                # Fallback to HTTP
                result = await self._execute_via_http(
                    command, parameters, timeout
                )

            # Create result message
            return create_desktop_result(
                session_id=message.session_id,
                command=command,
                success=result.get("success", False),
                request_id=message.request_id,
                result=result.get("result"),
                error=result.get("error")
            )

        except Exception as e:
            logger.error(f"Desktop command error: {e}")
            return create_desktop_result(
                session_id=message.session_id,
                command=command,
                success=False,
                request_id=message.request_id,
                error=str(e)
            )

    async def _execute_via_websocket(
        self,
        command: str,
        parameters: Dict[str, Any],
        timeout: int,
        request_id: Optional[str]
    ) -> Dict[str, Any]:
        """Execute command via WebSocket."""
        if not self._desktop_websocket:
            raise RuntimeError("Desktop WebSocket not connected")

        # Create command message (desktop agent maps command to skill in backend_client.py)
        cmd_msg = {
            "type": "command",
            "command": command,
            "parameters": parameters,
            "request_id": request_id
        }

        # Send command
        await self._desktop_websocket.send_json(cmd_msg)

        # Wait for response with timeout
        future = asyncio.Future()
        if request_id:
            self._pending_requests[request_id] = future

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            if request_id:
                self._pending_requests.pop(request_id, None)
            raise RuntimeError(f"Desktop command timeout after {timeout}s")

    async def _execute_via_http(
        self,
        command: str,
        parameters: Dict[str, Any],
        timeout: int
    ) -> Dict[str, Any]:
        """Execute command via HTTP (fallback)."""
        if not self._http_session:
            await self.initialize()

        url = f"{self._desktop_url}/execute"
        
        # Map command to skill name (Phase 6 format)
        skill_map = {
            "fs.open": "open_path",
            "app.launch": "launch_app",
            "web.open": "open_url",
            "screen.capture": "take_screenshot",
            "window.control": "manage_window",
            "mouse.click": "mouse_click",
            "keyboard.type": "type_text",
            "keyboard.press": "press_key",
        }
        skill = skill_map.get(command, command)
        
        # Desktop agent expects {"skill": ..., "args": ...}
        payload = {
            "skill": skill,
            "args": parameters
        }

        # Get API key
        api_key = self._get_desktop_api_key()
        headers = {"X-API-Key": api_key}

        try:
            async with self._http_session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return result
                else:
                    error_text = await response.text()
                    return {
                        "success": False,
                        "error": f"HTTP {response.status}: {error_text}"
                    }
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": f"Request timeout after {timeout}s"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def _get_desktop_api_key(self) -> str:
        """Get desktop agent API key from config file."""
        import os
        key_file = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "..", "..", "desktop-agent", "config", "api_key.txt"
        )
        
        if os.path.exists(key_file):
            with open(key_file, "r") as f:
                return f.read().strip()
        
        return "default-key"

    async def handle_desktop_response(self, data: Dict[str, Any]):
        """
        Handle response from desktop agent.

        Called when desktop agent sends a result via WebSocket.
        """
        request_id = data.get("request_id")

        if request_id and request_id in self._pending_requests:
            future = self._pending_requests.pop(request_id)
            if not future.done():
                future.set_result(data)

    async def send_to_session(self, session_id: str, message: UnifiedMessage):
        """Send message to desktop agent (if it's for desktop)."""
        await self.handle_message(message)

    def is_connected(self) -> bool:
        """Check if desktop agent is connected."""
        return self._desktop_connected


# Global instance
desktop_adapter = DesktopAdapter()
