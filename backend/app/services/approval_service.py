"""
Approval service for guarded planner-executor actions.

Stores pending approvals in memory so Web UI and Telegram can resume
guarded tasks after the user explicitly approves them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid

from loguru import logger


@dataclass
class PendingApproval:
    approval_id: str
    user_id: str
    conversation_id: str
    user_message: str
    reason: str
    channel: str
    affected_steps: list[str] = field(default_factory=list)
    task_type: str = "general"
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class ApprovalService:
    """In-memory approval registry for paused orchestrations."""

    def __init__(self) -> None:
        self._pending: Dict[str, PendingApproval] = {}

    def create_request(
        self,
        *,
        user_id: str,
        conversation_id: str,
        user_message: str,
        reason: str,
        channel: str,
        affected_steps: Optional[list[str]] = None,
        task_type: str = "general",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PendingApproval:
        approval = PendingApproval(
            approval_id=str(uuid.uuid4()),
            user_id=user_id,
            conversation_id=conversation_id,
            user_message=user_message,
            reason=reason,
            channel=channel,
            affected_steps=affected_steps or [],
            task_type=task_type,
            metadata=metadata or {},
        )
        self._pending[approval.approval_id] = approval
        logger.info(f"🔐 Created approval request {approval.approval_id} for {user_id}")
        return approval

    def get_request(self, approval_id: str) -> Optional[PendingApproval]:
        return self._pending.get(approval_id)

    def resolve(
        self,
        approval_id: str,
        approved: bool,
        result: Optional[Dict[str, Any]] = None,
    ) -> Optional[PendingApproval]:
        approval = self._pending.get(approval_id)
        if not approval:
            return None
        approval.status = "approved" if approved else "denied"
        approval.resolved_at = datetime.now(timezone.utc).isoformat()
        approval.result = result
        logger.info(f"🔐 Resolved approval {approval_id}: {approval.status}")
        return approval

    def remove(self, approval_id: str) -> None:
        self._pending.pop(approval_id, None)


approval_service = ApprovalService()
