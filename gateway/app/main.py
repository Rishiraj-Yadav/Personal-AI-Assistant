"""
Gateway — Main FastAPI application
Routes external requests to the Desktop Agent node.
"""
from __future__ import annotations
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from gateway.app.config import settings
from gateway.app.core.json import dumps, loads, safe_jsonable
from gateway.app.sessions.store import SessionStore
from gateway.app.tools.builtins import register_builtin_tools
from gateway.app.tools.registry import ToolRegistry

# ───── App ─────
app = FastAPI(title="Gateway", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ───── Services ─────
sessions = SessionStore()
tools = ToolRegistry()
register_builtin_tools(tools)


# ───── Routes ─────
@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "service": "Gateway",
        "version": "0.1.0",
        "status": "running",
        "tools": len(tools.list_tools()),
        "sessions": len(sessions.list_sessions()),
    }


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "healthy",
        "uptime": time.time(),
        "desktop_node": settings.DESKTOP_NODE_URL,
    }


@app.post("/_event")
async def _event(event_type: str, data: Any = None, session_id: Optional[str] = None) -> Dict[str, Any]:
    logger.info(f"Event received: {event_type} (session={session_id})")
    return {"ok": True, "event_type": event_type}


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    session_id = f"ws-{int(time.time() * 1000)}"
    session = sessions.create(session_id)
    logger.info(f"WebSocket connected: {session_id}")

    try:
        while True:
            raw = await websocket.receive_text()
            data = loads(raw)
            logger.debug(f"WS [{session_id}]: {data}")

            # Echo back for now — full tool routing will be added
            response = {
                "session_id": session_id,
                "received": safe_jsonable(data),
                "timestamp": time.time(),
            }
            await websocket.send_text(dumps(response))

    except WebSocketDisconnect:
        sessions.remove(session_id)
        logger.info(f"WebSocket disconnected: {session_id}")
