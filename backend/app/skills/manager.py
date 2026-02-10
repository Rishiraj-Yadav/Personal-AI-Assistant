"""
Skill Manager - Loads, validates, and manages skills
"""
import json
import os
from pathlib import Path
from typing import Dict, List, Optional
from loguru import logger

from app.skills.schema import SkillManifest, PermissionScope


class SkillManager:
    """Manages skill loading, validation, and registry"""
    
    # def __init__(self, skills_directory: str = "skills"):
    def __init__(self, skills_directory: str = "/app/skills"):
        """
        Initialize skill manager
        
        Args:
            skills_directory: Directory containing skill folders
        """
        self.skills_directory = Path(skills_directory)
        self.skills: Dict[str, SkillManifest] = {}
        self.skills_path: Dict[str, Path] = {}
        
        # Create skills directory if it doesn't exist
        self.skills_directory.mkdir(exist_ok=True)
        
        logger.info(f"Initialized SkillManager with directory: {self.skills_directory}")
    
    def load_skills(self) -> int:
        """
        Load all skills from the skills directory
        
        Returns:
            Number of skills loaded
        """
        loaded_count = 0
        
        if not self.skills_directory.exists():
            logger.warning(f"Skills directory not found: {self.skills_directory}")
            return 0
        
        # Iterate through skill directories
        for skill_dir in self.skills_directory.iterdir():
            if not skill_dir.is_dir():
                continue
            
            manifest_path = skill_dir / "manifest.json"
            
            if not manifest_path.exists():
                logger.warning(f"No manifest.json found in {skill_dir.name}")
                continue
            
            try:
                # Load and validate manifest
                with open(manifest_path, 'r') as f:
                    manifest_data = json.load(f)
                
                manifest = SkillManifest(**manifest_data)
                
                # Store skill
                self.skills[manifest.name] = manifest
                self.skills_path[manifest.name] = skill_dir
                
                loaded_count += 1
                logger.info(f"Loaded skill: {manifest.name} v{manifest.version}")
                
            except Exception as e:
                logger.error(f"Failed to load skill from {skill_dir.name}: {str(e)}")
        
        logger.info(f"Successfully loaded {loaded_count} skills")
        return loaded_count
    
    def get_skill(self, name: str) -> Optional[SkillManifest]:
        """
        Get skill manifest by name
        
        Args:
            name: Skill name
            
        Returns:
            SkillManifest or None if not found
        """
        return self.skills.get(name)
    
    def get_skill_path(self, name: str) -> Optional[Path]:
        """
        Get skill directory path
        
        Args:
            name: Skill name
            
        Returns:
            Path to skill directory or None
        """
        return self.skills_path.get(name)
    
    def list_skills(self) -> List[Dict]:
        """
        List all available skills
        
        Returns:
            List of skill summaries
        """
        return [
            {
                "name": skill.name,
                "version": skill.version,
                "description": skill.description,
                "author": skill.author,
                "permissions": [p.value for p in skill.permissions],
                "parameters": [
                    {
                        "name": p.name,
                        "type": p.type,
                        "description": p.description,
                        "required": p.required
                    }
                    for p in skill.parameters
                ],
                "verified": skill.verified
            }
            for skill in self.skills.values()
        ]
    
    def get_skills_for_llm(self) -> List[Dict]:
        """
        Get skill definitions formatted for LLM function calling
        
        Returns:
            List of function definitions for LLM
        """
        functions = []
        
        for skill in self.skills.values():
            # Build parameters schema
            properties = {}
            required = []
            
            for param in skill.parameters:
                properties[param.name] = {
                    "type": param.type,
                    "description": param.description
                }
                if param.default is not None:
                    properties[param.name]["default"] = param.default
                
                if param.required:
                    required.append(param.name)
            
            # Create function definition
            function_def = {
                "name": skill.name,
                "description": skill.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            }
            
            functions.append(function_def)
        
        return functions
    
    def validate_permissions(self, skill_name: str, user_permissions: List[str]) -> bool:
        """
        Check if user has granted required permissions for skill
        
        Args:
            skill_name: Name of skill
            user_permissions: List of granted permissions
            
        Returns:
            True if all required permissions are granted
        """
        skill = self.get_skill(skill_name)
        if not skill:
            return False
        
        required = {p.value for p in skill.permissions}
        granted = set(user_permissions)
        
        return required.issubset(granted)
    
    def reload_skills(self) -> int:
        """
        Reload all skills from directory
        
        Returns:
            Number of skills loaded
        """
        self.skills.clear()
        self.skills_path.clear()
        return self.load_skills()


# Global skill manager instance
skill_manager = SkillManager()