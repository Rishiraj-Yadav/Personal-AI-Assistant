"""
Desktop Agent Service — v2
Main HTTP server with natural language command endpoint.
Runs on host machine (not Docker) to access the physical desktop.
"""
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import uvicorn
from loguru import logger
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config import settings, save_api_key
from skill_registry import registry
from agent_brain import brain


# ───── Initialize Agents ─────
def register_all_agents():
    """Dynamically import and register all specialist agents"""
    # Simply point to the agents directory to dynamically load plugins
    # exactly like OpenClaw's plugin architecture!
    current_dir = Path(__file__).parent
    agents_dir = current_dir / "agents"
    return registry.discover_agents(str(agents_dir))


# Register agents at import time
_loaded_agents = register_all_agents()


# ───── FastAPI App ─────
app = FastAPI(
    title="Desktop Agent v2",
    description="AI-powered desktop assistant with natural language control",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ───── Request/Response Models ─────
class NLCommandRequest(BaseModel):
    """Natural language command request"""
    command: str
    context: Optional[str] = None


class NLCommandResponse(BaseModel):
    """Natural language command response"""
    response: str
    actions_taken: List[Dict[str, Any]] = []
    success: bool


class SkillExecutionRequest(BaseModel):
    """Direct skill execution request (backward compatible)"""
    skill: str
    args: Dict[str, Any] = {}
    safe_mode: Optional[bool] = None


class SkillExecutionResponse(BaseModel):
    """Skill execution response"""
    success: bool
    result: Any
    safe_mode: bool = False
    error: Optional[str] = None


class NodeDescribeResponse(BaseModel):
    """Node identity + status (OpenClaw-style)"""
    ok: bool
    node: Dict[str, Any]


class NodeToolsResponse(BaseModel):
    """Node tools list (OpenClaw-style)"""
    ok: bool
    tools: List[Dict[str, Any]]


class NodeExecuteRequest(BaseModel):
    """Node tool execution request (OpenClaw-style)"""
    tool: str
    args: Dict[str, Any] = {}
    session_id: Optional[str] = None


class NodeExecuteResponse(BaseModel):
    """Node tool execution response (OpenClaw-style)"""
    ok: bool
    tool: str
    result: Any = None
    error: Optional[str] = None


# ───── Auth ─────
def verify_api_key(x_api_key: str = Header(...)):
    """Verify API key from header"""
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key


# ───── Endpoints ─────
@app.get("/")
async def root():
    """Root — status & info"""
    return {
        "service": "Desktop Agent v2",
        "version": "2.0.0",
        "status": "running",
        "safe_mode": settings.SAFE_MODE,
        "agents": registry.agent_count,
        "tools": registry.tool_count,
        "brain": "ready" if brain.model else "not configured",
    }


@app.get("/health")
async def health():
    """Health check"""
    return {
        "status": "healthy",
        "agents_loaded": registry.agent_count,
        "tools_available": registry.tool_count,
        "brain_ready": brain.model is not None,
    }


@app.post("/execute-nl", response_model=NLCommandResponse)
async def execute_natural_language(
    request: NLCommandRequest,
    api_key: str = Depends(verify_api_key),
):
    """
    Execute a natural language command.
    The Orchestrator Agent Brain will plan and execute the necessary steps.
    """
    try:
        logger.info(f"📨 NL Command: {request.command}")
        result = await brain.process_command(request.command)

        return NLCommandResponse(
            response=result["response"],
            actions_taken=result.get("actions_taken", []),
            success=result.get("success", False),
        )
    except Exception as e:
        logger.error(f"NL execution error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/execute", response_model=SkillExecutionResponse)
async def execute_skill_direct(
    request: SkillExecutionRequest,
    api_key: str = Depends(verify_api_key),
):
    """
    Direct skill execution (backward compatible with v1 API).
    Bypasses the brain — calls the skill directly.
    """
    try:
        result = registry.execute_tool(request.skill, request.args)
        return SkillExecutionResponse(
            success=result.get("success", False),
            result=result.get("result"),
            safe_mode=request.safe_mode or settings.SAFE_MODE,
            error=result.get("error"),
        )
    except Exception as e:
        logger.error(f"Direct execution error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/capabilities")
async def list_capabilities(api_key: str = Depends(verify_api_key)):
    """List all agents, their tools, and descriptions"""
    return {
        "agents": registry.list_agents(),
        "total_tools": registry.tool_count,
    }


# ───── Node Protocol (Gateway ↔ Node) ─────
@app.get("/node/describe", response_model=NodeDescribeResponse)
async def node_describe(api_key: str = Depends(verify_api_key)):
    """
    Describe this node and its current status.
    This is designed for a Gateway to discover/monitor node capabilities.
    """
    return NodeDescribeResponse(
        ok=True,
        node={
            "id": "desktop-windows",
            "name": "Desktop Node (Windows)",
            "version": "2.0.0",
            "endpoint": f"http://{settings.HOST}:{settings.PORT}",
            "safe_mode": settings.SAFE_MODE,
            "agents_loaded": registry.agent_count,
            "tools_available": registry.tool_count,
            "brain_ready": brain.model is not None,
        },
    )


@app.get("/node/tools", response_model=NodeToolsResponse)
async def node_tools(api_key: str = Depends(verify_api_key)):
    """
    Return tool declarations in a node-friendly format.
    For now, we reuse the registry tools as-is; the Gateway will normalize schemas.
    """
    tools_raw = registry.get_all_tools()
    # Flatten to keep it lightweight for the Gateway.
    flat = []
    for item in tools_raw:
        fn = item.get("function") or {}
        if fn.get("name"):
            flat.append(fn)
    return NodeToolsResponse(ok=True, tools=flat)


@app.post("/node/execute", response_model=NodeExecuteResponse)
async def node_execute(
    request: NodeExecuteRequest,
    api_key: str = Depends(verify_api_key),
):
    """
    Execute a tool directly on this node.
    This bypasses the NL brain and is intended for Gateway-driven tool execution.
    """
    try:
        result = registry.execute_tool(request.tool, request.args)
        if result.get("success"):
            return NodeExecuteResponse(ok=True, tool=request.tool, result=result.get("result"))
        return NodeExecuteResponse(ok=False, tool=request.tool, error=result.get("error") or "Tool failed")
    except Exception as e:
        logger.error(f"Node execute error: {e}")
        return NodeExecuteResponse(ok=False, tool=request.tool, error=str(e))


@app.post("/clear-history")
async def clear_history(api_key: str = Depends(verify_api_key)):
    """Clear the brain's conversation history"""
    brain.clear_history()
    return {"success": True, "message": "Conversation history cleared"}


@app.post("/emergency-stop")
async def emergency_stop(api_key: str = Depends(verify_api_key)):
    """Emergency stop — enable safe mode"""
    settings.SAFE_MODE = True
    logger.warning("🚨 EMERGENCY STOP — Safe mode enabled")
    return {"success": True, "safe_mode": True}


@app.post("/resume")
async def resume(api_key: str = Depends(verify_api_key)):
    """Resume operations — disable safe mode"""
    settings.SAFE_MODE = False
    logger.info("▶️ Resumed — Safe mode disabled")
    return {"success": True, "safe_mode": False}


# ───── Startup ─────
def startup_banner():
    """Print startup banner"""
    print("\n" + "=" * 60)
    print("🤖  DESKTOP AGENT v2 — AI Desktop Assistant")
    print("=" * 60)
    print(f"Host: {settings.HOST}:{settings.PORT}")
    print(f"Brain: {'Gemini Flash ✓' if brain.model else '❌ NOT CONFIGURED'}")
    print(f"Agents: {registry.agent_count} loaded")
    print(f"Tools: {registry.tool_count} available")
    print(f"Safe Mode: {'ON ✓' if settings.SAFE_MODE else 'OFF ⚠️'}")
    print("=" * 60)
    print(f"API Key: {settings.API_KEY[:20]}...")
    print("=" * 60)

    if not brain.model:
        print("\n⚠️  Set GOOGLE_API_KEY in .env.desktop to enable the brain!")

    # List all agents
    for agent_info in registry.list_agents():
        print(f"  • {agent_info['name']}: {', '.join(agent_info['tools'])}")

    print("=" * 60 + "\n")


if __name__ == "__main__":
    # Setup logging
    os.makedirs("logs", exist_ok=True)
    os.makedirs("data", exist_ok=True)

    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level=settings.LOG_LEVEL,
    )
    logger.add(
        settings.LOG_FILE,
        rotation="1 day",
        retention="7 days",
        level=settings.LOG_LEVEL,
    )

    # Save API key
    save_api_key()

    # Show startup banner
    startup_banner()

    # Start server
    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        log_level=settings.LOG_LEVEL.lower(),
    )