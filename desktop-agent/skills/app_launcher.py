"""
App Launcher Skill
Launches applications on the desktop
"""
from typing import Dict, Any
import subprocess
import platform
import os
from loguru import logger
from config import settings


class AppLauncherSkill:
    """Launches applications"""
    
    # Browser apps that should get CDP flags for Browser Agent handoff
    BROWSER_APPS = {"chrome", "brave", "edge", "firefox"}
    CDP_PORT = 9222
    
    def __init__(self):
        """Initialize app launcher"""
        self.system = platform.system()
        logger.info(f"AppLauncherSkill initialized for {self.system}")
    
    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Launch an application
        
        Args:
            app: Application name or path
            args: Command line arguments (optional)
            wait: Wait for app to start (optional)
            
        Returns:
            Launch result
        """
        try:
            app = args.get("app", "")
            app_args = args.get("args", [])
            wait = args.get("wait", False)
            
            if not app:
                return {
                    "success": False,
                    "error": "No application specified"
                }
            
            # Normalize app name
            app_lower = app.lower()
            
            # Check for extra flags (e.g., from pipeline engine)
            extra_flags = args.get("flags", [])
            
            # Auto-inject CDP flags for browser apps
            is_browser = app_lower in self.BROWSER_APPS
            if is_browser:
                cdp_flag = f"--remote-debugging-port={self.CDP_PORT}"
                if cdp_flag not in extra_flags:
                    extra_flags.append(cdp_flag)
                logger.info(f"Browser detected: injecting CDP flag → port {self.CDP_PORT}")
            
            # Merge extra flags into app_args
            all_args = app_args + extra_flags
            
            # Get command based on OS and app
            command = self._get_app_command(app_lower, all_args)
            
            if not command:
                return {
                    "success": False,
                    "error": f"Unknown application: {app}. Try full path instead."
                }
            
            # Launch the application
            if wait:
                result = subprocess.run(command, shell=True, capture_output=True, text=True)
                success = result.returncode == 0
                output = result.stdout if success else result.stderr
            else:
                subprocess.Popen(command, shell=True)
                success = True
                output = "Application launched in background"
            
            result_data = {
                "success": success,
                "action": "launch",
                "app": app,
                "command": str(command),
                "output": output[:200] if output else None
            }
            
            # Include CDP info for browser handoff
            if is_browser and success:
                result_data["cdp_port"] = self.CDP_PORT
                result_data["cdp_url"] = f"http://localhost:{self.CDP_PORT}"
                logger.info(f"Browser CDP handoff ready at port {self.CDP_PORT}")
            
            return result_data
        
        except Exception as e:
            logger.error(f"App launch error: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _get_app_command(self, app: str, args: list = None) -> str:
        """
        Get platform-specific command to launch app
        
        Args:
            app: Application name (lowercase)
            args: Additional arguments
            
        Returns:
            Command string or None
        """
        args_str = " ".join(args) if args else ""
        
        # Common applications mapped to commands
        app_map = {
            # Web Browsers
            "chrome": {
                "Windows": f"start chrome {args_str}",
                "Darwin": f"open -a 'Google Chrome' {args_str}",
                "Linux": f"google-chrome {args_str}"
            },
            "firefox": {
                "Windows": f"start firefox {args_str}",
                "Darwin": f"open -a Firefox {args_str}",
                "Linux": f"firefox {args_str}"
            },
            "safari": {
                "Darwin": f"open -a Safari {args_str}"
            },
            "edge": {
                "Windows": f"start msedge {args_str}",
                "Darwin": f"open -a 'Microsoft Edge' {args_str}",
                "Linux": f"microsoft-edge {args_str}"
            },
            "brave": {
                "Windows": f"start brave {args_str}",
                "Darwin": f"open -a 'Brave Browser' {args_str}",
                "Linux": f"brave-browser {args_str}"
            },
            
            # Text Editors
            "notepad": {
                "Windows": f"notepad {args_str}"
            },
            "textedit": {
                "Darwin": f"open -a TextEdit {args_str}"
            },
            "gedit": {
                "Linux": f"gedit {args_str}"
            },
            "code": {
                "Windows": f"code {args_str}",
                "Darwin": f"code {args_str}",
                "Linux": f"code {args_str}"
            },
            "vscode": {
                "Windows": f"code {args_str}",
                "Darwin": f"code {args_str}",
                "Linux": f"code {args_str}"
            },
            
            # Terminals
            "terminal": {
                "Darwin": "open -a Terminal",
                "Linux": "gnome-terminal"
            },
            "cmd": {
                "Windows": "start cmd"
            },
            "powershell": {
                "Windows": "start powershell"
            },
            
            # System Apps
            "calculator": {
                "Windows": "calc",
                "Darwin": "open -a Calculator",
                "Linux": "gnome-calculator"
            },
            "calendar": {
                "Darwin": "open -a Calendar",
                "Linux": "gnome-calendar"
            },
            
            # Communication
            "slack": {
                "Windows": "start slack",
                "Darwin": "open -a Slack",
                "Linux": "slack"
            },
            "discord": {
                "Windows": "start Discord",
                "Darwin": "open -a Discord",
                "Linux": "discord"
            },
            "zoom": {
                "Windows": "start zoom",
                "Darwin": "open -a zoom.us",
                "Linux": "zoom"
            },
            
            # File Managers
            "explorer": {
                "Windows": "explorer"
            },
            "finder": {
                "Darwin": "open -a Finder"
            },
            "files": {
                "Linux": "nautilus"
            }
        }
        
        # Check if app is in our map
        if app in app_map:
            if self.system in app_map[app]:
                return app_map[app][self.system]
        
        # Try common patterns
        if self.system == "Windows":
            return f"start {app} {args_str}"
        elif self.system == "Darwin":
            # Try as application bundle
            return f"open -a '{app}' {args_str}"
        elif self.system == "Linux":
            return f"{app} {args_str}"
        
        return None
    
    def get_available_apps(self) -> Dict[str, Any]:
        """Get list of available applications"""
        # This is a simplified version
        # In production, could scan PATH, Applications folder, etc.
        
        common_apps = list({
            "chrome", "firefox", "safari", "edge",
            "notepad", "textedit", "gedit", "code",
            "terminal", "cmd", "calculator",
            "slack", "discord", "zoom"
        } & set(settings.ALLOWED_APPS))
        
        return {
            "success": True,
            "apps": sorted(common_apps),
            "system": self.system
        }


# Global instance
app_launcher_skill = AppLauncherSkill()