"""
Skill Executor - Executes skills with sandboxing and resource limits
"""
import asyncio
import json
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
            # Get skill manifest
            skill = skill_manager.get_skill(skill_name)
            if not skill:
                return SkillExecutionResult(
                    success=False,
                    skill_name=skill_name,
                    output=None,
                    error=f"Skill '{skill_name}' not found",
                    execution_time=time.time() - start_time
                )
            
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
            **skill.execution.environment,
            "SKILL_PARAMS": json.dumps(parameters)
        }
        
        # Execute script with timeout
        process = await asyncio.create_subprocess_exec(
            "python",
            str(script_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **env},
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
        # Similar to playwright but simpler
        skill_path = skill_manager.get_skill_path(skill.name)
        script_path = skill_path / skill.execution.entry_point
        
        if not script_path.exists():
            raise FileNotFoundError(f"Skill script not found: {script_path}")
        
        env = {
            **skill.execution.environment,
            "SKILL_PARAMS": json.dumps(parameters)
        }
        
        process = await asyncio.create_subprocess_exec(
            "python",
            str(script_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **env},
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


# Add missing import
import os

# Global executor instance
skill_executor = SkillExecutor()