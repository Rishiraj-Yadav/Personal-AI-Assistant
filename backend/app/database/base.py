"""
Database connection and setup - SonarBot
Persistent SQLite storage with proper path handling
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from pathlib import Path

# Database URL - use /app/data inside Docker (mapped to host volume)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./data/sonarbot.db"
)

# Create data directory if using SQLite
if DATABASE_URL.startswith("sqlite"):
    # Extract path from sqlite URL
    db_path = DATABASE_URL.replace("sqlite:///", "")
    data_dir = Path(db_path).parent
    data_dir.mkdir(parents=True, exist_ok=True)

# Create engine with WAL mode for better concurrent access
engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    pool_pre_ping=True,
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database (create tables)"""
    from app.database.models import Base
    Base.metadata.create_all(bind=engine)
    
    # Enable WAL mode for SQLite for better persistence
    if "sqlite" in DATABASE_URL:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.commit()
    
    print("✅ Database initialized")