"""
System File Finder Skill
Searches for files across the entire computer (with safety restrictions)
"""
from typing import Dict, Any, List
from pathlib import Path
import os
import fnmatch
from datetime import datetime, timedelta
from loguru import logger
import platform


class SystemFileFinderSkill:
    """Find files system-wide"""
    
    def __init__(self):
        """Initialize file finder"""
        self.system = platform.system()
        self._init_safe_paths()
        logger.info("SystemFileFinderSkill initialized")
    
    def _init_safe_paths(self):
        """Initialize safe search paths based on OS"""
        home = Path.home()
        
        if self.system == "Windows":
            self.safe_paths = [
                home / "Documents",
                home / "Downloads",
                home / "Desktop",
                home / "Pictures",
                home / "Videos",
                home / "Music",
            ]
            self.forbidden_paths = [
                Path("C:/Windows"),
                Path("C:/Program Files"),
                Path("C:/Program Files (x86)"),
                home / "AppData"
            ]
        
        elif self.system == "Darwin":  # macOS
            self.safe_paths = [
                home / "Documents",
                home / "Downloads",
                home / "Desktop",
                home / "Pictures",
                home / "Movies",
                home / "Music",
            ]
            self.forbidden_paths = [
                Path("/System"),
                Path("/Library"),
                home / "Library"
            ]
        
        else:  # Linux
            self.safe_paths = [
                home / "Documents",
                home / "Downloads",
                home / "Desktop",
                home / "Pictures",
                home / "Videos",
                home / "Music",
                home,
            ]
            self.forbidden_paths = [
                Path("/etc"),
                Path("/usr"),
                Path("/bin"),
                Path("/sbin"),
                Path("/var")
            ]
    
    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Search for files
        
        Args:
            query: Filename pattern (supports wildcards)
            extension: File extension filter (.pdf, .jpg, etc.)
            location: Specific folder to search (optional)
            modified_days: Files modified in last N days
            size_min: Minimum file size in bytes
            size_max: Maximum file size in bytes
            limit: Maximum results to return
            
        Returns:
            List of matching files
        """
        try:
            query = args.get("query", "*")
            extension = args.get("extension", "")
            location = args.get("location")
            modified_days = args.get("modified_days")
            size_min = args.get("size_min", 0)
            size_max = args.get("size_max", float('inf'))
            limit = args.get("limit", 100)
            
            # Determine search paths
            if location:
                search_path = Path(location).expanduser()
                if not self._is_safe_path(search_path):
                    return {
                        "success": False,
                        "error": f"Access denied to {location}. Choose from: {[str(p) for p in self.safe_paths]}"
                    }
                search_paths = [search_path]
            else:
                search_paths = self.safe_paths
            
            # Calculate date threshold
            date_threshold = None
            if modified_days:
                date_threshold = datetime.now() - timedelta(days=modified_days)
            
            # Search for files
            results = []
            for search_path in search_paths:
                if not search_path.exists():
                    continue
                
                try:
                    for file_path in search_path.rglob("*"):
                        # Skip directories
                        if not file_path.is_file():
                            continue
                        
                        # Skip forbidden paths
                        if self._is_forbidden(file_path):
                            continue
                        
                        # Apply filters
                        if not self._matches_filters(
                            file_path, query, extension, 
                            date_threshold, size_min, size_max
                        ):
                            continue
                        
                        # Add to results
                        try:
                            stat = file_path.stat()
                            results.append({
                                "name": file_path.name,
                                "path": str(file_path),
                                "size": stat.st_size,
                                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                                "extension": file_path.suffix,
                                "parent": str(file_path.parent)
                            })
                            
                            if len(results) >= limit:
                                break
                        except (PermissionError, OSError):
                            continue
                    
                    if len(results) >= limit:
                        break
                        
                except PermissionError:
                    logger.warning(f"Permission denied: {search_path}")
                    continue
            
            return {
                "success": True,
                "action": "search",
                "query": query,
                "results": results,
                "count": len(results),
                "limit_reached": len(results) >= limit
            }
        
        except Exception as e:
            logger.error(f"File search error: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _is_safe_path(self, path: Path) -> bool:
        """Check if path is in safe locations"""
        try:
            path = path.resolve()
            return any(
                path == safe_path or safe_path in path.parents
                for safe_path in self.safe_paths
            )
        except Exception:
            return False
    
    def _is_forbidden(self, path: Path) -> bool:
        """Check if path is forbidden"""
        try:
            path = path.resolve()
            return any(
                path == forbidden or forbidden in path.parents
                for forbidden in self.forbidden_paths
            )
        except Exception:
            return False
    
    def _matches_filters(
        self, 
        file_path: Path, 
        query: str,
        extension: str,
        date_threshold,
        size_min: int,
        size_max: int
    ) -> bool:
        """Check if file matches all filters"""
        try:
            # Filename pattern
            if not fnmatch.fnmatch(file_path.name.lower(), query.lower()):
                return False
            
            # Extension filter
            if extension and not file_path.suffix.lower() == extension.lower():
                return False
            
            # Size filter
            size = file_path.stat().st_size
            if size < size_min or size > size_max:
                return False
            
            # Date filter
            if date_threshold:
                mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                if mtime < date_threshold:
                    return False
            
            return True
        
        except (PermissionError, OSError):
            return False


# Global instance
system_file_finder_skill = SystemFileFinderSkill()