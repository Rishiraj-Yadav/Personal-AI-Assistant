"""
Terminal Executor Skill
Safely executes terminal/shell commands
"""
import subprocess
import platform
import os
from typing import Dict, Any, List, Optional


class TerminalExecutorSkill:
    """Safely executes terminal commands and scripts"""

    # Dangerous commands that should be blocked
    BLOCKED_COMMANDS = [
        "rm -rf /",
        "del /f /s /q",
        "format",
        "mkfs",
        "dd if=",
        ":(){ :|:& };:",  # Fork bomb
        "sudo rm",
        "shutdown",
        "reboot",
        "halt"
    ]

    # Commands that require confirmation
    REQUIRES_CONFIRMATION = [
        "rm",
        "del",
        "rmdir",
        "git push",
        "npm publish",
        "pip uninstall",
        "docker rm",
        "kubectl delete"
    ]

    def __init__(self):
        self.system = platform.system()

    # -----------------------------
    # Execute shell command
    # -----------------------------
    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute shell command safely

        Args:
            command: str
            working_dir: Optional[str]
            timeout: int (default 30)
            safe_mode: bool (default True)
        """

        command: str = args.get("command")
        working_dir: Optional[str] = args.get("working_dir")
        timeout: int = args.get("timeout", 30)
        safe_mode: bool = args.get("safe_mode", True)

        if not command:
            return {"success": False, "error": "No command provided"}

        try:
            # -----------------------------
            # Safety Checks
            # -----------------------------
            if safe_mode:
                # Block dangerous commands
                for blocked in self.BLOCKED_COMMANDS:
                    if blocked.lower() in command.lower():
                        return {
                            "success": False,
                            "error": f"Blocked dangerous command: {blocked}",
                            "requires_confirmation": True
                        }

                # Require confirmation
                for risky in self.REQUIRES_CONFIRMATION:
                    if command.strip().startswith(risky):
                        return {
                            "success": False,
                            "requires_confirmation": True,
                            "confirmation_message": (
                                f"⚠️ Command '{command}' requires confirmation. "
                                "This may modify/delete data."
                            )
                        }

            cwd = working_dir if working_dir else os.getcwd()

            # Windows → wrap in PowerShell
            if self.system == "Windows":
                if not command.startswith("powershell"):
                    command = f'powershell -Command "{command}"'

            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            return {
                "success": result.returncode == 0,
                "action": "execute_command",
                "command": command,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode,
                "working_dir": cwd
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Command timed out after {timeout} seconds",
                "command": command
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "command": command
            }

    # -----------------------------
    # Execute script file
    # -----------------------------
    def execute_script(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a script file

        Args:
            script_path: str
            args: Optional[List[str]]
            working_dir: Optional[str]
            timeout: int (default 60)
        """

        script_path: str = args.get("script_path")
        script_args: List[str] = args.get("args", [])
        working_dir: Optional[str] = args.get("working_dir")
        timeout: int = args.get("timeout", 60)

        if not script_path:
            return {"success": False, "error": "No script_path provided"}

        try:
            if script_path.endswith(".py"):
                cmd = ["python", script_path]
            elif script_path.endswith(".sh"):
                cmd = ["bash", script_path]
            elif script_path.endswith(".ps1"):
                cmd = ["powershell", "-File", script_path]
            elif script_path.endswith(".js"):
                cmd = ["node", script_path]
            else:
                return {
                    "success": False,
                    "error": f"Unsupported script type: {script_path}"
                }

            if script_args:
                cmd.extend(script_args)

            cwd = working_dir if working_dir else os.getcwd()

            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            return {
                "success": result.returncode == 0,
                "action": "execute_script",
                "script": script_path,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Script timed out after {timeout} seconds"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }


# ✅ Global instance (consistent with your architecture)
terminal_executor_skill = TerminalExecutorSkill()


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) > 1:
        cmd = " ".join(sys.argv[1:])
        result = terminal_executor_skill.execute({"command": cmd})
        print(json.dumps(result, indent=2))











# """
# Terminal Executor
# Safely executes terminal/shell commands
# """
# import subprocess
# import platform
# import os
# from typing import Dict, Any, List


# # Dangerous commands that should be blocked
# BLOCKED_COMMANDS = [
#     "rm -rf /",
#     "del /f /s /q",
#     "format",
#     "mkfs",
#     "dd if=",
#     ":(){ :|:& };:",  # Fork bomb
#     "sudo rm",
#     "shutdown",
#     "reboot",
#     "halt"
# ]

# # Commands that require confirmation
# REQUIRES_CONFIRMATION = [
#     "rm",
#     "del",
#     "rmdir",
#     "git push",
#     "npm publish",
#     "pip uninstall",
#     "docker rm",
#     "kubectl delete"
# ]


# def execute_command(
#     command: str,
#     working_dir: str = None,
#     timeout: int = 30,
#     safe_mode: bool = True
# ) -> Dict[str, Any]:
#     """
#     Execute shell command safely
    
#     Args:
#         command: Command to execute
#         working_dir: Working directory
#         timeout: Execution timeout in seconds
#         safe_mode: Enable safety checks
    
#     Returns:
#         Execution result
#     """
#     try:
#         # Safety checks
#         if safe_mode:
#             # Check for blocked commands
#             for blocked in BLOCKED_COMMANDS:
#                 if blocked.lower() in command.lower():
#                     return {
#                         "success": False,
#                         "error": f"Blocked dangerous command: {blocked}",
#                         "requires_confirmation": True
#                     }
            
#             # Check for commands requiring confirmation
#             for risky in REQUIRES_CONFIRMATION:
#                 if command.startswith(risky):
#                     return {
#                         "success": False,
#                         "requires_confirmation": True,
#                         "confirmation_message": f"⚠️ Command '{command}' requires confirmation. This may modify/delete data."
#                     }
        
#         # Set working directory
#         cwd = working_dir if working_dir else os.getcwd()
        
#         # Determine shell
#         system = platform.system()
#         if system == "Windows":
#             shell = True
#             # Use PowerShell for better compatibility
#             if not command.startswith("powershell"):
#                 command = f"powershell -Command \"{command}\""
#         else:
#             shell = True
        
#         # Execute command
#         result = subprocess.run(
#             command,
#             shell=shell,
#             cwd=cwd,
#             capture_output=True,
#             text=True,
#             timeout=timeout
#         )
        
#         return {
#             "success": result.returncode == 0,
#             "command": command,
#             "stdout": result.stdout,
#             "stderr": result.stderr,
#             "exit_code": result.returncode,
#             "working_dir": cwd
#         }
    
#     except subprocess.TimeoutExpired:
#         return {
#             "success": False,
#             "error": f"Command timed out after {timeout} seconds",
#             "command": command
#         }
#     except Exception as e:
#         return {
#             "success": False,
#             "error": str(e),
#             "command": command
#         }


# def execute_script(
#     script_path: str,
#     args: List[str] = None,
#     working_dir: str = None,
#     timeout: int = 60
# ) -> Dict[str, Any]:
#     """
#     Execute a script file
    
#     Args:
#         script_path: Path to script
#         args: Script arguments
#         working_dir: Working directory
#         timeout: Timeout in seconds
    
#     Returns:
#         Execution result
#     """
#     try:
#         # Determine how to run based on file extension
#         system = platform.system()
        
#         if script_path.endswith('.py'):
#             cmd = ['python', script_path]
#         elif script_path.endswith('.sh'):
#             cmd = ['bash', script_path]
#         elif script_path.endswith('.ps1'):
#             cmd = ['powershell', '-File', script_path]
#         elif script_path.endswith('.js'):
#             cmd = ['node', script_path]
#         else:
#             return {
#                 "success": False,
#                 "error": f"Unsupported script type: {script_path}"
#             }
        
#         # Add arguments
#         if args:
#             cmd.extend(args)
        
#         # Execute
#         cwd = working_dir if working_dir else os.getcwd()
        
#         result = subprocess.run(
#             cmd,
#             cwd=cwd,
#             capture_output=True,
#             text=True,
#             timeout=timeout
#         )
        
#         return {
#             "success": result.returncode == 0,
#             "script": script_path,
#             "stdout": result.stdout,
#             "stderr": result.stderr,
#             "exit_code": result.returncode
#         }
    
#     except subprocess.TimeoutExpired:
#         return {
#             "success": False,
#             "error": f"Script timed out after {timeout} seconds"
#         }
#     except Exception as e:
#         return {
#             "success": False,
#             "error": str(e)
#         }


# if __name__ == "__main__":
#     # For testing
#     import json
#     import sys
    
#     if len(sys.argv) > 1:
#         cmd = " ".join(sys.argv[1:])
#         result = execute_command(cmd)
#         print(json.dumps(result, indent=2))