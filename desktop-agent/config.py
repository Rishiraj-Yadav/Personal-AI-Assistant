"""
Desktop Agent Configuration
Isolated settings - prefers .env.desktop and falls back to .env.
"""
from pathlib import Path
from typing import List
import os
import secrets

from pydantic_settings import BaseSettings


_BASE_DIR = Path(__file__).resolve().parent


def _load_env_file(path: Path, *, override: bool) -> None:
    """Load simple KEY=VALUE pairs from an env file without extra dependencies."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value


_load_env_file(_BASE_DIR / ".env", override=False)
_load_env_file(_BASE_DIR / ".env.desktop", override=True)


class DesktopAgentSettings(BaseSettings):
    """Desktop Agent configuration."""

    GOOGLE_API_KEY: str = ""

    HOST: str = "127.0.0.1"
    PORT: int = 7777
    API_KEY: str = ""

    SAFE_MODE: bool = False
    REQUIRE_CONFIRMATION: bool = True
    LOG_ALL_ACTIONS: bool = True

    ACTION_TIMEOUT: int = 30
    SCREENSHOT_TIMEOUT: int = 5
    APP_LAUNCH_TIMEOUT: int = 10

    SAFE_PATHS: List[str] = [
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~/Downloads"),
    ]

    BLOCKED_COMMANDS: List[str] = [
        "format", "diskpart", "del /s /q C:",
        "Remove-Item -Recurse -Force C:",
        "rd /s /q C:", "shutdown", "restart",
    ]

    BLOCKED_APPS: List[str] = [
        "regedit", "registry",
        "format", "diskpart",
    ]

    DANGER_KEYWORDS: List[str] = [
        "delete", "remove", "format", "wipe",
        "install", "uninstall",
        "shutdown", "restart", "reboot",
        "permission", "admin", "root",
    ]

    MAX_SCREEN_WIDTH: int = 4096
    MAX_SCREEN_HEIGHT: int = 2160

    MOUSE_MOVE_DURATION: float = 0.3
    CLICK_DELAY: float = 0.1

    TYPING_INTERVAL: float = 0.05

    OCR_ENABLED: bool = True
    OCR_LANGUAGE: str = "eng"

    LOG_FILE: str = "logs/desktop_agent.log"
    LOG_LEVEL: str = "INFO"

    SCHEDULER_DATA_FILE: str = "data/scheduled_tasks.json"

    class Config:
        case_sensitive = True
        extra = "ignore"


_settings = DesktopAgentSettings()

if not _settings.API_KEY:
    _desktop_key = os.environ.get("DESKTOP_AGENT_API_KEY", "").strip()
    if _desktop_key:
        _settings.API_KEY = _desktop_key
    else:
        _settings.API_KEY = secrets.token_urlsafe(32)

settings = _settings


def save_api_key():
    """Save generated API key to file."""
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
