"""
Clarification service for ambiguous planner-executor steps.

Stores pending clarification prompts in memory so a follow-up chat reply can
resume the paused task instead of being treated like a brand-new request.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import re
from typing import Any, Dict, List, Optional
import uuid

from loguru import logger


@dataclass
class PendingClarification:
    clarification_id: str
    user_id: str
    conversation_id: str
    user_message: str
    question: str
    options: List[Dict[str, Any]]
    channel: str
    task_type: str = "desktop"
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_at: Optional[str] = None
    selected_option: Optional[Dict[str, Any]] = None


class ClarificationService:
    """In-memory clarification registry for paused orchestrations."""

    def __init__(self) -> None:
        self._pending: Dict[str, PendingClarification] = {}

    def create_request(
        self,
        *,
        user_id: str,
        conversation_id: str,
        user_message: str,
        question: str,
        options: List[Dict[str, Any]],
        channel: str,
        task_type: str = "desktop",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PendingClarification:
        clarification = PendingClarification(
            clarification_id=str(uuid.uuid4()),
            user_id=user_id,
            conversation_id=conversation_id,
            user_message=user_message,
            question=question,
            options=options,
            channel=channel,
            task_type=task_type,
            metadata=metadata or {},
        )
        self._pending[clarification.clarification_id] = clarification
        logger.info(
            f"Created clarification request {clarification.clarification_id} for {user_id}"
        )
        return clarification

    def get_request(self, clarification_id: str) -> Optional[PendingClarification]:
        return self._pending.get(clarification_id)

    def get_pending_request(
        self,
        *,
        user_id: str,
        conversation_id: str,
    ) -> Optional[PendingClarification]:
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

    def parse_response(
        self,
        clarification: PendingClarification,
        response_text: str,
    ) -> Optional[Dict[str, Any]]:
        answer = (response_text or "").strip()
        if not answer:
            return None

        number_match = re.match(r"^\s*(\d+)\b", answer)
        if number_match:
            index = int(number_match.group(1))
            if 1 <= index <= len(clarification.options):
                return clarification.options[index - 1]

        normalized_answer = self._normalize_option_value(answer)
        for option in clarification.options:
            candidates = [
                option.get("value", ""),
                option.get("label", ""),
                option.get("path", ""),
            ]
            if any(
                normalized_answer
                and normalized_answer == self._normalize_option_value(str(candidate))
                for candidate in candidates
                if candidate
            ):
                return option
        return None

    def resolve(
        self,
        clarification_id: str,
        *,
        selected_option: Optional[Dict[str, Any]] = None,
    ) -> Optional[PendingClarification]:
        clarification = self._pending.get(clarification_id)
        if not clarification:
            return None
        clarification.status = "resolved" if selected_option else "cancelled"
        clarification.resolved_at = datetime.now(timezone.utc).isoformat()
        clarification.selected_option = selected_option
        logger.info(
            f"Resolved clarification {clarification_id}: {clarification.status}"
        )
        return clarification

    def remove(self, clarification_id: str) -> None:
        self._pending.pop(clarification_id, None)

    def _normalize_option_value(self, value: str) -> str:
        candidate = (value or "").strip().strip('"').strip("'")
        if not candidate:
            return ""
        if os.path.isabs(candidate) or ":" in candidate or "\\" in candidate or "/" in candidate:
            return os.path.normcase(os.path.normpath(candidate))
        return candidate.casefold()


clarification_service = ClarificationService()
