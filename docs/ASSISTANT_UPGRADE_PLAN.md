# Production-Grade AI Assistant Upgrade Plan

> Transform from Request-Response Pipeline to Real-Time Assistant Experience

## Table of Contents

1. [Architecture Changes](#1-architecture-changes)
2. [Implementation Plan](#2-implementation-plan)
   - [Phase 1: WebSocket + Instant Response](#phase-1-websocket-infrastructure--instant-response-layer)
   - [Phase 2: Session Management](#phase-2-session-manager--context-persistence)
   - [Phase 3: Fast Path + Streaming](#phase-3-fast-path-routing--response-ux)
   - [Phase 4: Runtime + Gateway](#phase-4-assistant-runtime--multi-platform-gateway)
3. [Updated File Structure](#3-updated-file-structure)
4. [Integration Guide](#4-integration-with-existing-system)
5. [Before vs After](#5-before-vs-after-user-flow)
6. [Implementation Roadmap](#6-implementation-roadmap)

---

## 1. Architecture Changes

### BEFORE: Request-Response Pipeline

```
User Input
    │
    ▼
┌─────────┐    ┌─────────────┐    ┌────────────┐    ┌──────────┐
│ React   │───▶│ FastAPI     │───▶│ Router     │───▶│ Agent    │
│ Frontend│    │ /chat       │    │ Agent      │    │ Execution│
└─────────┘    └─────────────┘    └────────────┘    └──────────┘
                                                          │
                                                          ▼
                                                    ┌──────────┐
User sees response ◀─────────────────────────────── │ Full     │
(after 3-10 seconds)                                │ Response │
                                                    └──────────┘

PROBLEMS:
✗ User waits for ENTIRE pipeline to complete
✗ No streaming
✗ No session awareness
✗ Every request feels "cold"
✗ Internal errors exposed
✗ No typing indicators
```

### AFTER: Real-Time Assistant Experience

```
User Input
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ASSISTANT GATEWAY                            │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │ WebSocket    │  │ Session      │  │ Fast Path          │    │
│  │ Manager      │  │ Manager      │  │ Router             │    │
│  └──────────────┘  └──────────────┘  └────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
         │                  │                    │
         │                  │                    │
    ┌────┴────┐        ┌────┴────┐         ┌────┴────┐
    │ Instant │        │ Session │         │ Simple  │
    │ ACK     │        │ Context │         │ Query?  │
    │ (50ms)  │        │ Load    │         │         │
    └────┬────┘        └────┬────┘         └────┬────┘
         │                  │                    │
         ▼                  ▼                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                   ASSISTANT RUNTIME                             │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │ Stream       │  │ Background   │  │ Response           │    │
│  │ Manager      │  │ Task Queue   │  │ Sanitizer          │    │
│  └──────────────┘  └──────────────┘  └────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
         │                  │                    │
         ▼                  ▼                    ▼
    ┌─────────┐       ┌───────────┐       ┌───────────┐
    │ Stream  │       │ TaskExec  │       │ Clean     │
    │ Tokens  │       │ + SafeExec│       │ Output    │
    │ Live    │       │ (existing)│       │ to User   │
    └─────────┘       └───────────┘       └───────────┘

USER EXPERIENCE:
✓ Instant acknowledgment (<100ms)
✓ Streaming tokens in real-time
✓ Session context preserved
✓ Errors handled gracefully
✓ Feels like ChatGPT/Claude
```

---

## 2. Implementation Plan

### Phase 1: WebSocket Infrastructure + Instant Response Layer

**Timeline:** Week 1

#### Goal

Replace HTTP polling with persistent WebSocket connections. Add instant acknowledgment so users see response immediately.

#### Files to Create

```
backend/app/realtime/
├── __init__.py
├── websocket_manager.py      # Connection management
├── message_types.py          # Typed message schemas
├── instant_responder.py      # <100ms acknowledgment
└── connection_pool.py        # Connection lifecycle
```

#### Files to Modify

```
backend/app/main.py                    # Add WebSocket routes
backend/app/api/routes/chat.py         # Add WS endpoint
frontend/src/services/websocket.ts     # Client WS handler
frontend/src/hooks/useAssistant.ts     # React hook for WS
```

#### Step-by-Step Tasks

##### Task 1.1: Create Message Type Definitions

```python
# backend/app/realtime/message_types.py
from enum import Enum
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime
import uuid

class MessageType(str, Enum):
    # Client → Server
    USER_MESSAGE = "user_message"
    PING = "ping"
    SESSION_INIT = "session_init"
    CANCEL_REQUEST = "cancel_request"

    # Server → Client
    ACK = "ack"
    THINKING = "thinking"
    STREAM_START = "stream_start"
    STREAM_CHUNK = "stream_chunk"
    STREAM_END = "stream_end"
    ERROR = "error"
    PONG = "pong"
    SESSION_RESTORED = "session_restored"

class BaseMessage(BaseModel):
    type: MessageType
    id: str = None
    timestamp: datetime = None

    def __init__(self, **data):
        if 'id' not in data or data['id'] is None:
            data['id'] = str(uuid.uuid4())
        if 'timestamp' not in data or data['timestamp'] is None:
            data['timestamp'] = datetime.utcnow()
        super().__init__(**data)

class UserMessage(BaseMessage):
    type: MessageType = MessageType.USER_MESSAGE
    content: str
    session_id: str
    attachments: list = []

class AckMessage(BaseMessage):
    type: MessageType = MessageType.ACK
    request_id: str
    message: str = "Processing your request..."

class ThinkingMessage(BaseMessage):
    type: MessageType = MessageType.THINKING
    request_id: str
    stage: str  # "understanding", "planning", "executing", "generating"

class StreamChunk(BaseMessage):
    type: MessageType = MessageType.STREAM_CHUNK
    request_id: str
    content: str
    is_final: bool = False

class ErrorMessage(BaseMessage):
    type: MessageType = MessageType.ERROR
    request_id: str
    error_code: str
    user_message: str  # Safe message for user
    retry_allowed: bool = True
```

##### Task 1.2: Build WebSocket Manager

```python
# backend/app/realtime/websocket_manager.py
from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, Set, Optional
from datetime import datetime
import asyncio
import json
from .message_types import BaseMessage, MessageType, AckMessage

class ConnectionState:
    def __init__(self, websocket: WebSocket, user_id: str, session_id: str):
        self.websocket = websocket
        self.user_id = user_id
        self.session_id = session_id
        self.connected_at = datetime.utcnow()
        self.last_ping = datetime.utcnow()
        self.is_alive = True

class WebSocketManager:
    def __init__(self):
        # user_id -> set of ConnectionState
        self._connections: Dict[str, Set[ConnectionState]] = {}
        # session_id -> ConnectionState
        self._sessions: Dict[str, ConnectionState] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self,
        websocket: WebSocket,
        user_id: str,
        session_id: str
    ) -> ConnectionState:
        await websocket.accept()

        conn = ConnectionState(websocket, user_id, session_id)

        async with self._lock:
            if user_id not in self._connections:
                self._connections[user_id] = set()
            self._connections[user_id].add(conn)
            self._sessions[session_id] = conn

        return conn

    async def disconnect(self, conn: ConnectionState):
        async with self._lock:
            if conn.user_id in self._connections:
                self._connections[conn.user_id].discard(conn)
                if not self._connections[conn.user_id]:
                    del self._connections[conn.user_id]
            if conn.session_id in self._sessions:
                del self._sessions[conn.session_id]
        conn.is_alive = False

    async def send_to_session(self, session_id: str, message: BaseMessage):
        """Send message to specific session"""
        conn = self._sessions.get(session_id)
        if conn and conn.is_alive:
            try:
                await conn.websocket.send_json(message.model_dump(mode='json'))
            except Exception:
                await self.disconnect(conn)

    async def send_ack(self, session_id: str, request_id: str):
        """Send instant acknowledgment - MUST complete in <100ms"""
        ack = AckMessage(request_id=request_id)
        await self.send_to_session(session_id, ack)

    async def broadcast_to_user(self, user_id: str, message: BaseMessage):
        """Send to all user's connections (multi-device)"""
        conns = self._connections.get(user_id, set())
        for conn in list(conns):
            if conn.is_alive:
                try:
                    await conn.websocket.send_json(message.model_dump(mode='json'))
                except Exception:
                    await self.disconnect(conn)

# Singleton instance
ws_manager = WebSocketManager()
```

##### Task 1.3: Create Instant Responder

```python
# backend/app/realtime/instant_responder.py
import asyncio
from typing import Callable, Awaitable
from .websocket_manager import ws_manager
from .message_types import (
    AckMessage, ThinkingMessage, StreamChunk,
    StreamStart, StreamEnd, ErrorMessage
)

class InstantResponder:
    """
    Handles immediate user feedback while heavy processing runs in background.
    Target: ACK within 50ms of receiving message.
    """

    def __init__(self):
        self._thinking_messages = {
            "understanding": "Understanding your request...",
            "planning": "Planning the best approach...",
            "executing": "Working on it...",
            "generating": "Generating response..."
        }

    async def acknowledge(self, session_id: str, request_id: str):
        """Send instant ACK - fire and forget"""
        ack = AckMessage(
            request_id=request_id,
            message="Got it! Working on your request..."
        )
        await ws_manager.send_to_session(session_id, ack)

    async def send_thinking(self, session_id: str, request_id: str, stage: str):
        """Update user on current processing stage"""
        msg = ThinkingMessage(
            request_id=request_id,
            stage=stage
        )
        await ws_manager.send_to_session(session_id, msg)

    async def stream_response(
        self,
        session_id: str,
        request_id: str,
        generator: Callable[[], Awaitable[str]]
    ):
        """Stream tokens as they're generated"""
        await ws_manager.send_to_session(
            session_id,
            StreamStart(request_id=request_id)
        )

        try:
            async for chunk in generator():
                await ws_manager.send_to_session(
                    session_id,
                    StreamChunk(request_id=request_id, content=chunk)
                )
                # Small delay to prevent overwhelming client
                await asyncio.sleep(0.01)
        finally:
            await ws_manager.send_to_session(
                session_id,
                StreamEnd(request_id=request_id)
            )

    async def send_error(
        self,
        session_id: str,
        request_id: str,
        error_code: str,
        user_message: str
    ):
        """Send user-friendly error"""
        error = ErrorMessage(
            request_id=request_id,
            error_code=error_code,
            user_message=user_message
        )
        await ws_manager.send_to_session(session_id, error)

instant_responder = InstantResponder()
```

##### Task 1.4: Add WebSocket Route to FastAPI

```python
# backend/app/api/routes/websocket.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from app.realtime.websocket_manager import ws_manager
from app.realtime.message_types import MessageType, UserMessage
from app.realtime.instant_responder import instant_responder
from app.core.auth import get_current_user_ws
import json
import asyncio

router = APIRouter()

@router.websocket("/ws/assistant/{session_id}")
async def assistant_websocket(
    websocket: WebSocket,
    session_id: str,
    user_id: str = Depends(get_current_user_ws)
):
    conn = await ws_manager.connect(websocket, user_id, session_id)

    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)

            msg_type = data.get("type")

            if msg_type == MessageType.PING:
                await websocket.send_json({"type": MessageType.PONG})
                continue

            if msg_type == MessageType.USER_MESSAGE:
                request_id = data.get("id")

                # INSTANT ACK - must happen within 50ms
                asyncio.create_task(
                    instant_responder.acknowledge(session_id, request_id)
                )

                # Process message in background
                asyncio.create_task(
                    process_user_message(session_id, request_id, data)
                )

    except WebSocketDisconnect:
        await ws_manager.disconnect(conn)
    except Exception as e:
        await ws_manager.disconnect(conn)
        raise

async def process_user_message(session_id: str, request_id: str, data: dict):
    """Background processing - integrates with existing orchestrator"""
    from app.agents.multi_agent_orchestrator import orchestrator
    from app.realtime.instant_responder import instant_responder

    try:
        # Update thinking status
        await instant_responder.send_thinking(session_id, request_id, "understanding")

        # Call existing orchestrator with streaming callback
        async def stream_callback(chunk: str):
            await ws_manager.send_to_session(
                session_id,
                StreamChunk(request_id=request_id, content=chunk)
            )

        await instant_responder.send_thinking(session_id, request_id, "executing")

        # Your existing orchestrator call
        response = await orchestrator.process_message(
            message=data.get("content"),
            user_id=data.get("user_id"),
            session_id=session_id,
            stream_callback=stream_callback  # NEW: streaming support
        )

    except Exception as e:
        await instant_responder.send_error(
            session_id,
            request_id,
            "PROCESSING_ERROR",
            "Sorry, I encountered an issue. Please try again."
        )
```

##### Task 1.5: Frontend WebSocket Service

```typescript
// frontend/src/services/websocket.ts
type MessageHandler = (message: any) => void;

interface WebSocketConfig {
  url: string;
  sessionId: string;
  onMessage: MessageHandler;
  onStateChange: (state: 'connecting' | 'connected' | 'disconnected') => void;
}

class AssistantWebSocket {
  private ws: WebSocket | null = null;
  private config: WebSocketConfig;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private pingInterval: NodeJS.Timeout | null = null;

  constructor(config: WebSocketConfig) {
    this.config = config;
  }

  connect() {
    this.config.onStateChange('connecting');

    this.ws = new WebSocket(
      `${this.config.url}/ws/assistant/${this.config.sessionId}`
    );

    this.ws.onopen = () => {
      this.config.onStateChange('connected');
      this.reconnectAttempts = 0;
      this.startPingInterval();
    };

    this.ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      this.config.onMessage(message);
    };

    this.ws.onclose = () => {
      this.config.onStateChange('disconnected');
      this.stopPingInterval();
      this.attemptReconnect();
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  send(message: object) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    }
  }

  sendMessage(content: string): string {
    const id = crypto.randomUUID();
    this.send({
      type: 'user_message',
      id,
      content,
      session_id: this.config.sessionId,
      timestamp: new Date().toISOString()
    });
    return id;
  }

  private startPingInterval() {
    this.pingInterval = setInterval(() => {
      this.send({ type: 'ping' });
    }, 30000);
  }

  private stopPingInterval() {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
  }

  private attemptReconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
      setTimeout(() => this.connect(), delay);
    }
  }

  disconnect() {
    this.stopPingInterval();
    this.ws?.close();
  }
}

export { AssistantWebSocket };
```

#### Risks

| Risk | Mitigation |
|------|------------|
| WebSocket connections may not work behind certain proxies | Keep HTTP fallback |
| Memory leaks if connections not properly cleaned up | Connection lifecycle management |
| Message ordering issues | Request IDs and sequence numbers |

#### Expected Outcome

- Users see "Got it!" within 50-100ms of sending message
- Typing indicators show processing stages
- Foundation for streaming in Phase 2

---

### Phase 2: Session Manager + Context Persistence

**Timeline:** Week 2

#### Goal

Implement session-based assistant that remembers context within conversations and can restore sessions.

#### Files to Create

```
backend/app/session/
├── __init__.py
├── session_manager.py        # Session lifecycle
├── session_store.py          # Redis/Memory persistence
├── context_builder.py        # Build context from history
└── session_models.py         # Session data structures
```

#### Files to Modify

```
backend/app/realtime/websocket_manager.py   # Add session restoration
backend/app/agents/multi_agent_orchestrator.py  # Accept session context
```

#### Step-by-Step Tasks

##### Task 2.1: Session Models

```python
# backend/app/session/session_models.py
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum

class SessionStatus(str, Enum):
    ACTIVE = "active"
    IDLE = "idle"
    EXPIRED = "expired"

class ConversationTurn(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime
    metadata: Dict[str, Any] = {}

class SessionContext(BaseModel):
    """Lightweight context passed to LLM"""
    recent_turns: List[ConversationTurn]  # Last N turns
    user_preferences: Dict[str, Any]
    active_task: Optional[str]
    entities_mentioned: List[str]  # People, files, projects referenced

class Session(BaseModel):
    id: str
    user_id: str
    status: SessionStatus
    created_at: datetime
    last_activity: datetime
    conversation_history: List[ConversationTurn]
    context: SessionContext
    metadata: Dict[str, Any] = {}

    def get_context_window(self, max_turns: int = 10) -> SessionContext:
        """Get recent context for LLM"""
        return SessionContext(
            recent_turns=self.conversation_history[-max_turns:],
            user_preferences=self.context.user_preferences,
            active_task=self.context.active_task,
            entities_mentioned=self.context.entities_mentioned
        )
```

##### Task 2.2: Session Store (Redis-backed with Memory fallback)

```python
# backend/app/session/session_store.py
from typing import Optional, Dict
from datetime import datetime, timedelta
import json
import asyncio
from abc import ABC, abstractmethod
from .session_models import Session, SessionStatus

class SessionStore(ABC):
    @abstractmethod
    async def get(self, session_id: str) -> Optional[Session]:
        pass

    @abstractmethod
    async def save(self, session: Session) -> None:
        pass

    @abstractmethod
    async def delete(self, session_id: str) -> None:
        pass

class MemorySessionStore(SessionStore):
    """In-memory store for development/single-instance"""

    def __init__(self, ttl_minutes: int = 60):
        self._sessions: Dict[str, Session] = {}
        self._ttl = timedelta(minutes=ttl_minutes)
        self._lock = asyncio.Lock()

    async def get(self, session_id: str) -> Optional[Session]:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session:
                if datetime.utcnow() - session.last_activity > self._ttl:
                    session.status = SessionStatus.EXPIRED
                    del self._sessions[session_id]
                    return None
            return session

    async def save(self, session: Session) -> None:
        async with self._lock:
            session.last_activity = datetime.utcnow()
            self._sessions[session.id] = session

    async def delete(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)

class RedisSessionStore(SessionStore):
    """Redis store for production/multi-instance"""

    def __init__(self, redis_client, ttl_minutes: int = 60):
        self._redis = redis_client
        self._ttl = ttl_minutes * 60
        self._prefix = "session:"

    async def get(self, session_id: str) -> Optional[Session]:
        data = await self._redis.get(f"{self._prefix}{session_id}")
        if data:
            return Session.model_validate_json(data)
        return None

    async def save(self, session: Session) -> None:
        session.last_activity = datetime.utcnow()
        await self._redis.setex(
            f"{self._prefix}{session.id}",
            self._ttl,
            session.model_dump_json()
        )

    async def delete(self, session_id: str) -> None:
        await self._redis.delete(f"{self._prefix}{session_id}")
```

##### Task 2.3: Session Manager

```python
# backend/app/session/session_manager.py
from typing import Optional
from datetime import datetime
import uuid
from .session_models import Session, SessionContext, SessionStatus, ConversationTurn
from .session_store import SessionStore, MemorySessionStore

class SessionManager:
    def __init__(self, store: Optional[SessionStore] = None):
        self._store = store or MemorySessionStore()

    async def create_session(self, user_id: str) -> Session:
        """Create new session for user"""
        session = Session(
            id=str(uuid.uuid4()),
            user_id=user_id,
            status=SessionStatus.ACTIVE,
            created_at=datetime.utcnow(),
            last_activity=datetime.utcnow(),
            conversation_history=[],
            context=SessionContext(
                recent_turns=[],
                user_preferences={},
                active_task=None,
                entities_mentioned=[]
            )
        )
        await self._store.save(session)
        return session

    async def get_or_create(self, session_id: str, user_id: str) -> Session:
        """Get existing session or create new one"""
        session = await self._store.get(session_id)
        if session and session.user_id == user_id:
            session.status = SessionStatus.ACTIVE
            return session
        return await self.create_session(user_id)

    async def add_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict = None
    ):
        """Add conversation turn to session"""
        session = await self._store.get(session_id)
        if session:
            turn = ConversationTurn(
                role=role,
                content=content,
                timestamp=datetime.utcnow(),
                metadata=metadata or {}
            )
            session.conversation_history.append(turn)

            # Keep only last 50 turns in memory
            if len(session.conversation_history) > 50:
                session.conversation_history = session.conversation_history[-50:]

            await self._store.save(session)

    async def get_context(self, session_id: str, max_turns: int = 10) -> Optional[SessionContext]:
        """Get context for LLM prompt"""
        session = await self._store.get(session_id)
        if session:
            return session.get_context_window(max_turns)
        return None

    async def update_active_task(self, session_id: str, task: str):
        """Track what user is currently working on"""
        session = await self._store.get(session_id)
        if session:
            session.context.active_task = task
            await self._store.save(session)

# Singleton
session_manager = SessionManager()
```

##### Task 2.4: Context Builder for LLM

```python
# backend/app/session/context_builder.py
from typing import List, Optional
from .session_models import SessionContext, ConversationTurn

class ContextBuilder:
    """Builds optimized context for LLM from session data"""

    def __init__(self, max_tokens: int = 4000):
        self.max_tokens = max_tokens

    def build_system_context(self, context: SessionContext) -> str:
        """Build context string for system prompt"""
        parts = []

        # Add user preferences
        if context.user_preferences:
            prefs = ", ".join(f"{k}: {v}" for k, v in context.user_preferences.items())
            parts.append(f"User preferences: {prefs}")

        # Add active task context
        if context.active_task:
            parts.append(f"Current task: {context.active_task}")

        # Add mentioned entities
        if context.entities_mentioned:
            parts.append(f"Recently discussed: {', '.join(context.entities_mentioned[-5:])}")

        return "\n".join(parts)

    def build_conversation_history(self, turns: List[ConversationTurn]) -> List[dict]:
        """Build message history for LLM"""
        messages = []
        for turn in turns:
            messages.append({
                "role": turn.role,
                "content": turn.content
            })
        return messages

    def build_prompt_with_context(
        self,
        current_message: str,
        context: SessionContext,
        system_prompt: str
    ) -> List[dict]:
        """Build full prompt with session context"""
        messages = []

        # System prompt with context
        context_str = self.build_system_context(context)
        full_system = f"{system_prompt}\n\n{context_str}" if context_str else system_prompt
        messages.append({"role": "system", "content": full_system})

        # Conversation history
        messages.extend(self.build_conversation_history(context.recent_turns))

        # Current message
        messages.append({"role": "user", "content": current_message})

        return messages

context_builder = ContextBuilder()
```

##### Task 2.5: Integrate Session with Orchestrator

```python
# Modify: backend/app/agents/multi_agent_orchestrator.py
# Add these imports and modify process_message

from app.session.session_manager import session_manager
from app.session.context_builder import context_builder

class MultiAgentOrchestrator:
    # ... existing code ...

    async def process_message(
        self,
        message: str,
        user_id: str,
        session_id: str,
        stream_callback: callable = None  # NEW
    ):
        # Get session context
        context = await session_manager.get_context(session_id, max_turns=10)

        # Add user message to session
        await session_manager.add_turn(session_id, "user", message)

        # Build contextualized prompt
        if context:
            messages = context_builder.build_prompt_with_context(
                message,
                context,
                self.system_prompt
            )
        else:
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": message}
            ]

        # Call existing routing logic with context
        response = await self._route_and_execute(
            messages=messages,
            user_id=user_id,
            stream_callback=stream_callback
        )

        # Add assistant response to session
        await session_manager.add_turn(session_id, "assistant", response)

        return response
```

#### Risks

| Risk | Mitigation |
|------|------------|
| Session bloat if conversations become very long | Auto-summarization after 50 turns |
| Redis connection issues | Graceful fallback to memory store |
| Context window overflow | Smart truncation in context_builder |

#### Expected Outcome

- Assistant remembers conversation context
- Sessions persist across page refreshes
- "Where were we?" queries work naturally
- Context-aware responses

---

### Phase 3: Fast Path Routing + Response UX

**Timeline:** Week 3

#### Goal

Implement fast path for simple queries (greetings, simple facts, clarifications) that bypass heavy orchestration. Add response streaming and sanitization.

#### Files to Create

```
backend/app/fastpath/
├── __init__.py
├── fast_router.py            # Quick classification
├── simple_responder.py       # Direct LLM for simple queries
├── intent_classifier.py      # Classify intent type
└── response_cache.py         # Cache common responses

backend/app/output/
├── __init__.py
├── response_sanitizer.py     # Clean output for users
├── stream_formatter.py       # Format streaming chunks
└── error_humanizer.py        # Convert errors to friendly messages
```

#### Files to Modify

```
backend/app/realtime/websocket.py     # Add fast path check
backend/app/core/llm.py               # Add streaming support
```

#### Step-by-Step Tasks

##### Task 3.1: Intent Classifier

```python
# backend/app/fastpath/intent_classifier.py
from enum import Enum
from typing import Tuple
import re

class IntentType(str, Enum):
    GREETING = "greeting"
    SIMPLE_QUESTION = "simple_question"
    CLARIFICATION = "clarification"
    SMALL_TALK = "small_talk"
    COMPLEX_TASK = "complex_task"
    CODE_TASK = "code_task"
    DESKTOP_TASK = "desktop_task"
    UNKNOWN = "unknown"

class IntentClassifier:
    """Fast, rule-based intent classification"""

    def __init__(self):
        self.greeting_patterns = [
            r"^(hi|hey|hello|good morning|good afternoon|good evening)[\s!.,]*$",
            r"^(what'?s up|sup|yo)[\s!.,]*$",
            r"^(how are you|how's it going)[\s!.,?]*$"
        ]

        self.simple_question_patterns = [
            r"^(what is|what's|who is|who's|when is|where is|how do you)\s",
            r"^(define|explain|describe)\s\w+[\s.,?]*$",
            r"^(what|who|when|where|why|how)\s.{5,50}\?$"
        ]

        self.clarification_patterns = [
            r"^(yes|no|yeah|nope|correct|right|exactly|sure)[\s!.,]*$",
            r"^(i mean|i meant|actually|sorry,? i meant)",
            r"^(the (first|second|third|last) one)",
            r"^(option [a-d1-4])"
        ]

        self.code_indicators = [
            r"(write|create|generate|fix|debug|refactor)\s.*(code|function|script|program)",
            r"(python|javascript|typescript|java|c\+\+|rust|go)\s",
            r"\.(py|js|ts|java|cpp|rs|go)\b",
            r"```"
        ]

        self.desktop_indicators = [
            r"(open|close|launch|start|run)\s.*(app|application|program|browser|chrome|firefox)",
            r"(click|type|press|scroll|move mouse)",
            r"(screenshot|screen grab|capture screen)",
            r"(copy|paste|select all)"
        ]

    def classify(self, message: str) -> Tuple[IntentType, float]:
        """Classify message intent. Returns (intent, confidence)"""
        message_lower = message.lower().strip()

        # Check greeting
        for pattern in self.greeting_patterns:
            if re.match(pattern, message_lower, re.IGNORECASE):
                return IntentType.GREETING, 0.95

        # Check clarification
        for pattern in self.clarification_patterns:
            if re.match(pattern, message_lower, re.IGNORECASE):
                return IntentType.CLARIFICATION, 0.9

        # Check code task
        for pattern in self.code_indicators:
            if re.search(pattern, message_lower, re.IGNORECASE):
                return IntentType.CODE_TASK, 0.85

        # Check desktop task
        for pattern in self.desktop_indicators:
            if re.search(pattern, message_lower, re.IGNORECASE):
                return IntentType.DESKTOP_TASK, 0.85

        # Check simple question
        for pattern in self.simple_question_patterns:
            if re.match(pattern, message_lower, re.IGNORECASE):
                return IntentType.SIMPLE_QUESTION, 0.8

        # Short messages are likely small talk or simple
        if len(message) < 30 and "?" not in message:
            return IntentType.SMALL_TALK, 0.6

        # Complex by default
        return IntentType.COMPLEX_TASK, 0.5

intent_classifier = IntentClassifier()
```

##### Task 3.2: Fast Router

```python
# backend/app/fastpath/fast_router.py
from typing import Optional, Tuple
from .intent_classifier import intent_classifier, IntentType
from .simple_responder import simple_responder

class FastRouter:
    """
    Routes messages to fast path or full orchestration.
    Fast path: <500ms response for simple queries.
    Full path: Full agent orchestration for complex tasks.
    """

    FAST_PATH_INTENTS = {
        IntentType.GREETING,
        IntentType.SMALL_TALK,
        IntentType.CLARIFICATION,
        IntentType.SIMPLE_QUESTION
    }

    FULL_PATH_INTENTS = {
        IntentType.CODE_TASK,
        IntentType.DESKTOP_TASK,
        IntentType.COMPLEX_TASK
    }

    async def route(
        self,
        message: str,
        session_context: dict = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Returns (is_fast_path, response_or_none)
        If is_fast_path=True and response is not None, use the response directly.
        If is_fast_path=False, route to full orchestration.
        """
        intent, confidence = intent_classifier.classify(message)

        # High confidence fast path
        if intent in self.FAST_PATH_INTENTS and confidence > 0.8:
            response = await simple_responder.respond(
                message,
                intent,
                session_context
            )
            return True, response

        # Definitely needs full orchestration
        if intent in self.FULL_PATH_INTENTS:
            return False, None

        # Uncertain - use fast path with fallback
        if intent == IntentType.SIMPLE_QUESTION and confidence > 0.6:
            response = await simple_responder.respond(
                message,
                intent,
                session_context,
                allow_escalation=True  # Can say "let me look into this"
            )
            if response:
                return True, response

        return False, None

fast_router = FastRouter()
```

##### Task 3.3: Simple Responder

```python
# backend/app/fastpath/simple_responder.py
from typing import Optional
from .intent_classifier import IntentType
from app.core.llm import llm_client
import random

class SimpleResponder:
    """Direct LLM responses for simple queries - no orchestration needed"""

    def __init__(self):
        self.greeting_responses = [
            "Hey! What can I help you with?",
            "Hi there! How can I assist you today?",
            "Hello! Ready to help when you are.",
            "Hey! What's on your mind?"
        ]

        self.small_talk_prompt = """You are a friendly AI assistant.
        Respond naturally and briefly to small talk.
        Keep responses under 2 sentences.
        Be warm but professional."""

    async def respond(
        self,
        message: str,
        intent: IntentType,
        context: dict = None,
        allow_escalation: bool = False
    ) -> Optional[str]:
        """Generate quick response for simple intents"""

        if intent == IntentType.GREETING:
            return random.choice(self.greeting_responses)

        if intent == IntentType.SMALL_TALK:
            return await self._llm_quick_response(
                message,
                self.small_talk_prompt,
                max_tokens=100
            )

        if intent == IntentType.SIMPLE_QUESTION:
            response = await self._llm_quick_response(
                message,
                "Answer this simple question briefly and directly. If you don't know or it requires research, say so.",
                max_tokens=200
            )

            # Check if LLM indicated it needs more work
            if allow_escalation and any(phrase in response.lower() for phrase in [
                "i don't know",
                "i'm not sure",
                "let me look",
                "i would need to"
            ]):
                return None  # Escalate to full orchestration

            return response

        if intent == IntentType.CLARIFICATION:
            # Use context to understand what they're clarifying
            if context and context.get("pending_question"):
                return await self._handle_clarification(message, context)
            return "Got it! What would you like me to do with that?"

        return None

    async def _llm_quick_response(
        self,
        message: str,
        system_prompt: str,
        max_tokens: int = 150
    ) -> str:
        """Quick LLM call with minimal tokens"""
        response = await llm_client.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            max_tokens=max_tokens,
            temperature=0.7
        )
        return response.content

    async def _handle_clarification(self, message: str, context: dict) -> str:
        """Handle user clarification based on context"""
        pending = context.get("pending_question", "")
        return await self._llm_quick_response(
            f"User was asked: {pending}\nUser responded: {message}\nAcknowledge their choice and confirm.",
            "You are confirming a user's selection. Be brief.",
            max_tokens=50
        )

simple_responder = SimpleResponder()
```

##### Task 3.4: Response Sanitizer

```python
# backend/app/output/response_sanitizer.py
import re
from typing import Optional

class ResponseSanitizer:
    """Clean and format responses before sending to user"""

    def __init__(self):
        # Patterns to remove
        self.internal_patterns = [
            r"\[INTERNAL:.*?\]",
            r"\[DEBUG:.*?\]",
            r"\[TRACE:.*?\]",
            r"<think>.*?</think>",
            r"<<.*?>>",
        ]

        # Error patterns to humanize
        self.error_patterns = {
            r"HTTPException.*?500": "I ran into a technical issue.",
            r"TimeoutError": "The operation took too long.",
            r"ConnectionError": "I'm having trouble connecting.",
            r"KeyError.*?'(\w+)'": r"I couldn't find the \1 information.",
        }

    def sanitize(self, response: str) -> str:
        """Clean response for user consumption"""
        result = response

        # Remove internal markers
        for pattern in self.internal_patterns:
            result = re.sub(pattern, "", result, flags=re.DOTALL | re.IGNORECASE)

        # Clean up extra whitespace
        result = re.sub(r'\n{3,}', '\n\n', result)
        result = result.strip()

        return result

    def humanize_error(self, error: str) -> str:
        """Convert technical errors to friendly messages"""
        for pattern, replacement in self.error_patterns.items():
            if re.search(pattern, error, re.IGNORECASE):
                return re.sub(pattern, replacement, error, flags=re.IGNORECASE)

        # Generic fallback
        return "I encountered an issue processing that. Could you try again?"

    def format_for_display(self, response: str, format_type: str = "markdown") -> str:
        """Format response for specific display type"""
        if format_type == "plain":
            # Strip markdown
            result = re.sub(r'\*\*(.+?)\*\*', r'\1', response)
            result = re.sub(r'\*(.+?)\*', r'\1', result)
            result = re.sub(r'`(.+?)`', r'\1', result)
            return result

        return response  # Default markdown

response_sanitizer = ResponseSanitizer()
```

##### Task 3.5: Integrate Fast Path into WebSocket Handler

```python
# Modify: backend/app/api/routes/websocket.py

from app.fastpath.fast_router import fast_router
from app.output.response_sanitizer import response_sanitizer

async def process_user_message(session_id: str, request_id: str, data: dict):
    """Process message with fast path check"""
    message = data.get("content")

    # Check fast path first
    is_fast, quick_response = await fast_router.route(
        message,
        session_context=await session_manager.get_context(session_id)
    )

    if is_fast and quick_response:
        # Fast path - respond immediately, no orchestration
        sanitized = response_sanitizer.sanitize(quick_response)
        await ws_manager.send_to_session(
            session_id,
            StreamChunk(request_id=request_id, content=sanitized, is_final=True)
        )
        await session_manager.add_turn(session_id, "user", message)
        await session_manager.add_turn(session_id, "assistant", sanitized)
        return

    # Full orchestration path
    await instant_responder.send_thinking(session_id, request_id, "understanding")

    # ... rest of existing orchestration logic
```

##### Task 3.6: Add Streaming to LLM Client

```python
# Modify: backend/app/core/llm.py

from typing import AsyncGenerator

class LLMClient:
    # ... existing code ...

    async def chat_stream(
        self,
        messages: list,
        max_tokens: int = 1000,
        temperature: float = 0.7
    ) -> AsyncGenerator[str, None]:
        """Stream response tokens"""

        if self._provider == "groq":
            response = await self._groq_client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True
            )

            async for chunk in response:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        elif self._provider == "openai":
            response = await self._openai_client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True
            )

            async for chunk in response:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
```

#### Risks

| Risk | Mitigation |
|------|------------|
| False positives in intent classification | allow_escalation flag |
| Inconsistent response quality between fast/full paths | Same LLM, different prompts |
| Latency in first token when streaming | Connection pooling |

#### Expected Outcome

- Greetings answered in <200ms
- Simple questions in <500ms
- Streaming responses for complex queries
- Clean, professional output

---

### Phase 4: Assistant Runtime + Multi-Platform Gateway

**Timeline:** Week 4

#### Goal

Create the "always-on" assistant runtime that manages background tasks, handles multi-platform delivery, and provides the core assistant loop.

#### Files to Create

```
backend/app/runtime/
├── __init__.py
├── assistant_runtime.py      # Main runtime loop
├── task_queue.py             # Background task management
├── capability_registry.py    # What assistant can do
└── runtime_state.py          # Global runtime state

backend/app/gateway/
├── __init__.py
├── gateway_router.py         # Platform-agnostic routing
├── platform_adapters/
│   ├── __init__.py
│   ├── web_adapter.py        # Web/React frontend
│   ├── desktop_adapter.py    # Desktop app
│   └── api_adapter.py        # REST API clients
└── message_transformer.py    # Platform-specific formatting
```

#### Files to Modify

```
backend/app/main.py                    # Register runtime
backend/app/agents/multi_agent_orchestrator.py  # Runtime integration
```

#### Step-by-Step Tasks

##### Task 4.1: Assistant Runtime Core

```python
# backend/app/runtime/assistant_runtime.py
import asyncio
from typing import Dict, Any, Optional, Callable
from datetime import datetime
from enum import Enum
import logging

from app.session.session_manager import session_manager
from app.fastpath.fast_router import fast_router
from app.agents.multi_agent_orchestrator import orchestrator
from app.realtime.instant_responder import instant_responder
from app.output.response_sanitizer import response_sanitizer
from .task_queue import task_queue
from .runtime_state import runtime_state

logger = logging.getLogger(__name__)

class ProcessingStage(str, Enum):
    RECEIVED = "received"
    CLASSIFYING = "classifying"
    FAST_PATH = "fast_path"
    ROUTING = "routing"
    EXECUTING = "executing"
    STREAMING = "streaming"
    COMPLETED = "completed"
    ERROR = "error"

class AssistantRuntime:
    """
    Core runtime that manages the assistant lifecycle.
    Handles message processing, background tasks, and state management.
    """

    def __init__(self):
        self._running = False
        self._background_tasks: Dict[str, asyncio.Task] = {}
        self._request_handlers: Dict[str, Callable] = {}

    async def start(self):
        """Start the runtime"""
        self._running = True
        runtime_state.set_running(True)
        logger.info("Assistant runtime started")

        # Start background workers
        asyncio.create_task(self._background_worker())
        asyncio.create_task(self._health_check_worker())

    async def stop(self):
        """Gracefully stop the runtime"""
        self._running = False
        runtime_state.set_running(False)

        # Cancel all background tasks
        for task_id, task in self._background_tasks.items():
            task.cancel()

        logger.info("Assistant runtime stopped")

    async def process_message(
        self,
        message: str,
        user_id: str,
        session_id: str,
        request_id: str,
        platform: str = "web",
        stream_callback: Callable = None,
        stage_callback: Callable = None
    ) -> str:
        """
        Main entry point for processing user messages.
        Handles the full lifecycle: receive → classify → route → execute → respond
        """
        start_time = datetime.utcnow()

        try:
            # Stage 1: Received
            if stage_callback:
                await stage_callback(ProcessingStage.RECEIVED)

            # Get/create session
            session = await session_manager.get_or_create(session_id, user_id)
            context = await session_manager.get_context(session_id)

            # Stage 2: Classifying
            if stage_callback:
                await stage_callback(ProcessingStage.CLASSIFYING)

            # Try fast path first
            is_fast, quick_response = await fast_router.route(
                message,
                context.model_dump() if context else None
            )

            if is_fast and quick_response:
                # Stage 3: Fast path
                if stage_callback:
                    await stage_callback(ProcessingStage.FAST_PATH)

                response = response_sanitizer.sanitize(quick_response)
                await self._finalize_response(
                    session_id, message, response, start_time
                )
                return response

            # Stage 4: Full routing
            if stage_callback:
                await stage_callback(ProcessingStage.ROUTING)

            # Stage 5: Executing
            if stage_callback:
                await stage_callback(ProcessingStage.EXECUTING)

            # Call orchestrator with streaming
            response = await orchestrator.process_message(
                message=message,
                user_id=user_id,
                session_id=session_id,
                stream_callback=stream_callback
            )

            # Sanitize final response
            response = response_sanitizer.sanitize(response)

            # Stage 6: Completed
            if stage_callback:
                await stage_callback(ProcessingStage.COMPLETED)

            await self._finalize_response(
                session_id, message, response, start_time
            )

            return response

        except Exception as e:
            logger.exception(f"Error processing message: {e}")
            if stage_callback:
                await stage_callback(ProcessingStage.ERROR)

            error_response = response_sanitizer.humanize_error(str(e))
            return error_response

    async def _finalize_response(
        self,
        session_id: str,
        message: str,
        response: str,
        start_time: datetime
    ):
        """Record turn and metrics"""
        processing_time = (datetime.utcnow() - start_time).total_seconds()

        await session_manager.add_turn(session_id, "user", message)
        await session_manager.add_turn(session_id, "assistant", response, {
            "processing_time": processing_time
        })

        runtime_state.record_request(processing_time)

    async def schedule_background_task(
        self,
        task_id: str,
        coroutine: Callable,
        *args,
        **kwargs
    ):
        """Schedule a task to run in background"""
        await task_queue.enqueue(task_id, coroutine, *args, **kwargs)

    async def _background_worker(self):
        """Process background tasks"""
        while self._running:
            try:
                task = await task_queue.dequeue()
                if task:
                    asyncio.create_task(self._execute_background_task(task))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Background worker error: {e}")

            await asyncio.sleep(0.1)

    async def _execute_background_task(self, task: dict):
        """Execute a background task with error handling"""
        task_id = task["id"]
        self._background_tasks[task_id] = asyncio.current_task()

        try:
            await task["coroutine"](*task.get("args", []), **task.get("kwargs", {}))
        except Exception as e:
            logger.exception(f"Background task {task_id} failed: {e}")
        finally:
            self._background_tasks.pop(task_id, None)

    async def _health_check_worker(self):
        """Periodic health checks"""
        while self._running:
            try:
                await runtime_state.health_check()
            except Exception as e:
                logger.exception(f"Health check failed: {e}")

            await asyncio.sleep(30)

# Singleton
assistant_runtime = AssistantRuntime()
```

##### Task 4.2: Task Queue

```python
# backend/app/runtime/task_queue.py
import asyncio
from typing import Callable, Any, Optional
from datetime import datetime
import uuid

class TaskQueue:
    """Async task queue for background operations"""

    def __init__(self, max_size: int = 1000):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_size)
        self._in_progress: dict = {}

    async def enqueue(
        self,
        task_id: str,
        coroutine: Callable,
        *args,
        priority: int = 5,
        **kwargs
    ):
        """Add task to queue"""
        task = {
            "id": task_id or str(uuid.uuid4()),
            "coroutine": coroutine,
            "args": args,
            "kwargs": kwargs,
            "priority": priority,
            "enqueued_at": datetime.utcnow()
        }
        await self._queue.put(task)

    async def dequeue(self, timeout: float = 1.0) -> Optional[dict]:
        """Get next task from queue"""
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    @property
    def size(self) -> int:
        return self._queue.qsize()

task_queue = TaskQueue()
```

##### Task 4.3: Runtime State

```python
# backend/app/runtime/runtime_state.py
from datetime import datetime
from typing import Dict, Any
import asyncio

class RuntimeState:
    """Global runtime state and metrics"""

    def __init__(self):
        self._running = False
        self._start_time: datetime = None
        self._request_count = 0
        self._total_processing_time = 0.0
        self._error_count = 0
        self._last_health_check: datetime = None
        self._health_status: Dict[str, Any] = {}
        self._lock = asyncio.Lock()

    def set_running(self, running: bool):
        self._running = running
        if running:
            self._start_time = datetime.utcnow()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def uptime_seconds(self) -> float:
        if self._start_time:
            return (datetime.utcnow() - self._start_time).total_seconds()
        return 0

    async def record_request(self, processing_time: float):
        async with self._lock:
            self._request_count += 1
            self._total_processing_time += processing_time

    async def record_error(self):
        async with self._lock:
            self._error_count += 1

    @property
    def average_processing_time(self) -> float:
        if self._request_count == 0:
            return 0
        return self._total_processing_time / self._request_count

    async def health_check(self):
        """Run health checks on subsystems"""
        from app.core.llm import llm_client
        from app.services.vector_memory_service import vector_memory

        checks = {}

        # LLM health
        try:
            await llm_client.chat(
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5
            )
            checks["llm"] = "healthy"
        except Exception:
            checks["llm"] = "unhealthy"

        # Vector DB health
        try:
            await vector_memory.health_check()
            checks["vector_db"] = "healthy"
        except Exception:
            checks["vector_db"] = "unhealthy"

        self._health_status = checks
        self._last_health_check = datetime.utcnow()

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "uptime_seconds": self.uptime_seconds,
            "request_count": self._request_count,
            "error_count": self._error_count,
            "avg_processing_time": self.average_processing_time,
            "last_health_check": self._last_health_check.isoformat() if self._last_health_check else None,
            "subsystems": self._health_status
        }

runtime_state = RuntimeState()
```

##### Task 4.4: Gateway Router

```python
# backend/app/gateway/gateway_router.py
from typing import Dict, Any, Optional
from enum import Enum

class Platform(str, Enum):
    WEB = "web"
    DESKTOP = "desktop"
    API = "api"
    MOBILE = "mobile"
    DISCORD = "discord"
    SLACK = "slack"

class GatewayRouter:
    """
    Platform-agnostic gateway for the assistant.
    Routes messages from any platform through unified processing.
    """

    def __init__(self):
        self._adapters: Dict[Platform, "PlatformAdapter"] = {}

    def register_adapter(self, platform: Platform, adapter: "PlatformAdapter"):
        """Register platform-specific adapter"""
        self._adapters[platform] = adapter

    async def route_incoming(
        self,
        platform: Platform,
        raw_message: Any,
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Transform incoming message to standard format"""
        adapter = self._adapters.get(platform)
        if adapter:
            return await adapter.parse_incoming(raw_message, metadata)

        # Default passthrough
        return {
            "content": str(raw_message),
            "platform": platform,
            "metadata": metadata
        }

    async def route_outgoing(
        self,
        platform: Platform,
        response: str,
        metadata: Dict[str, Any]
    ) -> Any:
        """Transform response to platform-specific format"""
        adapter = self._adapters.get(platform)
        if adapter:
            return await adapter.format_outgoing(response, metadata)

        return response

gateway_router = GatewayRouter()
```

##### Task 4.5: Platform Adapters

```python
# backend/app/gateway/platform_adapters/web_adapter.py
from typing import Dict, Any
from abc import ABC, abstractmethod

class PlatformAdapter(ABC):
    @abstractmethod
    async def parse_incoming(self, raw: Any, metadata: Dict) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def format_outgoing(self, response: str, metadata: Dict) -> Any:
        pass

class WebAdapter(PlatformAdapter):
    """Adapter for web/React frontend"""

    async def parse_incoming(self, raw: Any, metadata: Dict) -> Dict[str, Any]:
        return {
            "content": raw.get("content", ""),
            "attachments": raw.get("attachments", []),
            "session_id": metadata.get("session_id"),
            "user_id": metadata.get("user_id")
        }

    async def format_outgoing(self, response: str, metadata: Dict) -> Any:
        return {
            "content": response,
            "format": "markdown",
            "timestamp": metadata.get("timestamp")
        }
```

```python
# backend/app/gateway/platform_adapters/desktop_adapter.py
class DesktopAdapter(PlatformAdapter):
    """Adapter for desktop agent"""

    async def parse_incoming(self, raw: Any, metadata: Dict) -> Dict[str, Any]:
        return {
            "content": raw.get("command", ""),
            "context": raw.get("screen_context"),
            "active_app": raw.get("active_app"),
            "session_id": metadata.get("session_id"),
            "user_id": metadata.get("user_id")
        }

    async def format_outgoing(self, response: str, metadata: Dict) -> Any:
        # Desktop might need structured commands
        return {
            "response": response,
            "actions": metadata.get("actions", []),
            "requires_confirmation": metadata.get("requires_confirmation", False)
        }
```

##### Task 4.6: Register Runtime in FastAPI

```python
# Modify: backend/app/main.py

from contextlib import asynccontextmanager
from app.runtime.assistant_runtime import assistant_runtime
from app.gateway.gateway_router import gateway_router, Platform
from app.gateway.platform_adapters.web_adapter import WebAdapter
from app.gateway.platform_adapters.desktop_adapter import DesktopAdapter

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await assistant_runtime.start()

    # Register platform adapters
    gateway_router.register_adapter(Platform.WEB, WebAdapter())
    gateway_router.register_adapter(Platform.DESKTOP, DesktopAdapter())

    yield

    # Shutdown
    await assistant_runtime.stop()

app = FastAPI(lifespan=lifespan)

# Add runtime status endpoint
@app.get("/runtime/status")
async def runtime_status():
    from app.runtime.runtime_state import runtime_state
    return runtime_state.get_status()
```

#### Risks

| Risk | Mitigation |
|------|------------|
| Runtime resource consumption | Resource limits, monitoring |
| Background task accumulation | Task TTL, max queue size |
| Platform adapter inconsistencies | Common test suite |

#### Expected Outcome

- Single runtime managing all assistant operations
- Multi-platform support through adapters
- Background task processing
- Health monitoring and metrics

---

## 3. Updated File Structure

```
backend/
├── app/
│   ├── main.py                          # FastAPI entry + runtime lifecycle
│   ├── api/
│   │   ├── routes/
│   │   │   ├── chat.py                  # HTTP fallback
│   │   │   └── websocket.py             # WebSocket endpoint [NEW]
│   │
│   ├── realtime/                        # [NEW DIRECTORY]
│   │   ├── __init__.py
│   │   ├── websocket_manager.py         # Connection management
│   │   ├── message_types.py             # Message schemas
│   │   ├── instant_responder.py         # ACK & thinking indicators
│   │   └── connection_pool.py           # Connection lifecycle
│   │
│   ├── session/                         # [NEW DIRECTORY]
│   │   ├── __init__.py
│   │   ├── session_manager.py           # Session lifecycle
│   │   ├── session_store.py             # Redis/Memory persistence
│   │   ├── session_models.py            # Session data structures
│   │   └── context_builder.py           # LLM context builder
│   │
│   ├── fastpath/                        # [NEW DIRECTORY]
│   │   ├── __init__.py
│   │   ├── fast_router.py               # Fast path routing
│   │   ├── simple_responder.py          # Quick responses
│   │   ├── intent_classifier.py         # Intent classification
│   │   └── response_cache.py            # Cached responses
│   │
│   ├── output/                          # [NEW DIRECTORY]
│   │   ├── __init__.py
│   │   ├── response_sanitizer.py        # Clean output
│   │   ├── stream_formatter.py          # Format streaming
│   │   └── error_humanizer.py           # Friendly errors
│   │
│   ├── runtime/                         # [NEW DIRECTORY]
│   │   ├── __init__.py
│   │   ├── assistant_runtime.py         # Main runtime
│   │   ├── task_queue.py                # Background tasks
│   │   ├── capability_registry.py       # What assistant can do
│   │   └── runtime_state.py             # Global state/metrics
│   │
│   ├── gateway/                         # [NEW DIRECTORY]
│   │   ├── __init__.py
│   │   ├── gateway_router.py            # Platform routing
│   │   ├── message_transformer.py       # Message transforms
│   │   └── platform_adapters/
│   │       ├── __init__.py
│   │       ├── web_adapter.py
│   │       ├── desktop_adapter.py
│   │       └── api_adapter.py
│   │
│   ├── agents/                          # EXISTING - Modified
│   │   ├── multi_agent_orchestrator.py  # Add session context + streaming
│   │   ├── router_agent.py
│   │   └── ...
│   │
│   ├── core/                            # EXISTING - Modified
│   │   ├── llm.py                       # Add streaming support
│   │   └── ...
│   │
│   └── services/                        # EXISTING - Unchanged
│       ├── memory_service.py
│       └── vector_memory_service.py

frontend/
├── src/
│   ├── services/
│   │   └── websocket.ts                 # [NEW] WebSocket service
│   │
│   ├── hooks/
│   │   ├── useAssistant.ts              # [NEW] Assistant hook
│   │   └── useStreaming.ts              # [NEW] Streaming hook
│   │
│   ├── components/
│   │   ├── ChatMessage.tsx              # Modified - streaming support
│   │   ├── ThinkingIndicator.tsx        # [NEW] Thinking states
│   │   └── StreamingText.tsx            # [NEW] Streaming display
│   │
│   └── store/
│       └── assistantStore.ts            # [NEW] Session state
```

---

## 4. Integration with Existing System

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                    INTEGRATION ARCHITECTURE                         │
└─────────────────────────────────────────────────────────────────────┘

User Request
     │
     ▼
┌─────────────────┐      ┌─────────────────┐
│ WebSocket       │ ───▶ │ Gateway Router  │
│ Manager         │      │ (Platform adapt)│
└─────────────────┘      └────────┬────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      ASSISTANT RUNTIME                              │
│  ┌─────────────┐   ┌─────────────┐   ┌────────────────────────┐   │
│  │ Session     │   │ Fast Path   │   │ Instant Responder      │   │
│  │ Manager     │   │ Router      │   │ (ACK + Thinking)       │   │
│  └──────┬──────┘   └──────┬──────┘   └────────────────────────┘   │
│         │                 │                                        │
│    Session Context   Fast/Full Decision                            │
│         │                 │                                        │
│         └────────┬────────┘                                        │
│                  │                                                 │
│                  ▼                                                 │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │                 EXISTING ORCHESTRATOR                        │  │
│  │  ┌─────────────────────────────────────────────────────┐    │  │
│  │  │               TaskExecutor                           │    │  │
│  │  │    ┌────────────────────────────────────────────┐   │    │  │
│  │  │    │            SafeExecutor                     │   │    │  │
│  │  │    │  ┌─────────────────────────────────────┐   │   │    │  │
│  │  │    │  │ Router Agent → Specialist Agents    │   │   │    │  │
│  │  │    │  │  • Code Specialist                  │   │   │    │  │
│  │  │    │  │  • Desktop Specialist               │   │   │    │  │
│  │  │    │  │  • General Assistant                │   │   │    │  │
│  │  │    │  └─────────────────────────────────────┘   │   │    │  │
│  │  │    └────────────────────────────────────────────┘   │    │  │
│  │  └─────────────────────────────────────────────────────┘    │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                    │
│                  │                                                 │
│                  ▼                                                 │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │              Response Sanitizer                              │  │
│  └─────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        STREAMING OUTPUT                             │
│   WebSocket ──▶ StreamChunk ──▶ Frontend ──▶ User sees live text   │
└─────────────────────────────────────────────────────────────────────┘
```

### Connection Points

| New Component | Connects To | How |
|---------------|-------------|-----|
| `AssistantRuntime` | `MultiAgentOrchestrator` | Calls `orchestrator.process_message()` with session context and stream callback |
| `SessionManager` | `MemoryService` | Can optionally persist sessions to SQL for durability |
| `FastRouter` | `RouterAgent` | Bypasses router for simple queries; delegates complex ones |
| `InstantResponder` | `WebSocketManager` | Sends ACK/thinking/streaming through WS connection |
| `ResponseSanitizer` | `SafeExecutor` | Cleans output after SafeExecutor validation |
| `GatewayRouter` | `DesktopAgent` | Desktop adapter translates commands for existing desktop agent |

### Minimal Changes to Existing Code

```python
# backend/app/agents/multi_agent_orchestrator.py
# ONLY these additions needed:

class MultiAgentOrchestrator:
    async def process_message(
        self,
        message: str,
        user_id: str,
        session_id: str = None,           # NEW: Optional session
        stream_callback: callable = None   # NEW: Optional streaming
    ):
        # Existing routing logic unchanged

        # NEW: If streaming callback provided, use it
        if stream_callback:
            async for chunk in self._stream_response(result):
                await stream_callback(chunk)

        return result
```

---

## 5. Before vs After User Flow

### BEFORE: Current Experience

```
┌─────────────────────────────────────────────────────────────────────┐
│ STEP 1: User types "Help me write a Python function"               │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (hits send)
┌─────────────────────────────────────────────────────────────────────┐
│ STEP 2: Screen shows loading spinner...                            │
│         User waits 3-5 seconds with NO feedback                    │
│         User wonders "Did it work? Is it stuck?"                   │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (after 5-10 seconds)
┌─────────────────────────────────────────────────────────────────────┐
│ STEP 3: ENTIRE response appears at once                            │
│         "Here's a Python function that... [500 word response]"     │
│         User sees everything or nothing                            │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ STEP 4: User refreshes page → conversation GONE                    │
│         "Where was I? What did we discuss?"                        │
│         Starts over from scratch                                   │
└─────────────────────────────────────────────────────────────────────┘

PROBLEMS:
✗ No immediate feedback
✗ No visibility into processing
✗ All-or-nothing response
✗ Lost context on refresh
✗ Feels like "submitting a form"
```

### AFTER: Upgraded Experience

```
┌─────────────────────────────────────────────────────────────────────┐
│ STEP 1: User types "Help me write a Python function"               │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (hits send)
┌─────────────────────────────────────────────────────────────────────┐
│ STEP 2: INSTANT (50ms) "Got it! Working on your request..."       │
│         User sees acknowledgment immediately                       │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (100ms later)
┌─────────────────────────────────────────────────────────────────────┐
│ STEP 3: Thinking indicator: "Understanding your request..."        │
│         Then: "Planning the best approach..."                      │
│         Then: "Generating response..."                             │
│         User sees PROGRESS, feels assistant is working             │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (500ms later)
┌─────────────────────────────────────────────────────────────────────┐
│ STEP 4: Response STREAMS in live:                                  │
│         "Here's" ... "a Python" ... "function that" ...            │
│         User reads AS IT'S GENERATED (like ChatGPT)                │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ STEP 5: User refreshes page → conversation RESTORED                │
│         "Welcome back! Here's where we left off..."                │
│         Session context preserved                                  │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ STEP 6: Later... "Hey" → INSTANT: "Hey! What can I help with?"    │
│         Simple queries answered in <200ms via fast path            │
│         No waiting for full orchestration                          │
└─────────────────────────────────────────────────────────────────────┘

EXPERIENCE:
✓ Instant acknowledgment
✓ Visible progress stages
✓ Live streaming response
✓ Session persistence
✓ Fast path for simple queries
✓ Feels like ChatGPT/Claude
```

---

## 6. Implementation Roadmap

### Summary Table

| Phase | Week | Goal | Key Files | Risk Level |
|-------|------|------|-----------|------------|
| **1** | 1 | WebSocket + Instant Response | `realtime/*`, `websocket.py` | Low |
| **2** | 2 | Session Management | `session/*` | Low |
| **3** | 3 | Fast Path + Streaming | `fastpath/*`, `output/*` | Medium |
| **4** | 4 | Runtime + Gateway | `runtime/*`, `gateway/*` | Medium |

### Quick Start Commands

```bash
# Create directory structure
mkdir -p backend/app/{realtime,session,fastpath,output,runtime,gateway/platform_adapters}

# Create __init__.py files
touch backend/app/{realtime,session,fastpath,output,runtime,gateway}/__init__.py
touch backend/app/gateway/platform_adapters/__init__.py

# Start with Phase 1
# Copy message_types.py, websocket_manager.py, instant_responder.py
```

### Success Metrics

| Metric | Before | After | Target |
|--------|--------|-------|--------|
| Time to first feedback | 3-10s | <100ms | ✓ |
| Simple query response | 3-5s | <500ms | ✓ |
| Complex query first token | 5-10s | <1s | ✓ |
| Session persistence | None | Full | ✓ |
| Error messages | Technical | Friendly | ✓ |

---

## Appendix: Frontend React Hooks

### useAssistant Hook

```typescript
// frontend/src/hooks/useAssistant.ts
import { useState, useEffect, useCallback, useRef } from 'react';
import { AssistantWebSocket } from '../services/websocket';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  status: 'sending' | 'streaming' | 'complete' | 'error';
  timestamp: Date;
}

interface UseAssistantOptions {
  sessionId: string;
  onError?: (error: Error) => void;
}

export function useAssistant({ sessionId, onError }: UseAssistantOptions) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const [thinkingStage, setThinkingStage] = useState<string | null>(null);
  const wsRef = useRef<AssistantWebSocket | null>(null);
  const streamingMessageRef = useRef<string>('');

  useEffect(() => {
    const ws = new AssistantWebSocket({
      url: process.env.REACT_APP_WS_URL || 'ws://localhost:8000',
      sessionId,
      onStateChange: (state) => {
        setIsConnected(state === 'connected');
      },
      onMessage: (message) => {
        handleMessage(message);
      }
    });

    ws.connect();
    wsRef.current = ws;

    return () => {
      ws.disconnect();
    };
  }, [sessionId]);

  const handleMessage = useCallback((message: any) => {
    switch (message.type) {
      case 'ack':
        setIsThinking(true);
        setThinkingStage('received');
        break;

      case 'thinking':
        setThinkingStage(message.stage);
        break;

      case 'stream_start':
        streamingMessageRef.current = '';
        setMessages(prev => [...prev, {
          id: message.request_id,
          role: 'assistant',
          content: '',
          status: 'streaming',
          timestamp: new Date()
        }]);
        break;

      case 'stream_chunk':
        streamingMessageRef.current += message.content;
        setMessages(prev => prev.map(m =>
          m.id === message.request_id
            ? { ...m, content: streamingMessageRef.current }
            : m
        ));
        break;

      case 'stream_end':
        setIsThinking(false);
        setThinkingStage(null);
        setMessages(prev => prev.map(m =>
          m.id === message.request_id
            ? { ...m, status: 'complete' }
            : m
        ));
        break;

      case 'error':
        setIsThinking(false);
        setThinkingStage(null);
        onError?.(new Error(message.user_message));
        break;
    }
  }, [onError]);

  const sendMessage = useCallback((content: string) => {
    if (!wsRef.current || !isConnected) return;

    const id = wsRef.current.sendMessage(content);

    setMessages(prev => [...prev, {
      id,
      role: 'user',
      content,
      status: 'sending',
      timestamp: new Date()
    }]);
  }, [isConnected]);

  return {
    messages,
    sendMessage,
    isConnected,
    isThinking,
    thinkingStage
  };
}
```

### ThinkingIndicator Component

```tsx
// frontend/src/components/ThinkingIndicator.tsx
import React from 'react';

interface ThinkingIndicatorProps {
  stage: string | null;
}

const stageMessages: Record<string, string> = {
  received: 'Got it...',
  understanding: 'Understanding your request...',
  classifying: 'Analyzing...',
  planning: 'Planning the best approach...',
  routing: 'Finding the right expert...',
  executing: 'Working on it...',
  generating: 'Generating response...'
};

export function ThinkingIndicator({ stage }: ThinkingIndicatorProps) {
  if (!stage) return null;

  return (
    <div className="thinking-indicator">
      <div className="thinking-dots">
        <span></span>
        <span></span>
        <span></span>
      </div>
      <span className="thinking-text">
        {stageMessages[stage] || 'Thinking...'}
      </span>
    </div>
  );
}
```

---

## Notes

- This plan is designed for **incremental adoption** — each phase can be deployed independently
- **Zero breaking changes** to existing functionality
- **Backward compatible** — HTTP fallback remains available
- Test each phase thoroughly before moving to the next
- Monitor metrics after each deployment

---

*Last Updated: 2026-03-19*
