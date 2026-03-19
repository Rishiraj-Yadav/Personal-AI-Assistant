"""
Window Manager Skill
Manages application windows - focus, minimize, maximize, close
"""
from typing import Dict, Any, List
import psutil
import platform
from loguru import logger


class WindowManagerSkill:
    """Manages application windows"""
    
    def __init__(self):
        """Initialize window manager"""
        self.system = platform.system()
        
        # Import platform-specific libraries
        if self.system == "Windows":
            try:
                import win32gui
                import win32con
                self.win32gui = win32gui
                self.win32con = win32con
            except ImportError:
                logger.warning("pywin32 not installed - limited Windows functionality")
                self.win32gui = None
        
        logger.info(f"WindowManagerSkill initialized for {self.system}")
    
    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Manage windows
        
        Args:
            action: list, focus, minimize, maximize, close
            window_id: Window identifier
            title: Window title (partial match)
            process_name: Process name
            
        Returns:
            Action result
        """
        try:
            action = args.get("action", "list")
            
            if action == "list":
                return self._list_windows()
            
            elif action == "focus":
                return self._focus_window(args)
            
            elif action == "minimize":
                return self._minimize_window(args)
            
            elif action == "maximize":
                return self._maximize_window(args)
            
            elif action == "close":
                return self._close_window(args)
            
            elif action == "get_active":
                return self._get_active_window()
            
            else:
                return {
                    "success": False,
                    "error": f"Unknown action: {action}"
                }
        
        except Exception as e:
            logger.error(f"Window manager error: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _list_windows(self) -> Dict[str, Any]:
        """List all open windows"""
        windows = []
        
        if self.system == "Windows" and self.win32gui:
            def callback(hwnd, windows_list):
                if self.win32gui.IsWindowVisible(hwnd):
                    title = self.win32gui.GetWindowText(hwnd)
                    if title:
                        windows_list.append({
                            "id": hwnd,
                            "title": title
                        })
            
            self.win32gui.EnumWindows(callback, windows)
        
        elif self.system == "Darwin":
            # macOS - use AppleScript
            import subprocess
            script = '''
            tell application "System Events"
                set windowList to {}
                repeat with proc in (every process whose background only is false)
                    repeat with win in (windows of proc)
                        set end of windowList to name of win
                    end repeat
                end repeat
                return windowList
            end tell
            '''
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                titles = result.stdout.strip().split(', ')
                windows = [{"id": i, "title": t} for i, t in enumerate(titles) if t]
        
        elif self.system == "Linux":
            # Linux - use wmctrl if available
            import subprocess
            try:
                result = subprocess.run(
                    ['wmctrl', '-l'],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n'):
                        parts = line.split(None, 3)
                        if len(parts) >= 4:
                            windows.append({
                                "id": parts[0],
                                "title": parts[3]
                            })
            except FileNotFoundError:
                logger.warning("wmctrl not installed - cannot list windows")
        
        return {
            "success": True,
            "action": "list",
            "windows": windows,
            "count": len(windows)
        }
    
    def _focus_window(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Focus/activate a window"""
        title = args.get("title", "")
        
        if not title:
            return {
                "success": False,
                "error": "No window title provided"
            }
        
        if self.system == "Darwin":
            # macOS - use AppleScript
            import subprocess
            script = f'''
            tell application "System Events"
                set frontmost of first process whose name contains "{title}" to true
            end tell
            '''
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True
            )
            success = result.returncode == 0
        
        elif self.system == "Windows" and self.win32gui:
            # Find window by title
            hwnd = self.win32gui.FindWindow(None, title)
            if hwnd:
                self.win32gui.SetForegroundWindow(hwnd)
                success = True
            else:
                success = False
        
        else:
            success = False
        
        return {
            "success": success,
            "action": "focus",
            "title": title
        }
    
    def _minimize_window(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Minimize a window"""
        title = args.get("title", "")
        
        if self.system == "Windows" and self.win32gui:
            hwnd = self.win32gui.FindWindow(None, title)
            if hwnd:
                self.win32gui.ShowWindow(hwnd, self.win32con.SW_MINIMIZE)
                success = True
            else:
                success = False
        else:
            success = False
        
        return {
            "success": success,
            "action": "minimize",
            "title": title
        }
    
    def _maximize_window(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Maximize a window"""
        title = args.get("title", "")
        
        if self.system == "Windows" and self.win32gui:
            hwnd = self.win32gui.FindWindow(None, title)
            if hwnd:
                self.win32gui.ShowWindow(hwnd, self.win32con.SW_MAXIMIZE)
                success = True
            else:
                success = False
        else:
            success = False
        
        return {
            "success": success,
            "action": "maximize",
            "title": title
        }
    
    def _close_window(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Close a window"""
        title = args.get("title", "")
        
        if self.system == "Windows" and self.win32gui:
            hwnd = self.win32gui.FindWindow(None, title)
            if hwnd:
                self.win32gui.PostMessage(hwnd, self.win32con.WM_CLOSE, 0, 0)
                success = True
            else:
                success = False
        else:
            success = False
        
        return {
            "success": success,
            "action": "close",
            "title": title
        }
    
    def _get_active_window(self) -> Dict[str, Any]:
        """Get currently active window"""
        if self.system == "Windows" and self.win32gui:
            hwnd = self.win32gui.GetForegroundWindow()
            title = self.win32gui.GetWindowText(hwnd)
        else:
            title = "Unknown"
        
        return {
            "success": True,
            "action": "get_active",
            "title": title
        }


# Global instance
window_manager_skill = WindowManagerSkill()