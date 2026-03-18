"""
Shell Agent — Safe PowerShell/CMD command execution
"""
import subprocess
import os
from typing import Dict, Any, List
from loguru import logger
from agents.base_agent import BaseAgent
from config import settings


class ShellAgent(BaseAgent):
    """Agent for executing shell commands safely"""

    def __init__(self):
        super().__init__(
            name="shell_agent",
            description="Execute PowerShell and CMD commands safely with output capture",
        )

    def _is_blocked(self, command: str) -> bool:
        """Check if a command is blocked for safety"""
        cmd_lower = command.lower().strip()
        for blocked in settings.BLOCKED_COMMANDS:
            if blocked.lower() in cmd_lower:
                return True
        return False

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "run_command",
                "description": "Run a PowerShell command and return output. Use for listing files, checking system info, installing packages with pip, running scripts, etc. Commands that could delete system files or format drives are blocked.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The PowerShell command to execute",
                        },
                        "working_directory": {
                            "type": "string",
                            "description": "Optional working directory. Defaults to user's home folder.",
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Timeout in seconds (default: 30, max: 120)",
                        },
                    },
                    "required": ["command"],
                },
            },
            {
                "name": "run_cmd",
                "description": "Run a CMD (cmd.exe) command. Use when PowerShell is not needed.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The CMD command to execute",
                        },
                        "working_directory": {
                            "type": "string",
                            "description": "Optional working directory",
                        },
                    },
                    "required": ["command"],
                },
            },
        ]

    def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "run_command":
            return self._run_powershell(
                args.get("command", ""),
                args.get("working_directory"),
                args.get("timeout", 30),
            )
        elif tool_name == "run_cmd":
            return self._run_cmd(
                args.get("command", ""),
                args.get("working_directory"),
            )
        return self._error(f"Unknown tool: {tool_name}")

    def _run_powershell(
        self, command: str, cwd: str = None, timeout: int = 30
    ) -> Dict[str, Any]:
        """Run a PowerShell command"""
        if not command:
            return self._error("No command provided")

        if self._is_blocked(command):
            return self._error(
                f"Command blocked for safety: '{command}'. "
                f"Blocked patterns: {settings.BLOCKED_COMMANDS}"
            )

        timeout = min(timeout, 120)
        cwd = cwd or os.path.expanduser("~")

        try:
            logger.info(f"💻 Running PowerShell: {command}")
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                encoding="utf-8",
                errors="replace",
            )

            return self._success(
                {
                    "stdout": result.stdout.strip(),
                    "stderr": result.stderr.strip(),
                    "exit_code": result.returncode,
                },
                f"Command completed (exit code: {result.returncode})",
            )
        except subprocess.TimeoutExpired:
            return self._error(f"Command timed out after {timeout}s")
        except Exception as e:
            return self._error(f"Command failed: {e}")

    def _run_cmd(self, command: str, cwd: str = None) -> Dict[str, Any]:
        """Run a CMD command"""
        if not command:
            return self._error("No command provided")

        if self._is_blocked(command):
            return self._error(f"Command blocked for safety: '{command}'")

        cwd = cwd or os.path.expanduser("~")

        try:
            logger.info(f"💻 Running CMD: {command}")
            result = subprocess.run(
                ["cmd", "/c", command],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=cwd,
                encoding="utf-8",
                errors="replace",
            )

            return self._success(
                {
                    "stdout": result.stdout.strip(),
                    "stderr": result.stderr.strip(),
                    "exit_code": result.returncode,
                },
                f"Command completed (exit code: {result.returncode})",
            )
        except subprocess.TimeoutExpired:
            return self._error("Command timed out after 30s")
        except Exception as e:
            return self._error(f"Command failed: {e}")


# Global instance
shell_agent = ShellAgent()
