"""Session Manager - Phase 2"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from collections import OrderedDict
from loguru import logger

@dataclass
class SessionMessage:
    role: str
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ActiveTask:
    task_id: str
    task_type: str
    status: str = "pending"
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    agent_path: List[str] = field(default_factory=list)
    current_step: Optional[str] = None
    progress: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class SessionState:
    user_id: str
    conversation_id: str
    messages: List[SessionMessage] = field(default_factory=list)
    active_task: Optional[ActiveTask] = None
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    current_file: Optional[str] = None
    current_app: Optional[str] = None
    last_action: Optional[str] = None
    preferences: Dict[str, Any] = field(default_factory=dict)
    tokens_used: int = 0
    request_count: int = 0

class SessionManager:
    def __init__(self, max_messages_per_session: int = 20, session_ttl_minutes: int = 60, max_sessions: int = 1000):
        self.max_messages = max_messages_per_session
        self.session_ttl = session_ttl_minutes * 60
        self.max_sessions = max_sessions
        self._sessions: OrderedDict[str, SessionState] = OrderedDict()
        self._locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        logger.info(f"SessionManager initialized: max_messages={max_messages_per_session}, ttl={session_ttl_minutes}min, max_sessions={max_sessions}")

    def _session_key(self, user_id: str, conversation_id: str) -> str:
        return f"{user_id}:{conversation_id}"

    async def _get_lock(self, session_key: str) -> asyncio.Lock:
        async with self._global_lock:
            if session_key not in self._locks:
                self._locks[session_key] = asyncio.Lock()
            return self._locks[session_key]

    async def get_or_create_session(self, user_id: str, conversation_id: str) -> SessionState:
        session_key = self._session_key(user_id, conversation_id)
        lock = await self._get_lock(session_key)
        async with lock:
            if session_key in self._sessions:
                self._sessions.move_to_end(session_key)
                session = self._sessions[session_key]
                session.last_activity = datetime.now(timezone.utc)
                return session
            session = SessionState(user_id=user_id, conversation_id=conversation_id)
            async with self._global_lock:
                while len(self._sessions) >= self.max_sessions:
                    oldest_key, _ = self._sessions.popitem(last=False)
                    self._locks.pop(oldest_key, None)
                self._sessions[session_key] = session
            logger.info(f"Created new session: {session_key}")
            return session

    async def add_message(self, user_id: str, conversation_id: str, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> SessionMessage:
        session = await self.get_or_create_session(user_id, conversation_id)
        session_key = self._session_key(user_id, conversation_id)
        lock = await self._get_lock(session_key)
        async with lock:
            message = SessionMessage(role=role, content=content, metadata=metadata or {})
            session.messages.append(message)
            if len(session.messages) > self.max_messages:
                session.messages = session.messages[-self.max_messages:]
            session.last_activity = datetime.now(timezone.utc)
            session.request_count += 1
            return message

    async def get_recent_messages(self, user_id: str, conversation_id: str, limit: Optional[int] = None) -> List[SessionMessage]:
        session_key = self._session_key(user_id, conversation_id)
        if session_key not in self._sessions:
            return []
        session = self._sessions[session_key]
        messages = session.messages
        if limit and limit < len(messages):
            return messages[-limit:]
        return messages.copy()

    async def set_active_task(self, user_id: str, conversation_id: str, task_id: str, task_type: str, metadata: Optional[Dict[str, Any]] = None) -> ActiveTask:
        session = await self.get_or_create_session(user_id, conversation_id)
        session_key = self._session_key(user_id, conversation_id)
        lock = await self._get_lock(session_key)
        async with lock:
            task = ActiveTask(task_id=task_id, task_type=task_type, status="running", metadata=metadata or {})
            session.active_task = task
            logger.debug(f"Set active task: {task_id} ({task_type})")
            return task

    async def update_task_progress(self, user_id: str, conversation_id: str, progress: float, current_step: Optional[str] = None, agent_path: Optional[List[str]] = None) -> bool:
        session_key = self._session_key(user_id, conversation_id)
        if session_key not in self._sessions:
            return False
        session = self._sessions[session_key]
        lock = await self._get_lock(session_key)
        async with lock:
            if not session.active_task:
                return False
            session.active_task.progress = min(1.0, max(0.0, progress))
            if current_step:
                session.active_task.current_step = current_step
            if agent_path:
                session.active_task.agent_path = agent_path
            return True

    async def complete_task(self, user_id: str, conversation_id: str, status: str = "completed", result_metadata: Optional[Dict[str, Any]] = None) -> Optional[ActiveTask]:
        session_key = self._session_key(user_id, conversation_id)
        if session_key not in self._sessions:
            return None
        session = self._sessions[session_key]
        lock = await self._get_lock(session_key)
        async with lock:
            task = session.active_task
            if task:
                task.status = status
                task.progress = 1.0 if status == "completed" else task.progress
                if result_metadata:
                    task.metadata.update(result_metadata)
                session.active_task = None
                logger.debug(f"Task {task.task_id} completed with status: {status}")
            return task

    async def get_active_task(self, user_id: str, conversation_id: str) -> Optional[ActiveTask]:
        session_key = self._session_key(user_id, conversation_id)
        if session_key not in self._sessions:
            return None
        return self._sessions[session_key].active_task

    async def has_active_task(self, user_id: str, conversation_id: str) -> bool:
        task = await self.get_active_task(user_id, conversation_id)
        return task is not None and task.status == "running"

    async def get_session_context(self, user_id: str, conversation_id: str) -> Dict[str, Any]:
        session_key = self._session_key(user_id, conversation_id)
        if session_key not in self._sessions:
            return {}
        session = self._sessions[session_key]
        context = {"conversation_id": conversation_id, "message_count": len(session.messages), "request_count": session.request_count, "tokens_used": session.tokens_used}
        if session.messages:
            recent = session.messages[-5:]
            context["recent_messages"] = [{"role": m.role, "content": m.content[:200]} for m in recent]
        if session.current_file:
            context["current_file"] = session.current_file
        if session.current_app:
            context["current_app"] = session.current_app
        if session.last_action:
            context["last_action"] = session.last_action
        if session.active_task:
            context["active_task"] = {"task_id": session.active_task.task_id, "task_type": session.active_task.task_type, "status": session.active_task.status, "progress": session.active_task.progress, "current_step": session.active_task.current_step}
        return context

    async def build_context_string(self, user_id: str, conversation_id: str) -> str:
        context = await self.get_session_context(user_id, conversation_id)
        if not context:
            return ""
        parts = ["[Session Context]"]
        if context.get("current_file"):
            parts.append(f"Current File: {context['current_file']}")
        if context.get("current_app"):
            parts.append(f"Current App: {context['current_app']}")
        if context.get("last_action"):
            parts.append(f"Last Action: {context['last_action']}")
        if context.get("active_task"):
            task = context["active_task"]
            parts.append(f"Active Task: {task['task_type']} ({task['progress']*100:.0f}% - {task.get('current_step', 'in progress')})")
        if context.get("recent_messages"):
            parts.append(f"Conversation: {context['message_count']} messages this session")
        return "\n".join(parts)

    async def get_stats(self) -> Dict[str, Any]:
        active_tasks = sum(1 for s in self._sessions.values() if s.active_task and s.active_task.status == "running")
        return {"total_sessions": len(self._sessions), "active_tasks": active_tasks, "max_sessions": self.max_sessions, "max_messages_per_session": self.max_messages, "session_ttl_minutes": self.session_ttl // 60}

session_manager = SessionManager()
