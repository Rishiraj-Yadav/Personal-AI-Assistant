"""
Context Memory — Tiered scoped memory for multi-agent pipelines.

Tier 1: Step Context (ephemeral, scoped to dependencies)
Tier 2: Session Memory (conversation-scoped, token-pruned)
Tier 3: Persistent Memory (cross-session, SQLite)
"""

import json
import sqlite3
import os
from typing import Dict, Any, List, Optional, Set
from datetime import datetime
from loguru import logger


class ContextMemory:
    """
    Manages context passing between agents in a pipeline.
    Prevents token explosion by scoping what each step sees.
    """

    MAX_CONTEXT_TOKENS = 2000  # Approximate token budget per step
    PERSISTENT_DB = os.path.join(
        os.path.dirname(__file__), "..", "..", "logs", "memory.db"
    )

    def __init__(self, pipeline_id: str):
        self.pipeline_id = pipeline_id
        self.step_context: Dict[str, Dict[str, Any]] = {}   # Tier 1
        self.session_context: Dict[str, Any] = {}            # Tier 2
        self._init_persistent_db()                           # Tier 3
        logger.debug(f"ContextMemory created for pipeline {pipeline_id}")

    # ════════════════════════════════════════════════════════
    # Tier 1 — Step Context (scoped, ephemeral)
    # ════════════════════════════════════════════════════════

    def store_step_output(self, step_id: str, outputs: Dict[str, Any]):
        """Store outputs from a completed step."""
        self.step_context[step_id] = outputs
        logger.debug(f"Stored step context: {step_id} → {list(outputs.keys())}")

    def get_scoped(self, context_keys: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Get only the context keys that a step declares it needs.
        If context_keys is None, returns nothing (zero exposure).
        """
        if not context_keys:
            return {}

        result = {}
        # Search across all step outputs for the requested keys
        for step_outputs in self.step_context.values():
            for key in context_keys:
                if key in step_outputs and key not in result:
                    result[key] = step_outputs[key]

        # Also check session context
        for key in context_keys:
            if key in self.session_context and key not in result:
                result[key] = self.session_context[key]

        return result

    def get_step_output(self, step_id: str) -> Dict[str, Any]:
        """Get all outputs from a specific step."""
        return self.step_context.get(step_id, {})

    # ════════════════════════════════════════════════════════
    # Tier 2 — Session Memory (conversation-scoped)
    # ════════════════════════════════════════════════════════

    def set_session(self, key: str, value: Any):
        """Store a session-level value (persists across pipeline)."""
        self.session_context[key] = value
        self._prune_session_if_needed()

    def get_session(self, key: str, default: Any = None) -> Any:
        """Get a session-level value."""
        return self.session_context.get(key, default)

    def update_session(self, data: Dict[str, Any]):
        """Bulk update session context."""
        self.session_context.update(data)
        self._prune_session_if_needed()

    def _prune_session_if_needed(self):
        """Drop oldest non-critical entries when over token budget."""
        serialized = json.dumps(self.session_context)
        approx_tokens = len(serialized) // 4  # rough token estimate

        if approx_tokens > self.MAX_CONTEXT_TOKENS:
            keys = list(self.session_context.keys())
            # Keep the last N entries that fit
            while approx_tokens > self.MAX_CONTEXT_TOKENS and keys:
                oldest_key = keys.pop(0)
                del self.session_context[oldest_key]
                serialized = json.dumps(self.session_context)
                approx_tokens = len(serialized) // 4

            logger.info(
                f"Pruned session context to ~{approx_tokens} tokens "
                f"({len(self.session_context)} entries)"
            )

    # ════════════════════════════════════════════════════════
    # Tier 3 — Persistent Memory (cross-session, SQLite)
    # ════════════════════════════════════════════════════════

    def _init_persistent_db(self):
        """Initialize SQLite for persistent memory."""
        os.makedirs(os.path.dirname(self.PERSISTENT_DB), exist_ok=True)
        try:
            db = sqlite3.connect(self.PERSISTENT_DB)
            db.execute("""
                CREATE TABLE IF NOT EXISTS persistent_memory (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            db.commit()
            db.close()
        except Exception as e:
            logger.warning(f"Could not init persistent DB: {e}")

    def store_persistent(self, key: str, value: Any):
        """Store a value that persists across sessions."""
        try:
            db = sqlite3.connect(self.PERSISTENT_DB)
            db.execute(
                """INSERT OR REPLACE INTO persistent_memory (key, value, updated_at)
                   VALUES (?, ?, ?)""",
                (key, json.dumps(value), datetime.now().isoformat()),
            )
            db.commit()
            db.close()
        except Exception as e:
            logger.warning(f"Persistent store failed: {e}")

    def get_persistent(self, key: str, default: Any = None) -> Any:
        """Retrieve a persistent value."""
        try:
            db = sqlite3.connect(self.PERSISTENT_DB)
            row = db.execute(
                "SELECT value FROM persistent_memory WHERE key = ?", (key,)
            ).fetchone()
            db.close()
            return json.loads(row[0]) if row else default
        except Exception as e:
            logger.warning(f"Persistent read failed: {e}")
            return default

    # ════════════════════════════════════════════════════════
    # Utility
    # ════════════════════════════════════════════════════════

    def get_full_snapshot(self) -> Dict[str, Any]:
        """Debug: get complete memory state."""
        return {
            "pipeline_id": self.pipeline_id,
            "step_context": self.step_context,
            "session_context": self.session_context,
        }

    def clear(self):
        """Clear ephemeral memory (Tier 1 + 2). Persistent untouched."""
        self.step_context.clear()
        self.session_context.clear()
