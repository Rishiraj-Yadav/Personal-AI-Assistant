"""
Desktop Bridge Skill
Allows Docker backend to communicate with Desktop Agent running on host
"""
import asyncio
import aiohttp
from typing import Dict, Any
from pathlib import Path
from loguru import logger
import os


class DesktopBridgeSkill:
    """
    Bridge between Docker backend and Desktop Agent
    Sends commands to Desktop Agent HTTP service
    """
    
    def __init__(self):
        """Initialize desktop bridge"""
        # Priority order for Desktop Agent URL:
        # 1. Environment variable (set in docker-compose.yml)
        # 2. host.docker.internal (Docker Desktop)
        # 3. localhost (if running outside Docker)
        
        desktop_agent_url = os.environ.get("DESKTOP_AGENT_URL")
        
        if desktop_agent_url:
            self.desktop_agent_url = desktop_agent_url
            logger.info(f"Using DESKTOP_AGENT_URL from environment: {desktop_agent_url}")
        elif self._is_docker():
            # Running in Docker - use host.docker.internal
            self.desktop_agent_url = "http://host.docker.internal:7777"
            logger.info("Running in Docker - using host.docker.internal:7777")
        else:
            # Running on host - use localhost
            self.desktop_agent_url = "http://localhost:7777"
            logger.info("Running on host - using localhost:7777")
        
        self.api_key = self._load_api_key()
        self.timeout = aiohttp.ClientTimeout(total=30)
        logger.info(f"✅ DesktopBridge initialized: {self.desktop_agent_url}")
    
    def _is_docker(self) -> bool:
        """Check if running inside Docker"""
        # Check for Docker-specific files
        return (
            os.path.exists('/.dockerenv') or
            os.path.exists('/proc/1/cgroup') and 'docker' in open('/proc/1/cgroup').read()
        )
    
    def _load_api_key(self) -> str:
        """Load API key from desktop agent"""
        # Try multiple locations
        possible_paths = [
            # Windows direct paths
            Path("R:/6_semester/mini_project/PAI/desktop-agent/config/api_key.txt"),
            
            # Docker mount paths
            Path("/desktop-agent-key/api_key.txt"),
            Path("/app/desktop_agent_key.txt"),
            
            # Relative paths (when running outside Docker)
            Path(__file__).parent.parent.parent / "desktop-agent" / "config" / "api_key.txt",
            Path("../desktop-agent/config/api_key.txt"),
            Path("../../desktop-agent/config/api_key.txt"),
        ]
        
        for path in possible_paths:
            try:
                if path.exists():
                    with open(path, 'r') as f:
                        key = f.read().strip()
                        logger.info(f"✅ Loaded Desktop Agent API key from {path}")
                        return key
            except Exception as e:
                logger.debug(f"Could not read API key from {path}: {e}")
        
        # Try environment variable
        if os.environ.get("DESKTOP_AGENT_API_KEY"):
            logger.info("✅ Using API key from environment variable")
            return os.environ.get("DESKTOP_AGENT_API_KEY")
        
        # Default key for testing (not secure!)
        logger.warning("⚠️ Using default API key - update for production!")
        return "default-key-change-me"
    
    async def execute_skill(
        self, 
        skill_name: str, 
        args: Dict[str, Any],
        safe_mode: bool = None
    ) -> Dict[str, Any]:
        """
        Execute a skill on the desktop agent
        
        Args:
            skill_name: Name of desktop skill
            args: Skill arguments
            safe_mode: Override safe mode setting
            
        Returns:
            Skill execution result
        """
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                headers = {
                    "X-API-Key": self.api_key,
                    "Content-Type": "application/json"
                }
                
                payload = {
                    "skill": skill_name,
                    "args": args
                }
                
                if safe_mode is not None:
                    payload["safe_mode"] = safe_mode
                
                logger.info(f"🔵 Calling Desktop Agent: {skill_name} at {self.desktop_agent_url}")
                logger.debug(f"Payload: {payload}")
                
                async with session.post(
                    f"{self.desktop_agent_url}/execute",
                    json=payload,
                    headers=headers
                ) as response:
                    
                    if response.status == 401:
                        return {
                            "success": False,
                            "error": "Invalid API key. Desktop Agent authentication failed."
                        }
                    
                    if response.status == 404:
                        return {
                            "success": False,
                            "error": f"Desktop skill not found: {skill_name}"
                        }
                    
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Desktop Agent error: {error_text}")
                        return {
                            "success": False,
                            "error": f"Desktop Agent error: {error_text}"
                        }
                    
                    result = await response.json()
                    logger.info(f"✅ Desktop Agent response received")
                    logger.debug(f"Result: {result}")
                    return result
        
        except aiohttp.ClientConnectorError as e:
            logger.error(f"❌ Cannot connect to Desktop Agent at {self.desktop_agent_url}")
            logger.error(f"Error: {str(e)}")
            return {
                "success": False,
                "error": f"Desktop Agent not reachable at {self.desktop_agent_url}. Please ensure:\n1. Desktop Agent is running (check desktop-agent service)\n2. Port 7777 is accessible\n3. Firewall allows connections"
            }
        
        except asyncio.TimeoutError:
            logger.error("⏱️ Desktop Agent request timeout")
            return {
                "success": False,
                "error": "Desktop Agent request timed out"
            }
        
        except Exception as e:
            logger.error(f"❌ Desktop bridge error: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def check_connection(self) -> bool:
        """Check if Desktop Agent is reachable"""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(f"{self.desktop_agent_url}/health") as response:
                    is_healthy = response.status == 200
                    if is_healthy:
                        logger.info(f"✅ Desktop Agent is reachable at {self.desktop_agent_url}")
                    return is_healthy
        except Exception as e:
            logger.warning(f"⚠️ Desktop Agent health check failed: {str(e)}")
            return False
    
    async def get_available_skills(self) -> Dict[str, Any]:
        """Get list of available desktop skills"""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                headers = {"X-API-Key": self.api_key}
                async with session.get(
                    f"{self.desktop_agent_url}/skills",
                    headers=headers
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        return {
                            "success": False,
                            "error": "Failed to fetch skills"
                        }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }


# Global instance
desktop_bridge = DesktopBridgeSkill()


# Convenience functions for common desktop actions
async def take_screenshot(region: Dict = None, monitor: int = 1):
    """Take a screenshot"""
    return await desktop_bridge.execute_skill("screenshot", {
        "region": region,
        "monitor": monitor,
        "format": "base64"
    }, safe_mode=False)


async def move_mouse(x: int, y: int, duration: float = 0.3):
    """Move mouse to position"""
    return await desktop_bridge.execute_skill("mouse_control", {
        "action": "move",
        "x": x,
        "y": y,
        "duration": duration
    }, safe_mode=False)


async def click_mouse(x: int = None, y: int = None, button: str = "left"):
    """Click mouse"""
    args = {
        "action": "click",
        "button": button
    }
    if x is not None and y is not None:
        args["x"] = x
        args["y"] = y
    
    return await desktop_bridge.execute_skill("mouse_control", args, safe_mode=False)


async def type_text(text: str, interval: float = 0.05):
    """Type text"""
    return await desktop_bridge.execute_skill("keyboard_control", {
        "action": "type",
        "text": text,
        "interval": interval
    }, safe_mode=False)


async def press_key(key: str, presses: int = 1):
    """Press a key"""
    return await desktop_bridge.execute_skill("keyboard_control", {
        "action": "press",
        "key": key,
        "presses": presses
    }, safe_mode=False)


async def press_hotkey(keys: list):
    """Press a hotkey combination"""
    return await desktop_bridge.execute_skill("keyboard_control", {
        "action": "hotkey",
        "keys": keys
    }, safe_mode=False)


async def open_app(app: str, wait: bool = False):
    """Open an application"""
    return await desktop_bridge.execute_skill("app_launcher", {
        "app": app,
        "wait": wait
    }, safe_mode=False)


async def list_windows():
    """List open windows"""
    return await desktop_bridge.execute_skill("window_manager", {
        "action": "list"
    }, safe_mode=False)


async def focus_window(title: str):
    """Focus a window by title"""
    return await desktop_bridge.execute_skill("window_manager", {
        "action": "focus",
        "title": title
    }, safe_mode=False)


async def read_screen(region: Dict = None, language: str = "eng"):
    """Read text from screen using OCR"""
    args = {"language": language}
    if region:
        args["region"] = region
    
    return await desktop_bridge.execute_skill("screen_reader", args, safe_mode=False)