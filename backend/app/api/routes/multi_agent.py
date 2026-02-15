"""
Multi-Agent API Routes - WITH CONVERSATIONAL WEBSOCKET
Real-time conversational updates like VS Code Copilot
"""
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from loguru import logger
import asyncio
import json
from datetime import datetime,timezone

# Import multi-agent orchestrator
from app.agents.multi_agent_orchestrator import orchestrator

router = APIRouter()


class MultiAgentRequest(BaseModel):
    """Request for multi-agent code generation"""
    message: str
    conversation_id: Optional[str] = None
    user_id: str = "web_user"
    max_iterations: Optional[int] = 5


class MultiAgentResponse(BaseModel):
    """Response from multi-agent system"""
    success: bool
    task_type: str
    confidence: float
    response: str
    
    # Single file (legacy)
    code: Optional[str] = None
    file_path: Optional[str] = None
    
    # Multi-file (NEW)
    files: Optional[Dict[str, str]] = None
    project_structure: Optional[Dict] = None
    main_file: Optional[str] = None
    project_type: Optional[str] = None
    
    # Server info (NEW)
    server_running: Optional[bool] = False
    server_url: Optional[str] = None
    server_port: Optional[int] = None
    
    # Metadata
    language: Optional[str] = None
    metadata: Dict[str, Any]
    error: Optional[str] = None
    agent_path: List[str]


@router.post("/generate", response_model=MultiAgentResponse)
async def generate_code(request: MultiAgentRequest):
    """
    Generate code using multi-agent system with iteration
    
    This endpoint:
    1. Routes task to appropriate agent (Router Agent)
    2. Generates code if coding task (Code Specialist)
    3. Tests in E2B sandbox iteratively
    4. Fixes errors automatically (up to max_iterations)
    5. Returns working code + file
    """
    try:
        logger.info(f"🚀 Multi-agent request: {request.message[:50]}...")
        
        # Process through multi-agent system (without callback)
        result = await orchestrator.process(
            user_message=request.message,
            conversation_id=request.conversation_id
        )
        
        # Format response
       # Add new fields to response
        response = MultiAgentResponse(
            success=result.get("success", False),
            task_type=result.get("task_type", "unknown"),
            confidence=result.get("confidence", 0.0),
            response=result.get("output", ""),
            
            # Legacy single file
            code=result.get("code"),
            file_path=result.get("file_path"),
            
            # Multi-file (NEW)
            files=result.get("files"),
            project_structure=result.get("project_structure"),
            main_file=result.get("main_file"),
            project_type=result.get("project_type"),
            
            # Server info (NEW)
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
    """
    WebSocket endpoint for CONVERSATIONAL real-time code generation
    
    Like VS Code Copilot / Cursor AI:
    - Greets user
    - Explains what it's doing
    - Shows progress updates
    - Explains errors
    - Celebrates success
    
    Example (JavaScript):
        const ws = new WebSocket('ws://localhost:8000/api/v1/multi-agent/stream');
        ws.send(JSON.stringify({
            message: "create a flask app",
            max_iterations: 5
        }));
        
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            console.log(data.type, data.message);
            // Types: greeting, thinking, analysis, iteration, testing, success, error, complete
        };
    """
    await websocket.accept()
    
    try:
        # Receive initial message
        data = await websocket.receive_json()
        message = data.get("message", "")
        conversation_id = data.get("conversation_id")
        max_iterations = data.get("max_iterations", 5)
        
        logger.info(f"🔌 WebSocket: {message[:50]}...")
        
        # Create callback function to send messages to frontend
        async def send_to_frontend(msg_data: Dict[str, Any]):
            """
            Send conversational message to frontend
            
            msg_data format:
            {
                "type": "greeting" | "thinking" | "iteration" | "success" | etc,
                "message": "The actual message text"
            }
            """
            try:
                await websocket.send_json({
                    "type": msg_data.get("type", "status"),
                    "message": msg_data.get("message", ""),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
            except Exception as e:
                logger.warning(f"⚠️ Failed to send message: {e}")
        
        # Send initial router classification message
        await websocket.send_json({
            "type": "router",
            "message": "🎯 Analyzing your request...",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        await asyncio.sleep(0.3)
        
        # Process through orchestrator WITH CALLBACK
        result = await orchestrator.process(
            user_message=message,
            conversation_id=conversation_id,
            max_iterations=max_iterations,
            message_callback=send_to_frontend  # ✅ ENABLE CONVERSATION
        )
        
        # Send classification result
        await websocket.send_json({
            "type": "classification",
            "task_type": result.get("task_type"),
            "confidence": result.get("confidence"),
            "message": f"📍 Identified as: {result.get('task_type')} task",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        await asyncio.sleep(0.3)
        
        # Send final result
        await websocket.send_json({
            "type": "complete",
            "success": result.get("success"),
            "result": {
                "task_type": result.get("task_type"),
                "response": result.get("output"),
                "code": result.get("code"),
                "file_path": result.get("file_path"),
                "metadata": result.get("metadata"),
                "agent_path": result.get("agent_path")
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    
    except WebSocketDisconnect:
        logger.info("🔌 WebSocket disconnected")
    except Exception as e:
        logger.error(f"❌ WebSocket error: {str(e)}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"Error: {str(e)}",
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
        except:
            pass


@router.get("/health")
async def multi_agent_health():
    """
    Health check for multi-agent system
    
    Returns status of all agents
    """
    return {
        "status": "healthy",
        "service": "multi-agent",
        "agents": {
            "router": "Google Gemini Flash",
            "code_specialist": "Google Gemini Pro (Conversational)",
            "desktop_specialist": "Existing Skills",
            "general_assistant": "Groq Llama"
        },
        "features": [
            "Task classification",
            "Iterative code generation",
            "Automatic error fixing",
            "E2B sandbox execution",
            "Real-time conversational updates",  # ✅ NEW
            "JavaScript support",  # ✅ NEW
            "Project structure detection"
        ],
        "conversational": True,  # ✅ NEW
        "timestamp": datetime.now(timezone.utc).isoformat()
    }