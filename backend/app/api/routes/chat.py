"""
Chat API Routes
Main chat endpoint and conversation management
"""
from fastapi import APIRouter, HTTPException, status
from app.models import (
    ChatRequest, 
    ChatResponse, 
    HealthResponse,
    ErrorResponse
)
from app.skills.schema import SkillExecutionRequest, SkillExecutionResult
from app.core.agent import agent
from app.skills.manager import skill_manager
from app.skills.executor import skill_executor
from app.config import settings
from loguru import logger
from datetime import datetime

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Main chat endpoint
    
    Process user message and return agent response
    """
    try:
        logger.info(f"Received chat request from user: {request.user_id}")
        
        result = await agent.process_message(
            user_message=request.message,
            conversation_id=request.conversation_id,
            user_id=request.user_id
        )
        
        return ChatResponse(
            response=result["response"],
            conversation_id=result["conversation_id"],
            model_used=result["model_used"],
            tokens_used=result["tokens_used"],
            timestamp=datetime.utcnow()
        )
        
    except Exception as e:
        logger.error(f"Error in chat endpoint: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process message: {str(e)}"
        )


@router.get("/conversation/{conversation_id}")
async def get_conversation(conversation_id: str):
    """
    Get conversation history
    """
    try:
        conversation = await agent.get_conversation_history(conversation_id)
        
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Conversation {conversation_id} not found"
            )
        
        return conversation
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving conversation: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.delete("/conversation/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """
    Clear conversation history
    """
    try:
        success = await agent.clear_conversation(conversation_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Conversation {conversation_id} not found"
            )
        
        return {"message": "Conversation cleared successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting conversation: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint
    
    Returns service health status
    """
    try:
        health_status = await agent.health_check()
        
        return HealthResponse(
            status="healthy" if health_status["groq_api_status"] == "healthy" else "degraded",
            version=settings.APP_VERSION,
            groq_api_status=health_status["groq_api_status"],
            timestamp=datetime.utcnow()
        )
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return HealthResponse(
            status="unhealthy",
            version=settings.APP_VERSION,
            groq_api_status="error",
            timestamp=datetime.utcnow()
        )


# ========== Skill Management Endpoints ==========

@router.get("/skills")
async def list_skills():
    """
    List all available skills
    
    Returns list of skills with metadata
    """
    try:
        skills = skill_manager.list_skills()
        return {
            "skills": skills,
            "count": len(skills)
        }
    except Exception as e:
        logger.error(f"Error listing skills: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/skills/{skill_name}")
async def get_skill(skill_name: str):
    """
    Get details about a specific skill
    """
    try:
        skill = skill_manager.get_skill(skill_name)
        
        if not skill:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Skill '{skill_name}' not found"
            )
        
        return skill.dict()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving skill: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/skills/execute", response_model=SkillExecutionResult)
async def execute_skill(request: SkillExecutionRequest):
    """
    Execute a skill directly (for testing/manual use)
    """
    try:
        result = await skill_executor.execute_skill(
            skill_name=request.skill_name,
            parameters=request.parameters,
            user_id=request.user_id
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Error executing skill: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/skills/reload")
async def reload_skills():
    """
    Reload all skills from the skills directory
    """
    try:
        count = skill_manager.reload_skills()
        return {
            "message": f"Reloaded {count} skills",
            "count": count
        }
    except Exception as e:
        logger.error(f"Error reloading skills: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )