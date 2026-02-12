"""
VS Code Launcher
Opens projects in Visual Studio Code
"""
import subprocess
import sys
import platform
from pathlib import Path
from typing import Dict, Optional


class VSCodeLauncher:
    """Launches VS Code with optional project or file"""

    def __init__(self):
        self.system = platform.system()

    def _get_vscode_command(self) -> Optional[str]:
        """Determine VS Code command based on OS"""

        if self.system == "Windows":
            vscode_paths = [
                r"C:\Program Files\Microsoft VS Code\Code.exe",
                r"C:\Program Files (x86)\Microsoft VS Code\Code.exe",
                rf"C:\Users\{Path.home().name}\AppData\Local\Programs\Microsoft VS Code\Code.exe",
                "code"  # If in PATH
            ]

            for path in vscode_paths:
                if Path(path).exists() or path == "code":
                    return path

            return None

        elif self.system == "Darwin":  # macOS
            path = "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
            if Path(path).exists():
                return path
            return "code"

        else:  # Linux
            return "code"

    def execute(self, project_path: str = None, file_path: str = None) -> Dict:
        """Launch VS Code"""

        try:
            vscode_cmd = self._get_vscode_command()

            if not vscode_cmd:
                return {
                    "success": False,
                    "error": "VS Code not found. Please install it."
                }

            cmd = [vscode_cmd]

            if file_path:
                cmd.append(file_path)
            elif project_path:
                cmd.append(project_path)

            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            result = {
                "success": True,
                "application": "VS Code",
                "command": " ".join(cmd)
            }

            if project_path:
                result["project_path"] = project_path
            if file_path:
                result["file_path"] = file_path

            return result

        except FileNotFoundError:
            return {
                "success": False,
                "error": "VS Code not found in PATH."
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }


# ✅ Global instance (like screen_reader_skill)
vscode_launcher = VSCodeLauncher()


if __name__ == "__main__":
    import json

    if len(sys.argv) > 1:
        path = sys.argv[1]
        result = vscode_launcher.execute(project_path=path)
    else:
        result = vscode_launcher.execute()

    print(json.dumps(result, indent=2))










# """
# VS Code Launcher
# Opens projects in Visual Studio Code
# """
# import subprocess
# import sys
# import platform
# from pathlib import Path


# def launch_vscode(project_path: str = None, file_path: str = None):
#     """
#     Launch VS Code with optional project or file
    
#     Args:
#         project_path: Path to project folder
#         file_path: Path to specific file
    
#     Returns:
#         dict: Launch result
#     """
#     try:
#         system = platform.system()
        
#         # Determine VS Code command based on OS
#         if system == "Windows":
#             # Try common VS Code installation paths
#             vscode_paths = [
#                 r"C:\Program Files\Microsoft VS Code\Code.exe",
#                 r"C:\Program Files (x86)\Microsoft VS Code\Code.exe",
#                 r"C:\Users\{}\AppData\Local\Programs\Microsoft VS Code\Code.exe".format(
#                     Path.home().name
#                 ),
#                 "code"  # If in PATH
#             ]
            
#             vscode_cmd = None
#             for path in vscode_paths:
#                 if Path(path).exists() or path == "code":
#                     vscode_cmd = path
#                     break
            
#             if not vscode_cmd:
#                 return {
#                     "success": False,
#                     "error": "VS Code not found. Please install from https://code.visualstudio.com/"
#                 }
        
#         elif system == "Darwin":  # macOS
#             vscode_cmd = "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
#             if not Path(vscode_cmd).exists():
#                 vscode_cmd = "code"  # Try PATH
        
#         else:  # Linux
#             vscode_cmd = "code"
        
#         # Build command
#         cmd = [vscode_cmd]
        
#         if file_path:
#             cmd.append(file_path)
#         elif project_path:
#             cmd.append(project_path)
#         else:
#             # Just open VS Code
#             pass
        
#         # Launch VS Code
#         subprocess.Popen(
#             cmd,
#             stdout=subprocess.DEVNULL,
#             stderr=subprocess.DEVNULL
#         )
        
#         result = {
#             "success": True,
#             "application": "VS Code",
#             "command": " ".join(cmd)
#         }
        
#         if project_path:
#             result["project_path"] = project_path
#         if file_path:
#             result["file_path"] = file_path
        
#         return result
    
#     except FileNotFoundError:
#         return {
#             "success": False,
#             "error": "VS Code not found in PATH. Please install or add to PATH."
#         }
#     except Exception as e:
#         return {
#             "success": False,
#             "error": str(e)
#         }


# if __name__ == "__main__":
#     # For testing
#     import json
    
#     if len(sys.argv) > 1:
#         path = sys.argv[1]
#         result = launch_vscode(project_path=path)
#     else:
#         result = launch_vscode()
    
#     print(json.dumps(result, indent=2))