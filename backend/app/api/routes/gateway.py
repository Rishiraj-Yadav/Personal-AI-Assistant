"""
Integrated WebSocket Endpoints - Phase 4

Unified WebSocket endpoints for:
- Frontend (web client)
- Desktop Agent
- Real-time bidirectional communication
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Optional
from loguru import logger
import uuid

from app.gateway import (
    gateway_router,
    Platform,
    UnifiedMessage,
    MessageType,
    create_thinking_message,
    create_action_message,
    create_error_message
)
from app.gateway.platform_adapters import web_adapter, desktop_adapter
from app.realtime import fast_path_handler


router = APIRouter()


@router.websocket("/ws/chat")
async def websocket_chat_endpoint(
    websocket: WebSocket,
    session_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None)
):
    """
    WebSocket endpoint for web frontend.

    Handles:
    - User messages
    - Assistant responses
    - Real-time streaming
    - Action notifications
    """
    await websocket.accept()

    # Generate session_id if not provided
    if not session_id:
        session_id = f"web_{uuid.uuid4().hex[:12]}"

    # Generate user_id if not provided
    if not user_id:
        user_id = f"user_{uuid.uuid4().hex[:8]}"

    logger.info(f"Web client connected: session={session_id}, user={user_id}")

    try:
        # Register connection with web adapter
        await web_adapter.register_connection(session_id, websocket)

        # Register session with gateway
        await gateway_router.register_session(
            session_id,
            Platform.WEB,
            {"websocket": websocket, "user_id": user_id}
        )

        # Send initial ACK
        await websocket.send_json({
            "type": "ack",
            "session_id": session_id,
            "user_id": user_id,
            "message": "Connected to assistant"
        })

        # Message processing loop
        while True:
            # Receive message from frontend
            data = await websocket.receive_json()

            # Convert to UnifiedMessage
            message = await web_adapter.receive_from_frontend(session_id, data)

            # Update session activity
            await gateway_router.update_session_activity(session_id)

            # Handle user messages
            if message.type == MessageType.USER_MESSAGE:
                await handle_user_message(
                    session_id,
                    user_id,
                    message,
                    websocket
                )

            # Handle other message types
            else:
                # Route through gateway
                await gateway_router.route_message(message)

    except WebSocketDisconnect:
        logger.info(f"Web client disconnected: {session_id}")

    except Exception as e:
        logger.error(f"WebSocket error ({session_id}): {e}")

    finally:
        # Cleanup
        await web_adapter.unregister_connection(session_id)
        await gateway_router.unregister_session(session_id)


@router.websocket("/ws/desktop")
async def websocket_desktop_endpoint(
    websocket: WebSocket,
    agent_id: Optional[str] = Query(None)
):
    """
    WebSocket endpoint for desktop agent.

    Handles:
    - Desktop commands
    - Context updates
    - Command results
    """
    await websocket.accept()

    # Generate agent_id if not provided
    if not agent_id:
        agent_id = f"desktop_{uuid.uuid4().hex[:8]}"

    logger.info(f"Desktop agent connected: {agent_id}")

    try:
        # Register with desktop adapter
        await desktop_adapter.register_desktop_connection(websocket)

        # Register with gateway
        await gateway_router.register_session(
            agent_id,
            Platform.DESKTOP,
            {"websocket": websocket, "agent_id": agent_id}
        )

        # Send handshake ACK
        await websocket.send_json({
            "type": "handshake_ack",
            "agent_id": agent_id,
            "message": "Connected to backend"
        })

        # Message processing loop
        while True:
            data = await websocket.receive_json()

            # Handle desktop messages
            msg_type = data.get("type")

            if msg_type == "result":
                # Command result from desktop
                await desktop_adapter.handle_desktop_response(data)

                # Broadcast result to relevant sessions
                # (Gateway will route to frontend)
                result_msg = UnifiedMessage(
                    type=MessageType.DESKTOP_RESULT,
                    session_id=agent_id,
                    payload=data
                )
                await gateway_router.route_message(result_msg)

            elif msg_type == "context_update":
                # Context update from desktop
                context_msg = UnifiedMessage(
                    type=MessageType.DESKTOP_CONTEXT,
                    session_id=agent_id,
                    payload=data.get("context", {})
                )
                await gateway_router.route_message(context_msg)

            elif msg_type == "pong":
                # Heartbeat response
                pass

            else:
                logger.debug(f"Unknown desktop message type: {msg_type}")

    except WebSocketDisconnect:
        logger.info(f"Desktop agent disconnected: {agent_id}")

    except Exception as e:
        logger.error(f"Desktop WebSocket error ({agent_id}): {e}")

    finally:
        # Cleanup
        await desktop_adapter.unregister_desktop_connection()
        await gateway_router.unregister_session(agent_id)


async def handle_user_message(
    session_id: str,
    user_id: str,
    message: UnifiedMessage,
    websocket: WebSocket
):
    """
    Handle user message through fast path handler.

    Streams response back through WebSocket.
    """
    user_msg = message.payload.get("message", "")
    conversation_id = message.conversation_id or session_id

    logger.info(f"Processing message from {user_id}: {user_msg[:50]}...")

    # Define streaming callback
    async def stream_callback(event: dict):
        """Send events to frontend."""
        try:
            # Convert to UnifiedMessage format
            msg = UnifiedMessage(
                type=MessageType(event.get("type", "stream_chunk")),
                session_id=session_id,
                request_id=event.get("request_id"),
                conversation_id=conversation_id,
                user_id=user_id,
                payload=event
            )

            # Send through web adapter (converts to frontend format)
            await web_adapter.handle_message(msg)

        except Exception as e:
            logger.warning(f"Stream callback error: {e}")

    # Process through fast path handler
    try:
        result = await fast_path_handler.handle(
            message=user_msg,
            user_id=user_id,
            conversation_id=conversation_id,
            stream_callback=stream_callback
        )

        # Send final completion message
        complete_msg = UnifiedMessage(
            type=MessageType.COMPLETE,
            session_id=session_id,
            conversation_id=conversation_id,
            user_id=user_id,
            payload={
                "success": result.success,
                "task_type": result.intent_type,
                "is_fast_path": result.is_fast_path,
                "total_time_ms": result.total_time_ms
            }
        )

        await web_adapter.handle_message(complete_msg)

    except Exception as e:
        logger.error(f"Message processing error: {e}")

        # Send error message
        error_msg = create_error_message(
            session_id=session_id,
            error_type="processing_error",
            message=str(e)
        )

        await web_adapter.handle_message(error_msg)


@router.on_event("startup")
async def startup_gateway():
    """Initialize gateway on startup."""
    logger.info("Initializing gateway...")

    # Register adapters with gateway
    await gateway_router.register_adapter(Platform.WEB, web_adapter)
    await gateway_router.register_adapter(Platform.DESKTOP, desktop_adapter)

    # Initialize desktop adapter
    await desktop_adapter.initialize()

    logger.info("Gateway initialized successfully")


@router.on_event("shutdown")
async def shutdown_gateway():
    """Cleanup gateway on shutdown."""
    logger.info("Shutting down gateway...")

    # Cleanup desktop adapter
    await desktop_adapter.shutdown()

    logger.info("Gateway shutdown complete")
