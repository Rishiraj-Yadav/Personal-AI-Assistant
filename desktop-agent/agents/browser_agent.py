"""Browser agent compatibility facade over the OpenClaw-style runtime."""

from __future__ import annotations

from dataclasses import fields
from typing import Any, Dict, List, Optional

from loguru import logger

from agents.base_agent import BaseAgent
from browser_runtime.executor import browser_executor
from browser_runtime.service import BrowserCommand, browser_service


class BrowserAgent(BaseAgent):
    """Thin LLM-facing adapter for the browser runtime."""

    _command_fields = {field.name for field in fields(BrowserCommand)}

    def __init__(self):
        super().__init__(
            name="browser_agent",
            description=(
                "Control a visible browser using an OpenClaw-style runtime with profiles, tabs, "
                "snapshots, debug tools, and compatibility aliases for legacy browser actions."
            ),
        )

    def get_tools(self) -> List[Dict[str, Any]]:
        browser_properties = {
            "command": {
                "type": "string",
                "description": (
                    "Canonical browser command. Supported values include: "
                    "status, start, stop, tabs, open, focus, close, navigate, go_back, "
                    "snapshot, read_page, screenshot, pdf, click, type, press, hover, "
                    "scrollintoview, highlight, drag, select, fill, wait, evaluate, "
                    "console, errors, requests, responsebody, cookies, storage, "
                    "set_headers, set_offline, set_media, set_viewport, upload, dialog, "
                    "waitfordownload, trace_start, trace_stop, full_text, extract_table, check_sensitive."
                ),
            },
            "profile": {"type": "string", "description": "Browser profile name (default: openclaw)"},
            "session_id": {"type": "string", "description": "Desktop-agent session identifier"},
            "url": {"type": "string", "description": "URL used for open/navigate or remote CDP attach"},
            "tab_id": {"type": "string", "description": "Target tab id"},
            "ref": {"type": "string", "description": "Snapshot ref for an element"},
            "ref2": {"type": "string", "description": "Secondary ref for drag operations"},
            "text": {"type": "string", "description": "Typed text, wait text, or compatibility text match"},
            "key": {"type": "string", "description": "Keyboard key to press"},
            "value": {"type": "string", "description": "Command value"},
            "values": {"type": "array", "items": {"type": "string"}, "description": "Multiple values for select operations"},
            "selector": {"type": "string", "description": "Compatibility selector for legacy aliases"},
            "label": {"type": "string", "description": "Select option label for compatibility commands"},
            "index": {"type": "integer", "description": "Select option index for compatibility commands"},
            "direction": {"type": "string", "description": "Scroll direction for compatibility scroll"},
            "amount": {"type": "integer", "description": "Scroll amount for compatibility scroll"},
            "timeout_ms": {"type": "integer", "description": "Command timeout"},
            "full_page": {"type": "boolean", "description": "Capture full-page screenshot"},
            "mode": {"type": "string", "description": "Snapshot mode: ai or interactive"},
            "limit": {"type": "integer", "description": "Snapshot item limit"},
            "format": {"type": "string", "description": "Alternate snapshot format name"},
            "js": {"type": "string", "description": "JavaScript predicate or evaluate body"},
            "load": {"type": "string", "description": "Load state for wait"},
            "headers_json": {"type": "string", "description": "JSON-encoded HTTP headers"},
            "storage_type": {"type": "string", "description": "Storage type: local or session"},
            "storage_key": {"type": "string", "description": "Cookie or storage key"},
            "path": {"type": "string", "description": "Filesystem path for upload or output"},
            "paths": {"type": "array", "items": {"type": "string"}, "description": "Multiple upload paths"},
            "action": {"type": "string", "description": "Sub-action for cookies/storage/dialog/debug operations"},
            "prompt_text": {"type": "string", "description": "Dialog prompt text"},
            "table_index": {"type": "integer", "description": "HTML table index"},
            "fields": {"type": "object", "description": "Field map for fill commands"},
            "confirm_existing_session": {"type": "boolean", "description": "Required when attaching profile=user"},
            "allow_private_remote_cdp": {"type": "boolean", "description": "Allow private-network remote CDP endpoints"},
            "double": {"type": "boolean", "description": "Double click instead of click"},
            "submit": {"type": "boolean", "description": "Press Enter after typing"},
        }

        return [
            {
                "name": "browser",
                "description": "Canonical OpenClaw-style browser control surface.",
                "parameters": {
                    "type": "object",
                    "properties": browser_properties,
                    "required": ["command"],
                },
            },
            {
                "name": "open_browser",
                "description": "Open the managed visible browser and optionally navigate to a URL.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to open"},
                        "profile": {"type": "string"},
                        "session_id": {"type": "string"},
                    },
                },
            },
            {
                "name": "navigate_to",
                "description": "Navigate the current browser tab to a URL.",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}, "profile": {"type": "string"}, "session_id": {"type": "string"}},
                    "required": ["url"],
                },
            },
            {
                "name": "browser_click",
                "description": "Click by snapshot ref, visible text, or selector fallback.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string"},
                        "text": {"type": "string"},
                        "selector": {"type": "string"},
                        "double": {"type": "boolean"},
                        "profile": {"type": "string"},
                        "session_id": {"type": "string"},
                    },
                },
            },
            {
                "name": "browser_type",
                "description": "Type text using a snapshot ref or compatibility selector fallback.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string"},
                        "text": {"type": "string"},
                        "selector": {"type": "string"},
                        "press_enter": {"type": "boolean"},
                        "profile": {"type": "string"},
                        "session_id": {"type": "string"},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "leetcode_open_problem",
                "description": "Open a LeetCode problem by number.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "problem_number": {"type": "integer"},
                        "profile": {"type": "string"},
                        "session_id": {"type": "string"},
                    },
                    "required": ["problem_number"],
                },
            },
            {
                "name": "browser_press_key",
                "description": "Press a keyboard key in the current browser tab.",
                "parameters": {
                    "type": "object",
                    "properties": {"key": {"type": "string"}, "profile": {"type": "string"}, "session_id": {"type": "string"}},
                    "required": ["key"],
                },
            },
            {
                "name": "browser_scroll",
                "description": "Scroll the current browser page up or down.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "direction": {"type": "string"},
                        "amount": {"type": "integer"},
                        "profile": {"type": "string"},
                        "session_id": {"type": "string"},
                    },
                    "required": ["direction"],
                },
            },
            {"name": "browser_read_page", "description": "Read the current page summary using DOM text plus OCR of the visible browser viewport when available.", "parameters": {"type": "object", "properties": {"profile": {"type": "string"}, "session_id": {"type": "string"}}}},
            {"name": "browser_screenshot", "description": "Take a browser screenshot.", "parameters": {"type": "object", "properties": {"full_page": {"type": "boolean"}, "ref": {"type": "string"}, "profile": {"type": "string"}, "session_id": {"type": "string"}}}},
            {"name": "browser_go_back", "description": "Navigate back in browser history.", "parameters": {"type": "object", "properties": {"profile": {"type": "string"}, "session_id": {"type": "string"}}}},
            {"name": "browser_check_sensitive", "description": "Detect login/password/payment contexts on the current page.", "parameters": {"type": "object", "properties": {"profile": {"type": "string"}, "session_id": {"type": "string"}}}},
            {"name": "close_browser", "description": "Stop the browser for the current session/profile.", "parameters": {"type": "object", "properties": {"profile": {"type": "string"}, "session_id": {"type": "string"}}}},
            {"name": "browser_get_full_text", "description": "Read all visible text from the current page using DOM text plus OCR when needed.", "parameters": {"type": "object", "properties": {"profile": {"type": "string"}, "session_id": {"type": "string"}}}},
            {
                "name": "browser_extract_table",
                "description": "Extract an HTML table from the current page.",
                "parameters": {"type": "object", "properties": {"table_index": {"type": "integer"}, "profile": {"type": "string"}, "session_id": {"type": "string"}}},
            },
            {
                "name": "browser_wait_for_element",
                "description": "Wait until a selector becomes visible.",
                "parameters": {
                    "type": "object",
                    "properties": {"selector": {"type": "string"}, "timeout_ms": {"type": "integer"}, "profile": {"type": "string"}, "session_id": {"type": "string"}},
                    "required": ["selector"],
                },
            },
            {
                "name": "browser_select_option",
                "description": "Select an option on a <select> element using compatibility fallback.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selector": {"type": "string"},
                        "value": {"type": "string"},
                        "label": {"type": "string"},
                        "index": {"type": "integer"},
                        "profile": {"type": "string"},
                        "session_id": {"type": "string"},
                    },
                    "required": ["selector"],
                },
            },
            {
                "name": "browser_hover",
                "description": "Hover over an element by ref, selector, or visible text.",
                "parameters": {
                    "type": "object",
                    "properties": {"ref": {"type": "string"}, "selector": {"type": "string"}, "text": {"type": "string"}, "profile": {"type": "string"}, "session_id": {"type": "string"}},
                },
            },
            {
                "name": "browser_find_and_click",
                "description": "Find an element by a plain-English description/text and click it.",
                "parameters": {
                    "type": "object",
                    "properties": {"description": {"type": "string"}, "profile": {"type": "string"}, "session_id": {"type": "string"}},
                    "required": ["description"],
                },
            },
            {
                "name": "browser_fill_form",
                "description": "Fill multiple non-sensitive form fields using label/placeholder heuristics.",
                "parameters": {
                    "type": "object",
                    "properties": {"fields": {"type": "object"}, "profile": {"type": "string"}, "session_id": {"type": "string"}},
                    "required": ["fields"],
                },
            },
            {
                "name": "browser_request_user_input",
                "description": "Pause and request a sensitive value from the user.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "field_description": {"type": "string"},
                        "reason": {"type": "string"},
                        "input_type": {"type": "string"},
                    },
                    "required": ["field_description"],
                },
            },
            {
                "name": "browser_new_tab",
                "description": "Open a new browser tab and optionally navigate it.",
                "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "profile": {"type": "string"}, "session_id": {"type": "string"}}},
            },
            {
                "name": "ask_user_question",
                "description": "Ask the user for clarification and pause the browser flow.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "options": {"type": "array", "items": {"type": "string"}},
                        "context": {"type": "string"},
                    },
                    "required": ["question"],
                },
            },
        ]

    def _session_id(self, args: Dict[str, Any]) -> str:
        return str(args.get("session_id") or "default")

    def _profile(self, args: Dict[str, Any]) -> str:
        return str(args.get("profile") or "openclaw")

    def _command(self, command: str, args: Dict[str, Any], **overrides: Any) -> BrowserCommand:
        payload = dict(args or {})
        payload.setdefault("session_id", self._session_id(args))
        payload.setdefault("profile", self._profile(args))
        payload["command"] = command
        payload.update(overrides)
        filtered = {
            key: value
            for key, value in payload.items()
            if key in self._command_fields
        }
        return BrowserCommand(**filtered)

    def _request_user_input(self, field_description: str, reason: str = "", input_type: str = "text") -> Dict[str, Any]:
        logger.info(f"Requesting user input: {field_description} ({input_type})")
        return self._error(
            f"USER_INPUT_REQUIRED: Please provide {field_description}. Reason: {reason}",
            error_code="user_input_required",
            retryable=False,
            observed_state={
                "requires_user_input": True,
                "field_description": field_description,
                "reason": reason,
                "input_type": input_type,
            },
        )

    def _ask_user_question(
        self,
        question: str,
        options: Optional[List[str]] = None,
        context: str = "",
    ) -> Dict[str, Any]:
        logger.info(f"Asking user for clarification: {question}")
        return {
            "tool_name": "ask_user_question",
            "success": False,
            "result": None,
            "message": question,
            "error": "CLARIFICATION_NEEDED",
            "requires_clarification": True,
            "question": question,
            "options": options or [],
            "context": context,
        }

    def _run_browser_command(self, command: BrowserCommand) -> Dict[str, Any]:
        return browser_executor.call(browser_service.execute, command)

    def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "browser":
            return self._run_browser_command(self._command(str(args.get("command", "")), args))

        if tool_name == "browser_request_user_input":
            return self._request_user_input(
                str(args.get("field_description", "")),
                str(args.get("reason", "")),
                str(args.get("input_type", "text")),
            )

        if tool_name == "ask_user_question":
            return self._ask_user_question(
                str(args.get("question", "")),
                args.get("options", []),
                str(args.get("context", "")),
            )

        if tool_name == "open_browser":
            status = self._run_browser_command(self._command("status", args, url=""))
            if status.get("success") and (status.get("result") or {}).get("running"):
                url = str(args.get("url") or "").strip()
                if url:
                    return self._run_browser_command(self._command("tab_new", args, url=url))
                return status

            start = self._run_browser_command(self._command("start", args, url=""))
            if not start.get("success"):
                return start
            url = str(args.get("url") or "https://www.google.com")
            return self._run_browser_command(self._command("navigate", args, url=url))

        if tool_name == "navigate_to":
            return self._run_browser_command(self._command("navigate", args))

        if tool_name == "browser_click":
            if args.get("ref"):
                return self._run_browser_command(self._command("click", args))
            if args.get("selector"):
                return self._run_browser_command(self._command("compat_click_selector", args))
            if args.get("text"):
                return self._run_browser_command(self._command("compat_find_by_text", args))
            return self._error("browser_click requires ref, text, or selector")

        if tool_name == "browser_type":
            if args.get("ref"):
                return self._run_browser_command(self._command("type", args, submit=bool(args.get("press_enter", False))))
            return self._run_browser_command(self._command("compat_type", args, submit=bool(args.get("press_enter", False))))

        if tool_name == "leetcode_open_problem":
            return self._run_browser_command(
                self._command(
                    "leetcode_open_problem",
                    args,
                    value=str(int(float(args.get("problem_number", 0)))),
                )
            )

        if tool_name == "browser_press_key":
            return self._run_browser_command(self._command("press", args))

        if tool_name == "browser_scroll":
            return self._run_browser_command(self._command("compat_scroll", args))

        if tool_name == "browser_read_page":
            return self._run_browser_command(self._command("read_page", args))

        if tool_name == "browser_screenshot":
            return self._run_browser_command(self._command("screenshot", args))

        if tool_name == "browser_go_back":
            return self._run_browser_command(self._command("go_back", args))

        if tool_name == "browser_check_sensitive":
            return self._run_browser_command(self._command("check_sensitive", args))

        if tool_name == "close_browser":
            return self._run_browser_command(self._command("stop", args))

        if tool_name == "browser_get_full_text":
            return self._run_browser_command(self._command("full_text", args))

        if tool_name == "browser_extract_table":
            return self._run_browser_command(self._command("extract_table", args))

        if tool_name == "browser_wait_for_element":
            return self._run_browser_command(self._command("wait", args))

        if tool_name == "browser_select_option":
            return self._run_browser_command(self._command("compat_select", args))

        if tool_name == "browser_hover":
            if args.get("ref"):
                return self._run_browser_command(self._command("hover", args))
            return self._run_browser_command(self._command("compat_hover", args))

        if tool_name == "browser_find_and_click":
            return self._run_browser_command(self._command("compat_find_by_text", args, text=str(args.get("description", ""))))

        if tool_name == "browser_fill_form":
            return self._run_browser_command(self._command("compat_fill_form", args))

        if tool_name == "browser_new_tab":
            return self._run_browser_command(self._command("tab_new", args))

        return self._error(f"Unknown tool: {tool_name}")


browser_agent = BrowserAgent()
