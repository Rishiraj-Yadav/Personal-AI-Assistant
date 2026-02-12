"""
Bulk File Operations Skill
Perform operations on multiple files at once
"""
from typing import Dict, Any, List
from pathlib import Path
import shutil
import re
from loguru import logger


class BulkOperationsSkill:
    """Bulk file operations"""
    
    def __init__(self):
        """Initialize bulk operations"""
        logger.info("BulkOperationsSkill initialized")
    
    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform bulk file operations
        
        Args:
            action: "rename", "move", "copy", "delete"
            location: Directory containing files
            pattern: File pattern to match (*.txt, image*.png, etc.)
            rename_pattern: New name pattern (for rename)
            destination: Destination directory (for move/copy)
            prefix: Add prefix to filenames
            suffix: Add suffix to filenames
            find_replace: Dict with "find" and "replace" for filename
            dry_run: Preview changes without executing
            
        Returns:
            Operation results
        """
        try:
            action = args.get("action")
            location = args.get("location", str(Path.home() / "Downloads"))
            pattern = args.get("pattern", "*")
            dry_run = args.get("dry_run", False)
            
            source_path = Path(location).expanduser()
            if not source_path.exists():
                return {"success": False, "error": f"Location not found: {location}"}
            
            # Get matching files
            files = list(source_path.glob(pattern))
            files = [f for f in files if f.is_file()]
            
            if not files:
                return {
                    "success": True,
                    "message": f"No files matching '{pattern}' found in {location}",
                    "count": 0
                }
            
            # Perform action
            if action == "rename":
                result = self._bulk_rename(files, args, dry_run)
            elif action == "move":
                result = self._bulk_move(files, args, dry_run)
            elif action == "copy":
                result = self._bulk_copy(files, args, dry_run)
            elif action == "delete":
                result = self._bulk_delete(files, args, dry_run)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
            
            return {
                "success": True,
                "action": action,
                "location": str(source_path),
                "pattern": pattern,
                "dry_run": dry_run,
                "files_processed": len(files),
                **result
            }
        
        except Exception as e:
            logger.error(f"Bulk operations error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def _bulk_rename(self, files: List[Path], args: Dict, dry_run: bool) -> Dict:
        """Rename multiple files"""
        prefix = args.get("prefix", "")
        suffix = args.get("suffix", "")
        find_replace = args.get("find_replace", {})
        numbered = args.get("numbered", False)  # Add numbers: file_001, file_002
        
        operations = []
        stats = {"renamed": 0, "skipped": 0, "errors": 0}
        
        for idx, file_path in enumerate(files, 1):
            new_name = file_path.stem
            
            # Apply find/replace
            if find_replace:
                find_text = find_replace.get("find", "")
                replace_text = find_replace.get("replace", "")
                new_name = new_name.replace(find_text, replace_text)
            
            # Add prefix/suffix
            new_name = f"{prefix}{new_name}{suffix}"
            
            # Add numbering
            if numbered:
                digits = len(str(len(files)))
                new_name = f"{new_name}_{str(idx).zfill(digits)}"
            
            new_path = file_path.parent / f"{new_name}{file_path.suffix}"
            
            # Handle conflicts
            counter = 1
            while new_path.exists() and new_path != file_path:
                new_path = file_path.parent / f"{new_name}_{counter}{file_path.suffix}"
                counter += 1
            
            operations.append({
                "old": str(file_path),
                "new": str(new_path),
                "old_name": file_path.name,
                "new_name": new_path.name
            })
            
            # Execute rename
            if not dry_run and new_path != file_path:
                try:
                    file_path.rename(new_path)
                    stats["renamed"] += 1
                except Exception as e:
                    logger.error(f"Failed to rename {file_path}: {e}")
                    stats["errors"] += 1
        
        return {"operations": operations, "stats": stats}
    
    def _bulk_move(self, files: List[Path], args: Dict, dry_run: bool) -> Dict:
        """Move multiple files"""
        destination = args.get("destination")
        if not destination:
            return {"error": "Destination required for move operation"}
        
        dest_path = Path(destination).expanduser()
        if not dry_run:
            dest_path.mkdir(parents=True, exist_ok=True)
        
        operations = []
        stats = {"moved": 0, "skipped": 0, "errors": 0}
        
        for file_path in files:
            target = dest_path / file_path.name
            
            # Handle conflicts
            if target.exists():
                counter = 1
                while target.exists():
                    target = dest_path / f"{file_path.stem}_{counter}{file_path.suffix}"
                    counter += 1
            
            operations.append({
                "source": str(file_path),
                "target": str(target)
            })
            
            # Execute move
            if not dry_run:
                try:
                    shutil.move(str(file_path), str(target))
                    stats["moved"] += 1
                except Exception as e:
                    logger.error(f"Failed to move {file_path}: {e}")
                    stats["errors"] += 1
        
        return {"operations": operations, "stats": stats, "destination": str(dest_path)}
    
    def _bulk_copy(self, files: List[Path], args: Dict, dry_run: bool) -> Dict:
        """Copy multiple files"""
        destination = args.get("destination")
        if not destination:
            return {"error": "Destination required for copy operation"}
        
        dest_path = Path(destination).expanduser()
        if not dry_run:
            dest_path.mkdir(parents=True, exist_ok=True)
        
        operations = []
        stats = {"copied": 0, "skipped": 0, "errors": 0}
        
        for file_path in files:
            target = dest_path / file_path.name
            
            operations.append({
                "source": str(file_path),
                "target": str(target)
            })
            
            # Execute copy
            if not dry_run:
                try:
                    shutil.copy2(str(file_path), str(target))
                    stats["copied"] += 1
                except Exception as e:
                    logger.error(f"Failed to copy {file_path}: {e}")
                    stats["errors"] += 1
        
        return {"operations": operations, "stats": stats, "destination": str(dest_path)}
    
    def _bulk_delete(self, files: List[Path], args: Dict, dry_run: bool) -> Dict:
        """Delete multiple files (requires confirmation)"""
        operations = []
        stats = {"deleted": 0, "skipped": 0, "errors": 0}
        
        total_size = 0
        for file_path in files:
            size = file_path.stat().st_size
            total_size += size
            
            operations.append({
                "file": str(file_path),
                "name": file_path.name,
                "size": size
            })
            
            # Execute delete
            if not dry_run:
                try:
                    file_path.unlink()
                    stats["deleted"] += 1
                except Exception as e:
                    logger.error(f"Failed to delete {file_path}: {e}")
                    stats["errors"] += 1
        
        return {
            "operations": operations,
            "stats": stats,
            "total_size": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2)
        }


# Global instance
bulk_operations_skill = BulkOperationsSkill()