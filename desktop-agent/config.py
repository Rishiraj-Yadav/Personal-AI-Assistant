"""
Desktop Agent Configuration
Security and behavior settings
"""
from pydantic_settings import BaseSettings
from typing import List
import secrets


class DesktopAgentSettings(BaseSettings):
    """Desktop Agent configuration"""
    
    # Server settings
    HOST: str = "127.0.0.1"  # Only localhost for security
    PORT: int = 7777
    API_KEY: str = secrets.token_urlsafe(32)  # Auto-generated secret
    
    # Safety settings
    SAFE_MODE: bool = False  # True = log only, don't execute
    # SAFE_MODE: bool = True  # True = log only, don't execute
    REQUIRE_CONFIRMATION: bool = True  # Ask before dangerous actions
    LOG_ALL_ACTIONS: bool = True
    
    # Action timeouts (seconds)
    ACTION_TIMEOUT: int = 30
    SCREENSHOT_TIMEOUT: int = 5
    APP_LAUNCH_TIMEOUT: int = 10
    
    # Allowed applications (whitelist)
    ALLOWED_APPS: List[str] = [
        "chrome", "firefox", "safari", "edge",
        "notepad", "textedit", "gedit",
        "code", "vscode", "sublime",
        "terminal", "iterm", "cmd",
        "calculator", "calendar",
        "slack", "discord", "zoom",
         "task manager", "taskmgr", "taskmanager"  # ADD THIS LINE
    ]
    
    # Blocked applications (blacklist) - takes precedence
    BLOCKED_APPS: List[str] = [
        "regedit", "registry",
        "format", "diskpart",
        "rm", "dd",  # Dangerous Unix commands
        "sudo"
    ]
    
    # Dangerous keywords requiring confirmation
    DANGER_KEYWORDS: List[str] = [
        "delete", "remove", "format", "wipe",
        "install", "uninstall",
        "shutdown", "restart", "reboot",
        "permission", "admin", "root",
        "password", "credential",
        "bank", "payment", "purchase"
    ]
    
    # Screen boundaries
    MAX_SCREEN_WIDTH: int = 4096
    MAX_SCREEN_HEIGHT: int = 2160
    
    # Mouse settings
    MOUSE_MOVE_DURATION: float = 0.3  # Seconds for smooth movement
    CLICK_DELAY: float = 0.1
    
    # Keyboard settings
    TYPING_INTERVAL: float = 0.05  # Delay between keystrokes
    
    # OCR settings
    OCR_ENABLED: bool = True
    OCR_LANGUAGE: str = "eng"
    
    # Logging
    LOG_FILE: str = "logs/desktop_agent.log"
    LOG_LEVEL: str = "INFO"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# Global settings instance
settings = DesktopAgentSettings()


# Save API key to file for backend to use
def save_api_key():
    """Save generated API key to file"""
    with open("config/api_key.txt", "w") as f:
        f.write(settings.API_KEY)


if __name__ == "__main__":
    save_api_key()
    print(f"API Key: {settings.API_KEY}")
    print("Saved to: config/api_key.txt")