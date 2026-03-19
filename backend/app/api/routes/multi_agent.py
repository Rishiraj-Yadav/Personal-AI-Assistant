"""
Multi-Agent API Routes - Enhanced with LangGraph + Memory + Slash Commands
Now uses TaskExecutor abstraction with security and observability
"""
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from loguru import logger
from datetime import datetime, timezone

from app.services.enhanced_memory_service import enhanced_memory_service
from app.services.slash_command_service import slash_command_service

# Phase 1: TaskExecutor abstraction
from app.core.task_executor import TaskRequest, TaskType
from app.core.executor_factory import ExecutorFactory

# Phase 3: Observability
from app.observability.metrics import metrics
from app.observability.tracing import trace_async

router = APIRouter()


class MultiAgentRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    user_id: str = "web_user"
    max_iterations: Optional[int] = 3


class MultiAgentResponse(BaseModel):
    success: bool
    task_type: str
    confidence: float
    response: str
    code: Optional[str] = None
    file_path: Optional[str] = None
    files: Optional[Dict[str, str]] = None
    project_structure: Optional[Dict] = None
    main_file: Optional[str] = None
    project_type: Optional[str] = None
    server_running: Optional[bool] = False
    server_url: Optional[str] = None
    server_port: Optional[int] = None
    language: Optional[str] = None
    metadata: Dict[str, Any]
    error: Optional[str] = None
    agent_path: List[str]


def _determine_task_type(message: str) -> TaskType:
    """
    Determine task type from message content.
    Uses fast rule-based detection for common patterns.
    """
    message_lower = message.lower()

    # Coding patterns
    if any(word in message_lower for word in [
        "code", "build", "create", "write", "fix bug", "debug",
        "react", "python", "javascript", "function", "class"
    ]):
        return TaskType.CODE_GENERATION

    # Desktop patterns
    if any(word in message_lower for word in [
        "click", "open app", "type", "press key", "screenshot",
        "desktop", "window", "file manager"
    ]):
        return TaskType.DESKTOP_AUTOMATION

    # Web patterns
    if any(word in message_lower for word in [
        "browse", "website", "search online", "scrape", "navigate to"
    ]):
        return TaskType.WEB_AUTOMATION

    return TaskType.GENERAL_QUERY


@router.post("/generate", response_model=MultiAgentResponse)
@trace_async("generate_code")
async def generate_code(request: MultiAgentRequest):
    """Generate code using TaskExecutor with security and observability"""
    import time
    start_time = time.time()

    try:
        logger.info(f"🚀 Multi-agent request: {request.message[:50]}...")

        # Handle slash commands (bypass TaskExecutor)
        if slash_command_service.is_slash_command(request.message):
            result = await slash_command_service.execute(
                message=request.message,
                user_id=request.user_id,
                conversation_id=request.conversation_id or f"conv_{datetime.now().timestamp()}"
            )
            return MultiAgentResponse(
                success=True,
                task_type="slash_command",
                confidence=1.0,
                response=result.get("response", ""),
                metadata=result.get("metadata", {}),
                agent_path=["slash_command"]
            )

        # ============ Use TaskExecutor (Phase 1 + 2) ============
        # Get executor (LocalTaskExecutor or SafeExecutor based on config)
        executor = ExecutorFactory.get_executor()

        # Determine task type
        task_type = _determine_task_type(request.message)

        # Create task request
        task_request = TaskRequest(
            task_type=task_type,
            user_id=request.user_id,
            conversation_id=request.conversation_id or f"conv_{datetime.now().timestamp()}",
            message=request.message,
            max_iterations=request.max_iterations or 3
        )

        # Execute through TaskExecutor (applies security checks if SafeExecutor)
        result = await executor.execute(task_request)

        # Record metrics (Phase 3)
        duration = time.time() - start_time
        metrics.record_task(task_type.value, result.success, duration)

        response = MultiAgentResponse(
            success=result.success,
            task_type=result.task_type.value if hasattr(result.task_type, 'value') else str(result.task_type),
            confidence=result.confidence,
            response=result.output,
            code=result.code,
            file_path=result.project_path,
            files=result.files,
            project_structure=result.project_structure,
            main_file=None,
            project_type=result.metadata.get("project_type"),
            server_running=result.server_running,
            server_url=result.server_url,
            server_port=result.server_port,
            language=result.metadata.get("language"),
            metadata=result.metadata,
            error=result.error,
            agent_path=result.agent_path
        )

        return response

    except Exception as e:
        # Record error metric
        metrics.record_task("error", False, time.time() - start_time, error_type=type(e).__name__)
        logger.error(f"❌ Multi-agent error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/stream")
async def code_generation_stream(websocket: WebSocket):
    """Smart WebSocket with TaskExecutor + persistent memory"""
    await websocket.accept()
    import time as time_module
    start_time = time_module.time()

    try:
        data = await websocket.receive_json()
        message = data.get("message", "")
        user_id = data.get("user_id", "anonymous")
        conversation_id = data.get("conversation_id") or f"conv_{datetime.now().timestamp()}"
        max_iterations = data.get("max_iterations", 3)

        logger.info(f"🔌 WebSocket from {user_id}: {message[:50]}...")

        # === SLASH COMMAND HANDLING ===
        if slash_command_service.is_slash_command(message):
            logger.info(f"⚡ Slash command: {message}")
            result = await slash_command_service.execute(
                message=message,
                user_id=user_id,
                conversation_id=conversation_id
            )
            await websocket.send_json({
                "type": "complete",
                "success": True,
                "result": {
                    "task_type": "slash_command",
                    "response": result.get("response", ""),
                    "conversation_id": conversation_id,
                    "action": result.get("action"),
                    "agent_path": ["slash_command"],
                    "metadata": result.get("metadata", {})
                },
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            return

        # Callback for progress updates
        async def send_to_frontend(msg_data: Dict[str, Any]):
            try:
                payload = {
                    "type": msg_data.get("type", "status"),
                    "message": msg_data.get("message", ""),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                # Forward web agent specific data
                if msg_data.get("type", "").startswith("web_agent_"):
                    if "action" in msg_data:
                        payload["action"] = msg_data["action"]
                    if "plan" in msg_data:
                        payload["plan"] = msg_data["plan"]
                    if "step" in msg_data:
                        payload["step"] = msg_data["step"]
                    if "success" in msg_data:
                        payload["success"] = msg_data["success"]
                await websocket.send_json(payload)
            except Exception as e:
                logger.warning(f"⚠️ Send failed: {e}")

        # Initial message
        await websocket.send_json({
            "type": "context",
            "message": "🧠 Loading personalized context...",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

        # ============ Use TaskExecutor (Phase 1 + 2) ============
        executor = ExecutorFactory.get_executor()
        task_type = _determine_task_type(message)

        task_request = TaskRequest(
            task_type=task_type,
            user_id=user_id,
            conversation_id=conversation_id,
            message=message,
            max_iterations=max_iterations
        )

        # Execute through TaskExecutor with progress callback
        result = await executor.execute(task_request, progress_callback=send_to_frontend)

        # Record metrics
        duration = time_module.time() - start_time
        metrics.record_task(task_type.value, result.success, duration)

        # Send classification
        task_type_str = result.task_type.value if hasattr(result.task_type, 'value') else str(result.task_type)
        await websocket.send_json({
            "type": "classification",
            "task_type": task_type_str,
            "confidence": result.confidence,
            "message": f"📍 Task: {task_type_str}",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

        # Send agent path
        if result.agent_path:
            await websocket.send_json({
                "type": "agents",
                "message": f"🤖 Agents: {' → '.join(result.agent_path)}",
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

        # Send completion
        await websocket.send_json({
            "type": "complete",
            "success": result.success,
            "result": {
                "task_type": task_type_str,
                "response": result.output,
                "conversation_id": conversation_id,
                "code": result.code,
                "files": result.files,
                "file_path": result.project_path,
                "project_structure": result.project_structure,
                "main_file": None,
                "server_running": result.server_running,
                "server_url": result.server_url,
                "language": result.metadata.get("language") if result.metadata else None,
                "metadata": result.metadata,
                "agent_path": result.agent_path,
                "web_screenshots": result.web_screenshots,
                "web_current_url": result.web_current_url,
                "web_autonomous": result.metadata.get("web_autonomous", False) if result.metadata else False,
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    except WebSocketDisconnect:
        logger.info("🔌 WebSocket disconnected")
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"Error: {str(e)}",
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
        except:
            pass


@router.get("/conversations")
async def list_conversations(user_id: str):
    """List recent conversations for sidebar"""
    try:
        convs = enhanced_memory_service.get_recent_conversations(user_id, limit=30)
        return convs
    except Exception as e:
        logger.error(f"❌ Error listing conversations: {e}")
        return []


# ===== WEB AGENT ENDPOINTS =====

class WebAgentPermissionRequest(BaseModel):
    user_id: str
    approved: bool


@router.post("/web-agent/permission")
async def web_agent_permission(request: WebAgentPermissionRequest):
    """User responds to a web agent permission request (approve/deny)."""
    try:
        from app.services.web_agent_service import web_agent_service
        web_agent_service.set_permission_response(
            user_id=request.user_id,
            approved=request.approved
        )
        return {"success": True, "approved": request.approved}
    except Exception as e:
        logger.error(f"❌ Permission response error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/web-agent/close-session")
async def close_web_session(user_id: str):
    """Close user's browser session."""
    try:
        from app.services.web_agent_service import web_agent_service
        await web_agent_service.close_session(user_id)
        return {"success": True, "message": "Browser session closed"}
    except Exception as e:
        logger.error(f"❌ Close session error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversation/{conversation_id}")
async def get_conversation_history(conversation_id: str):
    """Load conversation history from database"""
    try:
        logger.info(f"📖 Loading conversation: {conversation_id}")
        
        messages = enhanced_memory_service.get_conversation_history(
            conversation_id, limit=100
        )
        
        if not messages:
            raise HTTPException(
                status_code=404, 
                detail=f"Conversation {conversation_id} not found"
            )
        
        # Convert to frontend format
        frontend_messages = []
        for msg in messages:
            frontend_messages.append({
                'role': msg['role'],
                'content': msg['content'],
                'timestamp': msg['timestamp'],
                'metadata': msg.get('metadata', {})
            })
        
        logger.info(f"✅ Loaded {len(frontend_messages)} messages")
        
        return {
            "conversation_id": conversation_id,
            "message_count": len(frontend_messages),
            "messages": frontend_messages
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error loading conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memory/stats/{user_id}")
async def get_memory_stats(user_id: str):
    """Get user's memory statistics"""
    try:
        from app.services.context_builder import context_builder
        
        stats = context_builder.get_memory_summary(user_id)
        
        return {
            "user_id": user_id,
            "stats": stats,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    except Exception as e:
        logger.error(f"❌ Error getting memory stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def multi_agent_health():
    """Health check with memory status"""
    return {
        "status": "healthy",
        "service": "multi-agent-langgraph",
        "version": "2.0",
        "agents": {
            "router": "Google Gemini Flash",
            "code_specialist": "Google Gemini Pro",
            "desktop_specialist": "Desktop Skills",
            "web_autonomous": "Playwright + LLM Vision",
            "general_assistant": "Groq Llama"
        },
        "orchestration": "LangGraph StateGraph",
        "memory": {
            "sql": "SQLite (structured)",
            "vector": "Qdrant (semantic)",
            "context_builder": "Integrated"
        },
        "features": [
            "Task classification",
            "Iterative code generation",
            "Automatic error fixing",
            "E2B sandbox execution",
            "Real-time updates",
            "Persistent SQL memory",
            "Semantic vector search",
            "Personalized context",
            "Reflection loop",
            "Behavioral learning",
            "Slash commands (/new, /status, /compact, /help)",
            "Context compaction",
            "Agent-to-agent routing",
            "Autonomous web agent (Perplexity Comet-style)",
            "Web agent permission system",
            "Model failover (Groq → Gemini)"
        ],
        "timestamp": datetime.now(timezone.utc).isoformat()
    }