"""
Multi-Agent API Routes - Enhanced with LangGraph + Memory + Slash Commands
"""
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from loguru import logger
from datetime import datetime, timezone

from app.agents.langgraph_orchestrator import langgraph_orchestrator
from app.services.enhanced_memory_service import enhanced_memory_service
from app.services.slash_command_service import slash_command_service

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
    plan: Optional[Dict[str, Any]] = None
    execution_trace: List[Dict[str, Any]] = Field(default_factory=list)
    approval_state: Optional[Dict[str, Any]] = None
    clarification_state: Optional[Dict[str, Any]] = None
    browser_input_state: Optional[Dict[str, Any]] = None
    browser_state: Dict[str, Any] = Field(default_factory=dict)
    artifacts: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    agent_path: List[str]


@router.post("/generate", response_model=MultiAgentResponse)
async def generate_code(request: MultiAgentRequest):
    """Generate code using LangGraph multi-agent system"""
    try:
        logger.info(f"🚀 Multi-agent request: {request.message[:50]}...")
        
        # Handle slash commands
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
                browser_input_state=None,
                browser_state={},
                agent_path=["slash_command"]
            )
        
        # Process through LangGraph
        result = await langgraph_orchestrator.process(
            user_message=request.message,
            user_id=request.user_id,
            conversation_id=request.conversation_id or f"conv_{datetime.now().timestamp()}",
            max_iterations=request.max_iterations
        )
        
        response = MultiAgentResponse(
            success=result.get("success", False),
            task_type=result.get("task_type", "unknown"),
            confidence=result.get("confidence", 0.0),
            response=result.get("output", ""),
            code=result.get("code"),
            file_path=result.get("file_path"),
            files=result.get("files"),
            project_structure=result.get("project_structure"),
            main_file=result.get("main_file"),
            project_type=result.get("project_type"),
            server_running=result.get("server_running", False),
            server_url=result.get("server_url"),
            server_port=result.get("server_port"),
            language=result.get("language"),
            metadata=result.get("metadata", {}),
            plan=result.get("plan"),
            execution_trace=result.get("execution_trace", []),
            approval_state=result.get("approval_state"),
            clarification_state=result.get("clarification_state"),
            browser_input_state=result.get("browser_input_state"),
            browser_state=result.get("browser_state", {}),
            artifacts=result.get("artifacts"),
            error=result.get("error"),
            agent_path=result.get("agent_path", [])
        )
        
        return response
    
    except Exception as e:
        logger.error(f"❌ Multi-agent error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/stream")
async def code_generation_stream(websocket: WebSocket):
    """Smart WebSocket with LangGraph + persistent memory.
    
    Browser input resumes are sent as a fresh websocket request using
    `type: "agent_answer"` plus the same user/conversation ids.
    """
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        request_type = data.get("type", "message")
        message = data.get("value", "") if request_type == "agent_answer" else data.get("message", "")
        user_id = data.get("user_id", "anonymous")
        conversation_id = data.get("conversation_id") or f"conv_{datetime.now().timestamp()}"
        max_iterations = data.get("max_iterations", 3)

        logger.info(f"🔌 WebSocket from {user_id}: {message[:50]}...")

        await websocket.send_json(
            {
                "type": "processing",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        # ── Two-way communication queue ───────────────────────────────
        async def _message_callback(event: dict):
            """Relay orchestrator events to the WebSocket client."""
            try:
                await websocket.send_json(jsonable_encoder(event))
            except Exception as _e:
                logger.warning(f"WebSocket send failed: {_e}")

        # Provide callbacks to the orchestrator via metadata
        extra_metadata = {
            "_message_callback": _message_callback,
        }

        # ── Run orchestrator + listen for agent_answer concurrently ───
        result = await langgraph_orchestrator.process(
            user_message=message,
            user_id=user_id,
            conversation_id=conversation_id,
            max_iterations=max_iterations,
            extra_metadata=extra_metadata,
        )

        async def _listen_for_answers():
            """While the orchestrator is running, forward user answers."""
            while True:
                try:
                    incoming = await _asyncio.wait_for(
                        websocket.receive_json(), timeout=1.0
                    )
                    msg_type = incoming.get("type", "")
                    if msg_type == "agent_answer":
                        value = incoming.get("value", "")
                        await answer_queue.put(value)
                        logger.info(f"Got agent_answer from user: {value[:30]}...")
                except _asyncio.TimeoutError:
                    pass  # no message yet — keep polling
                except Exception:
                    break  # disconnected or orchestrator done


        await websocket.send_json(
            jsonable_encoder(
                {
                    "type": "complete",
                    "result": result,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        )

    except WebSocketDisconnect:
        logger.info("🔌 WebSocket disconnected")
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}")
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": f"Error: {str(e)}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception:
            pass


# ── Conversations ─────────────────────────────────────────────────────────────

@router.get("/conversations")
async def list_conversations(user_id: str):
    """List recent conversations for sidebar"""
    try:
        convs = enhanced_memory_service.get_recent_conversations(user_id, limit=30)
        return convs
    except Exception as e:
        logger.error(f"❌ Error listing conversations: {e}")
        return []


# ── Web Agent endpoints ───────────────────────────────────────────────────────

class WebAgentPermissionRequest(BaseModel):
    user_id: str
    approved: bool


class ApprovalDecisionRequest(BaseModel):
    approval_id: str
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


@router.post("/approval/respond", response_model=MultiAgentResponse)
async def respond_to_guarded_approval(request: ApprovalDecisionRequest):
    """Approve or deny a guarded planner/executor action and resume if approved."""
    try:
        from app.services.approval_service import approval_service

        approval = approval_service.get_request(request.approval_id)
        if not approval:
            raise HTTPException(status_code=404, detail="Approval request not found")
        if approval.user_id != request.user_id:
            raise HTTPException(status_code=403, detail="Approval request does not belong to this user")
        if approval.status != "pending":
            raise HTTPException(status_code=409, detail=f"Approval request already {approval.status}")

        if not request.approved:
            approval_service.resolve(
                request.approval_id,
                approved=False,
                result={"output": "Action cancelled by user.", "task_type": approval.task_type},
            )
            return MultiAgentResponse(
                success=False,
                task_type=approval.task_type,
                confidence=1.0,
                response="Action cancelled by user.",
                metadata={"approval_id": request.approval_id, "approval_status": "denied"},
                plan=None,
                execution_trace=[],
                approval_state={
                    "status": "denied",
                    "reason": approval.reason,
                    "approval_id": request.approval_id,
                    "affected_steps": approval.affected_steps,
                },
                browser_input_state=None,
                browser_state={},
                artifacts={},
                agent_path=["approval_denied"],
            )

        result = await langgraph_orchestrator.process(
            user_message=approval.user_message,
            user_id=approval.user_id,
            conversation_id=approval.conversation_id,
            max_iterations=3,
            approval_override=True,
            resume_context=approval.metadata.get("resume_context") if isinstance(approval.metadata, dict) else None,
        )
        approval_service.resolve(request.approval_id, approved=True, result=result)

        return MultiAgentResponse(
            success=result.get("success", False),
            task_type=result.get("task_type", approval.task_type),
            confidence=result.get("confidence", 0.0),
            response=result.get("output", ""),
            code=result.get("code"),
            file_path=result.get("file_path"),
            files=result.get("files"),
            project_structure=result.get("project_structure"),
            main_file=result.get("main_file"),
            project_type=result.get("project_type"),
            server_running=result.get("server_running", False),
            server_url=result.get("server_url"),
            server_port=result.get("server_port"),
            language=result.get("language"),
            metadata={
                **result.get("metadata", {}),
                "approval_id": request.approval_id,
                "approval_status": "approved",
            },
            plan=result.get("plan"),
            execution_trace=result.get("execution_trace", []),
            approval_state={
                **(result.get("approval_state") or {}),
                "status": "approved",
                "approval_id": request.approval_id,
            },
            clarification_state=result.get("clarification_state"),
            browser_input_state=result.get("browser_input_state"),
            browser_state=result.get("browser_state", {}),
            artifacts=result.get("artifacts"),
            error=result.get("error"),
            agent_path=result.get("agent_path", []),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Approval response error: {e}")
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


# ── Conversation & memory ─────────────────────────────────────────────────────

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


# ── Health ────────────────────────────────────────────────────────────────────

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
            "Model failover (Groq → Gemini)",

        ],
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
