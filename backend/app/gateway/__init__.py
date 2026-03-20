"""
Gateway Module - Phase 4

Central communication hub for the assistant ecosystem.
"""

from .message_protocol import (
    UnifiedMessage,
    MessageType,
    Platform,
    UserMessagePayload,
    ThinkingPayload,
    StreamChunkPayload,
    ActionPayload,
    DesktopCommandPayload,
    DesktopResultPayload,
    DesktopContextPayload,
    SessionPayload,
    ErrorPayload,
    CompletePayload,
    create_user_message,
    create_thinking_message,
    create_action_message,
    create_desktop_command,
    create_desktop_result,
    create_stream_chunk,
    create_error_message,
)

from .gateway_router import (
    GatewayRouter,
    gateway_router,
)

__all__ = [
    # Message Protocol
    "UnifiedMessage",
    "MessageType",
    "Platform",
    "UserMessagePayload",
    "ThinkingPayload",
    "StreamChunkPayload",
    "ActionPayload",
    "DesktopCommandPayload",
    "DesktopResultPayload",
    "DesktopContextPayload",
    "SessionPayload",
    "ErrorPayload",
    "CompletePayload",
    "create_user_message",
    "create_thinking_message",
    "create_action_message",
    "create_desktop_command",
    "create_desktop_result",
    "create_stream_chunk",
    "create_error_message",

    # Gateway Router
    "GatewayRouter",
    "gateway_router",
]
