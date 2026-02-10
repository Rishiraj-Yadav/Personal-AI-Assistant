#!/usr/bin/env python3
"""
File Manager Skill
Safely manages files in a sandboxed workspace
"""
import os
import json
import sys
from pathlib import Path
import fnmatch


# Security configuration
WORKSPACE_ROOT = Path(os.environ.get("WORKSPACE_ROOT", "/workspace"))
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_EXTENSIONS = {
    '.txt', '.py', '.js', '.json', '.md', '.html', '.css', 
    '.yaml', '.yml', '.xml', '.csv', '.log', '.sh', '.sql',
    '.java', '.cpp', '.c', '.h', '.rs', '.go', '.rb', '.php'
}
FORBIDDEN_PATHS = {'.env', 'id_rsa', 'id_dsa', '.ssh', '.aws', 'credentials'}


def validate_path(path_str: str) -> Path:
    """
    Validate and resolve path to prevent directory traversal
    
    Args:
        path_str: Relative path from user
        
    Returns:
        Absolute path within workspace
        
    Raises:
        ValueError: If path is invalid or outside workspace
    """
    if not path_str:
        raise ValueError("Path cannot be empty")
    
    # Check for forbidden patterns
    path_lower = path_str.lower()
    for forbidden in FORBIDDEN_PATHS:
        if forbidden in path_lower:
            raise ValueError(f"Access to '{forbidden}' is forbidden")
    
    # Resolve path
    requested_path = Path(path_str)
    
    # Prevent absolute paths
    if requested_path.is_absolute():
        raise ValueError("Absolute paths are not allowed")
    
    # Resolve relative to workspace
    full_path = (WORKSPACE_ROOT / requested_path).resolve()
    
    # Ensure it's within workspace (prevent ../ traversal)
    try:
        full_path.relative_to(WORKSPACE_ROOT)
    except ValueError:
        raise ValueError("Path outside workspace is not allowed")
    
    return full_path


def validate_extension(path: Path) -> bool:
    """Check if file extension is allowed"""
    return path.suffix.lower() in ALLOWED_EXTENSIONS or path.suffix == ''


def create_file(path: str, content: str) -> dict:
    """Create a new file with content"""
    file_path = validate_path(path)
    
    if not validate_extension(file_path):
        raise ValueError(f"File extension {file_path.suffix} not allowed")
    
    if file_path.exists():
        raise ValueError(f"File already exists: {path}")
    
    if len(content.encode('utf-8')) > MAX_FILE_SIZE:
        raise ValueError(f"Content exceeds maximum size of {MAX_FILE_SIZE} bytes")
    
    # Create parent directories if needed
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write file
    file_path.write_text(content, encoding='utf-8')
    
    return {
        "action": "create",
        "path": str(file_path.relative_to(WORKSPACE_ROOT)),
        "size": len(content.encode('utf-8')),
        "message": f"File created successfully: {path}"
    }


def read_file(path: str) -> dict:
    """Read file contents"""
    file_path = validate_path(path)
    
    if not file_path.exists():
        raise ValueError(f"File not found: {path}")
    
    if not file_path.is_file():
        raise ValueError(f"Path is not a file: {path}")
    
    if file_path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError(f"File too large (max {MAX_FILE_SIZE} bytes)")
    
    content = file_path.read_text(encoding='utf-8')
    
    return {
        "action": "read",
        "path": str(file_path.relative_to(WORKSPACE_ROOT)),
        "content": content,
        "size": len(content.encode('utf-8')),
        "lines": len(content.splitlines())
    }


def edit_file(path: str, content: str) -> dict:
    """Edit/overwrite existing file"""
    file_path = validate_path(path)
    
    if not file_path.exists():
        raise ValueError(f"File not found: {path}. Use 'create' action for new files.")
    
    if not validate_extension(file_path):
        raise ValueError(f"File extension {file_path.suffix} not allowed")
    
    if len(content.encode('utf-8')) > MAX_FILE_SIZE:
        raise ValueError(f"Content exceeds maximum size of {MAX_FILE_SIZE} bytes")
    
    # Backup old size
    old_size = file_path.stat().st_size
    
    # Write new content
    file_path.write_text(content, encoding='utf-8')
    
    return {
        "action": "edit",
        "path": str(file_path.relative_to(WORKSPACE_ROOT)),
        "old_size": old_size,
        "new_size": len(content.encode('utf-8')),
        "message": f"File updated successfully: {path}"
    }


def list_files(path: str = ".", pattern: str = "*") -> dict:
    """List files in directory"""
    dir_path = validate_path(path) if path != "." else WORKSPACE_ROOT
    
    if not dir_path.exists():
        dir_path.mkdir(parents=True, exist_ok=True)
    
    if not dir_path.is_dir():
        raise ValueError(f"Path is not a directory: {path}")
    
    files = []
    directories = []
    
    for item in dir_path.iterdir():
        try:
            relative_path = str(item.relative_to(WORKSPACE_ROOT))
            
            if item.is_file():
                if fnmatch.fnmatch(item.name, pattern):
                    files.append({
                        "name": item.name,
                        "path": relative_path,
                        "size": item.stat().st_size,
                        "extension": item.suffix
                    })
            elif item.is_dir():
                directories.append({
                    "name": item.name,
                    "path": relative_path
                })
        except (PermissionError, OSError):
            continue
    
    return {
        "action": "list",
        "path": str(dir_path.relative_to(WORKSPACE_ROOT)),
        "pattern": pattern,
        "files": sorted(files, key=lambda x: x['name']),
        "directories": sorted(directories, key=lambda x: x['name']),
        "total_files": len(files),
        "total_directories": len(directories)
    }


def move_file(path: str, new_path: str) -> dict:
    """Move or rename a file"""
    old_path = validate_path(path)
    new_path_resolved = validate_path(new_path)
    
    if not old_path.exists():
        raise ValueError(f"Source file not found: {path}")
    
    if new_path_resolved.exists():
        raise ValueError(f"Destination already exists: {new_path}")
    
    if not validate_extension(new_path_resolved):
        raise ValueError(f"Destination extension {new_path_resolved.suffix} not allowed")
    
    # Create parent directories if needed
    new_path_resolved.parent.mkdir(parents=True, exist_ok=True)
    
    # Move file
    old_path.rename(new_path_resolved)
    
    return {
        "action": "move",
        "old_path": str(old_path.relative_to(WORKSPACE_ROOT)),
        "new_path": str(new_path_resolved.relative_to(WORKSPACE_ROOT)),
        "message": f"File moved from {path} to {new_path}"
    }


def delete_file(path: str) -> dict:
    """Delete a file (requires explicit user confirmation)"""
    file_path = validate_path(path)
    
    if not file_path.exists():
        raise ValueError(f"File not found: {path}")
    
    if not file_path.is_file():
        raise ValueError(f"Path is not a file: {path}")
    
    # Get size before deletion
    size = file_path.stat().st_size
    
    # Delete file
    file_path.unlink()
    
    return {
        "action": "delete",
        "path": str(file_path.relative_to(WORKSPACE_ROOT)),
        "size": size,
        "message": f"File deleted: {path}",
        "warning": "This action cannot be undone"
    }


def search_files(search_term: str, pattern: str = "*", path: str = ".") -> dict:
    """Search for term in files"""
    dir_path = validate_path(path) if path != "." else WORKSPACE_ROOT
    
    if not dir_path.exists() or not dir_path.is_dir():
        raise ValueError(f"Invalid directory: {path}")
    
    results = []
    
    for file_path in dir_path.rglob(pattern):
        if not file_path.is_file():
            continue
        
        if file_path.stat().st_size > MAX_FILE_SIZE:
            continue
        
        try:
            content = file_path.read_text(encoding='utf-8')
            lines = content.splitlines()
            
            matches = []
            for line_num, line in enumerate(lines, 1):
                if search_term.lower() in line.lower():
                    matches.append({
                        "line": line_num,
                        "content": line.strip()
                    })
            
            if matches:
                results.append({
                    "file": str(file_path.relative_to(WORKSPACE_ROOT)),
                    "matches": matches[:10]  # Limit to 10 matches per file
                })
        
        except (UnicodeDecodeError, PermissionError):
            continue
    
    return {
        "action": "search",
        "search_term": search_term,
        "pattern": pattern,
        "results": results[:50],  # Limit to 50 files
        "total_files_matched": len(results)
    }


def main():
    """Main entry point"""
    try:
        # Ensure workspace exists
        WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
        
        # Get parameters
        params_json = os.environ.get("SKILL_PARAMS", "{}")
        params = json.loads(params_json)
        
        action = params.get("action")
        if not action:
            raise ValueError("Missing required parameter: action")
        
        # Execute action
        if action == "create":
            path = params.get("path")
            content = params.get("content", "")
            if not path:
                raise ValueError("Missing required parameter: path")
            result = create_file(path, content)
        
        elif action == "read":
            path = params.get("path")
            if not path:
                raise ValueError("Missing required parameter: path")
            result = read_file(path)
        
        elif action == "edit":
            path = params.get("path")
            content = params.get("content", "")
            if not path:
                raise ValueError("Missing required parameter: path")
            result = edit_file(path, content)
        
        elif action == "list":
            path = params.get("path", ".")
            pattern = params.get("pattern", "*")
            result = list_files(path, pattern)
        
        elif action == "move":
            path = params.get("path")
            new_path = params.get("new_path")
            if not path or not new_path:
                raise ValueError("Missing required parameters: path and new_path")
            result = move_file(path, new_path)
        
        elif action == "delete":
            path = params.get("path")
            if not path:
                raise ValueError("Missing required parameter: path")
            result = delete_file(path)
        
        elif action == "search":
            search_term = params.get("search_term")
            if not search_term:
                raise ValueError("Missing required parameter: search_term")
            pattern = params.get("pattern", "*")
            path = params.get("path", ".")
            result = search_files(search_term, pattern, path)
        
        else:
            raise ValueError(f"Unknown action: {action}")
        
        # Output result
        print(json.dumps(result, indent=2))
    
    except Exception as e:
        print(json.dumps({
            "error": str(e),
            "action": params.get("action", "unknown")
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()