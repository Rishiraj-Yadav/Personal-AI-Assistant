"""
Desktop Agent Configuration
Isolated settings — reads from .env.desktop only
"""
from pydantic_settings import BaseSettings
from typing import List
import secrets
import os


class DesktopAgentSettings(BaseSettings):
    """Desktop Agent configuration"""

    # LLM Brain
    GOOGLE_API_KEY: str = ""

    # Server settings
    HOST: str = "127.0.0.1"
    PORT: int = 7777
    API_KEY: str = ""

    # Safety settings
    SAFE_MODE: bool = False
    REQUIRE_CONFIRMATION: bool = True
    LOG_ALL_ACTIONS: bool = True

    # Action timeouts (seconds)
    ACTION_TIMEOUT: int = 30
    SCREENSHOT_TIMEOUT: int = 5
    APP_LAUNCH_TIMEOUT: int = 10

    # Allowed safe paths for file operations
    SAFE_PATHS: List[str] = [
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~/Downloads"),
    ]

    # Blocked commands (for shell executor)
    BLOCKED_COMMANDS: List[str] = [
        "format", "diskpart", "del /s /q C:",
        "Remove-Item -Recurse -Force C:",
        "rd /s /q C:", "shutdown", "restart",
    ]

    # Blocked applications
    BLOCKED_APPS: List[str] = [
        "regedit", "registry",
        "format", "diskpart",
    ]

    # Dangerous keywords requiring confirmation
    DANGER_KEYWORDS: List[str] = [
        "delete", "remove", "format", "wipe",
        "install", "uninstall",
        "shutdown", "restart", "reboot",
        "permission", "admin", "root",
    ]

    # Screen boundaries
    MAX_SCREEN_WIDTH: int = 4096
    MAX_SCREEN_HEIGHT: int = 2160

    # Mouse settings
    MOUSE_MOVE_DURATION: float = 0.3
    CLICK_DELAY: float = 0.1

    # Keyboard settings
    TYPING_INTERVAL: float = 0.05

    # OCR settings
    OCR_ENABLED: bool = True
    OCR_LANGUAGE: str = "eng"

    # Logging
    LOG_FILE: str = "logs/desktop_agent.log"
    LOG_LEVEL: str = "INFO"

    # Scheduler
    SCHEDULER_DATA_FILE: str = "data/scheduled_tasks.json"

    class Config:
        env_file = ".env.desktop"
        case_sensitive = True
        extra = "ignore"


# Global settings instance
_settings = DesktopAgentSettings()

# If no API_KEY was loaded, auto-generate one
if not _settings.API_KEY:
    _desktop_key = os.environ.get("DESKTOP_AGENT_API_KEY", "").strip()
    if _desktop_key:
        _settings.API_KEY = _desktop_key
    else:
        _settings.API_KEY = secrets.token_urlsafe(32)

settings = _settings


def save_api_key():
    """Save generated API key to file"""
    os.makedirs("config", exist_ok=True)
    with open("config/api_key.txt", "w") as f:
        f.write(settings.API_KEY)


if __name__ == "__main__":
    save_api_key()
    print(f"API Key: {settings.API_KEY}")
    print(f"Google API Key: {'SET' if settings.GOOGLE_API_KEY else 'MISSING'}")
    print(f"Host: {settings.HOST}:{settings.PORT}")
    print(f"Safe Mode: {settings.SAFE_MODE}")
    print(f"Saved to: config/api_key.txt")