"""
File Organizer Skill
Auto-organize files by type, date, or custom rules
"""
from typing import Dict, Any, List
from pathlib import Path
import shutil
from datetime import datetime
from loguru import logger


class FileOrganizerSkill:
    """Organize files automatically"""
    
    def __init__(self):
        """Initialize file organizer"""
        self.file_categories = {
            "Images": ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.ico', '.webp'],
            "Documents": ['.pdf', '.doc', '.docx', '.txt', '.rtf', '.odt', '.xls', '.xlsx', '.ppt', '.pptx'],
            "Videos": ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm'],
            "Audio": ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', '.m4a'],
            "Archives": ['.zip', '.rar', '.7z', '.tar', '.gz', '.bz2'],
            "Code": ['.py', '.js', '.java', '.cpp', '.c', '.h', '.cs', '.php', '.rb', '.go', '.rs'],
            "Executables": ['.exe', '.msi', '.dmg', '.app', '.deb', '.rpm'],
        }
        logger.info("FileOrganizerSkill initialized")
    
    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Organize files in a directory
        
        Args:
            location: Directory to organize
            method: "type" (by file type), "date" (by date), "size" (by size)
            create_subdirs: Create subdirectories for categories
            dry_run: Preview changes without moving files
            
        Returns:
            Organization results
        """
        try:
            location = args.get("location", str(Path.home() / "Downloads"))
            method = args.get("method", "type")
            create_subdirs = args.get("create_subdirs", True)
            dry_run = args.get("dry_run", False)
            
            source_path = Path(location).expanduser()
            if not source_path.exists() or not source_path.is_dir():
                return {"success": False, "error": f"Directory not found: {location}"}
            
            if method == "type":
                result = self._organize_by_type(source_path, create_subdirs, dry_run)
            elif method == "date":
                result = self._organize_by_date(source_path, create_subdirs, dry_run)
            elif method == "size":
                result = self._organize_by_size(source_path, create_subdirs, dry_run)
            else:
                return {"success": False, "error": f"Unknown method: {method}"}
            
            return {
                "success": True,
                "action": "organize",
                "method": method,
                "location": str(source_path),
                "dry_run": dry_run,
                **result
            }
        
        except Exception as e:
            logger.error(f"File organizer error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def _organize_by_type(self, path: Path, create_subdirs: bool, dry_run: bool) -> Dict:
        """Organize files by file type"""
        operations = []
        stats = {"moved": 0, "skipped": 0, "errors": 0}
        
        for file_path in path.iterdir():
            if not file_path.is_file():
                continue
            
            # Determine category
            category = self._get_category(file_path.suffix.lower())
            
            if not category:
                stats["skipped"] += 1
                continue
            
            # Create target directory
            if create_subdirs:
                target_dir = path / category
            else:
                target_dir = path
            
            target_file = target_dir / file_path.name
            
            # Handle duplicates
            counter = 1
            while target_file.exists():
                target_file = target_dir / f"{file_path.stem}_{counter}{file_path.suffix}"
                counter += 1
            
            operations.append({
                "source": str(file_path),
                "target": str(target_file),
                "category": category,
                "size": file_path.stat().st_size
            })
            
            # Execute move
            if not dry_run:
                try:
                    target_dir.mkdir(exist_ok=True)
                    shutil.move(str(file_path), str(target_file))
                    stats["moved"] += 1
                except Exception as e:
                    logger.error(f"Failed to move {file_path}: {e}")
                    stats["errors"] += 1
        
        return {
            "operations": operations,
            "stats": stats,
            "total_files": len(operations)
        }
    
    def _organize_by_date(self, path: Path, create_subdirs: bool, dry_run: bool) -> Dict:
        """Organize files by modification date"""
        operations = []
        stats = {"moved": 0, "skipped": 0, "errors": 0}
        
        for file_path in path.iterdir():
            if not file_path.is_file():
                continue
            
            # Get modification date
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
            date_folder = mtime.strftime("%Y-%m")  # e.g., "2024-01"
            
            # Create target directory
            if create_subdirs:
                target_dir = path / date_folder
            else:
                target_dir = path
            
            target_file = target_dir / file_path.name
            
            operations.append({
                "source": str(file_path),
                "target": str(target_file),
                "date": mtime.strftime("%Y-%m-%d"),
                "size": file_path.stat().st_size
            })
            
            # Execute move
            if not dry_run:
                try:
                    target_dir.mkdir(exist_ok=True)
                    shutil.move(str(file_path), str(target_file))
                    stats["moved"] += 1
                except Exception as e:
                    logger.error(f"Failed to move {file_path}: {e}")
                    stats["errors"] += 1
        
        return {
            "operations": operations,
            "stats": stats,
            "total_files": len(operations)
        }
    
    def _organize_by_size(self, path: Path, create_subdirs: bool, dry_run: bool) -> Dict:
        """Organize files by size"""
        operations = []
        stats = {"moved": 0, "skipped": 0, "errors": 0}
        
        size_categories = {
            "Small": (0, 1024 * 1024),           # < 1MB
            "Medium": (1024 * 1024, 10 * 1024 * 1024),  # 1-10MB
            "Large": (10 * 1024 * 1024, float('inf'))   # > 10MB
        }
        
        for file_path in path.iterdir():
            if not file_path.is_file():
                continue
            
            size = file_path.stat().st_size
            
            # Determine size category
            size_cat = "Unknown"
            for cat, (min_size, max_size) in size_categories.items():
                if min_size <= size < max_size:
                    size_cat = cat
                    break
            
            # Create target directory
            if create_subdirs:
                target_dir = path / size_cat
            else:
                target_dir = path
            
            target_file = target_dir / file_path.name
            
            operations.append({
                "source": str(file_path),
                "target": str(target_file),
                "category": size_cat,
                "size": size
            })
            
            # Execute move
            if not dry_run:
                try:
                    target_dir.mkdir(exist_ok=True)
                    shutil.move(str(file_path), str(target_file))
                    stats["moved"] += 1
                except Exception as e:
                    logger.error(f"Failed to move {file_path}: {e}")
                    stats["errors"] += 1
        
        return {
            "operations": operations,
            "stats": stats,
            "total_files": len(operations)
        }
    
    def _get_category(self, extension: str) -> str:
        """Get category for file extension"""
        for category, extensions in self.file_categories.items():
            if extension in extensions:
                return category
        return None


# Global instance
file_organizer_skill = FileOrganizerSkill()