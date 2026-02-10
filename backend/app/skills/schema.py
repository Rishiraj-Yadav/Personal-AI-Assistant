"""
Skill manifest schema and validation
"""
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Literal
from enum import Enum


class PermissionScope(str, Enum):
    """Available permission scopes for skills"""
    NETWORK_EXTERNAL = "network.external"
    NETWORK_INTERNAL = "network.internal"
    BROWSER_AUTOMATE = "browser.automate"
    FILE_READ = "file.read"
    FILE_WRITE = "file.write"
    MEMORY_READ = "memory.read"
    MEMORY_WRITE = "memory.write"
    SCREENSHOT = "screenshot"


class SkillType(str, Enum):
    """Types of skill execution"""
    PYTHON_SCRIPT = "python_script"
    PLAYWRIGHT_SCRIPT = "playwright_script"
    SHELL_COMMAND = "shell_command"
    DOCKER_CONTAINER = "docker_container"


class SkillParameter(BaseModel):
    """Parameter definition for a skill"""
    name: str
    type: Literal["string", "number", "boolean", "array", "object"]
    description: str
    required: bool = True
    default: Optional[Any] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "url",
                "type": "string",
                "description": "The URL to scrape",
                "required": True
            }
        }


class SkillExecution(BaseModel):
    """Execution configuration for a skill"""
    type: SkillType
    entry_point: str  # Path to script or command
    timeout: int = 30  # Timeout in seconds
    memory_limit: str = "512M"  # Memory limit
    cpu_limit: float = 1.0  # CPU cores
    environment: Dict[str, str] = {}
    
    class Config:
        json_schema_extra = {
            "example": {
                "type": "playwright_script",
                "entry_point": "scraper.py",
                "timeout": 30,
                "memory_limit": "512M"
            }
        }


class SkillManifest(BaseModel):
    """
    Skill manifest - defines a skill's metadata, permissions, and execution
    """
    # Metadata
    name: str = Field(..., pattern=r"^[a-z0-9_]+$")
    version: str
    author: str
    description: str
    
    # Permissions
    permissions: List[PermissionScope] = []
    
    # Parameters
    parameters: List[SkillParameter] = []
    
    # Execution
    execution: SkillExecution
    
    # Optional metadata
    tags: List[str] = []
    examples: List[str] = []
    
    # Security
    signature: Optional[str] = None
    verified: bool = False
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "web_scraper",
                "version": "0.1.0",
                "author": "openclaw@example.com",
                "description": "Scrapes content from web pages",
                "permissions": ["network.external", "browser.automate"],
                "parameters": [
                    {
                        "name": "url",
                        "type": "string",
                        "description": "URL to scrape",
                        "required": True
                    }
                ],
                "execution": {
                    "type": "playwright_script",
                    "entry_point": "scraper.py",
                    "timeout": 30
                }
            }
        }


class SkillExecutionRequest(BaseModel):
    """Request to execute a skill"""
    skill_name: str
    parameters: Dict[str, Any]
    conversation_id: Optional[str] = None
    user_id: str = "default_user"


class SkillExecutionResult(BaseModel):
    """Result from skill execution"""
    success: bool
    skill_name: str
    output: Any
    error: Optional[str] = None
    execution_time: float  # seconds
    resources_used: Dict[str, Any] = {}
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "skill_name": "web_scraper",
                "output": {"title": "Example Site", "content": "..."},
                "execution_time": 2.5
            }
        }