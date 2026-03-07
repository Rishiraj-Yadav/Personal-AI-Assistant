"""
API Routes Package
Exports all route routers
"""
from fastapi import APIRouter
from .chat import router as chat_router
from .multi_agent import router as multi_agent_router
from .google import router as google_router
from .dashboard import router as dashboard_router

# Main router that includes all sub-routers
router = APIRouter()

# Include chat routes
router.include_router(chat_router, tags=["chat"])

# Include multi-agent routes
router.include_router(multi_agent_router, prefix="/multi-agent", tags=["multi-agent"])

# Include Google (OAuth, Gmail, Calendar, Scheduler) routes
router.include_router(google_router, prefix="/auth", tags=["google"])

# Include user dashboard routes
router.include_router(dashboard_router, tags=["dashboard"])

__all__ = ["router", "chat_router", "multi_agent_router", "google_router", "dashboard_router"]