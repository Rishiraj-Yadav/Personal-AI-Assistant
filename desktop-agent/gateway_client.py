"""
Desktop Agent WebSocket Client - Phase 4

Persistent WebSocket connection to backend gateway.

Features:
- Bidirectional real-time communication
- Automatic reconnection
- Context updates (active app, file, screen)
- Command execution with feedback
"""

import asyncio
import json
import pyautogui
import platform
from typing import Any, Dict, Optional, Callable
from datetime import datetime
import websockets
from loguru import logger

# Import existing desktop agent functionality
try:
    from desktop_agent import DesktopAutomation
except:
    # Fallback if running standalone
    class DesktopAutomation:
        def __init__(self):
            pass

        def execute_command(self, command: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
            return {"success": False, "error": "DesktopAutomation not available"}


class DesktopAgentClient:
    """
    Desktop Agent WebSocket Client.

    Connects to backend gateway and:
    - Receives commands
    - Executes actions
    - Sends results
    - Streams context updates
    """

    def __init__(
        self,
        backend_url: str = "ws://localhost:8000/ws/desktop",
        agent_id: Optional[str] = None,
        auto_reconnect: bool = True
    ):
        self.backend_url = backend_url
        self.agent_id = agent_id or self._generate_agent_id()
        self.auto_reconnect = auto_reconnect

        # WebSocket connection
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.connected = False

        # Desktop automation engine
        self.automation = DesktopAutomation()

        # Context tracking
        self.last_context = {}
        self.context_update_interval = 5  # seconds

        # Callbacks
        self.on_command: Optional[Callable] = None
        self.on_connected: Optional[Callable] = None
        self.on_disconnected: Optional[Callable] = None

        logger.info(f"DesktopAgentClient initialized: {self.agent_id}")

    def _generate_agent_id(self) -> str:
        """Generate unique agent ID."""
        import uuid
        hostname = platform.node()
        return f"desktop_{hostname}_{uuid.uuid4().hex[:8]}"

    async def connect(self):
        """Connect to backend gateway."""
        try:
            logger.info(f"Connecting to {self.backend_url}...")

            self.websocket = await websockets.connect(
                self.backend_url,
                extra_headers={"X-Agent-ID": self.agent_id}
            )

            self.connected = True
            logger.info("Connected to backend gateway")

            # Send initial handshake
            await self._send_handshake()

            # Notify callback
            if self.on_connected:
                await self._safe_callback(self.on_connected)

            # Start message loop
            await self._message_loop()

        except Exception as e:
            logger.error(f"Connection error: {e}")
            self.connected = False

            if self.auto_reconnect:
                await asyncio.sleep(5)
                await self.connect()

    async def disconnect(self):
        """Disconnect from backend."""
        self.connected = False

        if self.websocket:
            await self.websocket.close()
            self.websocket = None

        logger.info("Disconnected from backend")

        if self.on_disconnected:
            await self._safe_callback(self.on_disconnected)

    async def _send_handshake(self):
        """Send initial handshake message."""
        handshake = {
            "type": "handshake",
            "agent_id": self.agent_id,
            "platform": platform.system(),
            "hostname": platform.node(),
            "capabilities": [
                "click",
                "type",
                "screenshot",
                "open_app",
                "get_context"
            ]
        }

        await self._send_message(handshake)

    async def _message_loop(self):
        """Main message receiving loop."""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON received: {message}")
                except Exception as e:
                    logger.error(f"Message handling error: {e}")

        except websockets.exceptions.ConnectionClosed:
            logger.warning("Connection closed by server")
            self.connected = False

            if self.auto_reconnect:
                await asyncio.sleep(5)
                await self.connect()

    async def _handle_message(self, data: Dict[str, Any]):
        """Handle incoming message from backend."""
        msg_type = data.get("type")

        if msg_type == "command":
            await self._handle_command(data)
        elif msg_type == "ping":
            await self._handle_ping(data)
        elif msg_type == "context_request":
            await self._send_context()
        else:
            logger.debug(f"Unknown message type: {msg_type}")

    async def _handle_command(self, data: Dict[str, Any]):
        """Handle command execution request."""
        command = data.get("command")
        parameters = data.get("parameters", {})
        request_id = data.get("request_id")

        logger.info(f"Executing command: {command}")

        # Notify callback
        if self.on_command:
            await self._safe_callback(self.on_command, command, parameters)

        try:
            # Execute command
            result = await self._execute_command(command, parameters)

            # Send result back
            await self._send_result(request_id, command, result)

        except Exception as e:
            logger.error(f"Command execution error: {e}")

            await self._send_result(
                request_id,
                command,
                {"success": False, "error": str(e)}
            )

    async def _execute_command(
        self,
        command: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a desktop command."""
        # Map command to automation method
        if command == "click":
            x = parameters.get("x")
            y = parameters.get("y")
            if x is not None and y is not None:
                pyautogui.click(x, y)
                return {"success": True, "result": {"clicked": f"({x}, {y})"}}

        elif command == "type":
            text = parameters.get("text")
            if text:
                pyautogui.write(text)
                return {"success": True, "result": {"typed": len(text)}}

        elif command == "screenshot":
            screenshot = pyautogui.screenshot()
            # Save to temp file
            import tempfile
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            screenshot.save(temp_file.name)
            return {"success": True, "result": {"path": temp_file.name}}

        elif command == "get_active_window":
            import pygetwindow as gw
            active = gw.getActiveWindow()
            if active:
                return {
                    "success": True,
                    "result": {
                        "title": active.title,
                        "size": (active.width, active.height),
                        "position": (active.left, active.top)
                    }
                }

        elif command == "open_app":
            app_name = parameters.get("app_name")
            if app_name:
                import subprocess
                if platform.system() == "Windows":
                    subprocess.Popen(["start", app_name], shell=True)
                elif platform.system() == "Darwin":  # macOS
                    subprocess.Popen(["open", "-a", app_name])
                else:  # Linux
                    subprocess.Popen([app_name])

                return {"success": True, "result": {"opened": app_name}}

        # Fallback to automation engine
        return self.automation.execute_command(command, parameters)

    async def _handle_ping(self, data: Dict[str, Any]):
        """Handle ping message."""
        await self._send_message({"type": "pong"})

    async def _send_result(
        self,
        request_id: Optional[str],
        command: str,
        result: Dict[str, Any]
    ):
        """Send command result back to backend."""
        message = {
            "type": "result",
            "request_id": request_id,
            "command": command,
            "success": result.get("success", False),
            "result": result.get("result"),
            "error": result.get("error"),
            "timestamp": datetime.utcnow().isoformat()
        }

        await self._send_message(message)

    async def _send_context(self):
        """Send current desktop context to backend."""
        context = await self._get_current_context()

        message = {
            "type": "context_update",
            "context": context,
            "timestamp": datetime.utcnow().isoformat()
        }

        await self._send_message(message)

    async def _get_current_context(self) -> Dict[str, Any]:
        """Get current desktop context."""
        context = {}

        try:
            # Active window
            import pygetwindow as gw
            active = gw.getActiveWindow()
            if active:
                context["active_window"] = {
                    "title": active.title,
                    "app": self._extract_app_name(active.title)
                }

            # Screen resolution
            context["screen_resolution"] = pyautogui.size()

            # Mouse position
            context["mouse_position"] = pyautogui.position()

            # Platform info
            context["platform"] = platform.system()

        except Exception as e:
            logger.warning(f"Error getting context: {e}")

        return context

    def _extract_app_name(self, window_title: str) -> str:
        """Extract application name from window title."""
        # Simple heuristic: last part often contains app name
        parts = window_title.split(" - ")
        if parts:
            return parts[-1].strip()
        return window_title

    async def _send_message(self, data: Dict[str, Any]):
        """Send message to backend."""
        if not self.connected or not self.websocket:
            logger.warning("Cannot send message: not connected")
            return

        try:
            await self.websocket.send(json.dumps(data))
        except Exception as e:
            logger.error(f"Error sending message: {e}")

    async def _safe_callback(self, callback: Callable, *args, **kwargs):
        """Safely invoke callback."""
        try:
            result = callback(*args, **kwargs)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.warning(f"Callback error: {e}")

    async def start_context_updates(self):
        """Start periodic context updates."""
        while self.connected:
            await asyncio.sleep(self.context_update_interval)

            try:
                await self._send_context()
            except Exception as e:
                logger.warning(f"Context update error: {e}")


async def main():
    """Main entry point for desktop agent."""
    # Create client
    client = DesktopAgentClient(
        backend_url="ws://localhost:8000/ws/desktop",
        auto_reconnect=True
    )

    # Set up callbacks
    async def on_connected():
        logger.info("✓ Connected to backend")
        # Start context updates
        asyncio.create_task(client.start_context_updates())

    async def on_disconnected():
        logger.warning("✗ Disconnected from backend")

    async def on_command(command: str, parameters: Dict[str, Any]):
        logger.info(f"→ Executing: {command}")

    client.on_connected = on_connected
    client.on_disconnected = on_disconnected
    client.on_command = on_command

    # Connect and run
    try:
        await client.connect()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await client.disconnect()


if __name__ == "__main__":
    import sys

    # Configure logging
    logger.remove()
    logger.add(sys.stdout, level="INFO")

    # Run client
    asyncio.run(main())
