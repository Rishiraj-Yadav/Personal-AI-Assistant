"""Request Lifecycle Controller - Phase 2"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional, Set
from loguru import logger
import uuid

class RequestStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    STREAMING = "streaming"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REPLACED = "replaced"
    TIMEOUT = "timeout"
    ERROR = "error"

@dataclass
class ActiveRequest:
    request_id: str
    user_id: str
    conversation_id: str
    message: str
    status: RequestStatus = RequestStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    is_cancelled: bool = False
    progress: float = 0.0
    current_step: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

class RequestLifecycleController:
    def __init__(self, default_timeout_seconds: int = 120, allow_concurrent: bool = False):
        self.default_timeout = default_timeout_seconds
        self.allow_concurrent = allow_concurrent
        self._requests: Dict[str, ActiveRequest] = {}
        self._user_requests: Dict[str, Set[str]] = {}
        self._conversation_requests: Dict[str, str] = {}
        self._lock = asyncio.Lock()
        logger.info(f"RequestLifecycleController initialized: timeout={default_timeout_seconds}s, concurrent={allow_concurrent}")

    def generate_request_id(self) -> str:
        return f"req_{uuid.uuid4().hex[:12]}"

    async def create_request(self, user_id: str, conversation_id: str, message: str, metadata: Optional[Dict[str, Any]] = None, replace_existing: bool = True) -> ActiveRequest:
        request_id = self.generate_request_id()
        async with self._lock:
            existing_id = self._conversation_requests.get(conversation_id)
            if existing_id and existing_id in self._requests:
                existing = self._requests[existing_id]
                if existing.status in (RequestStatus.RUNNING, RequestStatus.STREAMING):
                    if replace_existing:
                        await self._cancel_request_internal(existing_id, status=RequestStatus.REPLACED, reason="Replaced by new request")
                        logger.info(f"Replaced existing request {existing_id} with {request_id}")
                    elif not self.allow_concurrent:
                        raise RuntimeError(f"Request {existing_id} is already running in this conversation")
            request = ActiveRequest(request_id=request_id, user_id=user_id, conversation_id=conversation_id, message=message, metadata=metadata or {})
            self._requests[request_id] = request
            self._conversation_requests[conversation_id] = request_id
            if user_id not in self._user_requests:
                self._user_requests[user_id] = set()
            self._user_requests[user_id].add(request_id)
            logger.debug(f"Created request {request_id} for user {user_id}")
            return request

    async def start_request(self, request_id: str) -> bool:
        async with self._lock:
            if request_id not in self._requests:
                return False
            request = self._requests[request_id]
            request.status = RequestStatus.RUNNING
            request.started_at = datetime.now(timezone.utc)
            return True

    async def update_progress(self, request_id: str, progress: float, current_step: Optional[str] = None) -> bool:
        if request_id not in self._requests:
            return False
        request = self._requests[request_id]
        request.progress = min(1.0, max(0.0, progress))
        if current_step:
            request.current_step = current_step
        return True

    async def set_streaming(self, request_id: str) -> bool:
        if request_id not in self._requests:
            return False
        request = self._requests[request_id]
        request.status = RequestStatus.STREAMING
        return True

    async def complete_request(self, request_id: str, result: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> Optional[ActiveRequest]:
        async with self._lock:
            if request_id not in self._requests:
                return None
            request = self._requests[request_id]
            request.completed_at = datetime.now(timezone.utc)
            request.progress = 1.0
            if error:
                request.status = RequestStatus.ERROR
                request.error = error
            else:
                request.status = RequestStatus.COMPLETED
                request.result = result
            await self._cleanup_request_internal(request_id)
            return request

    async def cancel_request(self, request_id: str, reason: str = "User cancelled") -> Optional[ActiveRequest]:
        async with self._lock:
            return await self._cancel_request_internal(request_id, status=RequestStatus.CANCELLED, reason=reason)

    async def _cancel_request_internal(self, request_id: str, status: RequestStatus, reason: str) -> Optional[ActiveRequest]:
        if request_id not in self._requests:
            return None
        request = self._requests[request_id]
        if request.status not in (RequestStatus.RUNNING, RequestStatus.STREAMING, RequestStatus.PENDING):
            return None
        request.status = status
        request.is_cancelled = True
        request.completed_at = datetime.now(timezone.utc)
        request.error = reason
        request.cancel_event.set()
        logger.info(f"Cancelled request {request_id}: {reason}")
        return request

    async def _cleanup_request_internal(self, request_id: str):
        if request_id not in self._requests:
            return
        request = self._requests[request_id]
        if self._conversation_requests.get(request.conversation_id) == request_id:
            del self._conversation_requests[request.conversation_id]
        if request.user_id in self._user_requests:
            self._user_requests[request.user_id].discard(request_id)
            if not self._user_requests[request.user_id]:
                del self._user_requests[request.user_id]

    def get_request(self, request_id: str) -> Optional[ActiveRequest]:
        return self._requests.get(request_id)

    def is_cancelled(self, request_id: str) -> bool:
        request = self._requests.get(request_id)
        if not request:
            return False
        return request.is_cancelled

    def has_active_request(self, conversation_id: str) -> bool:
        request_id = self._conversation_requests.get(conversation_id)
        if not request_id:
            return False
        request = self._requests.get(request_id)
        if not request:
            return False
        return request.status in (RequestStatus.RUNNING, RequestStatus.STREAMING, RequestStatus.PENDING)

    async def get_stats(self) -> Dict[str, Any]:
        status_counts = {}
        for request in self._requests.values():
            status_counts[request.status.value] = status_counts.get(request.status.value, 0) + 1
        return {"total_requests": len(self._requests), "active_conversations": len(self._conversation_requests), "active_users": len(self._user_requests), "status_counts": status_counts, "allow_concurrent": self.allow_concurrent, "default_timeout": self.default_timeout}

class CancellableStream:
    def __init__(self, request_id: str, lifecycle: RequestLifecycleController, generator):
        self.request_id = request_id
        self.lifecycle = lifecycle
        self.generator = generator

    async def __aiter__(self):
        return self

    async def __anext__(self):
        if self.lifecycle.is_cancelled(self.request_id):
            raise asyncio.CancelledError(f"Request {self.request_id} was cancelled")
        return await self.generator.__anext__()

request_lifecycle = RequestLifecycleController()
