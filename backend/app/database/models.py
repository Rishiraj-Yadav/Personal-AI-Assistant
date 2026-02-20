"""
Database Models for Memory System - FIXED VERSION
"""
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

Base = declarative_base()


class User(Base):
    """User profile"""
    __tablename__ = 'users'
    
    user_id = Column(String(255), primary_key=True)
    name = Column(String(255))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_active = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    preferences = relationship("UserPreference", back_populates="user", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")
    task_history = relationship("TaskHistory", back_populates="user", cascade="all, delete-orphan")


class UserPreference(Base):
    """User preferences (learned from behavior)"""
    __tablename__ = 'user_preferences'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), ForeignKey('users.user_id', ondelete='CASCADE'))
    
    category = Column(String(100))  # 'coding', 'desktop', 'general'
    preference_key = Column(String(100))
    preference_value = Column(JSON)
    
    confidence_score = Column(Float, default=0.5)  # 0.0 - 1.0
    learned_from = Column(String(50))  # 'explicit', 'behavior', 'pattern'
    occurrences = Column(Integer, default=1)  # How many times seen
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_updated = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    user = relationship("User", back_populates="preferences")


class Conversation(Base):
    """Conversation thread"""
    __tablename__ = 'conversations'
    
    conversation_id = Column(String(255), primary_key=True)
    user_id = Column(String(255), ForeignKey('users.user_id', ondelete='CASCADE'))
    
    title = Column(String(500))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_message_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    message_count = Column(Integer, default=0)
    
    # Relationships
    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    """Individual message in conversation"""
    __tablename__ = 'messages'
    
    message_id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(255), ForeignKey('conversations.conversation_id', ondelete='CASCADE'))
    
    role = Column(String(20))  # 'user', 'assistant'
    content = Column(Text)
    message_metadata = Column("metadata", JSON)
    
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    tokens_used = Column(Integer)
    
    # Relationships
    conversation = relationship("Conversation", back_populates="messages")


class TaskHistory(Base):
    """History of tasks performed"""
    __tablename__ = 'task_history'
    
    task_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), ForeignKey('users.user_id', ondelete='CASCADE'))
    conversation_id = Column(String(255), nullable=True)
    
    # Task details
    task_type = Column(String(50))  # 'coding', 'desktop', 'web', 'general'
    task_description = Column(Text)
    
    # Execution details
    agent_used = Column(String(100))
    iterations = Column(Integer)
    success = Column(Boolean)
    execution_time = Column(Float)
    
    # Code generation specific
    language = Column(String(50), nullable=True)
    framework = Column(String(100), nullable=True)
    project_type = Column(String(100), nullable=True)
    
    # Desktop specific
    skills_used = Column(JSON, nullable=True)
    
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    user = relationship("User", back_populates="task_history")


class BehavioralPattern(Base):
    """Detected behavioral patterns"""
    __tablename__ = 'behavioral_patterns'
    
    pattern_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), ForeignKey('users.user_id', ondelete='CASCADE'))
    
    pattern_type = Column(String(100))  # 'language_preference', 'workflow_sequence', etc.
    pattern_data = Column(JSON)
    frequency = Column(Integer, default=1)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_occurrence = Column(DateTime, default=lambda: datetime.now(timezone.utc))