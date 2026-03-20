"""
App Agent — Launch, close, and discover applications
"""
import os
import subprocess
import shutil
import webbrowser
import glob
import time
import psutil
from typing import Dict, Any, List, Optional
from loguru import logger
from agents.base_agent import BaseAgent


class AppAgent(BaseAgent):
    """Agent for application management — smart discovery, launch, close"""

    # Well-known website names → URLs
    KNOWN_WEBSITES: Dict[str, str] = {
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "github": "https://www.github.com",
        "gmail": "https://mail.google.com",
        "reddit": "https://www.reddit.com",
        "twitter": "https://www.twitter.com",
        "x": "https://www.x.com",
        "linkedin": "https://www.linkedin.com",
        "facebook": "https://www.facebook.com",
        "instagram": "https://www.instagram.com",
        "amazon": "https://www.amazon.com",
        "flipkart": "https://www.flipkart.com",
        "wikipedia": "https://www.wikipedia.org",
        "stackoverflow": "https://stackoverflow.com",
        "leetcode": "https://leetcode.com",
        "netflix": "https://www.netflix.com",
        "spotify": "https://open.spotify.com",
        "chatgpt": "https://chat.openai.com",
        "whatsapp": "https://web.whatsapp.com",
    }
    
    # Browser process names for detection
    BROWSER_PROCESSES = {
        "chrome": ["chrome.exe", "chrome"],
        "firefox": ["firefox.exe", "firefox"],
        "edge": ["msedge.exe", "msedge", "MicrosoftEdge.exe"],
        "brave": ["brave.exe", "brave"],
        "opera": ["opera.exe", "opera"],
    }

    def __init__(self):
        super().__init__(
            name="app_agent",
            description="Launch, close, and discover applications, folders, and URLs. Can open websites like YouTube, Google, GitHub etc. in the system's default browser."
        )
        self._app_cache: Dict[str, str] = {}
        self._browser_ready: bool = False
        self._active_browser: Optional[str] = None
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
                "name": "open_special_folder",
                "description": "Open a well-known folder directly (avoids typing/navigating in Explorer). Supports OneDrive-backed folders when available.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "folder": {
                            "type": "string",
                            "enum": [
                                "desktop",
                                "documents",
                                "downloads",
                                "pictures",
                                "onedrive_root",
                                "onedrive_desktop",
                                "onedrive_documents",
                                "onedrive_pictures",
                            ],
                            "description": "Which special folder to open",
                        },
                    },
                    "required": ["folder"],
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
            {
                "name": "open_url",
                "description": "Open a URL or a well-known website name (like 'youtube', 'google', 'github') in the system's default web browser",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "A full URL (e.g., 'https://youtube.com') or a website name (e.g., 'youtube', 'google', 'github')",
                        },
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "open_path",
                "description": "Open any file or folder path directly in the appropriate application (Explorer for folders, default app for files)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "The file or folder path to open",
                        },
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "launch_app",
                "description": "Launch an application by name (alias for open_application)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "app": {
                            "type": "string",
                            "description": "Application name to launch",
                        },
                    },
                    "required": ["app"],
                },
            },
            {
                "name": "ensure_browser",
                "description": "Ensure the default browser is open and ready for web tasks. Call this BEFORE any web interaction tasks.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "wait_time": {
                            "type": "number",
                            "description": "Seconds to wait for browser to start (default: 2.0)",
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "get_browser_status",
                "description": "Check if any browser is currently running and get its name",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        ]

    def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "open_application":
            return self._open_app(args.get("name", ""))
        if tool_name == "open_special_folder":
            return self._open_special_folder(args.get("folder", ""))
        elif tool_name == "close_application":
            return self._close_app(args.get("name", ""))
        elif tool_name == "list_running_apps":
            return self._list_running()
        elif tool_name == "is_app_running":
            return self._is_running(args.get("name", ""))
        elif tool_name == "open_url":
            return self._open_url(args.get("url", ""))
        elif tool_name == "open_path":
            return self._open_path(args.get("path", ""))
        elif tool_name == "launch_app":
            return self._open_app(args.get("app", ""))
        elif tool_name == "ensure_browser":
            result = self._ensure_browser_ready(args.get("wait_time", 2.0))
            return self._success(result, "Browser check complete")
        elif tool_name == "get_browser_status":
            is_running, browser_name = self._is_browser_running()
            return self._success({
                "is_running": is_running,
                "browser": browser_name,
                "browser_ready": self._browser_ready
            }, f"Browser {'running' if is_running else 'not running'}")
        return self._error(f"Unknown tool: {tool_name}")

    def _open_app(self, name: str) -> Dict[str, Any]:
        """Open an application, folder, or URL"""
        if not name:
            return self._error("No application name provided")

        resolved_folder = self._resolve_special_folder(name)
        if resolved_folder:
            try:
                # Be explicit on Windows: launching explorer with a path reliably opens that folder
                subprocess.Popen(
                    ["explorer.exe", resolved_folder],
                    shell=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return self._success(
                    {"opened": resolved_folder, "type": "folder", "resolved_from": name},
                    f"Opened folder: {resolved_folder}",
                )
            except Exception as e:
                return self._error(f"Failed to open folder '{resolved_folder}': {e}")

        # Check if it's a well-known website name
        name_lower = name.lower().strip()
        if name_lower in self.KNOWN_WEBSITES:
            return self._open_url(name_lower)

        # Check if it's a URL
        if name.startswith(("http://", "https://", "www.")):
            return self._open_url(name)

        # Check if it's a folder path
        if os.path.isdir(name):
            try:
                subprocess.Popen(
                    ["explorer.exe", name],
                    shell=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
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

    def _is_browser_running(self) -> tuple[bool, Optional[str]]:
        """Check if any known browser is currently running."""
        for browser_name, process_names in self.BROWSER_PROCESSES.items():
            for proc in psutil.process_iter(['name']):
                try:
                    if proc.info['name'] in process_names:
                        return True, browser_name
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        return False, None
    
    def _ensure_browser_ready(self, wait_time: float = 2.0) -> Dict[str, Any]:
        """
        Ensure the default browser is open and ready.
        
        This is called before web tasks that require browser interaction.
        Returns info about the browser state.
        """
        is_running, browser_name = self._is_browser_running()
        
        if is_running:
            self._browser_ready = True
            self._active_browser = browser_name
            logger.info(f"🌐 Browser already running: {browser_name}")
            return {
                "browser_ready": True,
                "browser": browser_name,
                "action": "already_running"
            }
        
        # Open browser with a blank page first
        logger.info("🌐 Opening browser...")
        try:
            webbrowser.open("about:blank")
            time.sleep(wait_time)  # Wait for browser to start
            
            # Check if it's running now
            is_running, browser_name = self._is_browser_running()
            if is_running:
                self._browser_ready = True
                self._active_browser = browser_name
                logger.info(f"✅ Browser started: {browser_name}")
                return {
                    "browser_ready": True,
                    "browser": browser_name,
                    "action": "started"
                }
            else:
                return {
                    "browser_ready": False,
                    "browser": None,
                    "action": "failed_to_start"
                }
        except Exception as e:
            logger.error(f"Failed to start browser: {e}")
            return {
                "browser_ready": False,
                "browser": None,
                "error": str(e)
            }

    def _open_url(self, url: str, ensure_browser: bool = True) -> Dict[str, Any]:
        """
        Open a URL or well-known website name in the system's default browser.
        
        Args:
            url: URL or website name (e.g., "youtube", "https://google.com")
            ensure_browser: If True, ensures browser is ready before opening URL
        """
        if not url:
            return self._error("No URL provided")

        url_lower = url.lower().strip()

        # Resolve well-known website names
        if url_lower in self.KNOWN_WEBSITES:
            resolved_url = self.KNOWN_WEBSITES[url_lower]
            logger.info(f"🌐 Resolved '{url_lower}' → {resolved_url}")
        elif url.startswith(("http://", "https://")):
            resolved_url = url
        elif url.startswith("www."):
            resolved_url = f"https://{url}"
        else:
            # Try adding https:// as a guess
            resolved_url = f"https://www.{url_lower}.com"

        try:
            # Check/ensure browser is running
            browser_info = None
            if ensure_browser:
                browser_info = self._ensure_browser_ready(wait_time=1.0)
            
            # Open the URL
            webbrowser.open(resolved_url)
            
            result_data = {
                "opened": resolved_url,
                "type": "url",
                "original_input": url,
                "browser_ready": self._browser_ready,
                "active_browser": self._active_browser
            }
            
            if browser_info:
                result_data["browser_info"] = browser_info
            
            return self._success(
                result_data,
                f"Opened {resolved_url} in default browser",
            )
        except Exception as e:
            return self._error(f"Failed to open URL '{resolved_url}': {e}")

    def _open_path(self, path: str) -> Dict[str, Any]:
        """
        Open a file or folder path directly.
        
        This is the primary method for the backend to open paths.
        - Folders open in Windows Explorer
        - Files open with their default application
        """
        if not path:
            return self._error("No path provided")
        
        # Expand environment variables and user home
        expanded = os.path.expanduser(os.path.expandvars(path))
        
        # Check if path exists
        if not os.path.exists(expanded):
            return self._error(f"Path does not exist: {expanded}")
        
        try:
            if os.path.isdir(expanded):
                # Open folder in Explorer
                subprocess.Popen(
                    ["explorer.exe", expanded],
                    shell=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return self._success(
                    {"opened": expanded, "type": "folder", "original_path": path},
                    f"Opened folder: {expanded}",
                )
            else:
                # Open file with default application
                os.startfile(expanded)
                return self._success(
                    {"opened": expanded, "type": "file", "original_path": path},
                    f"Opened file: {expanded}",
                )
        except Exception as e:
            return self._error(f"Failed to open path '{expanded}': {e}")

    def _open_special_folder(self, folder: str) -> Dict[str, Any]:
        key = (folder or "").strip().lower()
        if not key:
            return self._error("No folder specified")

        target: str | None = None
        if key == "desktop":
            target = self._get_known_folder_path("Desktop")
        elif key == "documents":
            target = self._get_known_folder_path("MyDocuments")
        elif key == "pictures":
            target = self._get_known_folder_path("MyPictures")
        elif key == "downloads":
            target = os.path.join(os.path.expanduser("~"), "Downloads")
            if not os.path.isdir(target):
                target = None
        elif key == "onedrive_root":
            target = self._get_onedrive_root()
        elif key in {"onedrive_desktop", "onedrive_documents", "onedrive_pictures"}:
            root = self._get_onedrive_root()
            if root:
                suffix = {
                    "onedrive_desktop": "Desktop",
                    "onedrive_documents": "Documents",
                    "onedrive_pictures": "Pictures",
                }[key]
                candidate = os.path.join(root, suffix)
                target = candidate if os.path.isdir(candidate) else None

        if not target or not os.path.isdir(target):
            return self._error(f"Special folder not available: {folder}")

        try:
            subprocess.Popen(
                ["explorer.exe", target],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return self._success({"opened": target, "type": "folder", "special": key}, f"Opened folder: {target}")
        except Exception as e:
            return self._error(f"Failed to open folder '{target}': {e}")

    def _resolve_special_folder(self, raw: str) -> str | None:
        """
        Resolve human-friendly folder names (e.g. "Documents folder") to real paths.
        Uses Windows known folders when possible, since users may have OneDrive redirection.
        """
        text = (raw or "").strip().lower()
        if not text:
            return None

        # Normalize common phrasing
        for suffix in [" folder", " directory", " in file explorer", " in explorer", " in windows explorer"]:
            if text.endswith(suffix):
                text = text[: -len(suffix)].strip()

        # OneDrive-specific phrasing (explicitly open OneDrive's Desktop/Documents when requested)
        if "onedrive" in text:
            onedrive_root = self._get_onedrive_root()
            if onedrive_root:
                if "desktop" in text:
                    candidate = os.path.join(onedrive_root, "Desktop")
                    return candidate if os.path.isdir(candidate) else None
                if "documents" in text or "document" in text:
                    candidate = os.path.join(onedrive_root, "Documents")
                    return candidate if os.path.isdir(candidate) else None
                if "pictures" in text or "photos" in text:
                    candidate = os.path.join(onedrive_root, "Pictures")
                    return candidate if os.path.isdir(candidate) else None

        # Keywords → known folder tokens
        # Keep these simple and high-confidence to avoid opening wrong locations.
        if text in {"documents", "document", "my documents"}:
            return self._get_known_folder_path("MyDocuments")
        if text in {"desktop", "my desktop"}:
            return self._get_known_folder_path("Desktop")
        if text in {"pictures", "photos", "my pictures"}:
            return self._get_known_folder_path("MyPictures")

        # Downloads isn't a standard .NET SpecialFolder on older versions; use a reliable fallback.
        if text in {"downloads", "download"}:
            candidate = os.path.join(os.path.expanduser("~"), "Downloads")
            return candidate if os.path.isdir(candidate) else None

        return None

    def _get_known_folder_path(self, special_folder: str) -> str | None:
        """Return a Windows known folder path via PowerShell, with a safe fallback."""
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"[Environment]::GetFolderPath('{special_folder}')",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            path = (result.stdout or "").strip()
            if path and os.path.isdir(path):
                return path
        except Exception:
            pass

        # Fallbacks if PowerShell fails
        home = os.path.expanduser("~")
        fallback_map = {
            "Desktop": os.path.join(home, "Desktop"),
            "MyDocuments": os.path.join(home, "Documents"),
            "MyPictures": os.path.join(home, "Pictures"),
        }
        fallback = fallback_map.get(special_folder)
        return fallback if fallback and os.path.isdir(fallback) else None

    def _get_onedrive_root(self) -> str | None:
        """
        Attempt to locate the user's OneDrive root directory.
        Common environment variables vary depending on account type.
        """
        candidates = [
            os.environ.get("OneDrive", ""),
            os.environ.get("OneDriveConsumer", ""),
            os.environ.get("OneDriveCommercial", ""),
        ]
        for c in candidates:
            c = (c or "").strip().strip('"')
            if c and os.path.isdir(c):
                return c

        # Fallback: typical default location under user profile
        home = os.path.expanduser("~")
        fallback = os.path.join(home, "OneDrive")
        return fallback if os.path.isdir(fallback) else None

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
