"""
Predictive Context Manager - Phase 6 Pillar 4
===============================================

Moves beyond reactive memory to predictive tracking:
- last_folder, recent_paths, frequent_paths
- active_project detection
- current_task inference
- Path frequency analysis
"""

import os
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from pathlib import Path
from loguru import logger


@dataclass
class PredictiveContext:
    """
    Rich context for predictive intelligence.
    
    Tracks user behavior patterns for intelligent suggestions
    and fast-path resolution.
    """
    # Recent activity
    last_folder: Optional[str] = None
    last_file: Optional[str] = None
    last_app: Optional[str] = None
    last_url: Optional[str] = None
    
    # Path tracking
    recent_paths: List[str] = field(default_factory=list)
    frequent_paths: List[str] = field(default_factory=list)
    
    # Project context
    active_project: Optional[str] = None
    active_project_type: Optional[str] = None  # python, node, react, etc.
    
    # Task context
    current_task: Optional[str] = None
    task_started_at: Optional[str] = None
    
    # User preferences (learned)
    preferred_editor: str = "vscode"
    preferred_browser: str = "chrome"
    preferred_terminal: str = "powershell"
    
    # Statistics
    path_frequency: Dict[str, int] = field(default_factory=dict)
    app_frequency: Dict[str, int] = field(default_factory=dict)
    
    # Session info
    session_start: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_activity: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "last_folder": self.last_folder,
            "last_file": self.last_file,
            "last_app": self.last_app,
            "last_url": self.last_url,
            "recent_paths": self.recent_paths[:10],
            "frequent_paths": self.frequent_paths[:5],
            "active_project": self.active_project,
            "active_project_type": self.active_project_type,
            "current_task": self.current_task,
            "task_started_at": self.task_started_at,
            "preferred_editor": self.preferred_editor,
            "preferred_browser": self.preferred_browser,
            "session_start": self.session_start,
            "last_activity": self.last_activity,
        }


class PredictiveContextManager:
    """
    Phase 6 Predictive Context Engine
    
    Manages context with predictive intelligence:
    - Tracks recent and frequent paths
    - Detects active project automatically
    - Infers current task from activity patterns
    - Provides context for fast-path target resolution
    """
    
    # Project detection files
    PROJECT_MARKERS = {
        "python": ["requirements.txt", "setup.py", "pyproject.toml", "Pipfile"],
        "node": ["package.json"],
        "react": ["package.json"],  # Detected by checking dependencies
        "rust": ["Cargo.toml"],
        "go": ["go.mod"],
        "java": ["pom.xml", "build.gradle"],
        "dotnet": ["*.csproj", "*.sln"],
    }
    
    MAX_RECENT_PATHS = 20
    MAX_FREQUENT_PATHS = 10
    
    def __init__(self, persistence_path: Optional[str] = None):
        """
        Initialize the Predictive Context Manager.
        
        Args:
            persistence_path: Path to persist context across sessions
        """
        self.context = PredictiveContext()
        self.persistence_path = persistence_path
        
        # Load persisted context if available
        if persistence_path:
            self._load_context()
        
        logger.info("✅ PredictiveContextManager initialized")
    
    def update(self, updates: Dict[str, Any]) -> None:
        """
        Apply context updates from execution feedback.
        
        Args:
            updates: Dict with keys matching PredictiveContext fields
        """
        now = datetime.now(timezone.utc).isoformat()
        self.context.last_activity = now
        
        # Handle special update keys
        if "add_recent_path" in updates:
            self._add_recent_path(updates.pop("add_recent_path"))
        
        # Apply direct updates
        for key, value in updates.items():
            if hasattr(self.context, key):
                setattr(self.context, key, value)
                
                # Update frequency tracking
                if key == "last_folder" and value:
                    self._track_path_frequency(value)
                elif key == "last_app" and value:
                    self._track_app_frequency(value)
        
        # Auto-detect project if folder changed
        if "last_folder" in updates:
            self._detect_project(updates["last_folder"])
        
        # Persist context
        if self.persistence_path:
            self._save_context()
        
        logger.debug(f"📝 Context updated: {list(updates.keys())}")
    
    def get_context(self) -> Dict[str, Any]:
        """Get current context as dict for routing decisions."""
        return self.context.to_dict()
    
    def get_context_for_resolution(self) -> Dict[str, Any]:
        """
        Get context optimized for target resolution.
        
        Used by MasterIntentRouter to resolve ambiguous targets
        like "python project" to actual paths.
        """
        return {
            "active_project": self.context.active_project,
            "recent_paths": self.context.recent_paths[:10],
            "frequent_paths": self.context.frequent_paths[:5],
            "last_folder": self.context.last_folder,
            "last_file": self.context.last_file,
            "current_task": self.context.current_task,
        }
    
    def set_current_task(self, task_description: str) -> None:
        """Set the current task being worked on."""
        self.context.current_task = task_description
        self.context.task_started_at = datetime.now(timezone.utc).isoformat()
        logger.info(f"📋 Current task: {task_description}")
    
    def clear_current_task(self) -> None:
        """Clear the current task."""
        self.context.current_task = None
        self.context.task_started_at = None
    
    def suggest_paths(self, query: str, limit: int = 5) -> List[str]:
        """
        Suggest paths based on query and context.
        
        Args:
            query: Search query (e.g., "python", "project", folder name)
            limit: Maximum suggestions to return
            
        Returns:
            List of suggested paths ranked by relevance
        """
        query_lower = query.lower()
        suggestions = []
        
        # Score each path
        scored_paths = []
        all_paths = (
            self.context.frequent_paths +
            self.context.recent_paths +
            ([self.context.active_project] if self.context.active_project else [])
        )
        
        seen = set()
        for path in all_paths:
            if not path or path in seen:
                continue
            seen.add(path)
            
            score = 0
            path_lower = path.lower()
            
            # Direct match
            if query_lower in path_lower:
                score += 10
            
            # Project type match
            if self.context.active_project_type and query_lower == self.context.active_project_type:
                if path == self.context.active_project:
                    score += 15
            
            # Frequency bonus
            freq = self.context.path_frequency.get(path, 0)
            score += min(freq, 5)  # Cap at 5
            
            # Recency bonus
            if path in self.context.recent_paths[:5]:
                score += 3
            
            if score > 0:
                scored_paths.append((path, score))
        
        # Sort by score descending
        scored_paths.sort(key=lambda x: x[1], reverse=True)
        
        return [p[0] for p in scored_paths[:limit]]
    
    def _add_recent_path(self, path: str) -> None:
        """Add a path to recent paths, maintaining uniqueness and limit."""
        if not path:
            return
        
        # Remove if already exists (will be re-added at front)
        if path in self.context.recent_paths:
            self.context.recent_paths.remove(path)
        
        # Add at front
        self.context.recent_paths.insert(0, path)
        
        # Trim to max
        self.context.recent_paths = self.context.recent_paths[:self.MAX_RECENT_PATHS]
    
    def _track_path_frequency(self, path: str) -> None:
        """Track path access frequency."""
        if not path:
            return
        
        self.context.path_frequency[path] = self.context.path_frequency.get(path, 0) + 1
        
        # Update frequent paths list
        sorted_paths = sorted(
            self.context.path_frequency.items(),
            key=lambda x: x[1],
            reverse=True
        )
        self.context.frequent_paths = [p[0] for p in sorted_paths[:self.MAX_FREQUENT_PATHS]]
    
    def _track_app_frequency(self, app: str) -> None:
        """Track app usage frequency."""
        if not app:
            return
        
        self.context.app_frequency[app] = self.context.app_frequency.get(app, 0) + 1
    
    def _detect_project(self, folder: str) -> None:
        """
        Auto-detect project type from folder contents.
        
        Args:
            folder: Path to check for project markers
        """
        if not folder or not os.path.isdir(folder):
            return
        
        try:
            contents = set(os.listdir(folder))
            
            # Check each project type
            for project_type, markers in self.PROJECT_MARKERS.items():
                for marker in markers:
                    if "*" in marker:
                        # Glob pattern
                        import fnmatch
                        if any(fnmatch.fnmatch(f, marker) for f in contents):
                            self._set_active_project(folder, project_type)
                            return
                    elif marker in contents:
                        # Check for React specifically
                        if project_type == "node" and "package.json" in contents:
                            pkg_path = os.path.join(folder, "package.json")
                            if self._is_react_project(pkg_path):
                                self._set_active_project(folder, "react")
                                return
                        
                        self._set_active_project(folder, project_type)
                        return
            
            # Check parent folders for project root
            parent = os.path.dirname(folder)
            if parent and parent != folder:
                # Only check 2 levels up
                depth = folder.count(os.sep) - parent.count(os.sep)
                if depth < 3:
                    self._detect_project(parent)
                    
        except Exception as e:
            logger.debug(f"Project detection error: {e}")
    
    def _set_active_project(self, path: str, project_type: str) -> None:
        """Set the active project."""
        self.context.active_project = path
        self.context.active_project_type = project_type
        logger.info(f"🎯 Active project: {path} ({project_type})")
    
    def _is_react_project(self, package_json_path: str) -> bool:
        """Check if package.json indicates a React project."""
        try:
            with open(package_json_path, 'r') as f:
                pkg = json.load(f)
                deps = pkg.get("dependencies", {})
                dev_deps = pkg.get("devDependencies", {})
                all_deps = {**deps, **dev_deps}
                return "react" in all_deps
        except:
            return False
    
    def _save_context(self) -> None:
        """Persist context to file."""
        if not self.persistence_path:
            return
        
        try:
            data = {
                "recent_paths": self.context.recent_paths,
                "frequent_paths": self.context.frequent_paths,
                "path_frequency": self.context.path_frequency,
                "app_frequency": self.context.app_frequency,
                "preferred_editor": self.context.preferred_editor,
                "preferred_browser": self.context.preferred_browser,
                "preferred_terminal": self.context.preferred_terminal,
            }
            
            os.makedirs(os.path.dirname(self.persistence_path), exist_ok=True)
            with open(self.persistence_path, 'w') as f:
                json.dump(data, f, indent=2)
                
        except Exception as e:
            logger.error(f"❌ Failed to save context: {e}")
    
    def _load_context(self) -> None:
        """Load persisted context from file."""
        if not self.persistence_path or not os.path.exists(self.persistence_path):
            return
        
        try:
            with open(self.persistence_path, 'r') as f:
                data = json.load(f)
            
            self.context.recent_paths = data.get("recent_paths", [])
            self.context.frequent_paths = data.get("frequent_paths", [])
            self.context.path_frequency = data.get("path_frequency", {})
            self.context.app_frequency = data.get("app_frequency", {})
            self.context.preferred_editor = data.get("preferred_editor", "vscode")
            self.context.preferred_browser = data.get("preferred_browser", "chrome")
            self.context.preferred_terminal = data.get("preferred_terminal", "powershell")
            
            logger.info(f"📂 Loaded persisted context ({len(self.context.recent_paths)} recent paths)")
            
        except Exception as e:
            logger.error(f"❌ Failed to load context: {e}")


# Global instance
_context_manager: Optional[PredictiveContextManager] = None


def get_predictive_context_manager(
    persistence_path: Optional[str] = None
) -> PredictiveContextManager:
    """Get or create the global PredictiveContextManager instance."""
    global _context_manager
    if _context_manager is None:
        _context_manager = PredictiveContextManager(persistence_path=persistence_path)
    return _context_manager
