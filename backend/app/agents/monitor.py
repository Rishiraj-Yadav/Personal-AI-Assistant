"""
Agent Monitor — Production observability for multi-agent pipeline execution.

Logs every decision, tracks costs, detects anomalies (deadlocks, infinite loops).
Uses SQLite for durable metrics storage.
"""

import os
import json
import sqlite3
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from loguru import logger


class AgentMonitor:
    """Full observability for multi-agent pipelines."""

    DB_PATH = os.path.join(
        os.path.dirname(__file__), "..", "..", "logs", "agent_metrics.db"
    )

    # Cost per 1M tokens (approximate, Gemini pricing)
    COST_PER_1M_INPUT = 0.075   # gemini-2.0-flash
    COST_PER_1M_OUTPUT = 0.30

    def __init__(self):
        os.makedirs(os.path.dirname(self.DB_PATH), exist_ok=True)
        self._init_tables()
        # In-memory tracking for active pipelines
        self._active_pipelines: Dict[str, Dict] = {}
        logger.info("📊 Agent Monitor initialized")

    def _init_tables(self):
        try:
            db = sqlite3.connect(self.DB_PATH)
            db.executescript("""
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    pipeline_id TEXT PRIMARY KEY,
                    user_message TEXT,
                    dag_json TEXT,
                    status TEXT DEFAULT 'running',
                    started_at TEXT,
                    ended_at TEXT,
                    total_duration_ms INTEGER,
                    total_tokens INTEGER DEFAULT 0,
                    total_cost_usd REAL DEFAULT 0.0,
                    steps_total INTEGER DEFAULT 0,
                    steps_succeeded INTEGER DEFAULT 0,
                    steps_failed INTEGER DEFAULT 0
                );
                
                CREATE TABLE IF NOT EXISTS step_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pipeline_id TEXT,
                    step_id TEXT,
                    agent TEXT,
                    action TEXT,
                    event_type TEXT,
                    attempt INTEGER DEFAULT 1,
                    status TEXT,
                    duration_ms INTEGER,
                    tokens_used INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0.0,
                    context_in TEXT,
                    context_out TEXT,
                    error TEXT,
                    timestamp TEXT,
                    FOREIGN KEY (pipeline_id) REFERENCES pipeline_runs(pipeline_id)
                );
                
                CREATE INDEX IF NOT EXISTS idx_step_pipeline
                    ON step_events(pipeline_id);
                CREATE INDEX IF NOT EXISTS idx_step_agent
                    ON step_events(agent);
            """)
            db.commit()
            db.close()
        except Exception as e:
            logger.error(f"Monitor DB init failed: {e}")

    # ════════════════════════════════════════════
    # Pipeline Lifecycle
    # ════════════════════════════════════════════

    def log_pipeline_start(
        self, pipeline_id: str, user_message: str, dag_json: str, steps_total: int
    ):
        now = datetime.now().isoformat()
        self._active_pipelines[pipeline_id] = {
            "started_at": time.time(),
            "last_activity": time.time(),
        }
        try:
            db = sqlite3.connect(self.DB_PATH)
            db.execute(
                """INSERT OR REPLACE INTO pipeline_runs
                   (pipeline_id, user_message, dag_json, status, started_at, steps_total)
                   VALUES (?, ?, ?, 'running', ?, ?)""",
                (pipeline_id, user_message, dag_json, now, steps_total),
            )
            db.commit()
            db.close()
        except Exception as e:
            logger.error(f"Monitor log_pipeline_start failed: {e}")

        logger.info(f"📊 Pipeline {pipeline_id} started ({steps_total} steps)")

    def log_pipeline_end(self, pipeline_id: str, success: bool):
        now = datetime.now().isoformat()
        started = self._active_pipelines.pop(pipeline_id, {}).get("started_at", 0)
        duration_ms = int((time.time() - started) * 1000) if started else 0
        status = "completed" if success else "failed"

        try:
            db = sqlite3.connect(self.DB_PATH)
            db.execute(
                """UPDATE pipeline_runs
                   SET status=?, ended_at=?, total_duration_ms=?
                   WHERE pipeline_id=?""",
                (status, now, duration_ms, pipeline_id),
            )
            db.commit()
            db.close()
        except Exception as e:
            logger.error(f"Monitor log_pipeline_end failed: {e}")

        logger.info(f"📊 Pipeline {pipeline_id} {status} ({duration_ms}ms)")

    # ════════════════════════════════════════════
    # Step Events
    # ════════════════════════════════════════════

    def log_step(
        self,
        pipeline_id: str,
        step_id: str,
        agent: str,
        action: str,
        event_type: str,
        attempt: int = 1,
        status: str = "running",
        duration_ms: int = 0,
        tokens_used: int = 0,
        context_in: Optional[Dict] = None,
        context_out: Optional[Dict] = None,
        error: Optional[str] = None,
    ):
        """Log any step event (start, success, error, timeout, retry, fallback)."""
        now = datetime.now().isoformat()
        cost = (tokens_used / 1_000_000) * self.COST_PER_1M_INPUT if tokens_used else 0

        # Update active pipeline timestamp
        if pipeline_id in self._active_pipelines:
            self._active_pipelines[pipeline_id]["last_activity"] = time.time()

        try:
            db = sqlite3.connect(self.DB_PATH)
            db.execute(
                """INSERT INTO step_events
                   (pipeline_id, step_id, agent, action, event_type, attempt,
                    status, duration_ms, tokens_used, cost_usd,
                    context_in, context_out, error, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    pipeline_id, step_id, agent, action, event_type, attempt,
                    status, duration_ms, tokens_used, cost,
                    json.dumps(context_in) if context_in else None,
                    json.dumps(context_out) if context_out else None,
                    error, now,
                ),
            )
            # Update pipeline aggregates
            if status == "success":
                db.execute(
                    """UPDATE pipeline_runs
                       SET steps_succeeded = steps_succeeded + 1,
                           total_tokens = total_tokens + ?,
                           total_cost_usd = total_cost_usd + ?
                       WHERE pipeline_id = ?""",
                    (tokens_used, cost, pipeline_id),
                )
            elif status in ("error", "timeout"):
                db.execute(
                    """UPDATE pipeline_runs
                       SET steps_failed = steps_failed + 1
                       WHERE pipeline_id = ?""",
                    (pipeline_id,),
                )
            db.commit()
            db.close()
        except Exception as e:
            logger.error(f"Monitor log_step failed: {e}")

        log_msg = f"📊 [{pipeline_id}] {agent}.{action} → {event_type} ({status})"
        if error:
            log_msg += f" error={error}"
        if duration_ms:
            log_msg += f" {duration_ms}ms"
        logger.info(log_msg)

    # ════════════════════════════════════════════
    # Alerts & Anomaly Detection
    # ════════════════════════════════════════════

    def check_deadlock(self, pipeline_id: str, max_idle_s: int = 60) -> bool:
        """Check if a pipeline has stalled (no activity for max_idle_s)."""
        info = self._active_pipelines.get(pipeline_id)
        if not info:
            return False
        idle_time = time.time() - info["last_activity"]
        if idle_time > max_idle_s:
            logger.warning(f"🚨 Deadlock detected: {pipeline_id} idle for {idle_time:.0f}s")
            return True
        return False

    def check_infinite_loop(
        self, pipeline_id: str, step_id: str, max_retries: int = 10
    ) -> bool:
        """Check if a step has retried too many times."""
        try:
            db = sqlite3.connect(self.DB_PATH)
            row = db.execute(
                """SELECT COUNT(*) FROM step_events
                   WHERE pipeline_id=? AND step_id=? AND event_type='retry'""",
                (pipeline_id, step_id),
            ).fetchone()
            db.close()
            count = row[0] if row else 0
            if count >= max_retries:
                logger.warning(
                    f"🚨 Infinite loop detected: {step_id} retried {count} times"
                )
                return True
            return False
        except Exception:
            return False

    # ════════════════════════════════════════════
    # Metrics Queries
    # ════════════════════════════════════════════

    def get_success_rate(self, agent: str = None, window_hours: int = 24) -> float:
        """Get success rate for an agent or overall."""
        try:
            db = sqlite3.connect(self.DB_PATH)
            cutoff = (datetime.now() - timedelta(hours=window_hours)).isoformat()
            if agent:
                total = db.execute(
                    """SELECT COUNT(*) FROM step_events
                       WHERE agent=? AND timestamp>? AND event_type='complete'""",
                    (agent, cutoff),
                ).fetchone()[0]
                success = db.execute(
                    """SELECT COUNT(*) FROM step_events
                       WHERE agent=? AND timestamp>? AND status='success'
                       AND event_type='complete'""",
                    (agent, cutoff),
                ).fetchone()[0]
            else:
                total = db.execute(
                    """SELECT COUNT(*) FROM step_events
                       WHERE timestamp>? AND event_type='complete'""",
                    (cutoff,),
                ).fetchone()[0]
                success = db.execute(
                    """SELECT COUNT(*) FROM step_events
                       WHERE timestamp>? AND status='success'
                       AND event_type='complete'""",
                    (cutoff,),
                ).fetchone()[0]
            db.close()
            return (success / total * 100) if total > 0 else 0.0
        except Exception:
            return 0.0

    def get_cost_total(self, window_hours: int = 24) -> float:
        """Get total cost in USD for a time window."""
        try:
            db = sqlite3.connect(self.DB_PATH)
            cutoff = (datetime.now() - timedelta(hours=window_hours)).isoformat()
            row = db.execute(
                """SELECT COALESCE(SUM(total_cost_usd), 0)
                   FROM pipeline_runs WHERE started_at > ?""",
                (cutoff,),
            ).fetchone()
            db.close()
            return row[0] if row else 0.0
        except Exception:
            return 0.0

    def get_recent_pipelines(self, limit: int = 20) -> List[Dict]:
        """Get recent pipeline runs for dashboard."""
        try:
            db = sqlite3.connect(self.DB_PATH)
            db.row_factory = sqlite3.Row
            rows = db.execute(
                """SELECT pipeline_id, user_message, status,
                          total_duration_ms, total_tokens, total_cost_usd,
                          steps_total, steps_succeeded, steps_failed, started_at
                   FROM pipeline_runs ORDER BY started_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            db.close()
            return [dict(r) for r in rows]
        except Exception:
            return []


# Global instance
agent_monitor = AgentMonitor()
