"""
GUI Agent — Mouse, keyboard, screenshots, OCR, window management
Wraps the existing skills into a unified agent with tool definitions.
"""
import base64
from typing import Dict, Any, List
from loguru import logger
from agents.base_agent import BaseAgent


class GUIAgent(BaseAgent):
    """Agent for direct GUI automation"""

    def __init__(self):
        super().__init__(
            name="gui_agent",
            description="Control mouse, keyboard, take screenshots, read screen text, manage windows",
        )
        # Lazy-load the existing skills
        self._mouse = None
        self._keyboard = None
        self._screenshot = None
        self._screen_reader = None
        self._window_manager = None

    def _load_skills(self):
        """Lazy-load existing skills to avoid import errors"""
        if self._mouse is None:
            try:
                from skills.mouse_control import mouse_control_skill
                self._mouse = mouse_control_skill
            except Exception as e:
                logger.warning(f"Mouse control unavailable: {e}")

        if self._keyboard is None:
            try:
                from skills.keyboard_control import keyboard_control_skill
                self._keyboard = keyboard_control_skill
            except Exception as e:
                logger.warning(f"Keyboard control unavailable: {e}")

        if self._screenshot is None:
            try:
                from skills.screenshot import screenshot_skill
                self._screenshot = screenshot_skill
            except Exception as e:
                logger.warning(f"Screenshot unavailable: {e}")

        if self._screen_reader is None:
            try:
                from skills.screen_reader import screen_reader_skill
                self._screen_reader = screen_reader_skill
            except Exception as e:
                logger.warning(f"Screen reader unavailable: {e}")

        if self._window_manager is None:
            try:
                from skills.window_manager import window_manager_skill
                self._window_manager = window_manager_skill
            except Exception as e:
                logger.warning(f"Window manager unavailable: {e}")

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "mouse_click",
                "description": "Click the mouse at specific screen coordinates. Use for clicking buttons, links, menu items, etc.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer", "description": "X coordinate"},
                        "y": {"type": "integer", "description": "Y coordinate"},
                        "button": {
                            "type": "string",
                            "description": "Mouse button: 'left', 'right', or 'middle' (default: left)",
                            "enum": ["left", "right", "middle"],
                        },
                        "clicks": {
                            "type": "integer",
                            "description": "Number of clicks (1 for single, 2 for double, default: 1)",
                        },
                    },
                    "required": ["x", "y"],
                },
            },
            {
                "name": "mouse_move",
                "description": "Move the mouse cursor to specific coordinates",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer", "description": "X coordinate"},
                        "y": {"type": "integer", "description": "Y coordinate"},
                    },
                    "required": ["x", "y"],
                },
            },
            {
                "name": "mouse_scroll",
                "description": "Scroll the mouse wheel up or down",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "amount": {
                            "type": "integer",
                            "description": "Scroll amount (positive = up, negative = down)",
                        },
                    },
                    "required": ["amount"],
                },
            },
            {
                "name": "type_text",
                "description": "Type text using the keyboard. Types each character with a small delay to simulate real typing.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Text to type",
                        },
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "press_key",
                "description": "Press a single key or key combination. Examples: 'enter', 'tab', 'escape', 'backspace', 'delete', 'space', 'f1'-'f12', 'up', 'down', 'left', 'right', 'home', 'end', 'pageup', 'pagedown'",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Key to press (e.g., 'enter', 'tab', 'escape')",
                        },
                    },
                    "required": ["key"],
                },
            },
            {
                "name": "press_hotkey",
                "description": "Press a keyboard shortcut/hotkey combination. Examples: ctrl+c, ctrl+v, ctrl+s, alt+tab, ctrl+shift+p, win+d",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keys": {
                            "type": "string",
                            "description": "Hotkey combo separated by + (e.g., 'ctrl+c', 'alt+tab', 'ctrl+shift+s')",
                        },
                    },
                    "required": ["keys"],
                },
            },
            {
                "name": "take_screenshot",
                "description": "Take a screenshot of the entire screen or a specific region. Returns base64-encoded image.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "region": {
                            "type": "string",
                            "description": "Optional region as 'x,y,width,height' (e.g., '0,0,800,600'). Omit for full screen.",
                        },
                    },
                },
            },
            {
                "name": "read_screen_text",
                "description": "Read all visible text on the screen using OCR. Useful for understanding what's displayed on screen.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "list_windows",
                "description": "List all open windows with their titles, positions, and sizes",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "focus_window",
                "description": "Bring a window to the foreground by its title (partial match)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Window title or partial title to match",
                        },
                    },
                    "required": ["title"],
                },
            },
            {
                "name": "minimize_window",
                "description": "Minimize a window by its title",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Window title to minimize",
                        },
                    },
                    "required": ["title"],
                },
            },
            {
                "name": "maximize_window",
                "description": "Maximize a window by its title",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Window title to maximize",
                        },
                    },
                    "required": ["title"],
                },
            },
            {
                "name": "find_element_coordinates_on_screen",
                "description": "Uses visual AI to look at the screen and find the exact X,Y coordinates of an element (button, icon, text) you want to click.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "element_description": {
                            "type": "string",
                            "description": "Description of the element to find (e.g., 'the green submit button', 'the minimize icon in the top right')",
                        },
                    },
                    "required": ["element_description"],
                },
            },
        ]

    def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        self._load_skills()

        handlers = {
            "mouse_click": self._mouse_click,
            "mouse_move": self._mouse_move,
            "mouse_scroll": self._mouse_scroll,
            "type_text": self._type_text,
            "press_key": self._press_key,
            "press_hotkey": self._press_hotkey,
            "take_screenshot": self._take_screenshot,
            "read_screen_text": self._read_screen,
            "list_windows": self._list_windows,
            "focus_window": self._focus_window,
            "minimize_window": self._minimize_window,
            "maximize_window": self._maximize_window,
            "find_element_coordinates_on_screen": self._find_element_coordinates,
        }

        handler = handlers.get(tool_name)
        if handler:
            return handler(args)
        return self._error(f"Unknown tool: {tool_name}")

    def _mouse_click(self, args: Dict) -> Dict[str, Any]:
        if not self._mouse:
            return self._error("Mouse control not available")
        try:
            result = self._mouse.execute({
                "action": "click",
                "x": args.get("x"),
                "y": args.get("y"),
                "button": args.get("button", "left"),
                "clicks": args.get("clicks", 1),
            })
            return self._success(result, f"Clicked at ({args.get('x')}, {args.get('y')})")
        except Exception as e:
            return self._error(f"Mouse click failed: {e}")

    def _mouse_move(self, args: Dict) -> Dict[str, Any]:
        if not self._mouse:
            return self._error("Mouse control not available")
        try:
            result = self._mouse.execute({
                "action": "move",
                "x": args.get("x"),
                "y": args.get("y"),
            })
            return self._success(result, f"Moved mouse to ({args.get('x')}, {args.get('y')})")
        except Exception as e:
            return self._error(f"Mouse move failed: {e}")

    def _mouse_scroll(self, args: Dict) -> Dict[str, Any]:
        if not self._mouse:
            return self._error("Mouse control not available")
        try:
            result = self._mouse.execute({
                "action": "scroll",
                "amount": args.get("amount", 3),
            })
            return self._success(result, f"Scrolled {args.get('amount')}")
        except Exception as e:
            return self._error(f"Mouse scroll failed: {e}")

    def _type_text(self, args: Dict) -> Dict[str, Any]:
        if not self._keyboard:
            return self._error("Keyboard control not available")
        try:
            result = self._keyboard.execute({
                "action": "type",
                "text": args.get("text", ""),
            })
            return self._success(result, f"Typed text")
        except Exception as e:
            return self._error(f"Type text failed: {e}")

    def _press_key(self, args: Dict) -> Dict[str, Any]:
        if not self._keyboard:
            return self._error("Keyboard control not available")
        try:
            result = self._keyboard.execute({
                "action": "press",
                "key": args.get("key", ""),
            })
            return self._success(result, f"Pressed {args.get('key')}")
        except Exception as e:
            return self._error(f"Press key failed: {e}")

    def _press_hotkey(self, args: Dict) -> Dict[str, Any]:
        if not self._keyboard:
            return self._error("Keyboard control not available")
        try:
            keys = args.get("keys", "").split("+")
            result = self._keyboard.execute({
                "action": "hotkey",
                "keys": [k.strip() for k in keys],
            })
            return self._success(result, f"Pressed hotkey {args.get('keys')}")
        except Exception as e:
            return self._error(f"Hotkey failed: {e}")

    def _take_screenshot(self, args: Dict) -> Dict[str, Any]:
        if not self._screenshot:
            return self._error("Screenshot not available")
        try:
            params = {"format": "base64"}
            region_str = args.get("region")
            if region_str:
                parts = [int(x.strip()) for x in region_str.split(",")]
                if len(parts) == 4:
                    params["region"] = {
                        "x": parts[0], "y": parts[1],
                        "width": parts[2], "height": parts[3],
                    }
            result = self._screenshot.execute(params)
            return self._success(
                {"screenshot_taken": True, "has_data": bool(result)},
                "Screenshot taken",
            )
        except Exception as e:
            return self._error(f"Screenshot failed: {e}")

    def _read_screen(self, args: Dict) -> Dict[str, Any]:
        if not self._screen_reader:
            return self._error("Screen reader not available (OCR not installed)")
        try:
            result = self._screen_reader.execute({})
            return self._success(result, "Screen text read via OCR")
        except Exception as e:
            return self._error(f"Screen read failed: {e}")

    def _list_windows(self, args: Dict) -> Dict[str, Any]:
        if not self._window_manager:
            return self._error("Window manager not available")
        try:
            result = self._window_manager.execute({"action": "list"})
            return self._success(result, "Listed all windows")
        except Exception as e:
            return self._error(f"List windows failed: {e}")

    def _focus_window(self, args: Dict) -> Dict[str, Any]:
        if not self._window_manager:
            return self._error("Window manager not available")
        try:
            result = self._window_manager.execute({
                "action": "focus",
                "title": args.get("title", ""),
            })
            return self._success(result, f"Focused window: {args.get('title')}")
        except Exception as e:
            return self._error(f"Focus window failed: {e}")

    def _minimize_window(self, args: Dict) -> Dict[str, Any]:
        if not self._window_manager:
            return self._error("Window manager not available")
        try:
            result = self._window_manager.execute({
                "action": "minimize",
                "title": args.get("title", ""),
            })
            return self._success(result, f"Minimized window: {args.get('title')}")
        except Exception as e:
            return self._error(f"Minimize failed: {e}")

    def _maximize_window(self, args: Dict) -> Dict[str, Any]:
        if not self._window_manager:
            return self._error("Window manager not available")
        try:
            result = self._window_manager.execute({
                "action": "maximize",
                "title": args.get("title", ""),
            })
            return self._success(result, f"Maximized window: {args.get('title')}")
        except Exception as e:
            return self._error(f"Maximize failed: {e}")

    def _find_element_coordinates(self, args: Dict) -> Dict[str, Any]:
        """Use Gemini Vision to analyze screenshot and return XY coordinates"""
        if not self._screenshot:
            return self._error("Screenshot not available")
        
        desc = args.get("element_description", "")
        if not desc:
            return self._error("Must provide element_description")

        try:
            # Get base64 screenshot
            screenshot_data = self._screenshot.execute({"format": "base64"})
            if not screenshot_data:
                return self._error("Failed to capture screenshot data")
                
            # Send to Gemini Flash for XY extraction (Vision capability)
            import google.generativeai as genai
            from config import settings
            import io
            from PIL import Image
            import base64
            import json
            
            genai.configure(api_key=settings.GOOGLE_API_KEY)
            vision_model = genai.GenerativeModel("gemini-2.0-flash")
            
            # Decode base64 to image
            try:
                img_bytes = base64.b64decode(screenshot_data)
                img = Image.open(io.BytesIO(img_bytes))
            except Exception as e:
                return self._error(f"Failed to decode image: {e}")
                
            width, height = img.size
            
            prompt = f"Look at this screenshot of size {width}x{height}. Find: '{desc}'. Return ONLY a JSON dictionary with 'x' and 'y' integer coordinates representing its center point. Do not wrap in markdown."
            
            response = vision_model.generate_content([prompt, img])
            text = response.text.strip()
            
            if text.startswith("```json"): text = text[7:-3].strip()
            if text.startswith("```"): text = text[3:-3].strip()
                
            coords = json.loads(text)
            
            return self._success(
                {"x": coords.get("x"), "y": coords.get("y"), "element": desc},
                f"Found {desc} at ({coords.get('x')}, {coords.get('y')})"
            )
            
        except Exception as e:
            return self._error(f"Visual grounding failed to find element: {e}")


# Global instance
gui_agent = GUIAgent()
