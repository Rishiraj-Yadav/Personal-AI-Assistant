"""
File Archiver Skill
Create and extract ZIP archives
"""
from typing import Dict, Any, List
from pathlib import Path
import zipfile
import tarfile
import shutil
from loguru import logger


class FileArchiverSkill:
    """Archive and extract files"""
    
    def __init__(self):
        """Initialize file archiver"""
        logger.info("FileArchiverSkill initialized")
    
    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Archive or extract files
        
        Args:
            action: "create" or "extract"
            source: File or directory to archive / Archive to extract
            destination: Output location
            format: "zip", "tar", "tar.gz" (default: zip)
            include_pattern: Include only matching files
            exclude_pattern: Exclude matching files
            
        Returns:
            Operation result
        """
        try:
            action = args.get("action")
            source = args.get("source")
            destination = args.get("destination")
            archive_format = args.get("format", "zip")
            
            if not source:
                return {"success": False, "error": "Source required"}
            
            source_path = Path(source).expanduser()
            if not source_path.exists():
                return {"success": False, "error": f"Source not found: {source}"}
            
            if action == "create":
                result = self._create_archive(source_path, destination, archive_format, args)
            elif action == "extract":
                result = self._extract_archive(source_path, destination, archive_format)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
            
            return {
                "success": True,
                "action": action,
                **result
            }
        
        except Exception as e:
            logger.error(f"File archiver error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def _create_archive(
        self, 
        source: Path, 
        destination: str, 
        format: str,
        args: Dict
    ) -> Dict:
        """Create an archive"""
        include_pattern = args.get("include_pattern", "*")
        exclude_pattern = args.get("exclude_pattern")
        
        # Determine output path
        if destination:
            output_path = Path(destination).expanduser()
        else:
            if source.is_file():
                output_path = source.parent / f"{source.stem}.{format}"
            else:
                output_path = source.parent / f"{source.name}.{format}"
        
        # Collect files to archive
        if source.is_file():
            files = [source]
        else:
            files = list(source.rglob(include_pattern))
            files = [f for f in files if f.is_file()]
            
            if exclude_pattern:
                import fnmatch
                files = [f for f in files if not fnmatch.fnmatch(str(f), exclude_pattern)]
        
        # Create archive
        if format == "zip":
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for file in files:
                    arcname = file.relative_to(source.parent)
                    zf.write(file, arcname)
        
        elif format in ("tar", "tar.gz", "tgz"):
            mode = "w:gz" if format in ("tar.gz", "tgz") else "w"
            with tarfile.open(output_path, mode) as tf:
                for file in files:
                    arcname = file.relative_to(source.parent)
                    tf.add(file, arcname)
        
        else:
            return {"error": f"Unsupported format: {format}"}
        
        # Get archive size
        archive_size = output_path.stat().st_size
        original_size = sum(f.stat().st_size for f in files)
        compression_ratio = (1 - archive_size / original_size) * 100 if original_size > 0 else 0
        
        return {
            "archive": str(output_path),
            "format": format,
            "files_archived": len(files),
            "original_size": original_size,
            "archive_size": archive_size,
            "compression_ratio": round(compression_ratio, 2),
            "size_saved_mb": round((original_size - archive_size) / (1024 * 1024), 2)
        }
    
    def _extract_archive(self, source: Path, destination: str, format: str) -> Dict:
        """Extract an archive"""
        # Determine output path
        if destination:
            output_path = Path(destination).expanduser()
        else:
            output_path = source.parent / source.stem
        
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Detect format from extension if not specified
        if not format or format == "auto":
            ext = source.suffix.lower()
            if ext == ".zip":
                format = "zip"
            elif ext in (".tar", ".gz", ".tgz"):
                format = "tar"
            else:
                return {"error": f"Cannot detect archive format from {ext}"}
        
        # Extract archive
        extracted_files = []
        
        if format == "zip":
            with zipfile.ZipFile(source, 'r') as zf:
                zf.extractall(output_path)
                extracted_files = zf.namelist()
        
        elif format == "tar":
            with tarfile.open(source, 'r:*') as tf:
                tf.extractall(output_path)
                extracted_files = tf.getnames()
        
        else:
            return {"error": f"Unsupported format: {format}"}
        
        return {
            "archive": str(source),
            "destination": str(output_path),
            "format": format,
            "files_extracted": len(extracted_files),
            "files": extracted_files[:20]  # Show first 20 files
        }


# Global instance
file_archiver_skill = FileArchiverSkill()