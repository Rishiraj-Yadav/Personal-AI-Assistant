"""
Mouse Control Skill
Controls mouse movement and clicks
"""
from typing import Dict, Any
import pyautogui
import time
from loguru import logger
from config import settings


class MouseControlSkill:
    """Controls mouse cursor"""
    
    def __init__(self):
        """Initialize mouse control"""
        # Safety: enable fail-safe (move to corner to abort)
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = settings.CLICK_DELAY
        logger.info("MouseControlSkill initialized")
    
    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Control mouse
        
        Args:
            action: move, click, right_click, double_click, drag, scroll
            x, y: Coordinates
            button: left, right, middle
            clicks: Number of clicks
            duration: Movement duration
            scroll_amount: Scroll distance
            
        Returns:
            Action result
        """
        try:
            action = args.get("action", "move")
            
            if action == "move":
                return self._move_mouse(args)
            
            elif action == "click":
                return self._click_mouse(args)
            
            elif action == "right_click":
                return self._click_mouse({**args, "button": "right"})
            
            elif action == "double_click":
                return self._click_mouse({**args, "clicks": 2})
            
            elif action == "drag":
                return self._drag_mouse(args)
            
            elif action == "scroll":
                return self._scroll_mouse(args)
            
            elif action == "get_position":
                return self._get_position()
            
            else:
                return {
                    "success": False,
                    "error": f"Unknown action: {action}"
                }
        
        except Exception as e:
            logger.error(f"Mouse control error: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _move_mouse(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Move mouse to position"""
        x = args.get("x", 0)
        y = args.get("y", 0)
        duration = args.get("duration", settings.MOUSE_MOVE_DURATION)
        
        # Validate coordinates
        if not self._validate_coordinates(x, y):
            return {
                "success": False,
                "error": f"Coordinates out of bounds: ({x}, {y})"
            }
        
        pyautogui.moveTo(x, y, duration=duration)
        
        return {
            "success": True,
            "action": "move",
            "x": x,
            "y": y,
            "final_position": pyautogui.position()
        }
    
    def _click_mouse(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Click mouse at position"""
        x = args.get("x")
        y = args.get("y")
        button = args.get("button", "left")
        clicks = args.get("clicks", 1)
        
        if x is not None and y is not None:
            # Click at specific position
            if not self._validate_coordinates(x, y):
                return {
                    "success": False,
                    "error": f"Coordinates out of bounds: ({x}, {y})"
                }
            
            pyautogui.click(x, y, clicks=clicks, button=button)
        else:
            # Click at current position
            pyautogui.click(clicks=clicks, button=button)
        
        return {
            "success": True,
            "action": "click",
            "button": button,
            "clicks": clicks,
            "position": pyautogui.position()
        }
    
    def _drag_mouse(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Drag mouse from current position or (x1,y1) to (x2,y2)"""
        from_x = args.get("from_x")
        from_y = args.get("from_y")
        to_x = args.get("to_x")
        to_y = args.get("to_y")
        duration = args.get("duration", 0.5)
        button = args.get("button", "left")
        
        if to_x is None or to_y is None:
            return {
                "success": False,
                "error": "Missing required parameters: to_x, to_y"
            }
        
        # Move to start position if specified
        if from_x is not None and from_y is not None:
            pyautogui.moveTo(from_x, from_y)
        
        # Perform drag
        pyautogui.drag(
            to_x - (from_x or pyautogui.position()[0]),
            to_y - (from_y or pyautogui.position()[1]),
            duration=duration,
            button=button
        )
        
        return {
            "success": True,
            "action": "drag",
            "from": (from_x, from_y) if from_x else None,
            "to": (to_x, to_y),
            "final_position": pyautogui.position()
        }
    
    def _scroll_mouse(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Scroll mouse wheel"""
        amount = args.get("amount", 0)  # Positive = up, negative = down
        
        pyautogui.scroll(amount)
        
        return {
            "success": True,
            "action": "scroll",
            "amount": amount,
            "direction": "up" if amount > 0 else "down"
        }
    
    def _get_position(self) -> Dict[str, Any]:
        """Get current mouse position"""
        x, y = pyautogui.position()
        
        return {
            "success": True,
            "action": "get_position",
            "x": x,
            "y": y
        }
    
    def _validate_coordinates(self, x: int, y: int) -> bool:
        """Validate coordinates are within screen bounds"""
        screen_width, screen_height = pyautogui.size()
        
        return (
            0 <= x <= min(screen_width, settings.MAX_SCREEN_WIDTH) and
            0 <= y <= min(screen_height, settings.MAX_SCREEN_HEIGHT)
        )


# Global instance
mouse_control_skill = MouseControlSkill()