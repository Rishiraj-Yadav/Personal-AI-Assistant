"""
Metadata Editor Skill
View and edit file metadata (EXIF, properties, tags)
"""
from typing import Dict, Any
from pathlib import Path
from PIL import Image
from PIL.ExifTags import TAGS
import os
from datetime import datetime
from loguru import logger


class MetadataEditorSkill:
    """Edit file metadata"""
    
    def __init__(self):
        """Initialize metadata editor"""
        logger.info("MetadataEditorSkill initialized")
    
    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        View or edit file metadata
        
        Args:
            action: "view" or "edit"
            file_path: Path to file
            metadata: Dict of metadata to set (for edit action)
            remove_exif: Remove all EXIF data from image
            
        Returns:
            Metadata information
        """
        try:
            action = args.get("action", "view")
            file_path = args.get("file_path")
            
            if not file_path:
                return {"success": False, "error": "File path required"}
            
            path = Path(file_path).expanduser()
            if not path.exists():
                return {"success": False, "error": f"File not found: {file_path}"}
            
            if action == "view":
                result = self._view_metadata(path)
            elif action == "edit":
                metadata = args.get("metadata", {})
                remove_exif = args.get("remove_exif", False)
                result = self._edit_metadata(path, metadata, remove_exif)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
            
            return {
                "success": True,
                "action": action,
                "file": str(path),
                **result
            }
        
        except Exception as e:
            logger.error(f"Metadata editor error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def _view_metadata(self, path: Path) -> Dict:
        """View file metadata"""
        metadata = {}
        
        # Basic file info
        stat = path.stat()
        metadata["basic"] = {
            "name": path.name,
            "size": stat.st_size,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "extension": path.suffix,
            "is_hidden": path.name.startswith('.'),
        }
        
        # Image-specific metadata (EXIF)
        if path.suffix.lower() in ['.jpg', '.jpeg', '.png', '.tiff', '.bmp']:
            try:
                metadata["exif"] = self._get_exif_data(path)
            except Exception as e:
                metadata["exif"] = {"error": str(e)}
        
        # Windows-specific attributes (if on Windows)
        try:
            import platform
            if platform.system() == "Windows":
                import win32api
                import win32con
                attrs = win32api.GetFileAttributes(str(path))
                metadata["windows_attributes"] = {
                    "readonly": bool(attrs & win32con.FILE_ATTRIBUTE_READONLY),
                    "hidden": bool(attrs & win32con.FILE_ATTRIBUTE_HIDDEN),
                    "system": bool(attrs & win32con.FILE_ATTRIBUTE_SYSTEM),
                    "archive": bool(attrs & win32con.FILE_ATTRIBUTE_ARCHIVE),
                }
        except:
            pass
        
        return {"metadata": metadata}
    
    def _edit_metadata(self, path: Path, metadata: Dict, remove_exif: bool) -> Dict:
        """Edit file metadata"""
        changes = []
        
        # Handle EXIF removal for images
        if remove_exif and path.suffix.lower() in ['.jpg', '.jpeg']:
            try:
                with Image.open(path) as img:
                    # Remove EXIF data
                    data = list(img.getdata())
                    image_without_exif = Image.new(img.mode, img.size)
                    image_without_exif.putdata(data)
                    
                    # Save without EXIF
                    image_without_exif.save(path)
                    changes.append("Removed all EXIF data")
            except Exception as e:
                return {"error": f"Failed to remove EXIF: {str(e)}"}
        
        # Edit file timestamps
        if "modified" in metadata:
            try:
                modified_time = datetime.fromisoformat(metadata["modified"]).timestamp()
                os.utime(path, (modified_time, modified_time))
                changes.append(f"Updated modified time to {metadata['modified']}")
            except Exception as e:
                changes.append(f"Failed to update modified time: {str(e)}")
        
        # Windows attributes
        if "attributes" in metadata:
            try:
                import platform
                if platform.system() == "Windows":
                    import win32api
                    import win32con
                    
                    attrs = win32api.GetFileAttributes(str(path))
                    
                    if metadata["attributes"].get("hidden"):
                        attrs |= win32con.FILE_ATTRIBUTE_HIDDEN
                    else:
                        attrs &= ~win32con.FILE_ATTRIBUTE_HIDDEN
                    
                    if metadata["attributes"].get("readonly"):
                        attrs |= win32con.FILE_ATTRIBUTE_READONLY
                    else:
                        attrs &= ~win32con.FILE_ATTRIBUTE_READONLY
                    
                    win32api.SetFileAttributes(str(path), attrs)
                    changes.append("Updated Windows file attributes")
            except Exception as e:
                changes.append(f"Failed to update attributes: {str(e)}")
        
        return {
            "changes": changes,
            "changes_count": len(changes)
        }
    
    def _get_exif_data(self, path: Path) -> Dict:
        """Extract EXIF data from image"""
        exif_data = {}
        
        try:
            with Image.open(path) as img:
                exif = img.getexif()
                
                if exif:
                    for tag_id, value in exif.items():
                        tag = TAGS.get(tag_id, tag_id)
                        
                        # Convert bytes to string
                        if isinstance(value, bytes):
                            try:
                                value = value.decode()
                            except:
                                value = str(value)
                        
                        exif_data[tag] = value
                
                # Add image dimensions
                exif_data["ImageWidth"] = img.width
                exif_data["ImageHeight"] = img.height
                exif_data["ImageMode"] = img.mode
                exif_data["ImageFormat"] = img.format
        
        except Exception as e:
            exif_data["error"] = str(e)
        
        return exif_data


# Global instance
metadata_editor_skill = MetadataEditorSkill()