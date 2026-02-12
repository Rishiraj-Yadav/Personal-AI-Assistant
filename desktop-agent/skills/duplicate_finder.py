"""
Duplicate Finder Skill
Find duplicate files based on content hash or name
"""
from typing import Dict, Any, List
from pathlib import Path
import hashlib
from collections import defaultdict
from loguru import logger


class DuplicateFinderSkill:
    """Find duplicate files"""
    
    def __init__(self):
        """Initialize duplicate finder"""
        self.chunk_size = 8192
        logger.info("DuplicateFinderSkill initialized")
    
    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Find duplicate files
        
        Args:
            location: Directory to search
            method: "hash" (content-based) or "name" (filename-based)
            min_size: Minimum file size to check (skip small files)
            extensions: List of extensions to check
            
        Returns:
            Groups of duplicate files
        """
        try:
            location = args.get("location", str(Path.home() / "Documents"))
            method = args.get("method", "hash")
            min_size = args.get("min_size", 1024)  # 1KB default
            extensions = args.get("extensions", [])
            
            search_path = Path(location).expanduser()
            if not search_path.exists():
                return {"success": False, "error": f"Location not found: {location}"}
            
            if method == "hash":
                duplicates = self._find_by_hash(search_path, min_size, extensions)
            else:
                duplicates = self._find_by_name(search_path, min_size, extensions)
            
            # Convert to list format
            duplicate_groups = []
            total_wasted_space = 0
            
            for key, files in duplicates.items():
                if len(files) > 1:
                    file_size = files[0]["size"]
                    wasted = file_size * (len(files) - 1)
                    total_wasted_space += wasted
                    
                    duplicate_groups.append({
                        "files": files,
                        "count": len(files),
                        "size_each": file_size,
                        "wasted_space": wasted
                    })
            
            return {
                "success": True,
                "action": "find_duplicates",
                "method": method,
                "duplicate_groups": duplicate_groups,
                "total_duplicates": sum(g["count"] - 1 for g in duplicate_groups),
                "total_wasted_space": total_wasted_space,
                "total_wasted_mb": round(total_wasted_space / (1024*1024), 2)
            }
        
        except Exception as e:
            logger.error(f"Duplicate finder error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def _find_by_hash(self, path: Path, min_size: int, extensions: List[str]) -> Dict:
        """Find duplicates by file content hash"""
        hashes = defaultdict(list)
        
        for file_path in path.rglob("*"):
            if not file_path.is_file():
                continue
            
            try:
                size = file_path.stat().st_size
                if size < min_size:
                    continue
                
                if extensions and file_path.suffix.lower() not in extensions:
                    continue
                
                file_hash = self._hash_file(file_path)
                hashes[file_hash].append({
                    "path": str(file_path),
                    "name": file_path.name,
                    "size": size
                })
            
            except (PermissionError, OSError):
                continue
        
        return hashes
    
    def _find_by_name(self, path: Path, min_size: int, extensions: List[str]) -> Dict:
        """Find duplicates by filename"""
        names = defaultdict(list)
        
        for file_path in path.rglob("*"):
            if not file_path.is_file():
                continue
            
            try:
                size = file_path.stat().st_size
                if size < min_size:
                    continue
                
                if extensions and file_path.suffix.lower() not in extensions:
                    continue
                
                names[file_path.name].append({
                    "path": str(file_path),
                    "name": file_path.name,
                    "size": size
                })
            
            except (PermissionError, OSError):
                continue
        
        return names
    
    def _hash_file(self, path: Path) -> str:
        """Calculate MD5 hash of file"""
        md5 = hashlib.md5()
        with open(path, 'rb') as f:
            while chunk := f.read(self.chunk_size):
                md5.update(chunk)
        return md5.hexdigest()


# Global instance
duplicate_finder_skill = DuplicateFinderSkill()