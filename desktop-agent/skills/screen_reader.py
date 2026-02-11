"""
Screen Reader Skill
Reads text from screen using OCR (Optical Character Recognition)
"""
from typing import Dict, Any, Optional
import pytesseract
from PIL import Image
import io
import base64
from loguru import logger
from config import settings
from skills.screenshot import screenshot_skill


class ScreenReaderSkill:
    """Reads text from screen using OCR"""
    
    def __init__(self):
        """Initialize screen reader"""
        self.ocr_enabled = settings.OCR_ENABLED
        logger.info(f"ScreenReaderSkill initialized (OCR: {self.ocr_enabled})")
    
    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Read text from screen
        
        Args:
            region: Optional region {x, y, width, height}
            language: OCR language (default: eng)
            image_base64: Optional - provide image instead of screenshot
            
        Returns:
            Extracted text
        """
        try:
            if not self.ocr_enabled:
                return {
                    "success": False,
                    "error": "OCR is disabled in configuration"
                }
            
            # Get image
            image_data = args.get("image_base64")
            
            if image_data:
                # Decode provided image
                image_bytes = base64.b64decode(image_data)
                image = Image.open(io.BytesIO(image_bytes))
            else:
                # Take screenshot
                screenshot_args = {}
                if args.get("region"):
                    screenshot_args["region"] = args["region"]
                
                screenshot_result = screenshot_skill.execute(screenshot_args)
                
                if not screenshot_result["success"]:
                    return screenshot_result
                
                # Decode screenshot
                image_bytes = base64.b64decode(screenshot_result["image_base64"])
                image = Image.open(io.BytesIO(image_bytes))
            
            # Perform OCR
            language = args.get("language", settings.OCR_LANGUAGE)
            text = pytesseract.image_to_string(image, lang=language)
            
            # Get detailed data if requested
            detailed = args.get("detailed", False)
            if detailed:
                data = pytesseract.image_to_data(image, lang=language, output_type=pytesseract.Output.DICT)
                words = []
                for i, word in enumerate(data['text']):
                    if word.strip():
                        words.append({
                            "text": word,
                            "confidence": data['conf'][i],
                            "x": data['left'][i],
                            "y": data['top'][i],
                            "width": data['width'][i],
                            "height": data['height'][i]
                        })
                
                return {
                    "success": True,
                    "action": "read_screen",
                    "text": text.strip(),
                    "words": words,
                    "word_count": len(words)
                }
            
            return {
                "success": True,
                "action": "read_screen",
                "text": text.strip(),
                "line_count": len(text.strip().split('\n'))
            }
        
        except Exception as e:
            logger.error(f"Screen reader error: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def find_text_on_screen(self, search_text: str, region: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Find specific text on screen and return its location
        
        Args:
            search_text: Text to find
            region: Optional region to search in
            
        Returns:
            Location of text or None
        """
        try:
            # Read screen with detailed data
            result = self.execute({
                "region": region,
                "detailed": True
            })
            
            if not result["success"]:
                return result
            
            # Search for text
            search_lower = search_text.lower()
            matches = []
            
            for word in result.get("words", []):
                if search_lower in word["text"].lower():
                    matches.append({
                        "text": word["text"],
                        "x": word["x"],
                        "y": word["y"],
                        "width": word["width"],
                        "height": word["height"],
                        "center_x": word["x"] + word["width"] // 2,
                        "center_y": word["y"] + word["height"] // 2
                    })
            
            return {
                "success": True,
                "search_text": search_text,
                "matches": matches,
                "found": len(matches) > 0
            }
        
        except Exception as e:
            logger.error(f"Find text error: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }


# Global instance
screen_reader_skill = ScreenReaderSkill()