"""
Session Store — manages active WebSocket sessions
"""
from __future__ import annotations
import time
from typing import Any, Dict, Optional
from loguru import logger


class Session:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.created_at = time.time()
        self.last_active = time.time()
        self.data: Dict[str, Any] = {}

    def touch(self):
        self.last_active = time.time()


class SessionStore:
    def __init__(self):
        self._sessions: Dict[str, Session] = {}
        logger.info("SessionStore initialized")

    def create(self, session_id: str) -> Session:
        session = Session(session_id)
        self._sessions[session_id] = session
        logger.info(f"Session created: {session_id}")
        return session

    def get(self, session_id: str) -> Optional[Session]:
        session = self._sessions.get(session_id)
        if session:
            session.touch()
        return session

    def remove(self, session_id: str):
        self._sessions.pop(session_id, None)
        logger.info(f"Session removed: {session_id}")

    def list_sessions(self) -> list[str]:
        return list(self._sessions.keys())
