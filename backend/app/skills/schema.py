"""
Skill manifest schema and validation - UPDATED
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
    
    # Desktop automation permissions
    DESKTOP_SCREENSHOT = "desktop.screenshot"
    DESKTOP_MOUSE = "desktop.mouse"
    DESKTOP_KEYBOARD = "desktop.keyboard"
    DESKTOP_APP_CONTROL = "desktop.app_control"
    DESKTOP_WINDOW = "desktop.window"
    
    # Code execution permissions
    CODE_GENERATE = "code.generate"
    CODE_EXECUTE = "code.execute"
    CODE_WRITE = "code.write"  # NEW - For code_writer skill
    SANDBOX_ACCESS = "sandbox.access"
    GIT_OPERATIONS = "git.operations"
    
         
 # NEW: Phase 1 - Enhanced file permissions
    FILE_SEARCH_SYSTEM = "file.search.system"      # Search entire computer
    FILE_SEARCH_CONTENT = "file.search.content"    # Search file contents
    FILE_BULK_OPS = "file.bulk.operations"         # Bulk rename, move, delete
    FILE_ARCHIVE = "file.archive"                  # Zip/unzip operations
    FILE_CONVERT = "file.convert"                  # File format conversion
    FILE_METADATA = "file.metadata"                # Edit file metadata
    FILE_ORGANIZE = "file.organize"                # Auto-organize files




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
    entry_point: str
    timeout: int = 30
    memory_limit: str = "512M"
    cpu_limit: float = 1.0
    environment: Dict[str, str] = {}
    
    class Config:
        json_schema_extra = {
            "example": {
                "type": "python_script",
                "entry_point": "script.py",
                "timeout": 30,
                "memory_limit": "512M"
            }
        }


class SkillManifest(BaseModel):
    """Skill manifest - defines skill metadata, permissions, and execution"""
    name: str = Field(..., pattern=r"^[a-z0-9_]+$")
    version: str
    author: str
    description: str
    permissions: List[PermissionScope] = []
    parameters: List[SkillParameter] = []
    execution: SkillExecution
    tags: List[str] = []
    examples: List[str] = []
    signature: Optional[str] = None
    verified: bool = False
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "code_generator",
                "version": "1.0.0",
                "author": "openclaw@example.com",
                "description": "Generates code from descriptions",
                "permissions": ["code.generate"],
                "parameters": [
                    {
                        "name": "description",
                        "type": "string",
                        "description": "What the code should do",
                        "required": True
                    }
                ],
                "execution": {
                    "type": "python_script",
                    "entry_point": "generator.py",
                    "timeout": 60
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
    execution_time: float
    resources_used: Dict[str, Any] = {}
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "skill_name": "code_generator",
                "output": {"code": "print('Hello')", "language": "python"},
                "execution_time": 1.5
            }
        }
        
        
   