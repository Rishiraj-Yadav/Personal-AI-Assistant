"""
Keyboard Control Skill
Controls keyboard input - typing, shortcuts, special keys
"""
from typing import Dict, Any, List
import pyautogui
import time
from loguru import logger
from config import settings


class KeyboardControlSkill:
    """Controls keyboard input"""
    
    def __init__(self):
        """Initialize keyboard control"""
        pyautogui.PAUSE = settings.TYPING_INTERVAL
        logger.info("KeyboardControlSkill initialized")
    
    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Control keyboard
        
        Args:
            action: type, press, hotkey, combo
            text: Text to type
            key: Key to press (enter, space, tab, etc.)
            keys: List of keys for hotkey (e.g., ['ctrl', 'c'])
            interval: Typing speed override
            
        Returns:
            Action result
        """
        try:
            action = args.get("action", "type")
            
            if action == "type":
                return self._type_text(args)
            
            elif action == "press":
                return self._press_key(args)
            
            elif action == "hotkey":
                return self._press_hotkey(args)
            
            elif action == "hold":
                return self._hold_key(args)
            
            else:
                return {
                    "success": False,
                    "error": f"Unknown action: {action}"
                }
        
        except Exception as e:
            logger.error(f"Keyboard control error: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _type_text(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Type text"""
        text = args.get("text", "")
        interval = args.get("interval", settings.TYPING_INTERVAL)
        
        if not text:
            return {
                "success": False,
                "error": "No text provided"
            }
        
        # Type the text
        pyautogui.write(text, interval=interval)
        
        return {
            "success": True,
            "action": "type",
            "text": text[:50] + "..." if len(text) > 50 else text,
            "length": len(text)
        }
    
    def _press_key(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Press a single key or special key"""
        key = args.get("key", "")
        presses = args.get("presses", 1)
        
        if not key:
            return {
                "success": False,
                "error": "No key provided"
            }
        
        # Validate key
        valid_keys = self._get_valid_keys()
        if key.lower() not in valid_keys and len(key) != 1:
            return {
                "success": False,
                "error": f"Invalid key: {key}. Must be a single character or special key."
            }
        
        # Press the key
        pyautogui.press(key, presses=presses)
        
        return {
            "success": True,
            "action": "press",
            "key": key,
            "presses": presses
        }
    
    def _press_hotkey(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Press a hotkey combination (e.g., Ctrl+C)"""
        keys = args.get("keys", [])
        
        if not keys or len(keys) < 2:
            return {
                "success": False,
                "error": "Hotkey requires at least 2 keys (e.g., ['ctrl', 'c'])"
            }
        
        # Press hotkey
        pyautogui.hotkey(*keys)
        
        return {
            "success": True,
            "action": "hotkey",
            "keys": keys,
            "combination": "+".join(keys)
        }
    
    def _hold_key(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Hold a key down for duration"""
        key = args.get("key", "")
        duration = args.get("duration", 1.0)
        
        if not key:
            return {
                "success": False,
                "error": "No key provided"
            }
        
        # Hold key
        pyautogui.keyDown(key)
        time.sleep(duration)
        pyautogui.keyUp(key)
        
        return {
            "success": True,
            "action": "hold",
            "key": key,
            "duration": duration
        }
    
    def _get_valid_keys(self) -> List[str]:
        """Get list of valid special keys"""
        return [
            # Navigation
            'enter', 'return', 'tab', 'space', 'backspace', 'delete',
            'esc', 'escape',
            
            # Arrow keys
            'up', 'down', 'left', 'right',
            'pageup', 'pagedown', 'home', 'end',
            
            # Modifiers
            'shift', 'ctrl', 'control', 'alt', 'option',
            'command', 'cmd', 'win', 'windows',
            
            # Function keys
            'f1', 'f2', 'f3', 'f4', 'f5', 'f6',
            'f7', 'f8', 'f9', 'f10', 'f11', 'f12',
            
            # Other
            'capslock', 'numlock', 'scrolllock',
            'insert', 'printscreen', 'pause',
            
            # Symbols (can also just use the character)
            'comma', 'period', 'slash', 'semicolon',
            'quote', 'bracket', 'backslash'
        ]


# Global instance
keyboard_control_skill = KeyboardControlSkill()