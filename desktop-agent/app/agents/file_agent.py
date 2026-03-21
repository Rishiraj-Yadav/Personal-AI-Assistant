"""
File Agent — File and folder CRUD, search, navigation
"""
import os
import re
import shutil
import glob
import string
import time
from datetime import datetime
from typing import Dict, Any, List
from loguru import logger
from agents.base_agent import BaseAgent
from config import settings


class FileAgent(BaseAgent):
    """Agent for file and folder operations"""

    def __init__(self):
        super().__init__(
            name="file_agent",
            description="Manage files and folders — create, delete, move, copy, search, read, write",
        )

    def _is_safe_path(self, path: str) -> bool:
        """Check if path is within allowed safe paths"""
        abs_path = os.path.abspath(path)
        # Always allow user's home subdirectories
        home = os.path.expanduser("~")
        if abs_path.startswith(home):
            return True
        # Check configured safe paths
        for safe in settings.SAFE_PATHS:
            if abs_path.startswith(os.path.abspath(safe)):
                return True
        return False

    def _is_blocked_system_path(self, path: str) -> bool:
        """Block destructive mutations against critical system locations."""
        normalized = os.path.abspath(path).lower()
        blocked_prefixes = [
            os.path.abspath(os.path.expandvars(r"%SystemRoot%")).lower(),
            os.path.abspath(os.path.expandvars(r"%ProgramFiles%")).lower(),
            os.path.abspath(os.path.expandvars(r"%ProgramFiles(x86)%")).lower(),
            os.path.abspath(os.path.expandvars(r"%ProgramData%")).lower(),
        ]
        return any(prefix and normalized.startswith(prefix) for prefix in blocked_prefixes)

    def _ensure_mutation_allowed(
        self,
        *paths: str,
        approval_granted: bool = False,
    ) -> Dict[str, Any] | None:
        """Guard file mutations to user-safe paths."""
        for path in paths:
            if not path:
                continue
            expanded = self._expand(path)
            if self._is_blocked_system_path(expanded):
                return self._error(
                    f"Blocked operation on protected system path: {expanded}",
                    error_code="protected_path",
                    retryable=False,
                    observed_state={"path": expanded},
                )
        destination = self._expand(paths[-1]) if paths else ""
        if destination and not approval_granted and not self._is_safe_path(destination):
            return self._error(
                f"Destination is outside safe user locations: {destination}",
                error_code="unsafe_destination",
                retryable=False,
                observed_state={
                    "path": destination,
                    "safe_paths": settings.SAFE_PATHS,
                    "approval_granted": approval_granted,
                },
            )
        return None

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "list_directory",
                "description": "List contents of a directory (files and folders with sizes and dates)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Directory path to list. Use ~ for home directory.",
                        },
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "read_file",
                "description": "Read the text content of a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file to read",
                        },
                        "max_lines": {
                            "type": "integer",
                            "description": "Maximum lines to read (default: 100)",
                        },
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "write_file",
                "description": "Write text content to a file (creates or overwrites)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file to write",
                        },
                        "content": {
                            "type": "string",
                            "description": "Text content to write",
                        },
                        "append": {
                            "type": "boolean",
                            "description": "If true, append instead of overwrite (default: false)",
                        },
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "create_folder",
                "description": "Create a new folder (and parent folders if needed)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path of the folder to create",
                        },
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "delete_path",
                "description": "Delete a file or folder",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to delete",
                        },
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "move_path",
                "description": "Move or rename a file or folder",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "string",
                            "description": "Source path",
                        },
                        "destination": {
                            "type": "string",
                            "description": "Destination path",
                        },
                    },
                    "required": ["source", "destination"],
                },
            },
            {
                "name": "copy_path",
                "description": "Copy a file or folder",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "string",
                            "description": "Source path",
                        },
                        "destination": {
                            "type": "string",
                            "description": "Destination path",
                        },
                    },
                    "required": ["source", "destination"],
                },
            },
            {
                "name": "search_files",
                "description": "Search for files by name pattern (glob) in a directory",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "directory": {
                            "type": "string",
                            "description": "Directory to search in",
                        },
                        "pattern": {
                            "type": "string",
                            "description": "Glob pattern (e.g., '*.pdf', '*.txt', 'report*')",
                        },
                        "recursive": {
                            "type": "boolean",
                            "description": "Search subdirectories too (default: false)",
                        },
                    },
                    "required": ["directory", "pattern"],
                },
            },
            {
                "name": "search_system",
                "description": "Search across local drives for files and folders by name. Uses safe drive scanning, depth limits, extension filters, result caps, and timeouts.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Free-text filename query (e.g., 'report', 'main.py', 'budget 2026').",
                        },
                        "roots": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional root folders or drives to scan. Defaults to all available local drives plus the user's home folder.",
                        },
                        "file_types": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional file extensions to include (e.g., ['pdf', '.txt', 'py']).",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum results to return (default: 25, max: 100).",
                        },
                        "max_depth": {
                            "type": "integer",
                            "description": "Maximum folder depth relative to each root (default: 6, max: 12).",
                        },
                        "timeout_seconds": {
                            "type": "integer",
                            "description": "Maximum scan time in seconds (default: 12, max: 30).",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "get_file_info",
                "description": "Get detailed information about a file or folder (size, dates, type)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to get info for",
                        },
                    },
                    "required": ["path"],
                },
            },
        ]

    def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        handlers = {
            "list_directory": lambda: self._list_dir(args.get("path", "")),
            "read_file": lambda: self._read_file(
                args.get("path", ""), args.get("max_lines", 100)
            ),
            "write_file": lambda: self._write_file(
                args.get("path", ""),
                args.get("content", ""),
                args.get("append", False),
                args.get("_approval_granted", False),
            ),
            "create_folder": lambda: self._create_folder(args.get("path", ""), args.get("_approval_granted", False)),
            "delete_path": lambda: self._delete_path(args.get("path", ""), args.get("_approval_granted", False)),
            "move_path": lambda: self._move_path(
                args.get("source", ""), args.get("destination", ""), args.get("_approval_granted", False)
            ),
            "copy_path": lambda: self._copy_path(
                args.get("source", ""), args.get("destination", ""), args.get("_approval_granted", False)
            ),
            "search_files": lambda: self._search_files(
                args.get("directory", ""),
                args.get("pattern", "*"),
                args.get("recursive", False),
            ),
            "search_system": lambda: self._search_system(
                query=args.get("query", ""),
                roots=args.get("roots"),
                file_types=args.get("file_types"),
                max_results=args.get("max_results", 25),
                max_depth=args.get("max_depth", 6),
                timeout_seconds=args.get("timeout_seconds", 12),
            ),
            "get_file_info": lambda: self._get_info(args.get("path", "")),
        }
        handler = handlers.get(tool_name)
        if handler:
            return handler()
        return self._error(f"Unknown tool: {tool_name}")

    def _expand(self, path: str) -> str:
        """Expand ~ and env vars in paths"""
        return os.path.abspath(os.path.expanduser(os.path.expandvars(path)))

    def _get_default_search_roots(self) -> List[str]:
        roots = []
        home = os.path.expanduser("~")
        if os.path.isdir(home):
            roots.append(home)
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                roots.append(drive)
        return roots

    def _normalize_extensions(self, file_types: List[str] | None) -> set[str]:
        normalized: set[str] = set()
        for file_type in file_types or []:
            if not isinstance(file_type, str):
                continue
            ext = file_type.strip().lower()
            if not ext:
                continue
            if not ext.startswith("."):
                ext = f".{ext}"
            normalized.add(ext)
        return normalized

    def _score_match(self, query: str, path: str) -> int:
        query_lower = query.lower().strip()
        name = os.path.basename(path).lower()
        path_lower = path.lower()
        stem = os.path.splitext(name)[0]
        if name == query_lower or stem == query_lower:
            return 140
        if query_lower in name:
            return 120
        if query_lower in path_lower:
            return 95

        # Keep compound names (with underscores/hyphens) as whole tokens
        # alongside individual fragments for partial matching
        compound_tokens = [
            token
            for token in re.sub(r"[^a-z0-9_\-]+", " ", query_lower).split()
            if len(token) >= 2
        ]
        individual_tokens = [
            token
            for token in re.sub(r"[^a-z0-9]+", " ", query_lower).split()
            if len(token) >= 2
        ]
        tokens = list(dict.fromkeys(compound_tokens + individual_tokens))
        if not tokens:
            return 0
        token_hits = sum(1 for token in tokens if token in name or token in path_lower)
        if token_hits == len(tokens):
            return 80 + min(15, len(tokens) * 3)
        if token_hits >= max(1, len(tokens) // 2):
            return 45 + (token_hits * 10)
        return 0

    def _match_sort_key(self, match: Dict[str, Any], query: str) -> tuple[int, int, int, str]:
        query_lower = query.lower().strip()
        name = str(match.get("name", "")).lower()
        stem = os.path.splitext(name)[0]
        score = int(match.get("score", 0) or 0)
        exact_name = int(name == query_lower or stem == query_lower)
        type_priority = int(str(match.get("type", "")).lower() == "folder")
        depth = int(match.get("depth", str(match.get("path", "")).rstrip("\\/").count(os.sep)))
        modified = str(match.get("modified") or "")
        return (score, exact_name, type_priority, -depth, modified)

    def _search_system(
        self,
        *,
        query: str,
        roots: List[str] | None = None,
        file_types: List[str] | None = None,
        max_results: int = 25,
        max_depth: int = 6,
        timeout_seconds: int = 12,
    ) -> Dict[str, Any]:
        """Search across local drives with bounded, safe scanning."""
        query = (query or "").strip()
        if not query:
            return self._error("No search query provided", error_code="validation_failed")
        query_lower = query.lower().strip()

        max_results = max(1, min(int(max_results or 25), 100))
        max_depth = max(1, min(int(max_depth or 6), 12))
        timeout_seconds = max(1, min(int(timeout_seconds or 12), 30))
        allowed_extensions = self._normalize_extensions(file_types)

        search_roots = [self._expand(root) for root in (roots or self._get_default_search_roots())]
        unique_roots: List[str] = []
        for root in search_roots:
            if os.path.exists(root) and root not in unique_roots:
                unique_roots.append(root)

        skipped_dirs = {
            "windows",
            "program files",
            "program files (x86)",
            "programdata",
            "$recycle.bin",
            "system volume information",
            "temp",
            "tmp",
            "__pycache__",
            "node_modules",
        }
        matches: List[Dict[str, Any]] = []
        start_time = time.monotonic()
        timed_out = False
        scanned_dirs = 0
        match_cap = max_results * 5

        for root in unique_roots:
            if time.monotonic() - start_time >= timeout_seconds:
                timed_out = True
                break

            root_depth = root.rstrip("\\/").count(os.sep)

            for current_root, dirs, files in os.walk(root):
                scanned_dirs += 1
                if time.monotonic() - start_time >= timeout_seconds:
                    timed_out = True
                    break

                current_depth = current_root.rstrip("\\/").count(os.sep) - root_depth
                dirs[:] = [
                    directory
                    for directory in dirs
                    if directory.lower() not in skipped_dirs and current_depth < max_depth
                ]

                candidates = list(dirs) + files
                for candidate in candidates:
                    candidate_path = os.path.join(current_root, candidate)
                    is_file = os.path.isfile(candidate_path)
                    if allowed_extensions and is_file:
                        _, ext = os.path.splitext(candidate_path)
                        if ext.lower() not in allowed_extensions:
                            continue

                    score = self._score_match(query, candidate_path)
                    if score <= 0:
                        continue

                    stat = None
                    try:
                        stat = os.stat(candidate_path)
                    except OSError:
                        stat = None

                    matches.append(
                        {
                            "path": candidate_path,
                            "name": candidate,
                            "type": "file" if is_file else "folder",
                            "score": score,
                            "normalized_name": candidate.lower(),
                            "stem": os.path.splitext(candidate.lower())[0],
                            "exact_name": candidate.lower() == query_lower,
                            "exact_stem": os.path.splitext(candidate.lower())[0] == query_lower,
                            "root": root,
                            "depth": current_depth + 1,
                            "size_bytes": stat.st_size if stat and is_file else None,
                            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat() if stat else None,
                        }
                    )

                    if len(matches) > match_cap:
                        matches.sort(key=lambda item: self._match_sort_key(item, query), reverse=True)
                        matches = matches[:match_cap]

            if timed_out:
                break

        matches.sort(key=lambda item: self._match_sort_key(item, query), reverse=True)
        limited_matches = matches[:max_results]
        observed_state = {
            "query": query,
            "roots_scanned": unique_roots,
            "roots_count": len(unique_roots),
            "directory_count": scanned_dirs,
            "result_count": len(limited_matches),
            "timed_out": timed_out,
            "file_types": sorted(allowed_extensions),
            "max_depth": max_depth,
        }
        evidence = [
            {
                "type": "search_results",
                "count": len(limited_matches),
                "paths": [match["path"] for match in limited_matches[:10]],
            }
        ]

        return self._success(
            {
                "query": query,
                "matches": limited_matches,
                "count": len(limited_matches),
                "timed_out": timed_out,
            },
            f"Found {len(limited_matches)} matching paths for '{query}'",
            observed_state=observed_state,
            evidence=evidence,
        )

    def _list_dir(self, path: str) -> Dict[str, Any]:
        path = self._expand(path)
        if not os.path.isdir(path):
            return self._error(f"Not a directory: {path}")

        try:
            entries = []
            for entry in os.scandir(path):
                info = {
                    "name": entry.name,
                    "type": "folder" if entry.is_dir() else "file",
                }
                try:
                    stat = entry.stat()
                    if entry.is_file():
                        info["size_bytes"] = stat.st_size
                        info["size"] = self._human_size(stat.st_size)
                    info["modified"] = datetime.fromtimestamp(
                        stat.st_mtime
                    ).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    pass
                entries.append(info)

            entries.sort(key=lambda x: (x["type"] != "folder", x["name"].lower()))
            return self._success(
                {"path": path, "entries": entries, "count": len(entries)},
                f"Listed {len(entries)} items in {path}",
            )
        except PermissionError:
            return self._error(f"Permission denied: {path}")
        except Exception as e:
            return self._error(f"Failed to list directory: {e}")

    def _read_file(self, path: str, max_lines: int = 100) -> Dict[str, Any]:
        path = self._expand(path)
        if not os.path.isfile(path):
            return self._error(f"File not found: {path}")

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            content = "".join(lines[:max_lines])
            return self._success(
                {
                    "path": path,
                    "content": content,
                    "total_lines": len(lines),
                    "lines_returned": min(len(lines), max_lines),
                },
                f"Read {min(len(lines), max_lines)} lines from {os.path.basename(path)}",
            )
        except Exception as e:
            return self._error(f"Failed to read file: {e}")

    def _write_file(
        self, path: str, content: str, append: bool = False, approval_granted: bool = False
    ) -> Dict[str, Any]:
        path = self._expand(path)
        guard = self._ensure_mutation_allowed(path, approval_granted=approval_granted)
        if guard:
            return guard

        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            mode = "a" if append else "w"
            with open(path, mode, encoding="utf-8") as f:
                f.write(content)
            action = "Appended to" if append else "Written to"
            return self._success(
                {"path": path, "bytes_written": len(content.encode("utf-8"))},
                f"{action} {os.path.basename(path)}",
                observed_state={
                    "path": path,
                    "append": append,
                    "exists": os.path.exists(path),
                    "approval_granted": approval_granted,
                },
                evidence=[{"type": "path", "path": path}],
            )
        except Exception as e:
            return self._error(f"Failed to write file: {e}", retryable=True)

    def _create_folder(self, path: str, approval_granted: bool = False) -> Dict[str, Any]:
        path = self._expand(path)
        guard = self._ensure_mutation_allowed(path, approval_granted=approval_granted)
        if guard:
            return guard
        try:
            os.makedirs(path, exist_ok=True)
            return self._success(
                {"path": path},
                f"Created folder: {path}",
                observed_state={"path": path, "exists": os.path.isdir(path), "approval_granted": approval_granted},
                evidence=[{"type": "path", "path": path}],
            )
        except Exception as e:
            return self._error(f"Failed to create folder: {e}", retryable=True)

    def _delete_path(self, path: str, approval_granted: bool = False) -> Dict[str, Any]:
        path = self._expand(path)
        if not os.path.exists(path):
            return self._error(f"Path not found: {path}", error_code="not_found")
        guard = self._ensure_mutation_allowed(path, approval_granted=approval_granted)
        if guard:
            return guard

        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            return self._success(
                {"deleted": path},
                f"Deleted: {path}",
                observed_state={"path": path, "exists_after_delete": os.path.exists(path), "approval_granted": approval_granted},
                evidence=[{"type": "path", "path": path}],
            )
        except Exception as e:
            return self._error(f"Failed to delete: {e}", retryable=True)

    def _move_path(self, source: str, destination: str, approval_granted: bool = False) -> Dict[str, Any]:
        source = self._expand(source)
        destination = self._expand(destination)
        if not os.path.exists(source):
            return self._error(f"Source not found: {source}", error_code="not_found")
        guard = self._ensure_mutation_allowed(source, destination, approval_granted=approval_granted)
        if guard:
            return guard

        try:
            actual_destination = shutil.move(source, destination)
            return self._success(
                {"source": source, "destination": actual_destination},
                f"Moved to {actual_destination}",
                observed_state={
                    "source_exists": os.path.exists(source),
                    "destination_exists": os.path.exists(actual_destination),
                    "destination": actual_destination,
                    "approval_granted": approval_granted,
                },
                evidence=[{"type": "path", "path": actual_destination}],
            )
        except Exception as e:
            return self._error(f"Failed to move: {e}", retryable=True)

    def _copy_path(self, source: str, destination: str, approval_granted: bool = False) -> Dict[str, Any]:
        source = self._expand(source)
        destination = self._expand(destination)
        if not os.path.exists(source):
            return self._error(f"Source not found: {source}", error_code="not_found")
        guard = self._ensure_mutation_allowed(source, destination, approval_granted=approval_granted)
        if guard:
            return guard

        try:
            if os.path.isdir(source):
                actual_destination = shutil.copytree(source, destination)
            else:
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                actual_destination = shutil.copy2(source, destination)
            return self._success(
                {"source": source, "destination": actual_destination},
                f"Copied to {actual_destination}",
                observed_state={
                    "source_exists": os.path.exists(source),
                    "destination_exists": os.path.exists(actual_destination),
                    "destination": actual_destination,
                    "approval_granted": approval_granted,
                },
                evidence=[{"type": "path", "path": actual_destination}],
            )
        except Exception as e:
            return self._error(f"Failed to copy: {e}", retryable=True)

    def _search_files(
        self, directory: str, pattern: str, recursive: bool = False
    ) -> Dict[str, Any]:
        directory = self._expand(directory)
        if not os.path.isdir(directory):
            return self._error(f"Directory not found: {directory}")

        try:
            if recursive:
                search_pattern = os.path.join(directory, "**", pattern)
                matches = glob.glob(search_pattern, recursive=True)
            else:
                search_pattern = os.path.join(directory, pattern)
                matches = glob.glob(search_pattern)

            results = []
            for m in matches[:50]:  # Cap at 50 results
                results.append({
                    "path": m,
                    "name": os.path.basename(m),
                    "type": "folder" if os.path.isdir(m) else "file",
                })

            return self._success(
                {
                    "directory": directory,
                    "pattern": pattern,
                    "matches": results,
                    "count": len(results),
                    "total_found": len(matches),
                },
                f"Found {len(matches)} matches for '{pattern}' in {directory}",
            )
        except Exception as e:
            return self._error(f"Search failed: {e}")

    def _get_info(self, path: str) -> Dict[str, Any]:
        path = self._expand(path)
        if not os.path.exists(path):
            return self._error(f"Path not found: {path}")

        try:
            stat = os.stat(path)
            info = {
                "path": path,
                "name": os.path.basename(path),
                "type": "folder" if os.path.isdir(path) else "file",
                "size_bytes": stat.st_size,
                "size": self._human_size(stat.st_size),
                "created": datetime.fromtimestamp(stat.st_ctime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "extension": os.path.splitext(path)[1] if os.path.isfile(path) else None,
            }
            return self._success(info, f"Info for {os.path.basename(path)}")
        except Exception as e:
            return self._error(f"Failed to get info: {e}")

    @staticmethod
    def _human_size(size_bytes: int) -> str:
        """Convert bytes to human-readable size"""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"


# Global instance
file_agent = FileAgent()
