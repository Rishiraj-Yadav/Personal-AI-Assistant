"""
Gateway Router - Phase 4

Central communication hub that routes messages between:
- Frontend (Web)
- Backend Runtime
- Desktop Agent
- Future platforms (CLI, Mobile)
"""

import asyncio
from typing import Any, Callable, Dict, List, Optional, Set
from loguru import logger
from datetime import datetime, timezone

from .message_protocol import (
    UnifiedMessage,
    MessageType,
    Platform,
    create_error_message
)


# Callback type for message handlers
MessageHandler = Callable[[UnifiedMessage], Any]


class GatewayRouter:
    """
    Central message router for the assistant ecosystem.

    Responsibilities:
    - Route messages to appropriate platform adapters
    - Normalize message formats
    - Broadcast events to subscribers
    - Track active connections
    """

    def __init__(self):
        # Platform adapters (registered dynamically)
        self._adapters: Dict[Platform, Any] = {}

        # Event subscribers: {event_type: [handlers]}
        self._subscribers: Dict[MessageType, List[MessageHandler]] = {}

        # Active sessions: {session_id: {platform, connection_info}}
        self._active_sessions: Dict[str, Dict[str, Any]] = {}

        # Session locks
        self._session_locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

        logger.info("GatewayRouter initialized")

    async def register_adapter(self, platform: Platform, adapter: Any):
        """Register a platform adapter."""
        self._adapters[platform] = adapter
        logger.info(f"Registered {platform.value} adapter")

    async def unregister_adapter(self, platform: Platform):
        """Unregister a platform adapter."""
        if platform in self._adapters:
            del self._adapters[platform]
            logger.info(f"Unregistered {platform.value} adapter")

    def subscribe(self, message_type: MessageType, handler: MessageHandler):
        """Subscribe to a message type."""
        if message_type not in self._subscribers:
            self._subscribers[message_type] = []
        self._subscribers[message_type].append(handler)
        logger.debug(f"Subscribed handler to {message_type.value}")

    def unsubscribe(self, message_type: MessageType, handler: MessageHandler):
        """Unsubscribe from a message type."""
        if message_type in self._subscribers:
            try:
                self._subscribers[message_type].remove(handler)
            except ValueError:
                pass

    async def route_message(
        self,
        message: UnifiedMessage,
        target_platform: Optional[Platform] = None
    ) -> Optional[UnifiedMessage]:
        """
        Route a message to the appropriate destination.

        Args:
            message: The message to route
            target_platform: Optional specific platform to target

        Returns:
            Response message if synchronous, None if async
        """
        # Broadcast to subscribers first
        await self._broadcast_to_subscribers(message)

        # Route to specific platform or all
        if target_platform:
            return await self._route_to_platform(message, target_platform)
        else:
            # Broadcast to all relevant platforms
            await self._broadcast_to_platforms(message)
            return None

    async def _route_to_platform(
        self,
        message: UnifiedMessage,
        platform: Platform
    ) -> Optional[UnifiedMessage]:
        """Route message to a specific platform."""
        adapter = self._adapters.get(platform)

        if not adapter:
            logger.warning(f"No adapter found for platform: {platform.value}")
            return create_error_message(
                session_id=message.session_id,
                error_type="routing_error",
                message=f"Platform {platform.value} not available",
                request_id=message.request_id
            )

        try:
            # Call adapter's handle_message method
            result = await adapter.handle_message(message)
            return result
        except Exception as e:
            logger.error(f"Error routing to {platform.value}: {e}")
            return create_error_message(
                session_id=message.session_id,
                error_type="platform_error",
                message=str(e),
                request_id=message.request_id
            )

    async def _broadcast_to_platforms(self, message: UnifiedMessage):
        """Broadcast message to all relevant platforms."""
        # Determine which platforms should receive this message
        target_platforms = self._get_target_platforms(message)

        # Send to all targets concurrently
        tasks = [
            self._route_to_platform(message, platform)
            for platform in target_platforms
        ]

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _get_target_platforms(self, message: UnifiedMessage) -> List[Platform]:
        """Determine which platforms should receive a message."""
        # Frontend should receive most messages for display
        targets = [Platform.WEB]

        # Desktop agent should receive desktop commands
        if message.type == MessageType.DESKTOP_COMMAND:
            targets.append(Platform.DESKTOP)

        # Desktop context updates should go to frontend
        if message.type == MessageType.DESKTOP_CONTEXT:
            if Platform.WEB not in targets:
                targets.append(Platform.WEB)

        return [p for p in targets if p in self._adapters]

    async def _broadcast_to_subscribers(self, message: UnifiedMessage):
        """Broadcast message to event subscribers."""
        handlers = self._subscribers.get(message.type, [])

        if not handlers:
            return

        # Call all handlers (don't wait for them)
        tasks = []
        for handler in handlers:
            try:
                result = handler(message)
                if asyncio.iscoroutine(result):
                    tasks.append(result)
            except Exception as e:
                logger.warning(f"Subscriber handler error: {e}")

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def register_session(
        self,
        session_id: str,
        platform: Platform,
        connection_info: Dict[str, Any]
    ):
        """Register an active session."""
        async with self._global_lock:
            self._active_sessions[session_id] = {
                "platform": platform,
                "connection_info": connection_info,
                "created_at": datetime.now(timezone.utc),
                "last_activity": datetime.now(timezone.utc)
            }
            self._session_locks[session_id] = asyncio.Lock()

        logger.info(f"Registered session {session_id} on {platform.value}")

    async def unregister_session(self, session_id: str):
        """Unregister a session."""
        async with self._global_lock:
            if session_id in self._active_sessions:
                del self._active_sessions[session_id]
            if session_id in self._session_locks:
                del self._session_locks[session_id]

        logger.info(f"Unregistered session {session_id}")

    async def update_session_activity(self, session_id: str):
        """Update last activity time for a session."""
        if session_id in self._active_sessions:
            self._active_sessions[session_id]["last_activity"] = datetime.now(timezone.utc)

    def get_active_sessions(self, platform: Optional[Platform] = None) -> List[str]:
        """Get list of active session IDs."""
        if platform:
            return [
                sid for sid, info in self._active_sessions.items()
                if info["platform"] == platform
            ]
        return list(self._active_sessions.keys())

    async def send_to_session(
        self,
        session_id: str,
        message: UnifiedMessage
    ) -> bool:
        """Send a message to a specific session."""
        session_info = self._active_sessions.get(session_id)

        if not session_info:
            logger.warning(f"Session {session_id} not found")
            return False

        platform = session_info["platform"]
        adapter = self._adapters.get(platform)

        if not adapter:
            logger.warning(f"No adapter for session's platform: {platform.value}")
            return False

        try:
            await adapter.send_to_session(session_id, message)
            await self.update_session_activity(session_id)
            return True
        except Exception as e:
            logger.error(f"Error sending to session {session_id}: {e}")
            return False

    async def broadcast_to_all_sessions(
        self,
        message: UnifiedMessage,
        platform: Optional[Platform] = None
    ):
        """Broadcast a message to all active sessions."""
        sessions = self.get_active_sessions(platform)

        tasks = [
            self.send_to_session(sid, message)
            for sid in sessions
        ]

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def get_stats(self) -> Dict[str, Any]:
        """Get gateway statistics."""
        platform_counts = {}
        for session_info in self._active_sessions.values():
            platform = session_info["platform"].value
            platform_counts[platform] = platform_counts.get(platform, 0) + 1

        return {
            "active_sessions": len(self._active_sessions),
            "registered_adapters": len(self._adapters),
            "event_subscribers": sum(len(h) for h in self._subscribers.values()),
            "sessions_by_platform": platform_counts
        }


# Global instance
gateway_router = GatewayRouter()
