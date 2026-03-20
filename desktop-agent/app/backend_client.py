"""
Backend WebSocket Client for Desktop Agent
==========================================

Connects to the backend via WebSocket for real-time communication.
This enables the backend to send commands directly to the desktop agent.
"""

import asyncio
import json
import websockets
from typing import Dict, Any, Optional, Callable
from loguru import logger

from config import settings
from skill_registry import registry


class BackendWSClient:
    """
    WebSocket client that connects to the backend.
    
    Enables real-time bidirectional communication:
    - Receives commands from backend
    - Sends results and context updates back
    """
    
    def __init__(
        self,
        backend_url: str = "ws://localhost:8000/ws/desktop",
        api_key: Optional[str] = None,
        on_command: Optional[Callable] = None
    ):
        """
        Initialize the WebSocket client.
        
        Args:
            backend_url: WebSocket URL of the backend
            api_key: API key for authentication
            on_command: Callback when command is received
        """
        self.backend_url = backend_url
        self.api_key = api_key or settings.API_KEY
        self.on_command = on_command
        
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._connected = False
        self._reconnect_delay = 5
        self._should_run = True
        self._agent_id: Optional[str] = None
        
    async def connect(self) -> bool:
        """
        Connect to the backend WebSocket.
        
        Returns:
            True if connected successfully
        """
        try:
            # Build URL with query params
            url = f"{self.backend_url}?agent_id=desktop_agent"
            
            logger.info(f"🔌 Connecting to backend: {url}")
            
            self._ws = await websockets.connect(
                url,
                extra_headers={"X-API-Key": self.api_key}
            )
            
            # Wait for handshake ACK
            response = await asyncio.wait_for(self._ws.recv(), timeout=10)
            data = json.loads(response)
            
            if data.get("type") == "handshake_ack":
                self._connected = True
                self._agent_id = data.get("agent_id")
                logger.info(f"✅ Connected to backend (agent_id: {self._agent_id})")
                return True
            else:
                logger.warning(f"⚠️ Unexpected handshake response: {data}")
                return False
                
        except asyncio.TimeoutError:
            logger.error("❌ Backend connection timeout")
            return False
        except Exception as e:
            logger.error(f"❌ Backend connection failed: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from the backend."""
        self._should_run = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        self._connected = False
        logger.info("🔌 Disconnected from backend")
    
    async def run(self):
        """
        Main loop - connect and handle messages.
        
        Automatically reconnects on disconnect.
        """
        while self._should_run:
            try:
                if not self._connected:
                    connected = await self.connect()
                    if not connected:
                        logger.info(f"⏳ Retrying in {self._reconnect_delay}s...")
                        await asyncio.sleep(self._reconnect_delay)
                        continue
                
                # Message loop
                await self._message_loop()
                
            except websockets.ConnectionClosed:
                logger.warning("🔌 Backend connection closed")
                self._connected = False
                await asyncio.sleep(self._reconnect_delay)
                
            except Exception as e:
                logger.error(f"❌ WebSocket error: {e}")
                self._connected = False
                await asyncio.sleep(self._reconnect_delay)
    
    async def _message_loop(self):
        """Process incoming messages from backend."""
        async for message in self._ws:
            try:
                data = json.loads(message)
                await self._handle_message(data)
            except json.JSONDecodeError:
                logger.warning(f"⚠️ Invalid JSON: {message}")
            except Exception as e:
                logger.error(f"❌ Message handling error: {e}")
    
    async def _handle_message(self, data: Dict[str, Any]):
        """Handle a message from the backend."""
        msg_type = data.get("type")
        
        if msg_type == "command":
            # Execute command
            await self._execute_command(data)
            
        elif msg_type == "ping":
            # Respond to ping
            await self.send({"type": "pong"})
            
        else:
            logger.debug(f"📩 Received: {msg_type}")
    
    async def _execute_command(self, data: Dict[str, Any]):
        """Execute a command from the backend."""
        command = data.get("command")
        parameters = data.get("parameters", {})
        request_id = data.get("request_id")
        
        logger.info(f"🔧 Executing command: {command}")
        
        try:
            # Map command to skill
            skill_name = self._map_command_to_skill(command, parameters)
            
            # Execute via registry
            result = registry.execute_tool(skill_name, parameters)
            
            # Send result back
            await self.send({
                "type": "result",
                "request_id": request_id,
                "command": command,
                "success": result.get("success", False),
                "result": result.get("result"),
                "error": result.get("error")
            })
            
        except Exception as e:
            logger.error(f"❌ Command execution error: {e}")
            await self.send({
                "type": "result",
                "request_id": request_id,
                "command": command,
                "success": False,
                "error": str(e)
            })
    
    def _map_command_to_skill(self, command: str, parameters: Dict[str, Any]) -> str:
        """Map backend command names to desktop agent skill names."""
        # Direct mapping
        skill_map = {
            "fs.open": "open_path",
            "app.launch": "launch_app",
            "web.open": "open_url",
            "screen.capture": "take_screenshot",
            "window.control": "manage_window",
            "mouse.click": "mouse_click",
            "keyboard.type": "type_text",
            "keyboard.press": "press_key",
            # Legacy names
            "open_path": "open_path",
            "launch_app": "launch_app",
            "open_url": "open_url",
            "take_screenshot": "take_screenshot",
        }
        
        return skill_map.get(command, command)
    
    async def send(self, data: Dict[str, Any]):
        """Send a message to the backend."""
        if not self._connected or not self._ws:
            logger.warning("⚠️ Cannot send - not connected")
            return
        
        try:
            await self._ws.send(json.dumps(data))
        except Exception as e:
            logger.error(f"❌ Send error: {e}")
            self._connected = False
    
    async def send_context_update(self, context: Dict[str, Any]):
        """Send context update to backend."""
        await self.send({
            "type": "context_update",
            "context": context
        })
    
    @property
    def is_connected(self) -> bool:
        """Check if connected to backend."""
        return self._connected


# Global instance
_ws_client: Optional[BackendWSClient] = None


def get_ws_client(backend_url: str = "ws://localhost:8000/ws/desktop") -> BackendWSClient:
    """Get or create the WebSocket client."""
    global _ws_client
    if _ws_client is None:
        _ws_client = BackendWSClient(backend_url=backend_url)
    return _ws_client


async def start_ws_client(backend_url: str = "ws://localhost:8000/ws/desktop"):
    """Start the WebSocket client in background."""
    client = get_ws_client(backend_url)
    asyncio.create_task(client.run())
    return client
