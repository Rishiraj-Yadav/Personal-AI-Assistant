"""
Screenshot Skill
Captures desktop screenshots
"""
import base64
import io
from typing import Dict, Any, Optional
from PIL import Image
import mss
from loguru import logger
from config import settings


class ScreenshotSkill:
    """Captures screenshots of the desktop"""
    
    def __init__(self):
        """Initialize screenshot skill"""
        self.sct = mss.mss()
        logger.info("ScreenshotSkill initialized")
    
    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Capture screenshot
        
        Args:
            region: Optional dict with {x, y, width, height}
            monitor: Monitor number (0=all, 1=primary, 2=secondary, etc.)
            format: Output format (base64, file)
            
        Returns:
            Screenshot data
        """
        try:
            monitor = args.get("monitor", 1)  # 1 = primary monitor
            region = args.get("region")
            output_format = args.get("format", "base64")
            
            # Capture screenshot
            if region:
                # Specific region
                screenshot = self.sct.grab({
                    "left": region["x"],
                    "top": region["y"],
                    "width": region["width"],
                    "height": region["height"]
                })
            else:
                # Full monitor
                screenshot = self.sct.grab(self.sct.monitors[monitor])
            
            # Convert to PIL Image
            img = Image.frombytes(
                "RGB",
                (screenshot.width, screenshot.height),
                screenshot.rgb
            )
            
            # Encode based on format
            if output_format == "base64":
                # Convert to base64
                buffered = io.BytesIO()
                img.save(buffered, format="PNG")
                img_base64 = base64.b64encode(buffered.getvalue()).decode()
                
                return {
                    "success": True,
                    "image_base64": img_base64,
                    "width": screenshot.width,
                    "height": screenshot.height,
                    "format": "PNG",
                    "monitor": monitor
                }
            
            elif output_format == "file":
                # Save to file
                filepath = args.get("filepath", "screenshot.png")
                img.save(filepath)
                
                return {
                    "success": True,
                    "filepath": filepath,
                    "width": screenshot.width,
                    "height": screenshot.height
                }
            
            else:
                return {
                    "success": False,
                    "error": f"Unknown format: {output_format}"
                }
        
        except Exception as e:
            logger.error(f"Screenshot error: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_monitors(self) -> Dict[str, Any]:
        """Get information about available monitors"""
        monitors = []
        for i, monitor in enumerate(self.sct.monitors):
            monitors.append({
                "index": i,
                "left": monitor["left"],
                "top": monitor["top"],
                "width": monitor["width"],
                "height": monitor["height"]
            })
        
        return {
            "success": True,
            "monitors": monitors,
            "count": len(monitors) - 1  # -1 because index 0 is all monitors
        }


# Global instance
screenshot_skill = ScreenshotSkill()