"""
SonarBot - Main FastAPI Application
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import os

from app.config import settings
from app.api.routes import router
from app.utils.logger import setup_logging
from loguru import logger
from app.database import init_db
from app.api.routes import multi_agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events
    """
    # Startup
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    if settings.GOOGLE_API_KEY:
        logger.info(f"Using primary model: {settings.GEMINI_MODEL}")
    if settings.GROQ_API_KEY:
        logger.info(f"Using fallback/tool model: {settings.GROQ_MODEL}")
    
    # Initialize database
    init_db()  # ✅ Create tables
    logger.info("✅ Database initialized")
    
    # Start scheduler
    from app.services.scheduler_service import scheduler_service
    scheduler_service.start()
    logger.info("✅ Scheduler started")
    
    # Start Telegram bot (non-blocking, runs in background)
    import asyncio
    from app.services.telegram_bot_service import telegram_bot_service
    if telegram_bot_service.is_configured:
        asyncio.create_task(telegram_bot_service.start())
        logger.info("✅ Telegram bot starting in background")
    else:
        logger.info("⏭️ Telegram bot not configured (set TELEGRAM_BOT_TOKEN to enable)")
    
    # Start virtual desktop idle cleanup loop
    from app.services.virtual_desktop_service import virtual_desktop_service
    asyncio.create_task(virtual_desktop_service.start_cleanup_loop())
    logger.info("✅ Virtual desktop cleanup loop started")

    # Probe Desktop Agent browser availability once at startup.
    try:
        from app.skills.desktop_bridge import desktop_bridge

        desktop_ok = await desktop_bridge.check_connection()
        if desktop_ok:
            capabilities = await desktop_bridge.get_available_skills()
            logger.info(
                "✅ Desktop Agent reachable for live browser routing"
                f" ({len(capabilities.get('tools', []) or [])} tools reported)"
            )
        else:
            logger.warning(
                "⚠️ Desktop Agent unavailable at startup. "
                "Interactive browser tasks will require fallback or fail cleanly."
            )
    except Exception as exc:
        logger.warning(f"⚠️ Desktop Agent startup probe failed: {exc}")
    
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)
    
    yield
    
    # Shutdown
    from app.services.scheduler_service import scheduler_service as sched
    sched.shutdown()
    from app.services.telegram_bot_service import telegram_bot_service as tbot
    await tbot.stop()
    logger.info(f"Shutting down {settings.APP_NAME}")


# Initialize FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI Agent with skill/plugin system for task automation",
    lifespan=lifespan
)

# Setup logging
setup_logging()

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router, prefix="/api/v1", tags=["agent"])
app.include_router(multi_agent.router)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "docs": "/docs"
    }


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if settings.DEBUG else "An error occurred"
        }
    )


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="debug" if settings.DEBUG else "info"
    )
