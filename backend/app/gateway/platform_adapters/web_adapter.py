"""
Web Platform Adapter - Phase 4

Handles communication between Gateway and Web Frontend (React).
"""

import asyncio
from typing import Any, Dict, Optional
from loguru import logger
from fastapi import WebSocket

from app.gateway.message_protocol import UnifiedMessage, Platform, MessageType


class WebAdapter:
    """
    Adapter for web platform (React frontend).

    Manages:
    - WebSocket connections
    - Message format conversion
    - Session tracking
    """

    def __init__(self):
        # Active WebSocket connections: {session_id: WebSocket}
        self._connections: Dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

        logger.info("WebAdapter initialized")

    async def register_connection(self, session_id: str, websocket: WebSocket):
        """Register a WebSocket connection for a session."""
        async with self._lock:
            self._connections[session_id] = websocket
        logger.info(f"Registered WebSocket for session {session_id}")

    async def unregister_connection(self, session_id: str):
        """Unregister a WebSocket connection."""
        async with self._lock:
            if session_id in self._connections:
                del self._connections[session_id]
        logger.info(f"Unregistered WebSocket for session {session_id}")

    async def handle_message(self, message: UnifiedMessage) -> Optional[UnifiedMessage]:
        """
        Handle incoming message from gateway.

        Converts UnifiedMessage to frontend-friendly format and sends via WebSocket.
        """
        # Convert to frontend format
        frontend_msg = self._to_frontend_format(message)

        # Send to session if connection exists
        session_id = message.session_id
        websocket = self._connections.get(session_id)

        if not websocket:
            logger.warning(f"No WebSocket connection for session {session_id}")
            return None

        try:
            await websocket.send_json(frontend_msg)
            return None  # Async, no response needed
        except Exception as e:
            logger.error(f"Error sending to WebSocket {session_id}: {e}")
            # Clean up dead connection
            await self.unregister_connection(session_id)
            return None

    async def send_to_session(self, session_id: str, message: UnifiedMessage):
        """Send a message to a specific session."""
        await self.handle_message(message)

    def _to_frontend_format(self, message: UnifiedMessage) -> Dict[str, Any]:
        """
        Convert UnifiedMessage to frontend-friendly format.

        Frontend expects:
        {
          "type": "...",
          "session_id": "...",
          "request_id": "...",
          "timestamp": "...",
          ...payload fields (flattened)
        }
        """
        # Start with message dict
        result = {
            "type": message.type.value,
            "session_id": message.session_id,
            "timestamp": message.timestamp,
        }

        # Add optional fields
        if message.request_id:
            result["request_id"] = message.request_id
        if message.conversation_id:
            result["conversation_id"] = message.conversation_id
        if message.user_id:
            result["user_id"] = message.user_id

        # Flatten payload into root level for frontend convenience
        if message.payload:
            for key, value in message.payload.items():
                # Avoid overwriting root fields
                if key not in result:
                    result[key] = value

        # Add metadata if present
        if message.metadata:
            result["metadata"] = message.metadata

        return result

    def _from_frontend_format(self, data: Dict[str, Any]) -> UnifiedMessage:
        """
        Convert frontend message to UnifiedMessage.

        Frontend sends:
        {
          "type": "user_message",
          "session_id": "...",
          "message": "...",
          ...other fields
        }
        """
        # Extract known root fields
        msg_type = MessageType(data.get("type", "user_message"))
        session_id = data.get("session_id", "")
        request_id = data.get("request_id")
        conversation_id = data.get("conversation_id")
        user_id = data.get("user_id")

        # All other fields go into payload
        payload = {}
        skip_fields = {"type", "session_id", "request_id", "conversation_id", "user_id", "timestamp", "metadata"}

        for key, value in data.items():
            if key not in skip_fields:
                payload[key] = value

        return UnifiedMessage(
            type=msg_type,
            session_id=session_id,
            request_id=request_id,
            conversation_id=conversation_id,
            user_id=user_id,
            payload=payload,
            metadata=data.get("metadata", {})
        )

    async def receive_from_frontend(
        self,
        session_id: str,
        data: Dict[str, Any]
    ) -> UnifiedMessage:
        """
        Receive a message from frontend and convert to UnifiedMessage.
        """
        # Ensure session_id is set
        if "session_id" not in data:
            data["session_id"] = session_id

        return self._from_frontend_format(data)

    def get_active_sessions(self) -> list:
        """Get list of active session IDs."""
        return list(self._connections.keys())


# Global instance
web_adapter = WebAdapter()
