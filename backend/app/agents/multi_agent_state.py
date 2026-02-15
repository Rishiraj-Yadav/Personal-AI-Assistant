"""
Multi-Agent State Definitions - UPDATED FOR MULTI-FILE PROJECTS
Defines the shared state across all agents
"""
from typing import TypedDict, List, Optional, Literal, Dict
from datetime import datetime


class AgentState(TypedDict):
    """
    Shared state across all agents in the graph
    This is passed between nodes and updated by each agent
    """
    # User input
    user_message: str
    conversation_id: str
    
    # Task classification
    task_type: Optional[Literal["coding", "desktop", "web", "general"]]
    confidence: Optional[float]
    
    # Code-specific fields - UPDATED FOR MULTI-FILE
    code_description: Optional[str]
    language: Optional[str]
    project_type: Optional[str]  # NEW: react, flask, node, python, etc.
    
    # Multi-file support - NEW
    files: Optional[Dict[str, str]]  # {filepath: content}
    project_structure: Optional[Dict]  # Tree structure
    main_file: Optional[str]  # Entry point
    
    # Legacy single file support (for backwards compatibility)
    generated_code: Optional[str]
    
    # Execution tracking
    iteration: int
    max_iterations: int
    execution_results: List[dict]
    
    # Server info - NEW
    is_server: bool  # Is this a web server project?
    server_running: bool  # Is server currently running?
    server_port: Optional[int]  # Port number
    server_url: Optional[str]  # Live preview URL
    start_command: Optional[str]  # Command to start server
    
    # Final output
    final_code: Optional[str]  # Legacy single file
    final_files: Optional[Dict[str, str]]  # NEW: Multiple files
    final_output: Optional[str]
    file_path: Optional[str]  # Legacy single file path
    project_path: Optional[str]  # NEW: Project directory
    success: bool
    error_message: Optional[str]
    
    # Metadata
    start_time: Optional[str]
    end_time: Optional[str]
    total_iterations: int
    agent_path: List[str]  # Track which agents were used


class ProjectStructure(TypedDict):
    """Project structure definition"""
    type: str  # react, flask, express, etc.
    root: str  # Root directory name
    files: Dict[str, str]  # {relative_path: content}
    entry_point: str  # Main file to run
    install_command: Optional[str]  # npm install, pip install, etc.
    start_command: str  # npm start, python app.py, etc.
    port: int  # Default port
    dependencies: List[str]  # List of packages


class CodeExecutionResult(TypedDict):
    """Result from sandbox code execution"""
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    execution_time: float
    iteration: int
    timestamp: str
    # NEW: Server info
    server_started: Optional[bool]
    server_url: Optional[str]
    server_port: Optional[int]


class AgentDecision(TypedDict):
    """Decision made by router agent"""
    task_type: str
    confidence: float
    reasoning: str
    next_agent: str


class FileParseResult(TypedDict):
    """Result from parsing multi-file code output"""
    files: Dict[str, str]
    structure: Dict
    main_file: str
    project_type: str
    has_server: bool