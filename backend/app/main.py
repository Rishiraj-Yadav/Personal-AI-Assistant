"""
SonarBot - Main FastAPI Application
Production-ready with observability, security, and async database
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
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
    logger.info(f"Using Groq model: {settings.GROQ_MODEL}")

    # ============ PHASE 3: Initialize Observability ============
    from app.observability import setup_observability
    setup_observability(
        service_name="sonarbot",
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        json_logs=os.getenv("LOG_JSON", "false").lower() == "true",
        jaeger_enabled=os.getenv("JAEGER_ENABLED", "false").lower() == "true"
    )
    logger.info("✅ Observability initialized (tracing, metrics, logging)")

    # ============ PHASE 4: Initialize Async Database ============
    try:
        from app.database.async_base import init_async_db
        await init_async_db()
        logger.info("✅ Async database initialized")
    except Exception as e:
        logger.warning(f"⚠️ Async database init failed (falling back to sync): {e}")

    # Initialize sync database (existing)
    init_db()
    logger.info("✅ Database initialized")
    
    # Start scheduler
    from app.services.scheduler_service import scheduler_service
    scheduler_service.start()
    logger.info("✅ Scheduler started")
    
    # Start Discord bot (non-blocking, runs in background)
    import asyncio
    from app.services.discord_bot_service import discord_bot_service
    if discord_bot_service.is_configured:
        asyncio.create_task(discord_bot_service.start())
        logger.info("✅ Discord bot starting in background")
    else:
        logger.info("⏭️ Discord bot not configured (set DISCORD_BOT_TOKEN to enable)")
    
    # Start virtual desktop idle cleanup loop
    from app.services.virtual_desktop_service import virtual_desktop_service
    asyncio.create_task(virtual_desktop_service.start_cleanup_loop())
    logger.info("✅ Virtual desktop cleanup loop started")
    
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)
    
    yield
    
    # Shutdown
    # ============ PHASE 4: Close Async Database ============
    try:
        from app.database.async_base import close_async_db
        await close_async_db()
        logger.info("✅ Async database closed")
    except Exception as e:
        logger.warning(f"⚠️ Async database close failed: {e}")

    from app.services.scheduler_service import scheduler_service as sched
    sched.shutdown()
    from app.services.discord_bot_service import discord_bot_service as dbot
    await dbot.stop()
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


# ============ PHASE 3: Metrics Endpoint ============
@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    from app.observability.metrics import metrics as metrics_collector
    return Response(
        content=metrics_collector.get_metrics(),
        media_type=metrics_collector.get_content_type()
    )


@app.get("/health")
async def health():
    """Health check endpoint with system status"""
    from app.core.executor_factory import ExecutorFactory

    try:
        executor = ExecutorFactory.get_executor()
        executor_health = await executor.health_check()
    except Exception as e:
        executor_health = {"status": "error", "error": str(e)}

    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "executor": executor_health
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