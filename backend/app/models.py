"""
Pydantic models for request/response validation
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from enum import Enum


class MessageRole(str, Enum):
    """Message role enum"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Message(BaseModel):
    """Single message in conversation"""
    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Optional[Dict[str, Any]] = None


class ChatRequest(BaseModel):
    """Request model for chat endpoint"""
    message: str = Field(..., min_length=1, max_length=5000)
    conversation_id: Optional[str] = None
    user_id: str = "default_user"
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "Hello, can you help me?",
                "conversation_id": "conv_123",
                "user_id": "user_456"
            }
        }
    )


class ChatResponse(BaseModel):
    """Response model for chat endpoint"""
    response: str
    conversation_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model_used: str
    tokens_used: Optional[int] = None
    skills_used: Optional[List[Dict[str, Any]]] = None
    
    model_config = ConfigDict(
        protected_namespaces=(),  # Disable protected namespace warning for model_used
        json_schema_extra={
            "example": {
                "response": "Hello! I'm here to help. What can I do for you?",
                "conversation_id": "conv_123",
                "timestamp": "2024-01-15T10:30:00",
                "model_used": "llama-3.3-70b-versatile",
                "tokens_used": 45,
                "skills_used": []
            }
        }
    )


class ConversationHistory(BaseModel):
    """Conversation history model"""
    conversation_id: str
    user_id: str
    messages: List[Message]
    created_at: datetime
    updated_at: datetime


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    version: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    groq_api_status: str = "unknown"


class ErrorResponse(BaseModel):
    """Error response model"""
    error: str
    detail: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# """
# Pydantic models for request/response validation
# """
# from pydantic import BaseModel, Field
# from typing import Optional, List, Dict, Any
# from datetime import datetime,timezone
# from enum import Enum


# class MessageRole(str, Enum):
#     """Message role enum"""
#     USER = "user"
#     ASSISTANT = "assistant"
#     SYSTEM = "system"


# class Message(BaseModel):
#     """Single message in conversation"""
#     role: MessageRole
#     content: str
#     timestamp: datetime = Field(default_factory=lambda : datetime.now(timezone.utc))
#     metadata: Optional[Dict[str, Any]] = None


# class ChatRequest(BaseModel):
#     """Request model for chat endpoint"""
#     message: str = Field(..., min_length=1, max_length=5000)
#     conversation_id: Optional[str] = None
#     user_id: str = "default_user"
    
#     class Config:
#         json_schema_extra = {
#             "example": {
#                 "message": "Hello, can you help me?",
#                 "conversation_id": "conv_123",
#                 "user_id": "user_456"
#             }
#         }


# class ChatResponse(BaseModel):
#     """Response model for chat endpoint"""
#     response: str
#     conversation_id: str
#     timestamp: datetime = Field(default_factory=lambda : datetime.now(timezone.utc))
#     model_used: str
#     tokens_used: Optional[int] = None
#     skills_used: Optional[List[Dict[str, Any]]] = None
    
#     class Config:
#         json_schema_extra = {
#             "example": {
#                 "response": "Hello! I'm here to help. What can I do for you?",
#                 "conversation_id": "conv_123",
#                 "timestamp": "2024-01-15T10:30:00",
#                 "model_used": "llama-3.3-70b-versatile",
#                 "tokens_used": 45,
#                 "skills_used": []
#             }
#         }


# class ConversationHistory(BaseModel):
#     """Conversation history model"""
#     conversation_id: str
#     user_id: str
#     messages: List[Message]
#     created_at: datetime
#     updated_at: datetime


# class HealthResponse(BaseModel):
#     """Health check response"""
#     status: str
#     version: str
#     timestamp: datetime = Field(default_factory=lambda : datetime.now(timezone.utc))
#     groq_api_status: str = "unknown"


# class ErrorResponse(BaseModel):
#     """Error response model"""
#     error: str
#     detail: Optional[str] = None
#     timestamp: datetime = Field(default_factory=lambda : datetime.now(timezone.utc))
#     """Pydantic models for request/response validation"""
# from pydantic import BaseModel, Field
# from typing import Optional, List, Dict, Any
# from datetime import datetime
# from enum import Enum


# class MessageRole(str, Enum):
#     """Message role enum"""
#     USER = "user"
#     ASSISTANT = "assistant"
#     SYSTEM = "system"


# class Message(BaseModel):
#     """Single message in conversation"""
#     role: MessageRole
#     content: str
#     timestamp: datetime = Field(default_factory=lambda : datetime.now(timezone.utc))
#     metadata: Optional[Dict[str, Any]] = None


# class ChatRequest(BaseModel):
#     """Request model for chat endpoint"""
#     message: str = Field(..., min_length=1, max_length=5000)
#     conversation_id: Optional[str] = None
#     user_id: str = "default_user"
    
#     class Config:
#         json_schema_extra = {
#             "example": {
#                 "message": "Hello, can you help me?",
#                 "conversation_id": "conv_123",
#                 "user_id": "user_456"
#             }
#         }


# class ChatResponse(BaseModel):
#     """Response model for chat endpoint"""
#     response: str
#     conversation_id: str
#     timestamp: datetime = Field(default_factory=lambda : datetime.now(timezone.utc))
#     model_used: str
#     tokens_used: Optional[int] = None
#     skills_used: Optional[List[Dict[str, Any]]] = None
    
#     class Config:
#         json_schema_extra = {
#             "example": {
#                 "response": "Hello! I'm here to help. What can I do for you?",
#                 "conversation_id": "conv_123",
#                 "timestamp": "2024-01-15T10:30:00",
#                 "model_used": "llama-3.3-70b-versatile",
#                 "tokens_used": 45,
#                 "skills_used": []
#             }
#         }


# class ConversationHistory(BaseModel):
#     """Conversation history model"""
#     conversation_id: str
#     user_id: str
#     messages: List[Message]
#     created_at: datetime
#     updated_at: datetime


# class HealthResponse(BaseModel):
#     """Health check response"""
#     status: str
#     version: str
#     timestamp: datetime = Field(default_factory=lambda : datetime.now(timezone.utc))
#     groq_api_status: str = "unknown"


# class ErrorResponse(BaseModel):
#     """Error response model"""
#     error: str
#     detail: Optional[str] = None
#     timestamp: datetime = Field(default_factory=lambda : datetime.now(timezone.utc))