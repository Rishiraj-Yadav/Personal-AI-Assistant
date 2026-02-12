"""
File Converter Skill
Convert files between different formats
"""
from typing import Dict, Any
from pathlib import Path
from PIL import Image
import subprocess
from loguru import logger


class FileConverterSkill:
    """Convert files between formats"""
    
    def __init__(self):
        """Initialize file converter"""
        self.image_formats = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff'}
        logger.info("FileConverterSkill initialized")
    
    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert file format
        
        Args:
            source: Source file path
            target_format: Target format (jpg, png, pdf, etc.)
            destination: Output file path (optional)
            quality: Image quality for lossy formats (1-100)
            resize: Resize image (width, height) tuple
            
        Returns:
            Conversion result
        """
        try:
            source = args.get("source")
            target_format = args.get("target_format", "").lower()
            destination = args.get("destination")
            quality = args.get("quality", 95)
            resize = args.get("resize")
            
            if not source:
                return {"success": False, "error": "Source file required"}
            
            if not target_format:
                return {"success": False, "error": "Target format required"}
            
            source_path = Path(source).expanduser()
            if not source_path.exists():
                return {"success": False, "error": f"Source not found: {source}"}
            
            # Determine output path
            if destination:
                output_path = Path(destination).expanduser()
            else:
                # Remove leading dot if present
                fmt = target_format.lstrip('.')
                output_path = source_path.parent / f"{source_path.stem}.{fmt}"
            
            # Detect conversion type
            source_ext = source_path.suffix.lower()
            
            if source_ext in self.image_formats:
                result = self._convert_image(source_path, output_path, quality, resize)
            else:
                return {
                    "success": False,
                    "error": f"Conversion from {source_ext} not supported yet"
                }
            
            return {
                "success": True,
                "action": "convert",
                "source": str(source_path),
                "destination": str(output_path),
                **result
            }
        
        except Exception as e:
            logger.error(f"File converter error: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def _convert_image(
        self, 
        source: Path, 
        destination: Path, 
        quality: int,
        resize: tuple = None
    ) -> Dict:
        """Convert image format"""
        try:
            # Open image
            with Image.open(source) as img:
                # Convert RGBA to RGB if saving as JPEG
                if destination.suffix.lower() in ('.jpg', '.jpeg') and img.mode == 'RGBA':
                    # Create white background
                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                    rgb_img.paste(img, mask=img.split()[3])  # Use alpha channel as mask
                    img = rgb_img
                
                # Resize if requested
                if resize:
                    width, height = resize
                    img = img.resize((width, height), Image.Resampling.LANCZOS)
                
                # Get original size
                original_size = source.stat().st_size
                original_dimensions = img.size
                
                # Save with appropriate parameters
                save_kwargs = {}
                if destination.suffix.lower() in ('.jpg', '.jpeg'):
                    save_kwargs['quality'] = quality
                    save_kwargs['optimize'] = True
                elif destination.suffix.lower() == '.png':
                    save_kwargs['optimize'] = True
                elif destination.suffix.lower() == '.webp':
                    save_kwargs['quality'] = quality
                
                img.save(destination, **save_kwargs)
            
            # Get converted file size
            converted_size = destination.stat().st_size
            
            return {
                "format": destination.suffix.lstrip('.'),
                "original_size": original_size,
                "converted_size": converted_size,
                "original_dimensions": original_dimensions,
                "saved_bytes": original_size - converted_size,
                "saved_mb": round((original_size - converted_size) / (1024 * 1024), 2)
            }
        
        except Exception as e:
            raise Exception(f"Image conversion failed: {str(e)}")


# Global instance
file_converter_skill = FileConverterSkill()