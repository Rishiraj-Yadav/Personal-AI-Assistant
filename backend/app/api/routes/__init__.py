"""
API Routes Package
Exports all route routers
"""
from fastapi import APIRouter
from .chat import router as chat_router
from .multi_agent import router as multi_agent_router

# Main router that includes all sub-routers
router = APIRouter()

# Include chat routes
router.include_router(chat_router, tags=["chat"])

# Include multi-agent routes
router.include_router(multi_agent_router, prefix="/multi-agent", tags=["multi-agent"])

__all__ = ["router", "chat_router", "multi_agent_router"]