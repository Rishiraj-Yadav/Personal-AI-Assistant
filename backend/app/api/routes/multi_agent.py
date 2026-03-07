"""
Multi-Agent API Routes - Enhanced with LangGraph + Memory + Slash Commands
"""
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
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
            error=result.get("error"),
            agent_path=result.get("agent_path", [])
        )
        
        return response
    
    except Exception as e:
        logger.error(f"❌ Multi-agent error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/stream")
async def code_generation_stream(websocket: WebSocket):
    """Smart WebSocket with LangGraph + persistent memory"""
    await websocket.accept()
    
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
                await websocket.send_json({
                    "type": msg_data.get("type", "status"),
                    "message": msg_data.get("message", ""),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
            except Exception as e:
                logger.warning(f"⚠️ Send failed: {e}")
        
        # Initial message
        await websocket.send_json({
            "type": "context",
            "message": "🧠 Loading personalized context...",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        # Process with LangGraph
        result = await langgraph_orchestrator.process(
            user_message=message,
            user_id=user_id,
            conversation_id=conversation_id,
            max_iterations=max_iterations,
            message_callback=send_to_frontend
        )
        
        # Send classification
        await websocket.send_json({
            "type": "classification",
            "task_type": result.get("task_type"),
            "confidence": result.get("confidence"),
            "message": f"📍 Task: {result.get('task_type')}",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        # Send agent path
        if result.get("agent_path"):
            await websocket.send_json({
                "type": "agents",
                "message": f"🤖 Agents: {' → '.join(result['agent_path'])}",
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
        
        # Send completion
        await websocket.send_json({
            "type": "complete",
            "success": result.get("success"),
            "result": {
                "task_type": result.get("task_type"),
                "response": result.get("output"),
                "conversation_id": conversation_id,
                "code": result.get("code"),
                "files": result.get("files"),
                "file_path": result.get("file_path"),
                "project_structure": result.get("project_structure"),
                "main_file": result.get("main_file"),
                "server_running": result.get("server_running"),
                "server_url": result.get("server_url"),
                "language": result.get("language"),
                "metadata": result.get("metadata"),
                "agent_path": result.get("agent_path")
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
            "Model failover (Groq → Gemini)"
        ],
        "timestamp": datetime.now(timezone.utc).isoformat()
    }