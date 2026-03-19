"""
App Agent — Launch, close, and discover applications
"""
import os
import subprocess
import shutil
import time
import json
from urllib.parse import urlparse
from typing import Dict, Any, List
from loguru import logger
from agents.base_agent import BaseAgent

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


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

    def _normalize_app_name(self, name: str) -> str:
        return name.lower().strip().replace(".exe", "")

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
            return self._error("No application name provided", error_code="validation_failed")

        # Check if it's a URL
        if name.startswith(("http://", "https://", "www.")):
            try:
                os.startfile(name)
                time.sleep(1.0)
                verification = self._verify_open_target(name, "url")
                if not verification["verified"]:
                    return self._error(
                        f"Opened the URL command but could not verify browser launch for {name}",
                        error_code="verification_failed",
                        retryable=True,
                        observed_state=verification["observed_state"],
                        evidence=verification["evidence"],
                    )
                return self._success(
                    {"opened": name, "type": "url"},
                    f"Opened URL: {name}",
                    observed_state=verification["observed_state"],
                    evidence=verification["evidence"],
                )
            except Exception as e:
                return self._error(f"Failed to open URL: {e}", retryable=True)

        # Check if it's a folder path
        if os.path.isdir(name):
            try:
                normalized_path = os.path.normpath(name)
                try:
                    subprocess.Popen(
                        ["explorer.exe", normalized_path],
                        shell=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    os.startfile(normalized_path)
                time.sleep(1.0)
                verification = self._verify_open_target(normalized_path, "folder")
                if not verification["verified"]:
                    return self._error(
                        f"Opened Explorer for {normalized_path}, but could not verify that Explorer navigated to that folder.",
                        error_code="verification_failed",
                        retryable=True,
                        observed_state=verification["observed_state"],
                        evidence=verification["evidence"],
                    )
                return self._success(
                    {"opened": normalized_path, "type": "folder"},
                    f"Opened folder: {normalized_path}",
                    observed_state=verification["observed_state"],
                    evidence=verification["evidence"],
                )
            except Exception as e:
                return self._error(f"Failed to open folder: {e}", retryable=True)

        # Check if it's a file path
        if os.path.isfile(name):
            try:
                os.startfile(name)
                time.sleep(0.5)
                return self._success(
                    {"opened": name, "type": "file"},
                    f"Opened file: {name}",
                    observed_state={"path": name, "exists": os.path.isfile(name)},
                    evidence=[{"type": "path", "path": name}],
                )
            except Exception as e:
                return self._error(f"Failed to open file: {e}", retryable=True)

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
                time.sleep(1.0)
                verification = self._verify_open_target(name, "application")
                if not verification["verified"]:
                    return self._error(
                        f"Launched {name}, but the desktop agent could not verify that it opened.",
                        error_code="verification_failed",
                        retryable=True,
                        observed_state=verification["observed_state"],
                        evidence=verification["evidence"],
                    )
                return self._success(
                    {"opened": name, "path": app_path, "type": "application"},
                    f"Opened {name}",
                    observed_state=verification["observed_state"],
                    evidence=verification["evidence"],
                )
            except Exception as e:
                return self._error(f"Failed to open {name}: {e}", retryable=True)

        # Last resort: try os.startfile with the raw name
        try:
            os.startfile(name)
            time.sleep(1.0)
            verification = self._verify_open_target(name, "application")
            return self._success(
                {"opened": name, "type": "system_default"},
                f"Opened {name} via system default handler",
                observed_state=verification["observed_state"],
                evidence=verification["evidence"],
            )
        except Exception:
            return self._error(
                f"Could not find application '{name}'. "
                f"Available apps include: {', '.join(list(self._app_cache.keys())[:20])}",
                error_code="not_found",
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
                verification = self._collect_process_matches(name)
                still_running = bool(verification)
                if still_running:
                    return self._error(
                        f"Close command ran, but {name} still appears to be running.",
                        error_code="verification_failed",
                        retryable=True,
                        observed_state={"requested_app": name, "still_running": True},
                        evidence=[{"type": "process_list", "processes": verification[:10]}],
                    )
                return self._success(
                    {"closed": name},
                    f"Closed {name}",
                    observed_state={"requested_app": name, "still_running": False},
                )
            else:
                return self._error(f"Could not close {name}: {result.stderr.strip()}", retryable=True)
        except Exception as e:
            return self._error(f"Failed to close {name}: {e}", retryable=True)

    def _list_running(self) -> Dict[str, Any]:
        """List running apps with visible windows"""
        try:
            windows = self._collect_window_matches("")
            return self._success(
                {"running_apps": windows, "count": len(windows)},
                f"Found running applications",
                observed_state={"window_count": len(windows)},
                evidence=[{"type": "window_list", "titles": [window.get("title", "") for window in windows[:10]]}],
            )
        except Exception as e:
            return self._error(f"Failed to list running apps: {e}", retryable=True)

    def _is_running(self, name: str) -> Dict[str, Any]:
        """Check if an app is running"""
        try:
            processes = self._collect_process_matches(name)
            is_running = bool(processes)
            return self._success(
                {"is_running": is_running, "processes": processes},
                f"{name} is {'running' if is_running else 'not running'}",
                observed_state={"requested_app": name, "is_running": is_running},
                evidence=[{"type": "process_list", "processes": processes[:10]}],
            )
        except Exception as e:
            return self._error(f"Failed to check {name}: {e}", retryable=True)

    def _collect_process_matches(self, name: str) -> List[Dict[str, Any]]:
        normalized_target = self._normalize_app_name(name)
        matches: List[Dict[str, Any]] = []

        if HAS_PSUTIL:
            for proc in psutil.process_iter(["pid", "name", "exe"]):
                try:
                    proc_name = self._normalize_app_name(proc.info.get("name") or "")
                    if not normalized_target or normalized_target in proc_name:
                        matches.append(
                            {
                                "pid": proc.info.get("pid"),
                                "name": proc.info.get("name"),
                                "path": proc.info.get("exe"),
                            }
                        )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return matches

        result = subprocess.run(
            [
                "powershell",
                "-Command",
                (
                    "Get-Process | Select-Object ProcessName, Id | "
                    "ConvertTo-Json -Depth 2"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = (result.stdout or "").strip()
        if not output:
            return matches
        import json

        parsed = json.loads(output)
        items = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            proc_name = self._normalize_app_name(item.get("ProcessName", ""))
            if not normalized_target or normalized_target in proc_name:
                matches.append(
                    {
                        "pid": item.get("Id"),
                        "name": item.get("ProcessName"),
                        "path": None,
                    }
                )
        return matches

    def _collect_window_matches(self, title_query: str) -> List[Dict[str, Any]]:
        result = subprocess.run(
            [
                "powershell",
                "-Command",
                (
                    "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} | "
                    "Select-Object ProcessName, MainWindowTitle, Id | ConvertTo-Json -Depth 2"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = (result.stdout or "").strip()
        if not output:
            return []
        import json

        parsed = json.loads(output)
        items = parsed if isinstance(parsed, list) else [parsed]
        normalized_query = title_query.lower().strip()
        windows: List[Dict[str, Any]] = []
        for item in items:
            title = str(item.get("MainWindowTitle", "") or "")
            if normalized_query and normalized_query not in title.lower():
                continue
            windows.append(
                {
                    "process_name": item.get("ProcessName"),
                    "title": title,
                    "pid": item.get("Id"),
                }
            )
        return windows

    def _verify_open_target(self, name: str, target_type: str) -> Dict[str, Any]:
        requested = name.strip()
        requested_lower = requested.lower()
        processes = self._collect_process_matches(requested)
        windows = self._collect_window_matches(requested)
        evidence: List[Dict[str, Any]] = []

        if processes:
            evidence.append({"type": "process_list", "processes": processes[:10]})
        if windows:
            evidence.append({"type": "window_list", "windows": windows[:10]})

        verified = bool(processes or windows)

        if target_type == "folder":
            normalized_requested = os.path.normpath(requested).lower()
            folder_name = os.path.basename(normalized_requested)
            explorer_windows = self._list_explorer_windows()
            exact_matches = [
                window for window in explorer_windows
                if os.path.normpath(str(window.get("path", ""))).lower() == normalized_requested
            ]
            title_matches = [
                window for window in explorer_windows
                if folder_name and folder_name in str(window.get("title", "")).lower()
            ]
            if explorer_windows:
                evidence.append({"type": "explorer_windows", "windows": explorer_windows[:10]})
            verified = bool(exact_matches or title_matches)
            observed_state = {
                "requested": requested,
                "target_type": target_type,
                "verified": verified,
                "folder_exists": os.path.isdir(requested),
                "matching_explorer_paths": [window.get("path", "") for window in exact_matches],
                "explorer_window_count": len(explorer_windows),
            }
            return {
                "verified": verified,
                "observed_state": observed_state,
                "evidence": evidence,
            }

        if target_type == "url":
            domain = urlparse(requested if requested.startswith(("http://", "https://")) else f"https://{requested}").netloc.lower()
            browser_processes = []
            for browser_name in ("chrome", "msedge", "edge", "firefox", "brave", "opera"):
                browser_processes.extend(self._collect_process_matches(browser_name))
            domain_windows = [window for window in self._collect_window_matches("") if domain and domain in window.get("title", "").lower()]
            if browser_processes:
                evidence.append({"type": "browser_processes", "processes": browser_processes[:10]})
            if domain_windows:
                evidence.append({"type": "browser_windows", "windows": domain_windows[:10]})
            verified = bool(browser_processes or domain_windows)
            processes = browser_processes or processes
            windows = domain_windows or windows

        observed_state = {
            "requested": requested,
            "target_type": target_type,
            "verified": verified,
            "process_count": len(processes),
            "window_count": len(windows),
        }
        return {
            "verified": verified,
            "observed_state": observed_state,
            "evidence": evidence,
        }

    def _list_explorer_windows(self) -> List[Dict[str, Any]]:
        script = r"""
        $items = @()
        $shell = New-Object -ComObject Shell.Application
        foreach ($window in $shell.Windows()) {
            try {
                $path = $window.Document.Folder.Self.Path
                if ($path) {
                    $items += [PSCustomObject]@{
                        title = $window.LocationName
                        path = $path
                        location_url = $window.LocationURL
                    }
                }
            } catch {}
        }
        $items | ConvertTo-Json -Depth 3
        """
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=10,
            )
            output = (result.stdout or "").strip()
            if result.returncode != 0 or not output:
                return []
            parsed = json.loads(output)
            return parsed if isinstance(parsed, list) else [parsed]
        except Exception:
            return []


# Global instance
app_agent = AppAgent()
