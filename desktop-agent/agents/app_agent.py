"""
App Agent — Launch, close, and discover applications
"""
import os
import subprocess
import shutil
import glob
from typing import Dict, Any, List
from loguru import logger
from agents.base_agent import BaseAgent


class AppAgent(BaseAgent):
    """Agent for application management — smart discovery, launch, close"""

    def __init__(self):
        super().__init__(
            name="app_agent",
            description="Launch, close, and discover applications, folders, and URLs"
        )
        self._app_cache: Dict[str, str] = {}
        self._build_app_cache()

    def _build_app_cache(self):
        """Discover installed applications on Windows"""
        search_dirs = [
            os.path.expandvars(r"%ProgramFiles%"),
            os.path.expandvars(r"%ProgramFiles(x86)%"),
            os.path.expandvars(r"%LocalAppData%\Programs"),
            os.path.expandvars(r"%AppData%\Microsoft\Windows\Start Menu\Programs"),
            os.path.expandvars(
                r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"
            ),
        ]

        # Well-known apps with common names
        self._app_cache = {
            "notepad": "notepad.exe",
            "calculator": "calc.exe",
            "paint": "mspaint.exe",
            "cmd": "cmd.exe",
            "powershell": "powershell.exe",
            "terminal": "wt.exe",
            "task manager": "taskmgr.exe",
            "explorer": "explorer.exe",
            "control panel": "control.exe",
            "settings": "ms-settings:",
            "snipping tool": "SnippingTool.exe",
            "wordpad": "wordpad.exe",
        }

        # Scan Start Menu for shortcuts
        for d in search_dirs:
            if not os.path.isdir(d):
                continue
            for root, dirs, files in os.walk(d):
                for f in files:
                    if f.endswith(".lnk") or f.endswith(".exe"):
                        name = os.path.splitext(f)[0].lower()
                        self._app_cache[name] = os.path.join(root, f)

        # Check PATH for common tools
        for cmd in ["code", "chrome", "firefox", "git", "node", "python"]:
            path = shutil.which(cmd)
            if path:
                self._app_cache[cmd] = path

        # Common browser paths
        chrome_paths = [
            os.path.expandvars(
                r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"
            ),
            os.path.expandvars(
                r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
            ),
            os.path.expandvars(
                r"%LocalAppData%\Google\Chrome\Application\chrome.exe"
            ),
        ]
        for p in chrome_paths:
            if os.path.isfile(p):
                self._app_cache["chrome"] = p
                self._app_cache["google chrome"] = p
                break

        edge_path = os.path.expandvars(
            r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
        )
        if os.path.isfile(edge_path):
            self._app_cache["edge"] = edge_path
            self._app_cache["microsoft edge"] = edge_path

        # VS Code
        code_path = shutil.which("code")
        if code_path:
            self._app_cache["vs code"] = code_path
            self._app_cache["vscode"] = code_path
            self._app_cache["visual studio code"] = code_path

        logger.info(f"📱 App cache: {len(self._app_cache)} apps discovered")

    def _find_app(self, name: str) -> str | None:
        """Find an application by fuzzy name matching"""
        name_lower = name.lower().strip()

        # Direct match
        if name_lower in self._app_cache:
            return self._app_cache[name_lower]

        # Partial match
        for key, path in self._app_cache.items():
            if name_lower in key or key in name_lower:
                return path

        # Try 'where' command as fallback
        try:
            result = subprocess.run(
                ["where", name_lower],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip().split("\n")[0]
        except Exception:
            pass

        return None

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "open_application",
                "description": "Open/launch an application by name. Can also open folders in Explorer or URLs in the default browser.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Application name (e.g., 'chrome', 'notepad', 'vs code'), folder path, or URL",
                        },
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "close_application",
                "description": "Close/kill a running application by name",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Application name to close (e.g., 'chrome', 'notepad')",
                        },
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "list_running_apps",
                "description": "List currently running applications with visible windows",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "is_app_running",
                "description": "Check if a specific application is currently running",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Application name to check",
                        },
                    },
                    "required": ["name"],
                },
            },
        ]

    def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "open_application":
            return self._open_app(args.get("name", ""))
        elif tool_name == "close_application":
            return self._close_app(args.get("name", ""))
        elif tool_name == "list_running_apps":
            return self._list_running()
        elif tool_name == "is_app_running":
            return self._is_running(args.get("name", ""))
        return self._error(f"Unknown tool: {tool_name}")

    def _open_app(self, name: str) -> Dict[str, Any]:
        """Open an application, folder, or URL"""
        if not name:
            return self._error("No application name provided")

        # Check if it's a URL
        if name.startswith(("http://", "https://", "www.")):
            try:
                os.startfile(name)
                return self._success(
                    {"opened": name, "type": "url"},
                    f"Opened URL: {name}",
                )
            except Exception as e:
                return self._error(f"Failed to open URL: {e}")

        # Check if it's a folder path
        if os.path.isdir(name):
            try:
                os.startfile(name)
                return self._success(
                    {"opened": name, "type": "folder"},
                    f"Opened folder: {name}",
                )
            except Exception as e:
                return self._error(f"Failed to open folder: {e}")

        # Check if it's a file path
        if os.path.isfile(name):
            try:
                os.startfile(name)
                return self._success(
                    {"opened": name, "type": "file"},
                    f"Opened file: {name}",
                )
            except Exception as e:
                return self._error(f"Failed to open file: {e}")

        # Find and launch application
        app_path = self._find_app(name)
        if app_path:
            try:
                if app_path.startswith("ms-"):
                    os.startfile(app_path)
                elif app_path.endswith(".lnk"):
                    os.startfile(app_path)
                else:
                    subprocess.Popen(
                        [app_path],
                        shell=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                return self._success(
                    {"opened": name, "path": app_path, "type": "application"},
                    f"Opened {name}",
                )
            except Exception as e:
                return self._error(f"Failed to open {name}: {e}")

        # Last resort: try os.startfile with the raw name
        try:
            os.startfile(name)
            return self._success(
                {"opened": name, "type": "system_default"},
                f"Opened {name} via system default handler",
            )
        except Exception:
            return self._error(
                f"Could not find application '{name}'. "
                f"Available apps include: {', '.join(list(self._app_cache.keys())[:20])}"
            )

    def _close_app(self, name: str) -> Dict[str, Any]:
        """Close an application by name"""
        try:
            result = subprocess.run(
                ["taskkill", "/IM", f"{name}*", "/F"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            # Also try with .exe suffix
            if result.returncode != 0:
                result = subprocess.run(
                    ["taskkill", "/IM", f"{name}.exe", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

            if result.returncode == 0:
                return self._success(
                    {"closed": name},
                    f"Closed {name}",
                )
            else:
                return self._error(f"Could not close {name}: {result.stderr.strip()}")
        except Exception as e:
            return self._error(f"Failed to close {name}: {e}")

    def _list_running(self) -> Dict[str, Any]:
        """List running apps with visible windows"""
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-Command",
                    "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} | "
                    "Select-Object ProcessName, MainWindowTitle, Id | "
                    "Format-Table -AutoSize | Out-String -Width 200",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            apps = result.stdout.strip()
            return self._success(
                {"running_apps": apps},
                f"Found running applications",
            )
        except Exception as e:
            return self._error(f"Failed to list running apps: {e}")

    def _is_running(self, name: str) -> Dict[str, Any]:
        """Check if an app is running"""
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-Command",
                    f"Get-Process -Name '*{name}*' -ErrorAction SilentlyContinue | "
                    f"Select-Object ProcessName, Id | Format-Table -AutoSize | Out-String",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            output = result.stdout.strip()
            is_running = bool(output and "ProcessName" in output)
            return self._success(
                {"is_running": is_running, "details": output},
                f"{name} is {'running' if is_running else 'not running'}",
            )
        except Exception as e:
            return self._error(f"Failed to check {name}: {e}")


# Global instance
app_agent = AppAgent()
