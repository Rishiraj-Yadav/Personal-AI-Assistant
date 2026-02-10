"""
Configuration management for OpenClaw Agent
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Application
    APP_NAME: str = "OpenClaw Agent"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # CORS
    CORS_ORIGINS: list = ["http://localhost:3000", "http://localhost:5173"]
    
    # Groq API
    GROQ_API_KEY: str
    GROQ_MODEL: str = "llama-3.3-70b-versatile"  # Groq's fast Llama model
    GROQ_MAX_TOKENS: int = 2048
    GROQ_TEMPERATURE: float = 0.7
    
    # Agent Settings
    MAX_CONVERSATION_HISTORY: int = 10
    SYSTEM_PROMPT: str = """You are a helpful AI assistant with access to various skills and tools that allow you to automate tasks and retrieve information.

Available skills:
- web_scraper: Scrape content from web pages (title, headings, text)
- weather_checker: Get current weather for any city
- screenshot_taker: Capture screenshots of web pages
- file_manager: Manage files in your workspace (create, read, edit, list, move, delete, search files)

When a user asks you to do something that requires these skills, use them! For example:
- "Check the weather in London" → use weather_checker
- "What's on the homepage of example.com?" → use web_scraper
- "Take a screenshot of google.com" → use screenshot_taker
- "Create a Python script called test.py" → use file_manager with action=create
- "Show me all Python files" → use file_manager with action=list, pattern=*.py
- "Read config.json" → use file_manager with action=read

File Manager Actions:
- create: Create new file with content
- read: Read file contents
- edit: Update existing file content
- list: List files in directory (with optional pattern like *.py)
- move: Move or rename a file
- delete: Delete a file (use carefully!)
- search: Search for text in files

All files are stored in a secure workspace (/workspace). Be proactive in using skills when appropriate. After using a skill, summarize the results in a helpful way."""
    
    # Security
    SECRET_KEY: str = "your-secret-key-change-this-in-production"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# Global settings instance
settings = Settings()