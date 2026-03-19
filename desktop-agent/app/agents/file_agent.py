"""
File Agent — File and folder CRUD, search, navigation
"""
import os
import shutil
import glob
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
            ),
            "create_folder": lambda: self._create_folder(args.get("path", "")),
            "delete_path": lambda: self._delete_path(args.get("path", "")),
            "move_path": lambda: self._move_path(
                args.get("source", ""), args.get("destination", "")
            ),
            "copy_path": lambda: self._copy_path(
                args.get("source", ""), args.get("destination", "")
            ),
            "search_files": lambda: self._search_files(
                args.get("directory", ""),
                args.get("pattern", "*"),
                args.get("recursive", False),
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
        self, path: str, content: str, append: bool = False
    ) -> Dict[str, Any]:
        path = self._expand(path)

        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            mode = "a" if append else "w"
            with open(path, mode, encoding="utf-8") as f:
                f.write(content)
            action = "Appended to" if append else "Written to"
            return self._success(
                {"path": path, "bytes_written": len(content.encode("utf-8"))},
                f"{action} {os.path.basename(path)}",
            )
        except Exception as e:
            return self._error(f"Failed to write file: {e}")

    def _create_folder(self, path: str) -> Dict[str, Any]:
        path = self._expand(path)
        try:
            os.makedirs(path, exist_ok=True)
            return self._success({"path": path}, f"Created folder: {path}")
        except Exception as e:
            return self._error(f"Failed to create folder: {e}")

    def _delete_path(self, path: str) -> Dict[str, Any]:
        path = self._expand(path)
        if not os.path.exists(path):
            return self._error(f"Path not found: {path}")

        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            return self._success({"deleted": path}, f"Deleted: {path}")
        except Exception as e:
            return self._error(f"Failed to delete: {e}")

    def _move_path(self, source: str, destination: str) -> Dict[str, Any]:
        source = self._expand(source)
        destination = self._expand(destination)
        if not os.path.exists(source):
            return self._error(f"Source not found: {source}")

        try:
            shutil.move(source, destination)
            return self._success(
                {"source": source, "destination": destination},
                f"Moved to {destination}",
            )
        except Exception as e:
            return self._error(f"Failed to move: {e}")

    def _copy_path(self, source: str, destination: str) -> Dict[str, Any]:
        source = self._expand(source)
        destination = self._expand(destination)
        if not os.path.exists(source):
            return self._error(f"Source not found: {source}")

        try:
            if os.path.isdir(source):
                shutil.copytree(source, destination)
            else:
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                shutil.copy2(source, destination)
            return self._success(
                {"source": source, "destination": destination},
                f"Copied to {destination}",
            )
        except Exception as e:
            return self._error(f"Failed to copy: {e}")

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
