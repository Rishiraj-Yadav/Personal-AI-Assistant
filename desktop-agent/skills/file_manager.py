"""
File Manager Skill
Read, write, search, move, rename, and organize files on the user's filesystem.
"""
import os
import shutil
import glob
import json
from typing import Dict, Any, List
from datetime import datetime
from loguru import logger
from config import settings


class FileManagerSkill:
    """Manage files and directories on the local filesystem."""

    # Maximum file size to read (5MB)
    MAX_READ_SIZE = 5 * 1024 * 1024

    def __init__(self):
        self.system = os.name
        logger.info("FileManagerSkill initialized")

    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a file management action.

        Args:
            action: One of list, read, write, move, copy, delete, search, mkdir, info
            path: Target file or directory path
            destination: Destination path (for move/copy)
            content: File content (for write)
            pattern: Search pattern (for search)
            recursive: Whether to search recursively (for search/list)
        """
        action = args.get("action", "list")

        action_map = {
            "list": self._list_dir,
            "read": self._read_file,
            "write": self._write_file,
            "move": self._move,
            "copy": self._copy,
            "delete": self._delete,
            "search": self._search,
            "mkdir": self._mkdir,
            "info": self._file_info,
            "tree": self._tree,
        }

        handler = action_map.get(action)
        if not handler:
            return {"success": False, "error": f"Unknown action: {action}"}

        try:
            return handler(args)
        except PermissionError:
            return {"success": False, "error": "Permission denied"}
        except Exception as e:
            logger.error(f"FileManager error ({action}): {e}")
            return {"success": False, "error": str(e)}

    def _list_dir(self, args: Dict) -> Dict[str, Any]:
        """List contents of a directory."""
        path = args.get("path", os.path.expanduser("~"))
        recursive = args.get("recursive", False)

        if not os.path.isdir(path):
            return {"success": False, "error": f"Not a directory: {path}"}

        entries = []
        try:
            for entry in os.scandir(path):
                info = {
                    "name": entry.name,
                    "type": "dir" if entry.is_dir() else "file",
                    "path": entry.path,
                }
                try:
                    stat = entry.stat()
                    info["size"] = stat.st_size
                    info["modified"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
                except OSError:
                    pass
                entries.append(info)

            # Sort: directories first, then files, alphabetically
            entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))

            return {
                "success": True,
                "path": path,
                "count": len(entries),
                "entries": entries[:100],  # Cap at 100 items
            }
        except PermissionError:
            return {"success": False, "error": f"Permission denied: {path}"}

    def _read_file(self, args: Dict) -> Dict[str, Any]:
        """Read contents of a file."""
        path = args.get("path", "")
        if not path or not os.path.isfile(path):
            return {"success": False, "error": f"File not found: {path}"}

        size = os.path.getsize(path)
        if size > self.MAX_READ_SIZE:
            return {
                "success": False,
                "error": f"File too large ({size} bytes). Max: {self.MAX_READ_SIZE}",
            }

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return {
                "success": True,
                "path": path,
                "size": size,
                "content": content,
            }
        except UnicodeDecodeError:
            return {"success": False, "error": "Binary file — cannot read as text"}

    def _write_file(self, args: Dict) -> Dict[str, Any]:
        """Write content to a file."""
        path = args.get("path", "")
        content = args.get("content", "")
        append = args.get("append", False)

        if not path:
            return {"success": False, "error": "No path specified"}

        # Create parent directories
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        mode = "a" if append else "w"
        with open(path, mode, encoding="utf-8") as f:
            f.write(content)

        return {
            "success": True,
            "path": path,
            "action": "append" if append else "write",
            "bytes_written": len(content.encode("utf-8")),
        }

    def _move(self, args: Dict) -> Dict[str, Any]:
        """Move or rename a file/directory."""
        source = args.get("path", "")
        destination = args.get("destination", "")

        if not source or not os.path.exists(source):
            return {"success": False, "error": f"Source not found: {source}"}
        if not destination:
            return {"success": False, "error": "No destination specified"}

        os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
        shutil.move(source, destination)
        return {
            "success": True,
            "action": "move",
            "from": source,
            "to": destination,
        }

    def _copy(self, args: Dict) -> Dict[str, Any]:
        """Copy a file or directory."""
        source = args.get("path", "")
        destination = args.get("destination", "")

        if not source or not os.path.exists(source):
            return {"success": False, "error": f"Source not found: {source}"}
        if not destination:
            return {"success": False, "error": "No destination specified"}

        os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
        if os.path.isdir(source):
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(source, destination)

        return {
            "success": True,
            "action": "copy",
            "from": source,
            "to": destination,
        }

    def _delete(self, args: Dict) -> Dict[str, Any]:
        """Delete a file or directory."""
        path = args.get("path", "")
        if not path or not os.path.exists(path):
            return {"success": False, "error": f"Not found: {path}"}

        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)

        return {"success": True, "action": "delete", "path": path}

    def _search(self, args: Dict) -> Dict[str, Any]:
        """Search for files matching a pattern."""
        path = args.get("path", os.path.expanduser("~"))
        pattern = args.get("pattern", "*")
        recursive = args.get("recursive", True)

        if recursive:
            search_pattern = os.path.join(path, "**", pattern)
            matches = glob.glob(search_pattern, recursive=True)
        else:
            search_pattern = os.path.join(path, pattern)
            matches = glob.glob(search_pattern)

        results = []
        for match in matches[:50]:  # Cap at 50 results
            try:
                stat = os.stat(match)
                results.append({
                    "path": match,
                    "name": os.path.basename(match),
                    "type": "dir" if os.path.isdir(match) else "file",
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
            except OSError:
                results.append({"path": match, "name": os.path.basename(match)})

        return {
            "success": True,
            "pattern": pattern,
            "search_path": path,
            "count": len(results),
            "total_matches": len(matches),
            "results": results,
        }

    def _mkdir(self, args: Dict) -> Dict[str, Any]:
        """Create a directory (and parents)."""
        path = args.get("path", "")
        if not path:
            return {"success": False, "error": "No path specified"}

        os.makedirs(path, exist_ok=True)
        return {"success": True, "action": "mkdir", "path": path}

    def _file_info(self, args: Dict) -> Dict[str, Any]:
        """Get detailed information about a file."""
        path = args.get("path", "")
        if not path or not os.path.exists(path):
            return {"success": False, "error": f"Not found: {path}"}

        stat = os.stat(path)
        return {
            "success": True,
            "path": path,
            "name": os.path.basename(path),
            "type": "dir" if os.path.isdir(path) else "file",
            "size": stat.st_size,
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "extension": os.path.splitext(path)[1] if os.path.isfile(path) else None,
        }

    def _tree(self, args: Dict) -> Dict[str, Any]:
        """Show directory tree structure (max 3 levels deep)."""
        path = args.get("path", os.path.expanduser("~"))
        max_depth = args.get("depth", 3)

        if not os.path.isdir(path):
            return {"success": False, "error": f"Not a directory: {path}"}

        tree_lines = []
        self._build_tree(path, "", 0, max_depth, tree_lines)

        return {
            "success": True,
            "path": path,
            "tree": "\n".join(tree_lines[:200]),  # Cap output
        }

    def _build_tree(self, path: str, prefix: str, depth: int, max_depth: int, lines: List[str]):
        """Recursively build tree representation."""
        if depth >= max_depth or len(lines) > 200:
            return

        try:
            entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return

        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            icon = "📁" if entry.is_dir() else "📄"
            lines.append(f"{prefix}{connector}{icon} {entry.name}")

            if entry.is_dir():
                extension = "    " if is_last else "│   "
                self._build_tree(entry.path, prefix + extension, depth + 1, max_depth, lines)


# Global instance
file_manager_skill = FileManagerSkill()
