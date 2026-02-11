"""
Desktop Agent Service
Main HTTP server that exposes desktop control capabilities
Runs on host machine (not in Docker) to access desktop
"""
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional
import uvicorn
from loguru import logger
import sys
from pathlib import Path

# Add skills to path
sys.path.insert(0, str(Path(__file__).parent))

from config import settings, save_api_key
from skills.safety_manager import safety_manager
from skills.screenshot import screenshot_skill
from skills.mouse_control import mouse_control_skill
from skills.keyboard_control import keyboard_control_skill
from skills.app_launcher import app_launcher_skill
from skills.window_manager import window_manager_skill
from skills.screen_reader import screen_reader_skill


# Initialize FastAPI
app = FastAPI(
    title="Desktop Agent Service",
    description="Exposes desktop control capabilities via HTTP API",
    version="1.0.0"
)

# CORS - allow backend to access this service
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response Models
class SkillExecutionRequest(BaseModel):
    """Request to execute a skill"""
    skill: str
    args: Dict[str, Any] = {}
    safe_mode: Optional[bool] = None


class SkillExecutionResponse(BaseModel):
    """Response from skill execution"""
    success: bool
    result: Any
    safe_mode: bool = False
    requires_confirmation: bool = False
    confirmation_message: Optional[str] = None


# API Key verification
def verify_api_key(x_api_key: str = Header(...)):
    """Verify API key from header"""
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key


# Skill registry
SKILLS = {
    "screenshot": screenshot_skill,
    "mouse_control": mouse_control_skill,
    "keyboard_control": keyboard_control_skill,
    "app_launcher": app_launcher_skill,
    "window_manager": window_manager_skill,
    "screen_reader": screen_reader_skill
}


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Desktop Agent",
        "version": "1.0.0",
        "status": "running",
        "safe_mode": settings.SAFE_MODE,
        "skills": list(SKILLS.keys())
    }


@app.get("/health")
async def health():
    """Health check"""
    return {
        "status": "healthy",
        "safe_mode": settings.SAFE_MODE,
        "skills_count": len(SKILLS)
    }


@app.get("/skills")
async def list_skills(api_key: str = Depends(verify_api_key)):
    """List available skills"""
    return {
        "skills": list(SKILLS.keys()),
        "count": len(SKILLS),
        "safe_mode": settings.SAFE_MODE
    }


@app.post("/execute", response_model=SkillExecutionResponse)
async def execute_skill(
    request: SkillExecutionRequest,
    api_key: str = Depends(verify_api_key)
):
    """
    Execute a desktop control skill
    
    Args:
        request: Skill execution request
        
    Returns:
        Execution result
    """
    try:
        skill_name = request.skill
        args = request.args
        
        # Check if skill exists
        if skill_name not in SKILLS:
            raise HTTPException(
                status_code=404,
                detail=f"Skill not found: {skill_name}"
            )
        
        # Override safe mode if requested
        safe_mode = request.safe_mode if request.safe_mode is not None else settings.SAFE_MODE
        
        # Safety check
        safety_check = safety_manager.validate_action(skill_name, args)
        
        if not safety_check["safe"] and not safety_check.get("safe_mode"):
            # Action blocked or requires confirmation
            if safety_check.get("blocked"):
                raise HTTPException(
                    status_code=403,
                    detail=safety_check["reason"]
                )
            
            if safety_check["requires_confirmation"]:
                # Return confirmation required
                return SkillExecutionResponse(
                    success=False,
                    result=None,
                    requires_confirmation=True,
                    confirmation_message=safety_check["confirmation_message"]
                )
        
        # Execute skill
        if safe_mode:
            # Safe mode - just log, don't execute
            logger.info(f"SAFE MODE: Would execute {skill_name} with args: {args}")
            result = {
                "success": True,
                "message": f"Safe mode: {skill_name} would be executed",
                "args": args
            }
            success = True
        else:
            # Execute for real
            skill = SKILLS[skill_name]
            result = skill.execute(args)
            success = result.get("success", False)
        
        # Log action
        safety_manager.log_action(skill_name, args, result, success)
        
        return SkillExecutionResponse(
            success=success,
            result=result,
            safe_mode=safe_mode
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Execution error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/history")
async def get_history(
    limit: int = 100,
    api_key: str = Depends(verify_api_key)
):
    """Get action history"""
    return {
        "history": safety_manager.get_action_history(limit=limit),
        "count": len(safety_manager.action_history)
    }


@app.post("/emergency_stop")
async def emergency_stop(api_key: str = Depends(verify_api_key)):
    """Emergency stop - enable safe mode"""
    settings.SAFE_MODE = True
    logger.warning("EMERGENCY STOP ACTIVATED - Safe mode enabled")
    
    return {
        "success": True,
        "message": "Safe mode activated. No actions will be executed.",
        "safe_mode": True
    }


@app.post("/resume")
async def resume(api_key: str = Depends(verify_api_key)):
    """Resume operations - disable safe mode"""
    settings.SAFE_MODE = False
    logger.info("Operations resumed - Safe mode disabled")
    
    return {
        "success": True,
        "message": "Safe mode disabled. Actions will be executed.",
        "safe_mode": False
    }


def startup_banner():
    """Print startup banner with important info"""
    print("\n" + "="*60)
    print("🖥️  DESKTOP AGENT SERVICE")
    print("="*60)
    print(f"Version: 1.0.0")
    print(f"Host: {settings.HOST}:{settings.PORT}")
    print(f"Safe Mode: {'ENABLED ✓' if settings.SAFE_MODE else 'DISABLED ⚠️'}")
    print(f"Confirmation Required: {settings.REQUIRE_CONFIRMATION}")
    print(f"Available Skills: {', '.join(SKILLS.keys())}")
    print("="*60)
    
    if not settings.SAFE_MODE:
        print("⚠️  WARNING: Safe mode is DISABLED!")
        print("   This service can control your computer!")
        print("   Press Ctrl+C to stop")
    else:
        print("✓ Safe mode is ENABLED")
        print("  Actions will be logged but not executed")
        print("  Use /resume endpoint to disable safe mode")
    
    print("="*60)
    print(f"API Key: {settings.API_KEY[:20]}...")
    print(f"Key saved to: config/api_key.txt")
    print("="*60 + "\n")


if __name__ == "__main__":
    # Setup logging
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level=settings.LOG_LEVEL
    )
    logger.add(
        settings.LOG_FILE,
        rotation="1 day",
        retention="7 days",
        level=settings.LOG_LEVEL
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
        log_level=settings.LOG_LEVEL.lower()
    )