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
                "name": "get_active_window",
                "description": "Get the currently active/focused window title and bounds",
                "parameters": {
                    "type": "object",
                    "properties": {},
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
            "get_active_window": self._get_active_window,
        }

        handler = handlers.get(tool_name)
        if handler:
            return handler(args)
        return self._error(f"Unknown tool: {tool_name}")

    def _mouse_click(self, args: Dict) -> Dict[str, Any]:
        if not self._mouse:
            return self._error("Mouse control not available", error_code="tool_unavailable")
        try:
            result = self._mouse.execute({
                "action": "click",
                "x": args.get("x"),
                "y": args.get("y"),
                "button": args.get("button", "left"),
                "clicks": args.get("clicks", 1),
            })
            if not result.get("success"):
                return self._error(result.get("error", "Mouse click failed"), retryable=True)
            return self._success(
                result,
                f"Clicked at ({args.get('x')}, {args.get('y')})",
                observed_state={"position": result.get("position"), "button": result.get("button"), "clicks": result.get("clicks")},
            )
        except Exception as e:
            return self._error(f"Mouse click failed: {e}", retryable=True)

    def _mouse_move(self, args: Dict) -> Dict[str, Any]:
        if not self._mouse:
            return self._error("Mouse control not available", error_code="tool_unavailable")
        try:
            result = self._mouse.execute({
                "action": "move",
                "x": args.get("x"),
                "y": args.get("y"),
            })
            if not result.get("success"):
                return self._error(result.get("error", "Mouse move failed"), retryable=True)
            return self._success(
                result,
                f"Moved mouse to ({args.get('x')}, {args.get('y')})",
                observed_state={"final_position": result.get("final_position")},
            )
        except Exception as e:
            return self._error(f"Mouse move failed: {e}", retryable=True)

    def _mouse_scroll(self, args: Dict) -> Dict[str, Any]:
        if not self._mouse:
            return self._error("Mouse control not available", error_code="tool_unavailable")
        try:
            result = self._mouse.execute({
                "action": "scroll",
                "amount": args.get("amount", 3),
            })
            if not result.get("success"):
                return self._error(result.get("error", "Mouse scroll failed"), retryable=True)
            return self._success(
                result,
                f"Scrolled {args.get('amount')}",
                observed_state={"amount": result.get("amount"), "direction": result.get("direction")},
            )
        except Exception as e:
            return self._error(f"Mouse scroll failed: {e}", retryable=True)

    def _type_text(self, args: Dict) -> Dict[str, Any]:
        if not self._keyboard:
            return self._error("Keyboard control not available", error_code="tool_unavailable")
        try:
            result = self._keyboard.execute({
                "action": "type",
                "text": args.get("text", ""),
            })
            if not result.get("success"):
                return self._error(result.get("error", "Type text failed"), retryable=True)
            return self._success(
                result,
                "Typed text",
                observed_state={"length": result.get("length")},
            )
        except Exception as e:
            return self._error(f"Type text failed: {e}", retryable=True)

    def _press_key(self, args: Dict) -> Dict[str, Any]:
        if not self._keyboard:
            return self._error("Keyboard control not available", error_code="tool_unavailable")
        try:
            result = self._keyboard.execute({
                "action": "press",
                "key": args.get("key", ""),
            })
            if not result.get("success"):
                return self._error(result.get("error", "Press key failed"), retryable=True)
            return self._success(result, f"Pressed {args.get('key')}")
        except Exception as e:
            return self._error(f"Press key failed: {e}", retryable=True)

    def _press_hotkey(self, args: Dict) -> Dict[str, Any]:
        if not self._keyboard:
            return self._error("Keyboard control not available", error_code="tool_unavailable")
        try:
            keys = args.get("keys", "").split("+")
            result = self._keyboard.execute({
                "action": "hotkey",
                "keys": [k.strip() for k in keys],
            })
            if not result.get("success"):
                return self._error(result.get("error", "Hotkey failed"), retryable=True)
            return self._success(result, f"Pressed hotkey {args.get('keys')}")
        except Exception as e:
            return self._error(f"Hotkey failed: {e}", retryable=True)

    def _take_screenshot(self, args: Dict) -> Dict[str, Any]:
        if not self._screenshot:
            return self._error("Screenshot not available", error_code="tool_unavailable")
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
            if not result.get("success"):
                return self._error(result.get("error", "Screenshot failed"), retryable=True)
            return self._success(
                result,
                "Screenshot taken",
                observed_state={
                    "width": result.get("width"),
                    "height": result.get("height"),
                    "monitor": result.get("monitor"),
                },
                evidence=[
                    {
                        "type": "screenshot",
                        "summary": "Screenshot captured from desktop.",
                        "image_base64": result.get("image_base64"),
                    }
                ],
            )
        except Exception as e:
            return self._error(f"Screenshot failed: {e}", retryable=True)

    def _read_screen(self, args: Dict) -> Dict[str, Any]:
        if not self._screen_reader:
            return self._error("Screen reader not available (OCR not installed)", error_code="tool_unavailable")
        try:
            result = self._screen_reader.execute({})
            if not result.get("success"):
                return self._error(result.get("error", "Screen read failed"), retryable=True)
            text = result.get("text", "")
            return self._success(
                result,
                "Screen text read via OCR",
                observed_state={"line_count": result.get("line_count"), "has_text": bool(text)},
                evidence=[{"type": "ocr_text", "text_excerpt": text[:1000], "summary": text[:200]}],
            )
        except Exception as e:
            return self._error(f"Screen read failed: {e}", retryable=True)

    def _list_windows(self, args: Dict) -> Dict[str, Any]:
        if not self._window_manager:
            return self._error("Window manager not available", error_code="tool_unavailable")
        try:
            result = self._window_manager.execute({"action": "list"})
            if not result.get("success"):
                return self._error(result.get("error", "List windows failed"), retryable=True)
            windows = result.get("windows", [])
            return self._success(
                {"windows": windows, "count": result.get("count", len(windows))},
                "Listed all windows",
                observed_state={"window_count": len(windows)},
                evidence=[{"type": "window_list", "windows": windows[:10]}],
            )
        except Exception as e:
            return self._error(f"List windows failed: {e}", retryable=True)

    def _focus_window(self, args: Dict) -> Dict[str, Any]:
        if not self._window_manager:
            return self._error("Window manager not available", error_code="tool_unavailable")
        try:
            result = self._window_manager.execute({
                "action": "focus",
                "title": args.get("title", ""),
            })
            if not result.get("success"):
                return self._error(result.get("error", "Focus window failed"), retryable=True)
            active = self._window_manager.execute({"action": "get_active"})
            active_title = active.get("title", "") if active.get("success") else ""
            verified = args.get("title", "").lower() in active_title.lower()
            if not verified:
                return self._error(
                    f"Window focus could not be verified for {args.get('title')}",
                    error_code="verification_failed",
                    retryable=True,
                    observed_state={"requested_title": args.get("title", ""), "active_title": active_title},
                    evidence=[{"type": "active_window", "title": active_title}],
                )
            return self._success(
                {"requested_title": args.get("title", ""), "active_title": active_title},
                f"Focused window: {args.get('title')}",
                observed_state={"requested_title": args.get("title", ""), "active_title": active_title},
                evidence=[{"type": "active_window", "title": active_title}],
            )
        except Exception as e:
            return self._error(f"Focus window failed: {e}", retryable=True)

    def _minimize_window(self, args: Dict) -> Dict[str, Any]:
        if not self._window_manager:
            return self._error("Window manager not available", error_code="tool_unavailable")
        try:
            result = self._window_manager.execute({
                "action": "minimize",
                "title": args.get("title", ""),
            })
            if not result.get("success"):
                return self._error(result.get("error", "Minimize failed"), retryable=True)
            return self._success(
                result,
                f"Minimized window: {args.get('title')}",
                observed_state={"requested_title": args.get("title", ""), "matched_title": result.get("matched_title", "")},
            )
        except Exception as e:
            return self._error(f"Minimize failed: {e}", retryable=True)

    def _maximize_window(self, args: Dict) -> Dict[str, Any]:
        if not self._window_manager:
            return self._error("Window manager not available", error_code="tool_unavailable")
        try:
            result = self._window_manager.execute({
                "action": "maximize",
                "title": args.get("title", ""),
            })
            if not result.get("success"):
                return self._error(result.get("error", "Maximize failed"), retryable=True)
            return self._success(
                result,
                f"Maximized window: {args.get('title')}",
                observed_state={"requested_title": args.get("title", ""), "matched_title": result.get("matched_title", "")},
            )
        except Exception as e:
            return self._error(f"Maximize failed: {e}", retryable=True)

    def _get_active_window(self, args: Dict) -> Dict[str, Any]:
        if not self._window_manager:
            return self._error("Window manager not available", error_code="tool_unavailable")
        try:
            result = self._window_manager.execute({"action": "get_active"})
            if not result.get("success"):
                return self._error(result.get("error", "Get active window failed"), retryable=True)
            return self._success(
                result,
                f"Active window: {result.get('title', 'Unknown')}",
                observed_state={"title": result.get("title", ""), "id": result.get("id")},
                evidence=[{"type": "active_window", "title": result.get("title", ""), "rect": result.get("rect", {})}],
            )
        except Exception as e:
            return self._error(f"Get active window failed: {e}", retryable=True)


# Global instance
gui_agent = GUIAgent()
