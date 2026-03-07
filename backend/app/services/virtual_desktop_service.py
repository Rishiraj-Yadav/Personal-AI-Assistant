"""
Virtual Desktop Service — OpenClaw-style sandboxed desktops for remote users.
Spawns per-user Xvfb containers so remote (Discord) users can have isolated
desktop control without touching the host machine.
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from loguru import logger


class VirtualDesktopSession:
    """Tracks a single virtual desktop session."""

    def __init__(self, user_id: str, display: int):
        self.session_id = str(uuid.uuid4())[:8]
        self.user_id = user_id
        self.display = display
        self.created_at = datetime.now(timezone.utc)
        self.last_activity = datetime.now(timezone.utc)
        self.process: Optional[asyncio.subprocess.Process] = None

    @property
    def display_str(self) -> str:
        return f":{self.display}"

    def touch(self):
        self.last_activity = datetime.now(timezone.utc)

    @property
    def idle_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.last_activity).total_seconds()


class VirtualDesktopService:
    """Manages per-user Xvfb virtual desktop sessions.

    Each remote user gets their own X display via Xvfb.  Desktop skills
    execute against that display instead of the real one.  Screenshots
    are captured with `xwd` / `import` and returned as base64 PNG.
    """

    IDLE_TIMEOUT = int(os.getenv("VIRTUAL_DESKTOP_TIMEOUT", "600"))  # 10 min
    MAX_SESSIONS = int(os.getenv("VIRTUAL_DESKTOP_MAX_SESSIONS", "5"))
    RESOLUTION = os.getenv("VIRTUAL_DESKTOP_RESOLUTION", "1280x720x24")

    def __init__(self):
        self._sessions: dict[str, VirtualDesktopSession] = {}  # user_id -> session
        self._next_display = 10  # Start Xvfb displays at :10
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start_cleanup_loop(self):
        """Background task that reaps idle sessions."""
        while True:
            await asyncio.sleep(60)
            await self._reap_idle()

    async def get_or_create(self, user_id: str) -> VirtualDesktopSession:
        """Get existing session or create a new Xvfb for this user."""
        async with self._lock:
            if user_id in self._sessions:
                session = self._sessions[user_id]
                session.touch()
                return session

            if len(self._sessions) >= self.MAX_SESSIONS:
                # Evict the oldest idle session
                await self._evict_oldest()

            display = self._next_display
            self._next_display += 1

            session = VirtualDesktopSession(user_id=user_id, display=display)

            try:
                # Start Xvfb
                proc = await asyncio.create_subprocess_exec(
                    "Xvfb", session.display_str,
                    "-screen", "0", self.RESOLUTION,
                    "-ac",  # disable access control
                    "+extension", "RANDR",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                session.process = proc
                self._sessions[user_id] = session

                # Give Xvfb a moment to start
                await asyncio.sleep(0.5)
                logger.info(
                    f"🖥️ Virtual desktop started for {user_id} "
                    f"(display {session.display_str}, pid {proc.pid})"
                )
            except FileNotFoundError:
                logger.warning(
                    "⚠️ Xvfb not installed — virtual desktop unavailable. "
                    "Install with: apt-get install xvfb"
                )
                raise RuntimeError(
                    "Virtual desktop is not available on this server. "
                    "Xvfb is not installed."
                )

            return session

    async def execute_in_session(
        self, user_id: str, command: str, timeout: float = 10.0
    ) -> dict:
        """Run a command in the user's virtual desktop environment."""
        session = await self.get_or_create(user_id)
        session.touch()

        env = os.environ.copy()
        env["DISPLAY"] = session.display_str

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            return {
                "success": proc.returncode == 0,
                "stdout": stdout.decode(errors="replace"),
                "stderr": stderr.decode(errors="replace"),
                "display": session.display_str,
            }
        except asyncio.TimeoutError:
            return {"success": False, "error": "Command timed out"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def take_screenshot(self, user_id: str) -> dict:
        """Capture a screenshot from the user's virtual desktop as base64 PNG."""
        import base64

        session = await self.get_or_create(user_id)
        session.touch()

        tmp_path = f"/tmp/vdesktop_{session.session_id}.png"

        result = await self.execute_in_session(
            user_id,
            f"import -window root -display {session.display_str} {tmp_path}",
            timeout=10.0,
        )

        if not result.get("success"):
            # Fallback: try xwd + convert
            result = await self.execute_in_session(
                user_id,
                f"xwd -root -display {session.display_str} | convert xwd:- png:{tmp_path}",
                timeout=10.0,
            )

        if os.path.exists(tmp_path):
            with open(tmp_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            os.remove(tmp_path)
            return {"success": True, "screenshot_base64": b64, "format": "png"}

        return {"success": False, "error": "Screenshot capture failed"}

    async def destroy_session(self, user_id: str):
        """Kill a user's virtual desktop."""
        async with self._lock:
            session = self._sessions.pop(user_id, None)
            if session and session.process:
                session.process.terminate()
                try:
                    await asyncio.wait_for(session.process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    session.process.kill()
                logger.info(f"🗑️ Destroyed virtual desktop for {user_id}")

    async def list_sessions(self) -> list[dict]:
        """List active virtual desktop sessions."""
        return [
            {
                "user_id": s.user_id,
                "session_id": s.session_id,
                "display": s.display_str,
                "created_at": s.created_at.isoformat(),
                "idle_seconds": int(s.idle_seconds),
            }
            for s in self._sessions.values()
        ]

    # --- Internal ---

    async def _reap_idle(self):
        """Destroy sessions idle longer than timeout."""
        to_destroy = [
            uid for uid, s in self._sessions.items()
            if s.idle_seconds > self.IDLE_TIMEOUT
        ]
        for uid in to_destroy:
            await self.destroy_session(uid)
            logger.info(f"⏰ Reaped idle virtual desktop for {uid}")

    async def _evict_oldest(self):
        """Evict the oldest idle session to make room."""
        if not self._sessions:
            return
        oldest = min(self._sessions.values(), key=lambda s: s.last_activity)
        await self.destroy_session(oldest.user_id)


# Global instance
virtual_desktop_service = VirtualDesktopService()
