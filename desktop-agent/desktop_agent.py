"""
Desktop Agent Service — v2
Main HTTP server with natural language command endpoint.
Runs on host machine (not Docker) to access the physical desktop.
"""
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
import asyncio
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
    """Import and register all specialist agents"""
    agents_loaded = []

    try:
        from agents.app_agent import app_agent
        registry.register_agent(app_agent)
        agents_loaded.append("app")
    except Exception as e:
        logger.warning(f"Failed to load App Agent: {e}")

    try:
        from agents.shell_agent import shell_agent
        registry.register_agent(shell_agent)
        agents_loaded.append("shell")
    except Exception as e:
        logger.warning(f"Failed to load Shell Agent: {e}")

    try:
        from agents.file_agent import file_agent
        registry.register_agent(file_agent)
        agents_loaded.append("file")
    except Exception as e:
        logger.warning(f"Failed to load File Agent: {e}")

    try:
        from agents.gui_agent import gui_agent
        registry.register_agent(gui_agent)
        agents_loaded.append("gui")
    except Exception as e:
        logger.warning(f"Failed to load GUI Agent: {e}")

    try:
        from agents.system_agent import system_agent
        registry.register_agent(system_agent)
        agents_loaded.append("system")
    except Exception as e:
        logger.warning(f"Failed to load System Agent: {e}")

    try:
        from agents.web_agent import web_agent
        registry.register_agent(web_agent)
        agents_loaded.append("web")
    except Exception as e:
        logger.warning(f"Failed to load Web Agent: {e}")

    try:
        from agents.scheduler_agent import scheduler_agent
        registry.register_agent(scheduler_agent)
        agents_loaded.append("scheduler")
    except Exception as e:
        logger.warning(f"Failed to load Scheduler Agent: {e}")

    try:
        from agents.notification_agent import notification_agent
        registry.register_agent(notification_agent)
        agents_loaded.append("notification")
    except Exception as e:
        logger.warning(f"Failed to load Notification Agent: {e}")

    try:
        from agents.browser_agent import browser_agent
        registry.register_agent(browser_agent)
        agents_loaded.append("browser")
    except Exception as e:
        logger.warning(f"Failed to load Browser Agent: {e}")

    logger.info(
        f"✅ Loaded {len(agents_loaded)}/{9} agents: {', '.join(agents_loaded)}"
    )
    return agents_loaded


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
    message: str = ""
    error_code: Optional[str] = None
    retryable: bool = False
    observed_state: Dict[str, Any] = Field(default_factory=dict)
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    tool_name: Optional[str] = None


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
        # Run sync tools off the asyncio loop (Playwright sync API forbids running on the loop)
        result = await asyncio.to_thread(registry.execute_tool, request.skill, request.args)
        return SkillExecutionResponse(
            success=result.get("success", False),
            result=result.get("result"),
            safe_mode=request.safe_mode or settings.SAFE_MODE,
            error=result.get("error"),
            message=result.get("message", ""),
            error_code=result.get("error_code"),
            retryable=result.get("retryable", False),
            observed_state=result.get("observed_state") or {},
            evidence=result.get("evidence") or [],
            tool_name=result.get("tool_name"),
        )
    except Exception as e:
        logger.error(f"Direct execution error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/capabilities")
async def list_capabilities(api_key: str = Depends(verify_api_key)):
    """List all agents, their tools, and descriptions"""
    agents = registry.list_agents()
    tools = sorted(
        {
            tool_name
            for agent in agents
            for tool_name in agent.get("tools", [])
        }
    )
    return {
        "agents": agents,
        "tools": tools,
        "total_tools": registry.tool_count,
    }


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
    print("DESKTOP AGENT v2 - AI Desktop Assistant")
    print("=" * 60)
    print(f"Host: {settings.HOST}:{settings.PORT}")
    print(f"Brain: {'Gemini Flash READY' if brain.model else 'NOT CONFIGURED'}")
    print(f"Agents: {registry.agent_count} loaded")
    print(f"Tools: {registry.tool_count} available")
    print(f"Safe Mode: {'ON' if settings.SAFE_MODE else 'OFF'}")
    print("=" * 60)
    print(f"API Key: {settings.API_KEY[:20]}...")
    print("=" * 60)

    if not brain.model:
        print("\nSet GOOGLE_API_KEY in .env.desktop or .env to enable the brain.")

    for agent_info in registry.list_agents():
        print(f"  - {agent_info['name']}: {', '.join(agent_info['tools'])}")

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

