"""
Skill Executor - Executes skills with sandboxing and resource limits
"""
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional
from loguru import logger

from app.skills.schema import (
    SkillManifest, 
    SkillExecutionResult, 
    SkillType
)
from app.skills.manager import skill_manager


# Desktop skills that should be routed to the desktop agent
DESKTOP_SKILL_NAMES = {
    "open_special_folder", "open_path", "open_url", "launch_app",
    "open_application", "close_application", "list_running_apps", "is_app_running",
    "type_text", "press_key", "press_hotkey", "mouse_click", "mouse_move", "mouse_scroll",
    "take_screenshot", "read_screen_text", "list_windows", "focus_window",
    "minimize_window", "maximize_window", "find_element_coordinates_on_screen",
    "list_directory", "read_file", "write_file", "create_folder", "delete_path",
    "move_path", "copy_path", "search_files", "get_file_info",
    "run_command", "run_cmd", "get_system_info", "get_cpu_usage", "get_memory_usage",
    "get_disk_usage", "get_battery_status", "list_processes", "kill_process",
    "get_clipboard", "set_clipboard", "get_network_info",
    "send_notification", "speak_text", "play_sound",
    "web_search", "fetch_webpage", "download_file", "get_current_datetime", "check_website",
    "ensure_browser", "get_browser_status"
}


class SkillExecutor:
    """Executes skills with sandboxing and monitoring"""
    
    def __init__(self):
        """Initialize skill executor"""
        logger.info("Initialized SkillExecutor")
    
    async def execute_skill(
        self,
        skill_name: str,
        parameters: Dict[str, Any],
        user_id: str = "default_user"
    ) -> SkillExecutionResult:
        """
        Execute a skill with given parameters
        
        Args:
            skill_name: Name of the skill to execute
            parameters: Parameters to pass to the skill
            user_id: User executing the skill
            
        Returns:
            SkillExecutionResult with output or error
        """
        start_time = time.time()
        
        try:
            # Check if this is a desktop skill - route to desktop agent
            if skill_name in DESKTOP_SKILL_NAMES:
                return await self._execute_desktop_skill(skill_name, parameters, start_time)
            
            # Otherwise, try local skill execution
            skill = skill_manager.get_skill(skill_name)
            if not skill:
                # Unknown skill - try desktop agent as fallback
                logger.info(f"Skill '{skill_name}' not in local manager, trying desktop agent")
                return await self._execute_desktop_skill(skill_name, parameters, start_time)
            
            # Validate parameters
            validation_error = self._validate_parameters(skill, parameters)
            if validation_error:
                return SkillExecutionResult(
                    success=False,
                    skill_name=skill_name,
                    output=None,
                    error=validation_error,
                    execution_time=time.time() - start_time
                )
            
            logger.info(f"Executing skill: {skill_name} for user: {user_id}")
            
            # Execute based on skill type
            if skill.execution.type == SkillType.PLAYWRIGHT_SCRIPT:
                result = await self._execute_playwright_script(skill, parameters)
            elif skill.execution.type == SkillType.PYTHON_SCRIPT:
                result = await self._execute_python_script(skill, parameters)
            else:
                return SkillExecutionResult(
                    success=False,
                    skill_name=skill_name,
                    output=None,
                    error=f"Unsupported skill type: {skill.execution.type}",
                    execution_time=time.time() - start_time
                )
            
            execution_time = time.time() - start_time
            logger.info(f"Skill {skill_name} completed in {execution_time:.2f}s")
            
            return SkillExecutionResult(
                success=True,
                skill_name=skill_name,
                output=result,
                execution_time=execution_time
            )
            
        except asyncio.TimeoutError:
            return SkillExecutionResult(
                success=False,
                skill_name=skill_name,
                output=None,
                error="Execution timeout exceeded",
                execution_time=time.time() - start_time
            )
        except Exception as e:
            logger.error(f"Error executing skill {skill_name}: {str(e)}")
            return SkillExecutionResult(
                success=False,
                skill_name=skill_name,
                output=None,
                error=str(e),
                execution_time=time.time() - start_time
            )
    
    async def _execute_desktop_skill(
        self,
        skill_name: str,
        parameters: Dict[str, Any],
        start_time: float
    ) -> SkillExecutionResult:
        """Execute a skill on the desktop agent"""
        from app.skills.desktop_bridge import desktop_bridge
        
        logger.info(f"🖥️ Routing skill to desktop agent: {skill_name}")
        
        result = await desktop_bridge.execute_skill(skill_name, parameters)
        
        execution_time = time.time() - start_time
        
        if result.get("success"):
            return SkillExecutionResult(
                success=True,
                skill_name=skill_name,
                output=result.get("result", result),
                execution_time=execution_time
            )
        else:
            return SkillExecutionResult(
                success=False,
                skill_name=skill_name,
                output=None,
                error=result.get("error", "Desktop skill execution failed"),
                execution_time=execution_time
            )
    
    def _validate_parameters(
        self, 
        skill: SkillManifest, 
        parameters: Dict[str, Any]
    ) -> Optional[str]:
        """
        Validate parameters against skill manifest
        
        Returns:
            Error message if validation fails, None if valid
        """
        # Check required parameters
        for param in skill.parameters:
            if param.required and param.name not in parameters:
                return f"Missing required parameter: {param.name}"
        
        # Check parameter types (basic validation)
        for param in skill.parameters:
            if param.name in parameters:
                value = parameters[param.name]
                
                # Type checking
                if param.type == "string" and not isinstance(value, str):
                    return f"Parameter {param.name} must be a string"
                elif param.type == "number" and not isinstance(value, (int, float)):
                    return f"Parameter {param.name} must be a number"
                elif param.type == "boolean" and not isinstance(value, bool):
                    return f"Parameter {param.name} must be a boolean"
        
        return None
    
    async def _execute_playwright_script(
        self,
        skill: SkillManifest,
        parameters: Dict[str, Any]
    ) -> Any:
        """
        Execute a Playwright-based skill
        
        Args:
            skill: Skill manifest
            parameters: Execution parameters
            
        Returns:
            Script output
        """
        skill_path = skill_manager.get_skill_path(skill.name)
        script_path = skill_path / skill.execution.entry_point
        
        if not script_path.exists():
            raise FileNotFoundError(f"Skill script not found: {script_path}")
        
        # Prepare execution command
        # Pass parameters as JSON via environment variable
        env = {
            **os.environ,
            **skill.execution.environment,
            "SKILL_PARAMS": json.dumps(parameters)
        }
        
        # Execute script with timeout
        process = await asyncio.create_subprocess_exec(
            "python",
            str(script_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(skill_path)
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=skill.execution.timeout
            )
            
            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise Exception(f"Script execution failed: {error_msg}")
            
            # Parse JSON output
            output = stdout.decode().strip()
            try:
                return json.loads(output)
            except json.JSONDecodeError:
                return {"output": output}
                
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise
    
    async def _execute_python_script(
        self,
        skill: SkillManifest,
        parameters: Dict[str, Any]
    ) -> Any:
        """
        Execute a Python script skill
        
        Args:
            skill: Skill manifest
            parameters: Execution parameters
            
        Returns:
            Script output
        """
        skill_path = skill_manager.get_skill_path(skill.name)
        script_path = skill_path / skill.execution.entry_point
        
        if not script_path.exists():
            raise FileNotFoundError(f"Skill script not found: {script_path}")
        
        env = {
            **os.environ,
            **skill.execution.environment,
            "SKILL_PARAMS": json.dumps(parameters)
        }
        
        process = await asyncio.create_subprocess_exec(
            "python",
            str(script_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(skill_path)
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=skill.execution.timeout
            )
            
            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise Exception(f"Script execution failed: {error_msg}")
            
            output = stdout.decode().strip()
            try:
                return json.loads(output)
            except json.JSONDecodeError:
                return {"output": output}
                
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise


# Global executor instance
skill_executor = SkillExecutor()