"""Active Context Tracker - Phase 2"""
import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from loguru import logger

@dataclass
class FileContext:
    path: str
    name: str
    language: Optional[str] = None
    last_modified: Optional[datetime] = None
    is_open: bool = True
    cursor_line: Optional[int] = None
    snippet: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class AppContext:
    name: str
    window_title: Optional[str] = None
    tab_info: Optional[str] = None
    state: str = "active"
    last_active: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ActionContext:
    action_type: str
    description: str
    target: Optional[str] = None
    result: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class UserActiveContext:
    user_id: str
    current_file: Optional[FileContext] = None
    recent_files: List[FileContext] = field(default_factory=list)
    current_app: Optional[AppContext] = None
    recent_apps: List[AppContext] = field(default_factory=list)
    recent_actions: List[ActionContext] = field(default_factory=list)
    working_directory: Optional[str] = None
    project_name: Optional[str] = None
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class ActiveContextTracker:
    def __init__(self, max_recent_files: int = 5, max_recent_apps: int = 3, max_recent_actions: int = 10, action_ttl_minutes: int = 30):
        self.max_recent_files = max_recent_files
        self.max_recent_apps = max_recent_apps
        self.max_recent_actions = max_recent_actions
        self.action_ttl = action_ttl_minutes * 60
        self._contexts: Dict[str, UserActiveContext] = {}
        self._lock = asyncio.Lock()
        self._language_map = {".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "typescript-react", ".jsx": "javascript-react", ".java": "java", ".cpp": "cpp", ".c": "c", ".go": "go", ".rs": "rust", ".rb": "ruby", ".php": "php", ".cs": "csharp", ".html": "html", ".css": "css", ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".md": "markdown", ".sql": "sql", ".sh": "bash"}
        logger.info("ActiveContextTracker initialized")

    def _get_language(self, file_path: str) -> Optional[str]:
        for ext, lang in self._language_map.items():
            if file_path.lower().endswith(ext):
                return lang
        return None

    def _extract_filename(self, file_path: str) -> str:
        parts = re.split(r'[/\\]', file_path)
        return parts[-1] if parts else file_path

    async def get_or_create_context(self, user_id: str) -> UserActiveContext:
        async with self._lock:
            if user_id not in self._contexts:
                self._contexts[user_id] = UserActiveContext(user_id=user_id)
            return self._contexts[user_id]

    async def set_current_file(self, user_id: str, file_path: str, cursor_line: Optional[int] = None, snippet: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> FileContext:
        context = await self.get_or_create_context(user_id)
        async with self._lock:
            file_ctx = FileContext(path=file_path, name=self._extract_filename(file_path), language=self._get_language(file_path), cursor_line=cursor_line, snippet=snippet, metadata=metadata or {})
            if context.current_file and context.current_file.path != file_path:
                context.current_file.is_open = False
                context.recent_files.insert(0, context.current_file)
                context.recent_files = context.recent_files[:self.max_recent_files]
            context.current_file = file_ctx
            context.last_updated = datetime.now(timezone.utc)
            logger.debug(f"Set current file for {user_id}: {file_path}")
            return file_ctx

    async def set_current_app(self, user_id: str, app_name: str, window_title: Optional[str] = None, tab_info: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> AppContext:
        context = await self.get_or_create_context(user_id)
        async with self._lock:
            app_ctx = AppContext(name=app_name, window_title=window_title, tab_info=tab_info, metadata=metadata or {})
            if context.current_app and context.current_app.name != app_name:
                context.current_app.state = "background"
                context.recent_apps.insert(0, context.current_app)
                context.recent_apps = context.recent_apps[:self.max_recent_apps]
            context.current_app = app_ctx
            context.last_updated = datetime.now(timezone.utc)
            logger.debug(f"Set current app for {user_id}: {app_name}")
            return app_ctx

    async def record_action(self, user_id: str, action_type: str, description: str, target: Optional[str] = None, result: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> ActionContext:
        context = await self.get_or_create_context(user_id)
        async with self._lock:
            action = ActionContext(action_type=action_type, description=description, target=target, result=result, metadata=metadata or {})
            context.recent_actions.insert(0, action)
            context.recent_actions = context.recent_actions[:self.max_recent_actions]
            context.last_updated = datetime.now(timezone.utc)
            logger.debug(f"Recorded action for {user_id}: {action_type}")
            return action

    async def set_working_directory(self, user_id: str, directory: str, project_name: Optional[str] = None) -> None:
        context = await self.get_or_create_context(user_id)
        async with self._lock:
            context.working_directory = directory
            if project_name:
                context.project_name = project_name
            context.last_updated = datetime.now(timezone.utc)

    async def get_context(self, user_id: str) -> Optional[UserActiveContext]:
        return self._contexts.get(user_id)

    async def get_context_summary(self, user_id: str) -> Dict[str, Any]:
        context = self._contexts.get(user_id)
        if not context:
            return {}
        summary: Dict[str, Any] = {}
        if context.current_file:
            summary["current_file"] = {"path": context.current_file.path, "name": context.current_file.name, "language": context.current_file.language, "cursor_line": context.current_file.cursor_line}
        if context.current_app:
            summary["current_app"] = {"name": context.current_app.name, "window_title": context.current_app.window_title}
        if context.recent_actions:
            summary["last_action"] = {"type": context.recent_actions[0].action_type, "description": context.recent_actions[0].description, "target": context.recent_actions[0].target}
        if context.working_directory:
            summary["working_directory"] = context.working_directory
        if context.project_name:
            summary["project_name"] = context.project_name
        summary["recent_files"] = [f.name for f in context.recent_files[:3]]
        return summary

    async def build_context_string(self, user_id: str, include_recent: bool = True, include_actions: bool = True) -> str:
        context = self._contexts.get(user_id)
        if not context:
            return ""
        parts = ["[Active Context]"]
        if context.current_file:
            file = context.current_file
            file_info = f"File: {file.name}"
            if file.language:
                file_info += f" ({file.language})"
            if file.cursor_line:
                file_info += f" at line {file.cursor_line}"
            parts.append(file_info)
            if file.snippet:
                parts.append(f"Code context:\n```\n{file.snippet}\n```")
        if include_recent and context.recent_files:
            recent = [f.name for f in context.recent_files[:3]]
            parts.append(f"Recent files: {', '.join(recent)}")
        if context.current_app:
            app = context.current_app
            app_info = f"App: {app.name}"
            if app.window_title:
                app_info += f" - {app.window_title}"
            parts.append(app_info)
        if context.working_directory:
            project = context.project_name or "project"
            parts.append(f"Working in: {context.working_directory} ({project})")
        if include_actions and context.recent_actions:
            actions = context.recent_actions[:3]
            parts.append("Recent actions:")
            for action in actions:
                parts.append(f"  - {action.description}")
        return "\n".join(parts)

    async def calculate_relevance_score(self, user_id: str, query: str) -> float:
        context = self._contexts.get(user_id)
        if not context:
            return 0.0
        score = 0.0
        query_lower = query.lower()
        if context.current_file:
            if context.current_file.name.lower() in query_lower:
                score += 0.3
            if context.current_file.language and context.current_file.language in query_lower:
                score += 0.2
        if context.current_app:
            if context.current_app.name.lower() in query_lower:
                score += 0.2
        for action in context.recent_actions[:3]:
            if any(word in query_lower for word in action.description.lower().split()):
                score += 0.1
                break
        if context.project_name and context.project_name.lower() in query_lower:
            score += 0.2
        return min(1.0, score)

    async def get_stats(self) -> Dict[str, Any]:
        total_actions = sum(len(ctx.recent_actions) for ctx in self._contexts.values())
        return {"tracked_users": len(self._contexts), "total_actions": total_actions, "max_recent_files": self.max_recent_files, "max_recent_actions": self.max_recent_actions, "action_ttl_minutes": self.action_ttl // 60}

active_context_tracker = ActiveContextTracker()
