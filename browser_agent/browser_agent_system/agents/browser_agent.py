"""
BrowserAgent — powered by Google Gemini
Uses google-generativeai SDK with function calling to control a browser.
"""

from __future__ import annotations
import asyncio
import json
import os
from typing import Optional

import google.generativeai as genai
from google.generativeai import protos
from dotenv import load_dotenv

import tools.browser_tools as bt

load_dotenv()

# ─── Configure Google AI ─────────────────────────────────────────────────────
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])


SYSTEM_PROMPT = """You are a Browser Agent — a specialized AI that controls a web browser to complete tasks.

You have access to browser tools to navigate, click, type, scroll, and extract information from web pages.

## STRATEGY
1. Start with `get_page_info` if already on a page, or `navigate` to go to a URL.
2. Use `get_page_info` before clicking to understand what's on the page.
3. Use `get_text` or `get_html` to read page content.
4. Always confirm the result after key actions.

## RULES
- Be precise with selectors — prefer IDs (#id) over classes (.class) when possible.
- If a click or type fails, try `get_page_info` to find the correct selector.
- Don't take unnecessary screenshots — use `get_text` for reading.
- When a task is complete, provide a clear summary of what was accomplished.
- If a task is impossible (e.g. requires login credentials you don't have), stop and explain why.

## OUTPUT FORMAT
When you finish a task, summarize:
- What you did (steps taken)
- What you found or accomplished
- Any relevant data extracted
"""


# ─── Tool schema in Google format ────────────────────────────────────────────

def _schema(props: dict, required: list = []) -> protos.Schema:
    """Helper to build a Google Schema object from a plain dict."""
    type_map = {
        "string":  protos.Type.STRING,
        "integer": protos.Type.INTEGER,
        "boolean": protos.Type.BOOLEAN,
        "number":  protos.Type.NUMBER,
    }
    properties = {}
    for name, info in props.items():
        p_type = type_map.get(info.get("type", "string"), protos.Type.STRING)
        if "enum" in info:
            properties[name] = protos.Schema(type=p_type, description=info.get("description", ""), enum=info["enum"])
        else:
            properties[name] = protos.Schema(type=p_type, description=info.get("description", ""))

    return protos.Schema(
        type=protos.Type.OBJECT,
        properties=properties,
        required=required,
    )


BROWSER_TOOL_DECLARATIONS = protos.Tool(function_declarations=[
    protos.FunctionDeclaration(
        name="navigate",
        description="Navigate the browser to a URL.",
        parameters=_schema({"url": {"type": "string", "description": "Full URL including https://"}}, ["url"])
    ),
    protos.FunctionDeclaration(
        name="click",
        description="Click an element by CSS selector or visible text.",
        parameters=_schema({
            "selector": {"type": "string", "description": "CSS selector or visible text of element"},
            "description": {"type": "string", "description": "Human-readable label for logging"},
        }, ["selector"])
    ),
    protos.FunctionDeclaration(
        name="type_text",
        description="Type text into an input field or textarea.",
        parameters=_schema({
            "selector": {"type": "string", "description": "CSS selector of the input element"},
            "text": {"type": "string", "description": "Text to type"},
            "clear_first": {"type": "boolean", "description": "Clear the field before typing (default: true)"},
        }, ["selector", "text"])
    ),
    protos.FunctionDeclaration(
        name="get_text",
        description="Get visible text content from an element or the whole page.",
        parameters=_schema({"selector": {"type": "string", "description": "CSS selector (default: body)"}})
    ),
    protos.FunctionDeclaration(
        name="get_page_info",
        description="Get current page URL, title, and a summary of all inputs, buttons, and links.",
        parameters=_schema({})
    ),
    protos.FunctionDeclaration(
        name="screenshot",
        description="Take a screenshot of the current page.",
        parameters=_schema({"filename": {"type": "string", "description": "Optional file path to save image"}})
    ),
    protos.FunctionDeclaration(
        name="scroll",
        description="Scroll the page up or down.",
        parameters=_schema({
            "direction": {"type": "string", "description": "up or down", "enum": ["up", "down"]},
            "amount": {"type": "integer", "description": "Pixels to scroll (default: 300)"},
        }, ["direction"])
    ),
    protos.FunctionDeclaration(
        name="wait_for_element",
        description="Wait for an element to appear on the page after a dynamic action.",
        parameters=_schema({
            "selector": {"type": "string", "description": "CSS selector to wait for"},
            "timeout": {"type": "integer", "description": "Max wait in milliseconds (default: 10000)"},
        }, ["selector"])
    ),
    protos.FunctionDeclaration(
        name="extract_links",
        description="Extract all clickable links from the current page.",
        parameters=_schema({})
    ),
    protos.FunctionDeclaration(
        name="execute_script",
        description="Run JavaScript in the browser context.",
        parameters=_schema({"script": {"type": "string", "description": "JS code to execute"}}, ["script"])
    ),
    protos.FunctionDeclaration(
        name="select_option",
        description="Select an option from a <select> dropdown.",
        parameters=_schema({
            "selector": {"type": "string", "description": "CSS selector of the <select> element"},
            "value": {"type": "string", "description": "Value or label of the option"},
        }, ["selector", "value"])
    ),
    protos.FunctionDeclaration(
        name="press_key",
        description="Press a keyboard key (Enter, Tab, Escape, ArrowDown, etc.).",
        parameters=_schema({"key": {"type": "string", "description": "Key name"}}, ["key"])
    ),
    protos.FunctionDeclaration(
        name="go_back",
        description="Go back to the previous page in browser history.",
        parameters=_schema({})
    ),
    protos.FunctionDeclaration(
        name="get_html",
        description="Get raw HTML of an element — useful for scraping structured data.",
        parameters=_schema({"selector": {"type": "string", "description": "CSS selector (default: body)"}})
    ),
])


class BrowserAgent:
    """
    Autonomous browser agent using Google Gemini + Playwright.
    """

    def __init__(
        self,
        model: str = "gemini-2.0-flash",
        max_steps: int = 20,
        verbose: bool = True,
    ):
        self.model_name = model
        self.max_steps = max_steps
        self.verbose = verbose
        self._chat: Optional[genai.ChatSession] = None
        self._model = genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=SYSTEM_PROMPT,
            tools=[BROWSER_TOOL_DECLARATIONS],
        )

    def _log(self, msg: str):
        if self.verbose:
            print(msg)

    def reset(self):
        """Clear conversation history — starts a fresh chat session."""
        self._chat = None

    def _get_chat(self) -> genai.ChatSession:
        """Get (or lazily create) the chat session."""
        if self._chat is None:
            self._chat = self._model.start_chat()
        return self._chat

    async def _dispatch_tool(self, tool_name: str, tool_input: dict) -> str:
        """Route a Gemini function call to the correct browser_tools function."""
        tool_map = {
            "navigate":         lambda: bt.navigate(tool_input["url"]),
            "click":            lambda: bt.click(tool_input["selector"], tool_input.get("description", "")),
            "type_text":        lambda: bt.type_text(tool_input["selector"], tool_input["text"], tool_input.get("clear_first", True)),
            "get_text":         lambda: bt.get_text(tool_input.get("selector", "body")),
            "get_page_info":    lambda: bt.get_page_info(),
            "screenshot":       lambda: bt.screenshot(tool_input.get("filename", "")),
            "scroll":           lambda: bt.scroll(tool_input["direction"], tool_input.get("amount", 300)),
            "wait_for_element": lambda: bt.wait_for_element(tool_input["selector"], tool_input.get("timeout", 10000)),
            "extract_links":    lambda: bt.extract_links(),
            "execute_script":   lambda: bt.execute_script(tool_input["script"]),
            "select_option":    lambda: bt.select_option(tool_input["selector"], tool_input["value"]),
            "press_key":        lambda: bt.press_key(tool_input["key"]),
            "go_back":          lambda: bt.go_back(),
            "get_html":         lambda: bt.get_html(tool_input.get("selector", "body")),
        }
        handler = tool_map.get(tool_name)
        if not handler:
            return f"Unknown tool: {tool_name}"
        return await handler()

    async def run(
        self,
        task: str,
        context: Optional[dict] = None,
        reset_history: bool = True,
    ) -> str:
        """
        Run the browser agent on a task.

        Args:
            task:          The task description in plain English.
            context:       Optional extra context dict from the orchestrator.
            reset_history: Whether to clear chat history before this task.
        """
        if reset_history:
            self.reset()

        user_message = task
        if context:
            context_str = "\n".join(f"  {k}: {v}" for k, v in context.items())
            user_message = f"{task}\n\n[Context]\n{context_str}"

        self._log(f"\n{'='*60}")
        self._log(f"[BrowserAgent] Task: {task}")
        self._log(f"{'='*60}")

        chat = self._get_chat()

        # Send first message
        response = await asyncio.to_thread(chat.send_message, user_message)

        for step in range(self.max_steps):
            self._log(f"\n[Step {step + 1}/{self.max_steps}]")

            # Collect all function calls from this response
            function_calls = [
                part.function_call
                for part in response.parts
                if part.function_call.name  # non-empty name = real call
            ]

            # No function calls → model is done
            if not function_calls:
                final_text = response.text if hasattr(response, "text") else "(No response)"
                self._log(f"\n[BrowserAgent] ✅ Done:\n{final_text}")
                return final_text

            # Execute all function calls and collect results
            function_responses = []
            for fc in function_calls:
                tool_name = fc.name
                tool_input = dict(fc.args)

                self._log(f"  🔧 Tool: {tool_name}({json.dumps(tool_input, ensure_ascii=False)[:120]})")

                try:
                    result = await self._dispatch_tool(tool_name, tool_input)
                except Exception as e:
                    result = f"Tool error: {e}"

                # Truncate huge results (but never truncate base64 images)
                if isinstance(result, str) and len(result) > 5000 and not result.startswith("data:image"):
                    result = result[:5000] + "\n...[truncated]"

                self._log(f"  📄 Result: {str(result)[:200]}")

                function_responses.append(
                    protos.Part(
                        function_response=protos.FunctionResponse(
                            name=tool_name,
                            response={"result": str(result)},
                        )
                    )
                )

            # Send all tool results back in one message
            response = await asyncio.to_thread(
                chat.send_message,
                protos.Content(parts=function_responses, role="user"),
            )

        return "Max steps reached. Task may be incomplete."

    async def close(self):
        """Clean up the browser."""
        await bt.close_browser()
