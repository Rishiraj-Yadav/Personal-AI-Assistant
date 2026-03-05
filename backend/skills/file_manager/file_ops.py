#!/usr/bin/env python3
"""
File Manager Skill — System-wide file management with security restrictions.
Can access any path on the user's computer EXCEPT forbidden system directories.
"""
import os
import json
import sys
import shutil
from pathlib import Path
import fnmatch
from datetime import datetime


# ── Security Configuration ──
USER_HOME = Path.home()
FORBIDDEN_DIRS = [
    Path("C:/Windows"),
    Path("C:/Program Files"),
    Path("C:/Program Files (x86)"),
    Path("C:/$Recycle.Bin"),
    Path("C:/System Volume Information"),
    Path("C:/ProgramData"),
]
FORBIDDEN_NAMES = {'.env', 'id_rsa', 'id_dsa', '.ssh', '.aws', 'credentials', '.git'}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
MAX_LIST_ITEMS = 200


def is_forbidden(path: Path) -> bool:
    """Check if a path is in a forbidden zone."""
    resolved = path.resolve()
    path_str = str(resolved).lower()
    
    # Block system directories
    for forbidden in FORBIDDEN_DIRS:
        try:
            resolved.relative_to(forbidden)
            return True
        except ValueError:
            pass
    
    # Block sensitive filenames
    for part in resolved.parts:
        if part.lower() in {f.lower() for f in FORBIDDEN_NAMES}:
            return True
    
    # Block other users' home directories
    users_dir = Path("C:/Users")
    try:
        rel = resolved.relative_to(users_dir)
        parts = rel.parts
        if parts and parts[0].lower() != USER_HOME.name.lower():
            return True
    except ValueError:
        pass
    
    return False


def resolve_path(path_str: str) -> Path:
    """
    Resolve a user-provided path. Supports:
    - Absolute paths: C:\\Users\\User\\Documents
    - Relative paths: resolved relative to user home
    - ~ expansion: ~/Documents
    """
    if not path_str or path_str.strip() == "":
        return USER_HOME
    
    path_str = path_str.strip()
    
    # Expand ~ to user home
    if path_str.startswith("~"):
        path_str = str(USER_HOME / path_str[2:]) if len(path_str) > 1 else str(USER_HOME)
    
    path = Path(path_str)
    
    # If relative, resolve from user home
    if not path.is_absolute():
        path = USER_HOME / path
    
    resolved = path.resolve()
    
    if is_forbidden(resolved):
        raise ValueError(f"Access denied: '{path_str}' is in a restricted location")
    
    return resolved


def list_files(path: str = "", pattern: str = "*") -> dict:
    """List files and directories at the given path."""
    dir_path = resolve_path(path)
    
    if not dir_path.exists():
        raise ValueError(f"Directory not found: {path}")
    
    if not dir_path.is_dir():
        raise ValueError(f"Not a directory: {path}")
    
    files = []
    directories = []
    
    for item in sorted(dir_path.iterdir()):
        try:
            if is_forbidden(item):
                continue
            
            if item.is_file():
                if fnmatch.fnmatch(item.name, pattern):
                    stat = item.stat()
                    files.append({
                        "name": item.name,
                        "path": str(item),
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                        "extension": item.suffix
                    })
            elif item.is_dir():
                directories.append({
                    "name": item.name,
                    "path": str(item)
                })
            
            if len(files) + len(directories) >= MAX_LIST_ITEMS:
                break
        except (PermissionError, OSError):
            continue
    
    return {
        "action": "list",
        "path": str(dir_path),
        "pattern": pattern,
        "files": files,
        "directories": directories,
        "total_files": len(files),
        "total_directories": len(directories)
    }


def read_file(path: str) -> dict:
    """Read file contents."""
    file_path = resolve_path(path)
    
    if not file_path.exists():
        raise ValueError(f"File not found: {path}")
    
    if not file_path.is_file():
        raise ValueError(f"Not a file: {path}")
    
    if file_path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError(f"File too large (max {MAX_FILE_SIZE // 1024 // 1024}MB)")
    
    try:
        content = file_path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        content = f"[Binary file — {file_path.stat().st_size} bytes]"
    
    return {
        "action": "read",
        "path": str(file_path),
        "content": content,
        "size": file_path.stat().st_size,
        "lines": len(content.splitlines())
    }


def write_file(path: str, content: str) -> dict:
    """Create or overwrite a file."""
    file_path = resolve_path(path)
    
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding='utf-8')
    
    return {
        "action": "write",
        "path": str(file_path),
        "size": len(content.encode('utf-8')),
        "message": f"File written successfully: {file_path.name}"
    }


def move_file(path: str, new_path: str) -> dict:
    """Move or rename a file/directory."""
    src = resolve_path(path)
    dst = resolve_path(new_path)
    
    if not src.exists():
        raise ValueError(f"Source not found: {path}")
    
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    
    return {
        "action": "move",
        "old_path": str(src),
        "new_path": str(dst),
        "message": f"Moved {src.name} → {dst.name}"
    }


def copy_file(path: str, new_path: str) -> dict:
    """Copy a file or directory."""
    src = resolve_path(path)
    dst = resolve_path(new_path)
    
    if not src.exists():
        raise ValueError(f"Source not found: {path}")
    
    dst.parent.mkdir(parents=True, exist_ok=True)
    
    if src.is_dir():
        shutil.copytree(str(src), str(dst))
    else:
        shutil.copy2(str(src), str(dst))
    
    return {
        "action": "copy",
        "source": str(src),
        "destination": str(dst),
        "message": f"Copied {src.name} → {dst.name}"
    }


def delete_file(path: str) -> dict:
    """Delete a file or directory."""
    target = resolve_path(path)
    
    if not target.exists():
        raise ValueError(f"Not found: {path}")
    
    name = target.name
    
    if target.is_dir():
        shutil.rmtree(str(target))
        return {"action": "delete", "path": str(target), "message": f"Directory deleted: {name}"}
    else:
        size = target.stat().st_size
        target.unlink()
        return {"action": "delete", "path": str(target), "size": size, "message": f"File deleted: {name}"}


def search_files(path: str = "", pattern: str = "*", search_term: str = "") -> dict:
    """Search for files by pattern, optionally containing a search term."""
    dir_path = resolve_path(path)
    
    if not dir_path.exists() or not dir_path.is_dir():
        raise ValueError(f"Invalid directory: {path}")
    
    results = []
    
    for file_path in dir_path.rglob(pattern):
        if not file_path.is_file() or is_forbidden(file_path):
            continue
        
        if search_term:
            try:
                if file_path.stat().st_size > MAX_FILE_SIZE:
                    continue
                content = file_path.read_text(encoding='utf-8')
                if search_term.lower() not in content.lower():
                    continue
                
                # Find matching lines
                matches = []
                for i, line in enumerate(content.splitlines(), 1):
                    if search_term.lower() in line.lower():
                        matches.append({"line": i, "content": line.strip()[:150]})
                        if len(matches) >= 5:
                            break
                
                results.append({"file": str(file_path), "matches": matches})
            except (UnicodeDecodeError, PermissionError):
                continue
        else:
            results.append({
                "file": str(file_path),
                "size": file_path.stat().st_size,
                "modified": datetime.fromtimestamp(file_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            })
        
        if len(results) >= 50:
            break
    
    return {
        "action": "search",
        "path": str(dir_path),
        "pattern": pattern,
        "search_term": search_term or None,
        "results": results,
        "total_found": len(results)
    }


def mkdir(path: str) -> dict:
    """Create a directory (including parents)."""
    dir_path = resolve_path(path)
    dir_path.mkdir(parents=True, exist_ok=True)
    return {"action": "mkdir", "path": str(dir_path), "message": f"Directory created: {dir_path.name}"}


def file_info(path: str) -> dict:
    """Get detailed info about a file or directory."""
    target = resolve_path(path)
    
    if not target.exists():
        raise ValueError(f"Not found: {path}")
    
    stat = target.stat()
    info = {
        "action": "info",
        "path": str(target),
        "name": target.name,
        "is_file": target.is_file(),
        "is_directory": target.is_dir(),
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "created": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
    }
    
    if target.is_dir():
        try:
            items = list(target.iterdir())
            info["children"] = len(items)
        except PermissionError:
            info["children"] = "access denied"
    
    return info


def tree(path: str = "", max_depth: int = 3) -> dict:
    """Show directory tree."""
    dir_path = resolve_path(path)
    
    if not dir_path.exists() or not dir_path.is_dir():
        raise ValueError(f"Invalid directory: {path}")
    
    lines = [str(dir_path)]
    count = {"files": 0, "dirs": 0}
    
    def walk(directory: Path, prefix: str, depth: int):
        if depth > max_depth:
            return
        
        try:
            entries = sorted(directory.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return
        
        for i, entry in enumerate(entries):
            if is_forbidden(entry) or entry.name.startswith('.'):
                continue
            
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            
            if entry.is_dir():
                lines.append(f"{prefix}{connector}📁 {entry.name}/")
                count["dirs"] += 1
                extension = "    " if is_last else "│   "
                walk(entry, prefix + extension, depth + 1)
            else:
                size = entry.stat().st_size
                size_str = f"{size}" if size < 1024 else f"{size // 1024}KB"
                lines.append(f"{prefix}{connector}📄 {entry.name} ({size_str})")
                count["files"] += 1
            
            if count["files"] + count["dirs"] >= 200:
                lines.append(f"{prefix}    ... (truncated)")
                return
    
    walk(dir_path, "", 1)
    
    return {
        "action": "tree",
        "path": str(dir_path),
        "tree": "\n".join(lines),
        "total_files": count["files"],
        "total_dirs": count["dirs"]
    }


def open_path(path: str) -> dict:
    """Open a file or folder in its default application (File Explorer for folders)."""
    import subprocess
    target = resolve_path(path)
    
    if not target.exists():
        raise ValueError(f"Not found: {path}")
    
    # Use os.startfile on Windows to open in default app
    try:
        os.startfile(str(target))
    except AttributeError:
        # Fallback for non-Windows
        subprocess.Popen(['xdg-open', str(target)])
    
    kind = "folder" if target.is_dir() else "file"
    return {
        "action": "open",
        "path": str(target),
        "message": f"Opened {kind}: {target.name}"
    }


# ── Main Entry Point ──
def main():
    try:
        params = json.loads(os.environ.get("SKILL_PARAMS", "{}"))
        action = params.get("action", "")
        
        actions = {
            "list": lambda: list_files(params.get("path", ""), params.get("pattern", "*")),
            "read": lambda: read_file(params.get("path", "")),
            "write": lambda: write_file(params.get("path", ""), params.get("content", "")),
            "create": lambda: write_file(params.get("path", ""), params.get("content", "")),
            "edit": lambda: write_file(params.get("path", ""), params.get("content", "")),
            "move": lambda: move_file(params.get("path", ""), params.get("new_path", "")),
            "copy": lambda: copy_file(params.get("path", ""), params.get("new_path", "")),
            "delete": lambda: delete_file(params.get("path", "")),
            "search": lambda: search_files(params.get("path", ""), params.get("pattern", "*"), params.get("search_term", "")),
            "mkdir": lambda: mkdir(params.get("path", "")),
            "info": lambda: file_info(params.get("path", "")),
            "tree": lambda: tree(params.get("path", ""), params.get("max_depth", 3)),
            "open": lambda: open_path(params.get("path", "")),
        }
        
        if action not in actions:
            raise ValueError(f"Unknown action: {action}. Available: {', '.join(actions.keys())}")
        
        result = actions[action]()
        print(json.dumps(result, indent=2, default=str))
    
    except Exception as e:
        print(json.dumps({"error": str(e), "action": params.get("action", "unknown")}))
        sys.exit(1)


if __name__ == "__main__":
    main()