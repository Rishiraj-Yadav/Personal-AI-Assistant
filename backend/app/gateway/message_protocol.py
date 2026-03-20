"""
Unified Message Protocol - Phase 4

Standard message format for all communication:
- Frontend ↔ Backend
- Backend ↔ Desktop Agent
- Backend ↔ Gateway
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class MessageType(str, Enum):
    """Standard message types across the system."""
    # User interaction
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"

    # System status
    ACK = "ack"
    THINKING = "thinking"

    # Streaming
    STREAM_START = "stream_start"
    STREAM_CHUNK = "stream_chunk"
    STREAM_END = "stream_end"

    # Actions
    ACTION_STARTED = "action_started"
    ACTION_PROGRESS = "action_progress"
    ACTION_COMPLETED = "action_completed"
    ACTION_FAILED = "action_failed"

    # Desktop operations
    DESKTOP_COMMAND = "desktop_command"
    DESKTOP_RESULT = "desktop_result"
    DESKTOP_ERROR = "desktop_error"
    DESKTOP_CONTEXT = "desktop_context"

    # Session events
    SESSION_CREATED = "session_created"
    SESSION_UPDATED = "session_updated"
    SESSION_ENDED = "session_ended"

    # Errors
    ERROR = "error"

    # Completion
    COMPLETE = "complete"


class Platform(str, Enum):
    """Platform identifiers."""
    WEB = "web"
    DESKTOP = "desktop"
    CLI = "cli"
    MOBILE = "mobile"


@dataclass
class MessageMetadata:
    """Standard metadata for all messages."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    platform: Platform = Platform.WEB
    source: str = "backend"  # "frontend", "backend", "desktop_agent", "gateway"
    trace_id: Optional[str] = None


class UnifiedMessage(BaseModel):
    """
    Unified message format for all system communication.

    This format is used across:
    - WebSocket messages
    - HTTP responses
    - Inter-service communication
    - Event streaming
    """
    type: MessageType
    session_id: str
    request_id: Optional[str] = None
    conversation_id: Optional[str] = None
    user_id: Optional[str] = None

    # Message payload (flexible based on type)
    payload: Dict[str, Any] = field(default_factory=dict)

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Timestamp
    timestamp: Optional[str] = None

    def __init__(self, **data):
        super().__init__(**data)
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


# Message payload schemas for specific types

class UserMessagePayload(BaseModel):
    """Payload for user messages."""
    message: str
    context: Optional[Dict[str, Any]] = None
    attachments: List[str] = field(default_factory=list)


class ThinkingPayload(BaseModel):
    """Payload for thinking/processing status."""
    message: str
    intent: Optional[str] = None
    confidence: Optional[float] = None
    routing_path: Optional[str] = None  # "fast" | "full"


class StreamChunkPayload(BaseModel):
    """Payload for streaming text chunks."""
    content: str
    chunk_index: Optional[int] = None


class ActionPayload(BaseModel):
    """Payload for action events."""
    action_type: str  # "code_generation", "desktop_control", "file_operation", etc.
    description: str
    target: Optional[str] = None
    progress: float = 0.0
    status: str = "pending"  # "pending", "running", "completed", "failed"
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class DesktopCommandPayload(BaseModel):
    """Payload for desktop commands."""
    command: str  # "click", "type", "open_app", "screenshot", etc.
    parameters: Dict[str, Any] = field(default_factory=dict)
    timeout: int = 30
    requires_confirmation: bool = False


class DesktopResultPayload(BaseModel):
    """Payload for desktop command results."""
    command: str
    success: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    execution_time_ms: Optional[float] = None


class DesktopContextPayload(BaseModel):
    """Payload for desktop context updates."""
    current_app: Optional[str] = None
    current_file: Optional[str] = None
    screen_resolution: Optional[tuple] = None
    active_window: Optional[str] = None
    clipboard: Optional[str] = None


class SessionPayload(BaseModel):
    """Payload for session events."""
    session_id: str
    user_id: str
    conversation_id: str
    status: str = "active"  # "active", "paused", "ended"
    message_count: int = 0
    active_task: Optional[Dict[str, Any]] = None


class ErrorPayload(BaseModel):
    """Payload for error messages."""
    error_type: str
    message: str
    details: Optional[Dict[str, Any]] = None
    recoverable: bool = True


class CompletePayload(BaseModel):
    """Payload for completion messages."""
    success: bool
    task_type: str
    intent: str
    is_fast_path: bool
    total_time_ms: float
    agent_path: List[str] = field(default_factory=list)


# Helper functions to create standard messages

def create_user_message(
    session_id: str,
    message: str,
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None
) -> UnifiedMessage:
    """Create a user message."""
    return UnifiedMessage(
        type=MessageType.USER_MESSAGE,
        session_id=session_id,
        user_id=user_id,
        conversation_id=conversation_id,
        payload={
            "message": message,
            "context": context or {}
        }
    )


def create_thinking_message(
    session_id: str,
    message: str,
    request_id: Optional[str] = None,
    intent: Optional[str] = None,
    routing_path: Optional[str] = None
) -> UnifiedMessage:
    """Create a thinking status message."""
    return UnifiedMessage(
        type=MessageType.THINKING,
        session_id=session_id,
        request_id=request_id,
        payload={
            "message": message,
            "intent": intent,
            "routing_path": routing_path
        }
    )


def create_action_message(
    session_id: str,
    action_type: str,
    description: str,
    status: str = "started",
    request_id: Optional[str] = None,
    target: Optional[str] = None,
    progress: float = 0.0
) -> UnifiedMessage:
    """Create an action event message."""
    msg_type = {
        "started": MessageType.ACTION_STARTED,
        "progress": MessageType.ACTION_PROGRESS,
        "completed": MessageType.ACTION_COMPLETED,
        "failed": MessageType.ACTION_FAILED
    }.get(status, MessageType.ACTION_STARTED)

    return UnifiedMessage(
        type=msg_type,
        session_id=session_id,
        request_id=request_id,
        payload={
            "action_type": action_type,
            "description": description,
            "target": target,
            "progress": progress,
            "status": status
        }
    )


def create_desktop_command(
    session_id: str,
    command: str,
    parameters: Dict[str, Any],
    request_id: Optional[str] = None,
    timeout: int = 30
) -> UnifiedMessage:
    """Create a desktop command message."""
    return UnifiedMessage(
        type=MessageType.DESKTOP_COMMAND,
        session_id=session_id,
        request_id=request_id,
        payload={
            "command": command,
            "parameters": parameters,
            "timeout": timeout
        }
    )


def create_desktop_result(
    session_id: str,
    command: str,
    success: bool,
    request_id: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None
) -> UnifiedMessage:
    """Create a desktop result message."""
    msg_type = MessageType.DESKTOP_RESULT if success else MessageType.DESKTOP_ERROR

    return UnifiedMessage(
        type=msg_type,
        session_id=session_id,
        request_id=request_id,
        payload={
            "command": command,
            "success": success,
            "result": result,
            "error": error
        }
    )


def create_stream_chunk(
    session_id: str,
    content: str,
    request_id: Optional[str] = None,
    chunk_index: Optional[int] = None
) -> UnifiedMessage:
    """Create a stream chunk message."""
    return UnifiedMessage(
        type=MessageType.STREAM_CHUNK,
        session_id=session_id,
        request_id=request_id,
        payload={
            "content": content,
            "chunk_index": chunk_index
        }
    )


def create_error_message(
    session_id: str,
    error_type: str,
    message: str,
    request_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None
) -> UnifiedMessage:
    """Create an error message."""
    return UnifiedMessage(
        type=MessageType.ERROR,
        session_id=session_id,
        request_id=request_id,
        payload={
            "error_type": error_type,
            "message": message,
            "details": details or {}
        }
    )
