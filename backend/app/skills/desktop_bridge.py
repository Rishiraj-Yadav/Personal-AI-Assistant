"""
Desktop Bridge Skill
Allows Docker backend to communicate with Desktop Agent running on host.
"""
import asyncio
import os
from pathlib import Path
from typing import Any, Dict, Set, Tuple

import aiohttp
from loguru import logger


class DesktopBridgeSkill:
    """Bridge between the Docker backend and the host desktop agent."""

    def __init__(self):
        """Initialize desktop bridge."""
        desktop_agent_url = os.environ.get("DESKTOP_AGENT_URL")

        if desktop_agent_url:
            self.desktop_agent_url = desktop_agent_url
            logger.info(f"Using DESKTOP_AGENT_URL from environment: {desktop_agent_url}")
        elif self._is_docker():
            self.desktop_agent_url = "http://host.docker.internal:7777"
            logger.info("Running in Docker - using host.docker.internal:7777")
        else:
            self.desktop_agent_url = "http://localhost:7777"
            logger.info("Running on host - using localhost:7777")

        self._api_key_paths = self._get_api_key_paths()
        self.timeout = aiohttp.ClientTimeout(total=30)
        self._capabilities_logged = False
        self._canonical_tools_logged: Set[str] = set()
        self._required_tools = {
            "open_application",
            "mouse_click",
            "mouse_move",
            "mouse_scroll",
            "type_text",
            "press_key",
            "press_hotkey",
            "take_screenshot",
            "read_screen_text",
            "list_windows",
            "focus_window",
            "minimize_window",
            "maximize_window",
        }
        logger.info(f"DesktopBridge initialized: {self.desktop_agent_url}")

    def _is_docker(self) -> bool:
        """Check if running inside Docker."""
        try:
            return (
                os.path.exists('/.dockerenv') or
                (os.path.exists('/proc/1/cgroup') and 'docker' in open('/proc/1/cgroup').read())
            )
        except Exception:
            return False

    def _get_api_key_paths(self) -> list[Path]:
        """Get possible API key file paths."""
        return [
            Path("/app/desktop_agent_key.txt"),
            Path("/desktop-agent-key/api_key.txt"),
            Path(__file__).parent.parent.parent / "desktop-agent" / "config" / "api_key.txt",
            Path("../desktop-agent/config/api_key.txt"),
            Path("../../desktop-agent/config/api_key.txt"),
            Path("R:/6_semester/mini_project/PAI/desktop-agent/config/api_key.txt"),
        ]

    def _get_api_key(self) -> str:
        """Read the latest Desktop Agent API key."""
        env_key = os.environ.get("DESKTOP_AGENT_API_KEY", "").strip()
        if env_key:
            return env_key

        for path in self._api_key_paths:
            try:
                if path.exists():
                    key = path.read_text().strip()
                    if key:
                        logger.debug(f"Loaded Desktop Agent API key from {path}")
                        return key
            except Exception as exc:
                logger.debug(f"Could not read API key from {path}: {exc}")

        logger.warning("Could not load Desktop Agent API key from any source")
        return "default-key-change-me"

    def _normalize_skill_request(
        self,
        skill_name: str,
        args: Dict[str, Any],
    ) -> Tuple[str, Dict[str, Any]]:
        """Map legacy desktop skill names to the canonical host agent tool names."""
        normalized_args = dict(args or {})

        if skill_name == "app_launcher":
            return "open_application", {
                "name": normalized_args.get("name") or normalized_args.get("app", "")
            }

        if skill_name == "keyboard_control":
            action = (normalized_args.get("action") or "").lower()
            if action == "type":
                return "type_text", {"text": normalized_args.get("text", "")}
            if action == "press":
                return "press_key", {"key": normalized_args.get("key", "")}
            if action == "hotkey":
                keys = normalized_args.get("keys", [])
                if isinstance(keys, list):
                    keys = "+".join(str(key).strip() for key in keys if str(key).strip())
                return "press_hotkey", {"keys": keys or ""}

        if skill_name == "mouse_control":
            action = (normalized_args.get("action") or "").lower()
            if action == "move":
                return "mouse_move", {
                    "x": normalized_args.get("x"),
                    "y": normalized_args.get("y"),
                }
            if action in {"click", "double_click", "right_click"}:
                button = normalized_args.get("button", "left")
                clicks = normalized_args.get("clicks", 1)
                if action == "double_click":
                    clicks = 2
                if action == "right_click":
                    button = "right"
                result = {"button": button, "clicks": clicks}
                if normalized_args.get("x") is not None:
                    result["x"] = normalized_args.get("x")
                if normalized_args.get("y") is not None:
                    result["y"] = normalized_args.get("y")
                return "mouse_click", result
            if action == "scroll":
                amount = normalized_args.get("amount", 3)
                if normalized_args.get("direction") == "down" and amount > 0:
                    amount = -amount
                return "mouse_scroll", {"amount": amount}

        if skill_name == "window_manager":
            action = (normalized_args.get("action") or "").lower()
            if action == "list":
                return "list_windows", {}
            if action == "focus":
                return "focus_window", {"title": normalized_args.get("title", "")}
            if action == "minimize":
                return "minimize_window", {"title": normalized_args.get("title", "")}
            if action == "maximize":
                return "maximize_window", {"title": normalized_args.get("title", "")}

        if skill_name == "screenshot":
            region = normalized_args.get("region")
            if isinstance(region, dict):
                region = ",".join(
                    str(region.get(key, ""))
                    for key in ("x", "y", "width", "height")
                )
            return "take_screenshot", {"region": region} if region else {}

        if skill_name == "screen_reader":
            return "read_screen_text", {}

        return skill_name, normalized_args

    def _extract_tool_names(self, capabilities: Dict[str, Any]) -> Set[str]:
        tools = capabilities.get("tools")
        if isinstance(tools, list):
            return {str(tool) for tool in tools}

        extracted: Set[str] = set()
        for agent in capabilities.get("agents", []):
            if not isinstance(agent, dict):
                continue
            for tool in agent.get("tools", []):
                extracted.add(str(tool))
        return extracted

    async def _log_capabilities_once(self) -> None:
        """Log canonical tool availability once and warn if expected tools are missing."""
        if self._capabilities_logged:
            return

        capabilities = await self.get_available_skills()
        if not capabilities.get("success", True):
            logger.warning(
                f"Desktop capability discovery failed: {capabilities.get('error', 'unknown error')}"
            )
            self._capabilities_logged = True
            return

        tool_names = self._extract_tool_names(capabilities)
        self._canonical_tools_logged = tool_names
        if tool_names:
            logger.info(f"Desktop Agent canonical tools: {', '.join(sorted(tool_names))}")

        missing = sorted(self._required_tools - tool_names)
        if missing:
            logger.warning(
                "Desktop Agent is reachable but missing canonical tools: " + ", ".join(missing)
            )

        self._capabilities_logged = True

    async def execute_skill(
        self,
        skill_name: str,
        args: Dict[str, Any],
        safe_mode: bool = None,
    ) -> Dict[str, Any]:
        """Execute a skill on the desktop agent."""
        try:
            canonical_skill_name, canonical_args = self._normalize_skill_request(skill_name, args)
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                headers = {
                    "X-API-Key": self._get_api_key(),
                    "Content-Type": "application/json",
                }

                payload = {
                    "skill": canonical_skill_name,
                    "args": canonical_args,
                }

                if safe_mode is not None:
                    payload["safe_mode"] = safe_mode

                if canonical_skill_name != skill_name or canonical_args != args:
                    logger.info(
                        f"Normalized desktop skill {skill_name} -> {canonical_skill_name}"
                    )

                logger.info(
                    f"Calling Desktop Agent: {canonical_skill_name} at {self.desktop_agent_url}"
                )
                logger.debug(f"Payload: {payload}")

                async with session.post(
                    f"{self.desktop_agent_url}/execute",
                    json=payload,
                    headers=headers,
                ) as response:
                    if response.status == 401:
                        return {
                            "success": False,
                            "error": "Invalid API key. Desktop Agent authentication failed.",
                        }

                    if response.status == 404:
                        return {
                            "success": False,
                            "error": f"Desktop skill not found: {canonical_skill_name}",
                        }

                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Desktop Agent error: {error_text}")
                        return {
                            "success": False,
                            "error": f"Desktop Agent error: {error_text}",
                        }

                    result = await response.json()
                    logger.info("Desktop Agent response received")
                    logger.debug(f"Result: {result}")
                    return result

        except aiohttp.ClientConnectorError as exc:
            logger.error(f"Cannot connect to Desktop Agent at {self.desktop_agent_url}")
            logger.error(f"Error: {str(exc)}")
            return {
                "success": False,
                "error": (
                    f"Desktop Agent not reachable at {self.desktop_agent_url}. Please ensure:\n"
                    "1. Desktop Agent is running (check desktop-agent service)\n"
                    "2. Port 7777 is accessible\n"
                    "3. Firewall allows connections"
                ),
            }

        except asyncio.TimeoutError:
            logger.error("Desktop Agent request timeout")
            return {
                "success": False,
                "error": "Desktop Agent request timed out",
            }

        except Exception as exc:
            logger.error(f"Desktop bridge error: {str(exc)}")
            return {
                "success": False,
                "error": str(exc),
            }

    async def check_connection(self) -> bool:
        """Check if Desktop Agent is reachable."""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(f"{self.desktop_agent_url}/health") as response:
                    is_healthy = response.status == 200
                    if is_healthy:
                        logger.info(f"Desktop Agent is reachable at {self.desktop_agent_url}")
                        await self._log_capabilities_once()
                    return is_healthy
        except Exception as exc:
            logger.warning(f"Desktop Agent health check failed: {str(exc)}")
            return False

    async def get_available_skills(self) -> Dict[str, Any]:
        """Get the list of available desktop skills."""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                headers = {"X-API-Key": self._get_api_key()}
                async with session.get(
                    f"{self.desktop_agent_url}/capabilities",
                    headers=headers,
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        data["success"] = True
                        return data
                    return {
                        "success": False,
                        "error": "Failed to fetch capabilities",
                    }
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
            }


# Global instance
desktop_bridge = DesktopBridgeSkill()


async def take_screenshot(region: Dict = None, monitor: int = 1):
    """Take a screenshot."""
    _ = monitor
    args: Dict[str, Any] = {}
    if region:
        if isinstance(region, dict):
            args["region"] = ",".join(
                str(region.get(key, "")) for key in ("x", "y", "width", "height")
            )
        else:
            args["region"] = region
    return await desktop_bridge.execute_skill("take_screenshot", args, safe_mode=False)


async def move_mouse(x: int, y: int, duration: float = 0.3):
    """Move mouse to position."""
    _ = duration
    return await desktop_bridge.execute_skill("mouse_move", {"x": x, "y": y}, safe_mode=False)


async def click_mouse(x: int = None, y: int = None, button: str = "left"):
    """Click mouse."""
    args: Dict[str, Any] = {"button": button}
    if x is not None and y is not None:
        args["x"] = x
        args["y"] = y
    return await desktop_bridge.execute_skill("mouse_click", args, safe_mode=False)


async def type_text(text: str, interval: float = 0.05):
    """Type text."""
    _ = interval
    return await desktop_bridge.execute_skill("type_text", {"text": text}, safe_mode=False)


async def press_key(key: str, presses: int = 1):
    """Press a key."""
    _ = presses
    return await desktop_bridge.execute_skill("press_key", {"key": key}, safe_mode=False)


async def press_hotkey(keys: list | str):
    """Press a hotkey combination."""
    hotkey = keys if isinstance(keys, str) else "+".join(str(key).strip() for key in keys)
    return await desktop_bridge.execute_skill("press_hotkey", {"keys": hotkey}, safe_mode=False)


async def open_app(app: str, wait: bool = False):
    """Open an application."""
    _ = wait
    return await desktop_bridge.execute_skill("open_application", {"name": app}, safe_mode=False)


async def list_windows():
    """List open windows."""
    return await desktop_bridge.execute_skill("list_windows", {}, safe_mode=False)


async def focus_window(title: str):
    """Focus a window by title."""
    return await desktop_bridge.execute_skill("focus_window", {"title": title}, safe_mode=False)


async def read_screen(region: Dict = None, language: str = "eng"):
    """Read text from screen using OCR."""
    _ = region, language
    return await desktop_bridge.execute_skill("read_screen_text", {}, safe_mode=False)
