"""
Database connection and setup - FIXED VERSION
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from pathlib import Path

# Database URL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./data/openclaw.db"  # Default to SQLite
)

# Create data directory if using SQLite
if DATABASE_URL.startswith("sqlite"):
    data_dir = Path("./data")
    data_dir.mkdir(exist_ok=True)

# Create engine
engine = create_engine(
    DATABASE_URL,
    echo=False,  # Set to True for SQL debugging
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
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
    Base.metadata.create_all(bind=engine)  # ✅ Create all tables defined in models
    print("✅ Database initialized")