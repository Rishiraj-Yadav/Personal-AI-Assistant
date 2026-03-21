"""
Browser input service for paused live-browser workflows.

Stores pending browser user-input requests in memory so follow-up messages
from the same channel/user/conversation can resume the Desktop Agent browser
session instead of being routed like brand-new tasks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid

from loguru import logger


@dataclass
class PendingBrowserInput:
    browser_input_id: str
    desktop_request_id: str
    user_id: str
    conversation_id: str
    channel: str
    field_description: str
    input_type: str
    reason: str
    task_type: str = "web_autonomous"
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class BrowserInputService:
    """In-memory browser-input registry for paused live-browser tasks."""

    def __init__(self) -> None:
        self._pending: Dict[str, PendingBrowserInput] = {}

    def create_request(
        self,
        *,
        desktop_request_id: str,
        user_id: str,
        conversation_id: str,
        channel: str,
        field_description: str,
        input_type: str,
        reason: str,
        task_type: str = "web_autonomous",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PendingBrowserInput:
        existing = self.get_pending_request(user_id=user_id, conversation_id=conversation_id)
        if existing:
            self.resolve(existing.browser_input_id, status="replaced")
            self.remove(existing.browser_input_id)

        pending = PendingBrowserInput(
            browser_input_id=str(uuid.uuid4()),
            desktop_request_id=desktop_request_id,
            user_id=user_id,
            conversation_id=conversation_id,
            channel=channel,
            field_description=field_description,
            input_type=input_type,
            reason=reason,
            task_type=task_type,
            metadata=metadata or {},
        )
        self._pending[pending.browser_input_id] = pending
        logger.info(
            f"Created browser input request {pending.browser_input_id} for "
            f"{pending.user_id}/{pending.conversation_id}"
        )
        return pending

    def get_request(self, browser_input_id: str) -> Optional[PendingBrowserInput]:
        return self._pending.get(browser_input_id)

    def get_pending_request(
        self,
        *,
        user_id: str,
        conversation_id: str,
    ) -> Optional[PendingBrowserInput]:
        matches = [
            item
            for item in self._pending.values()
            if item.user_id == user_id
            and item.conversation_id == conversation_id
            and item.status == "pending"
        ]
        if not matches:
            return None
        matches.sort(key=lambda item: item.created_at)
        return matches[-1]

    def resolve(
        self,
        browser_input_id: str,
        *,
        result: Optional[Dict[str, Any]] = None,
        status: str = "resolved",
    ) -> Optional[PendingBrowserInput]:
        pending = self._pending.get(browser_input_id)
        if not pending:
            return None
        pending.status = status
        pending.resolved_at = datetime.now(timezone.utc).isoformat()
        pending.result = result
        logger.info(f"Resolved browser input {browser_input_id}: {status}")
        return pending

    def remove(self, browser_input_id: str) -> None:
        self._pending.pop(browser_input_id, None)


browser_input_service = BrowserInputService()
