"""
Agent Brain — Orchestrator Agent
The brain of the desktop agent. Takes natural language commands,
plans multi-step execution, dispatches to specialist agents via the SkillRegistry.
Uses Gemini Flash for reasoning (ReAct pattern: Think → Act → Observe → Repeat).
"""
import asyncio
import base64
import io
import json
import re
import time
import google.generativeai as genai
from typing import Dict, Any, List, Optional
from loguru import logger
from config import settings
from skill_registry import registry

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency guard
    Image = None


class AgentBrain:
    """
    Orchestrator Agent — the brain of the desktop agent.
    Receives NL commands and executes them using specialist agents.
    """

    SYSTEM_PROMPT = """You are a fully autonomous AI assistant with internet access and computer control.
You understand the user's intent and carry tasks through to completion — autonomously, step by step —
without stopping unless you genuinely need sensitive information (password/OTP/captcha) or critical
missing details from the user.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TWO MODES OF INTERNET ACCESS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FAST MODE (no visible browser) — use for pure information:
  internet_search, read_full_page, get_news, wikipedia_lookup,
  scrape_page_tables, parallel_read_pages
  → Fast, no browser opens, used for questions / research / data.

INTERACTIVE MODE (live visible browser) — use for actual interaction:
  browser(command=...), open_browser, navigate_to, browser_click,
  browser_type, browser_fill_form, browser_find_and_click,
  browser_extract_table, browser_wait_for_element,
  browser_select_option, browser_hover, browser_get_full_text,
  browser_new_tab, browser_request_user_input
  → Opens real browser on screen; used for filling forms, logging in,
    booking, submitting, buying.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DECISION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• User asks a question about facts, news, prices, weather, people,
  events, scores, definitions → FAST MODE ONLY. NEVER open a browser.
• User asks to "search for X and show me results" → FAST MODE:
  internet_search then read_full_page on best result.
• User asks to "go to a website and do something" (book, fill, submit,
  interact) → INTERACTIVE MODE with live browser.
• User asks a desktop task (open app, manage files, run command) →
  Desktop tools (shell, file agent, app agent, etc.).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AUTONOMY RULES — EXECUTE FULLY, DON'T STOP EARLY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. NEVER stop after one tool call. Keep going until the ENTIRE task is done.
2. Infer the full chain of steps from the user's intent:
   "open browser and search X and login" → open browser → find URL → navigate
   → read login page → fill username → ask for password → submit.
3. After internet_search, ALWAYS read the best result with read_full_page.
   NEVER return search snippets as the final answer.
4. If a tool fails, try a different approach immediately — never give up
   after one failure.
5. For browser tasks: prefer browser(command='snapshot') or browser_read_page
   to understand a new page before interacting. Snapshot refs are the most
   reliable way to act on a page.
   browser_read_page and browser_get_full_text can include OCR of the visible
   browser viewport, so use them for visual pages such as typing tests,
   canvases, charts, and image-heavy sites where DOM text is incomplete.
6. For forms: use browser_fill_form for non-sensitive fields, then call
   browser_request_user_input ONLY for passwords/OTPs/captchas.
7. Use browser_wait_for_element before clicking async-loaded content.
8. Use browser_find_and_click instead of browser_click when selector unknown.
9. Navigate login pages freely — identify the username/email field, fill it,
   then ask for the password with browser_request_user_input. Do NOT stop
   just because a page has a login form.
10. If a CAPTCHA appears, call browser_request_user_input(input_type='captcha')
    to ask the user to solve it, then continue.
11. Complete EVERY step of a multi-step task without asking for intermediate
    approval — only pause when you truly need something from the user.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHEN TO ASK THE USER (sparingly — only when truly blocked)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Call browser_request_user_input(input_type='text') ONLY when:
  • You need a PASSWORD, OTP, PIN, or CAPTCHA answer.
  • Critical task information is genuinely missing and cannot be inferred
    (e.g., "book a flight" with no destination → ask "From and to where?").
  • You have tried 2+ strategies and are genuinely stuck on a specific step.
  • The page requires an action only a human can perform.

DO NOT ask for: URL confirmation, permission to click buttons, intermediate
  step approval, or anything you can figure out yourself by reading the page.
If page observation is still ambiguous after browser_read_page,
browser_get_full_text, or browser snapshot, call ask_user_question with a
short focused question instead of saying you cannot see the page.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SENSITIVE DATA RULES — ABSOLUTE, NO EXCEPTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• NEVER fill a password, OTP, CVV, or credit card field with
  browser_type or browser_fill_form.
• ALWAYS call browser_request_user_input for passwords, PINs,
  OTPs, captchas, and payment card numbers.
• NEVER click "Pay", "Buy", "Confirm Purchase", "Place Order", or
  "Submit Payment" without explicit user approval.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESPONSE FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Give the direct answer or result first.
• For information answers: cite the source URL at the end.
• For lists (flights, products, news): use bullet points with key data.
• For browser tasks: briefly describe what was done and the final state.
• Keep responses concise — users often read on mobile via Telegram.
• If something was blocked or skipped, explain why in one sentence.

FAST PATH: If the message contains words like "what is", "who is",
"latest", "today", "current", "price", "score", "news", "how does",
"explain" → start with internet_search immediately. Do NOT open a browser.

LeetCode numbers: call leetcode_open_problem(problem_number=N) directly.
Windows file paths: use backslashes.
"""

    def __init__(self):
        """Initialize the Orchestrator with Gemini Flash"""
        if not settings.GOOGLE_API_KEY:
            logger.error("GOOGLE_API_KEY not set in .env.desktop or .env. Agent brain will not work.")
            self.model = None
            return

        genai.configure(api_key=settings.GOOGLE_API_KEY)
        self.model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=self.SYSTEM_PROMPT,
        )
        # ── Per-session conversation histories ───────────────────────
        # Key: session_id (str), Value: list of {role, content} dicts
        self._histories: Dict[str, List[Dict]] = {}
        self._max_history = 20  # Keep last 20 messages per session

        # ── Browser state (updated after every browser tool call) ────
        self._browser_states: Dict[str, Dict] = {}  # keyed by session_id
        self._browser_visual_state: Dict[str, Dict[str, Any]] = {}  # keyed by session_id

        # ── Pending input/clarification state per session ────────────
        # Saved when the agent pauses and needs the user to answer
        # something (password, OTP, or clarifying question).
        # On the next message, this is used to build a resume prompt.
        self._pending_input_states: Dict[str, Dict] = {}

        # ── Pending clarification (set when ask_user_question fires) ─
        self._pending_clarification: Optional[Dict] = None

        logger.info("🧠 Agent Brain (Orchestrator) initialized with Gemini Flash")

    def _build_tools(self) -> List[Dict]:
        """Get all tools from the registry formatted for Gemini"""
        tools = registry.get_all_tools()
        if not tools:
            logger.warning("No tools registered in the skill registry!")
            return []

        # Convert to Gemini function declarations
        gemini_tools = []
        for tool in tools:
            func = tool["function"]
            declaration = {
                "name": func["name"],
                "description": func["description"],
                "parameters": func.get("parameters", {"type": "object", "properties": {}}),
            }
            gemini_tools.append(declaration)

        return gemini_tools

    def _sanitize_tool_payload_for_llm(self, obj: Any, max_depth: int = 14) -> Any:
        """Avoid huge base64 screenshots in Gemini tool responses (token limit errors)."""
        if max_depth <= 0:
            return "<truncated>"
        if isinstance(obj, dict):
            out: Dict[str, Any] = {}
            for k, v in obj.items():
                kl = str(k).lower()
                if kl in ("screenshot", "image_base64") or "base64" in kl:
                    s = v if isinstance(v, str) else ""
                    out[k] = f"<image data omitted, {len(s)} chars>"
                elif kl == "evidence":
                    out[k] = "<evidence omitted>"
                else:
                    out[k] = self._sanitize_tool_payload_for_llm(v, max_depth - 1)
            return out
        if isinstance(obj, list):
            return [self._sanitize_tool_payload_for_llm(x, max_depth - 1) for x in obj[:40]]
        if isinstance(obj, str) and len(obj) > 4000:
            return obj[:4000] + "…(truncated)"
        return obj

    def _get_browser_visual_state(self, session_id: str) -> Dict[str, Any]:
        if session_id not in self._browser_visual_state:
            self._browser_visual_state[session_id] = {
                "image_base64": "",
                "visible_text": "",
                "ocr_text": "",
                "observation_mode": "",
                "url": "",
                "title": "",
            }
        return self._browser_visual_state[session_id]

    def _clean_text(self, value: Any, max_chars: int = 0) -> str:
        text = " ".join(str(value or "").split()).strip()
        if max_chars > 0:
            return text[:max_chars]
        return text

    def _extract_image_base64(self, result: Dict[str, Any]) -> str:
        inner = result.get("result")
        if isinstance(inner, dict):
            for key in ("image_base64", "screenshot"):
                value = inner.get(key, "")
                if isinstance(value, str) and value:
                    return value
        for evidence in result.get("evidence") or []:
            if isinstance(evidence, dict) and evidence.get("type") == "screenshot":
                image = evidence.get("image_base64", "")
                if isinstance(image, str) and image:
                    return image
        return ""

    def _prepare_inline_image_part(self, image_base64: str, mime_type: str = "image/png") -> Optional[Any]:
        if not image_base64:
            return None
        try:
            raw = base64.b64decode(image_base64)
        except Exception:
            return None

        if Image is not None:
            try:
                with Image.open(io.BytesIO(raw)) as image:
                    image.load()
                    if max(image.size) > 1400:
                        image.thumbnail((1400, 1400))
                    if len(raw) > 1_500_000:
                        if image.mode not in ("RGB", "L"):
                            image = image.convert("RGB")
                        out = io.BytesIO()
                        image.save(out, format="JPEG", quality=80, optimize=True)
                        raw = out.getvalue()
                        mime_type = "image/jpeg"
            except Exception:
                pass

        if len(raw) > 2_500_000:
            return None

        return genai.protos.Part(
            inline_data=genai.protos.Blob(
                mime_type=mime_type,
                data=raw,
            )
        )

    def _should_observe_browser_step(self, tool_name: str, tool_args: Dict[str, Any]) -> bool:
        if not self._is_browser_tool_name(tool_name):
            return False
        browser_command = str(tool_args.get("command", "")).lower()
        return browser_command not in {
            "status",
            "tabs",
            "console",
            "errors",
            "requests",
            "responsebody",
            "cookies",
            "storage",
            "trace_start",
            "trace_stop",
            "check_sensitive",
        }

    def _is_dynamic_browser_step(self, tool_name: str, tool_args: Dict[str, Any]) -> bool:
        if tool_name in {
            "browser_type",
            "browser_press_key",
            "browser_click",
            "browser_scroll",
            "browser_find_and_click",
            "browser_hover",
        }:
            return True
        return str(tool_args.get("command", "")).lower() in {
            "type",
            "press",
            "click",
            "hover",
            "compat_type",
            "compat_click_selector",
            "compat_find_by_text",
            "compat_scroll",
        }

    def _capture_browser_observation(
        self,
        session_id: str,
        *,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not self._get_browser_state(session_id).get("is_open"):
            return {}

        dynamic = self._is_dynamic_browser_step(tool_name, tool_args)
        max_polls = 3 if dynamic else 1
        latest: Dict[str, Any] = {}
        previous_visible = ""

        for poll_index in range(max_polls):
            read_result = registry.execute_tool("browser_read_page", {"session_id": session_id})
            shot_result = registry.execute_tool("browser_screenshot", {"session_id": session_id})

            read_payload = read_result.get("result") if isinstance(read_result.get("result"), dict) else {}
            visible_text = self._clean_text(
                read_payload.get("visible_text")
                or read_payload.get("body_text")
                or read_payload.get("text"),
                max_chars=1200,
            )
            latest = {
                "url": read_payload.get("url") or self._get_browser_state(session_id).get("current_url", ""),
                "title": read_payload.get("title") or self._get_browser_state(session_id).get("current_title", ""),
                "visible_text": visible_text,
                "ocr_text": self._clean_text(read_payload.get("ocr_text", ""), max_chars=1200),
                "observation_mode": read_payload.get("observation_mode", ""),
                "image_base64": self._extract_image_base64(shot_result) or self._extract_image_base64(result),
                "tool_name": tool_name,
                "action_result": "ok" if result.get("success") else (result.get("error") or result.get("message", "")),
                "polls": poll_index + 1,
            }
            self._get_browser_visual_state(session_id).update(latest)

            if not dynamic:
                break
            if visible_text and visible_text == previous_visible:
                break
            previous_visible = visible_text
            if poll_index < max_polls - 1:
                time.sleep(0.25)

        return latest

    def _build_browser_observation_summary(self, observation: Dict[str, Any]) -> str:
        if not observation:
            return ""
        lines = ["Browser observation after the last action:"]
        if observation.get("url"):
            lines.append(f"URL: {observation['url']}")
        if observation.get("title"):
            lines.append(f"Title: {observation['title']}")
        if observation.get("observation_mode"):
            lines.append(f"Observation mode: {observation['observation_mode']}")
        if observation.get("visible_text"):
            lines.append(f"Visible text: {observation['visible_text']}")
        elif observation.get("ocr_text"):
            lines.append(f"OCR text: {observation['ocr_text']}")
        return "\n".join(lines)

    def _build_tool_feedback_parts(
        self,
        *,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: Dict[str, Any],
        session_id: str,
    ) -> List[Any]:
        safe = self._sanitize_tool_payload_for_llm(result)
        payload = json.dumps(safe, default=str)
        if len(payload) > 28000:
            payload = payload[:28000] + "â€¦(truncated)"

        parts: List[Any] = [
            genai.protos.Part(
                function_response=genai.protos.FunctionResponse(
                    name=tool_name,
                    response={"result": payload},
                )
            )
        ]

        observation: Dict[str, Any] = {}
        if self._should_observe_browser_step(tool_name, tool_args):
            observation = self._capture_browser_observation(
                session_id,
                tool_name=tool_name,
                tool_args=tool_args,
                result=result,
            )

        image_base64 = (
            observation.get("image_base64")
            or self._extract_image_base64(result)
            or self._get_browser_visual_state(session_id).get("image_base64", "")
        )
        summary = self._build_browser_observation_summary(observation)
        if summary:
            parts.append(genai.protos.Part(text=summary))
        image_part = self._prepare_inline_image_part(image_base64)
        if image_part is not None:
            parts.append(image_part)
        return parts

    def _build_user_message_content(self, prompt: str, session_id: str) -> Any:
        visual_state = self._get_browser_visual_state(session_id)
        image_part = self._prepare_inline_image_part(visual_state.get("image_base64", ""))
        if image_part is None:
            return prompt
        return genai.protos.Content(
            parts=[
                genai.protos.Part(text=prompt),
                image_part,
            ]
        )

    def _looks_like_browser_question(self, text: str) -> bool:
        normalized = self._clean_text(text).lower()
        if "?" not in normalized:
            return False
        browser_markers = (
            "screenshot",
            "selector",
            "search bar",
            "input field",
            "type box",
            "browser",
            "page",
            "response",
            "click",
            "github",
            "chatgpt",
            "describe",
            "provide",
        )
        return any(marker in normalized for marker in browser_markers)

    def _looks_like_answer_text(self, text: str) -> bool:
        normalized = self._clean_text(text).lower()
        if not normalized or len(normalized) > 220:
            return False
        if normalized in {"yes", "no", "ok", "okay", "done", "continue"}:
            return True
        imperative_prefixes = (
            "open ",
            "search ",
            "go to ",
            "navigate ",
            "click ",
            "type ",
            "press ",
            "scroll ",
            "find ",
            "open_browser",
            "browser_",
        )
        if any(normalized.startswith(prefix) for prefix in imperative_prefixes):
            return False
        answer_markers = (
            "input",
            "field",
            "search bar",
            "type box",
            "button",
            "left",
            "right",
            "top",
            "bottom",
            "there",
            "here",
            "yes",
            "no",
        )
        return any(marker in normalized for marker in answer_markers)

    def _infer_resume_prompt_from_recent_browser_question(self, session_id: str, user_reply: str) -> Optional[str]:
        if self._pending_input_states.get(session_id):
            return None
        if not self._get_browser_state(session_id).get("is_open"):
            return None
        if not self._looks_like_answer_text(user_reply):
            return None

        history = self._get_session_history(session_id)
        if len(history) < 2:
            return None

        last_question = None
        last_user_task = None
        for index in range(len(history) - 1, -1, -1):
            item = history[index]
            role = item.get("role")
            content = str(item.get("content", ""))
            if last_question is None and role in {"assistant", "model"} and self._looks_like_browser_question(content):
                last_question = content
                continue
            if last_question is not None and role == "user":
                last_user_task = content
                break

        if not last_question:
            return None

        lines = [
            "[TASK RESUME]",
            f"You were executing the task: \"{last_user_task or 'continue the browser task'}\"",
            f"You previously asked the user: {last_question}",
            f"The user has now answered: {user_reply}",
            "IMPORTANT: Treat this as the answer to your browser clarification and continue the existing browser task.",
            "Do NOT interpret this user reply as a brand-new unrelated task.",
        ]
        return "\n".join(lines)

    def _should_convert_browser_text_to_clarification(
        self,
        *,
        final_text: str,
        session_id: str,
        actions_taken: List[Dict[str, Any]],
    ) -> bool:
        if self._pending_input_states.get(session_id):
            return False
        if not self._get_browser_state(session_id).get("is_open"):
            return False
        if not self._looks_like_browser_question(final_text):
            return False
        return any(self._is_browser_tool_name(str(action.get("tool", ""))) for action in actions_taken)

    def _extract_target_site(self, command: str) -> str:
        normalized = str(command or "").lower()
        common_sites = {
            "chatgpt": "chatgpt.com",
            "chat.openai": "chatgpt.com",
            "github": "github.com",
            "leetcode": "leetcode.com",
            "monkeytype": "monkeytype.com",
        }
        for marker, host in common_sites.items():
            if marker in normalized:
                return host
        match = re.search(r"([a-z0-9-]+\.(?:com|org|io|ai|dev|app|net))", normalized)
        return match.group(1) if match else ""

    def _get_browser_site_guidance_prefix(self, session_id: str, command: str) -> str:
        state = self._get_browser_state(session_id)
        if not state.get("is_open"):
            return ""
        target_site = self._extract_target_site(command)
        if not target_site:
            return ""
        current_url = str(state.get("current_url", "")).lower()
        if target_site in current_url:
            return ""
        return (
            f"[SITE CONTINUITY: The user is referring to {target_site}, but the active browser tab is "
            f"{state.get('current_url', 'unknown')}. First list browser tabs and focus the matching {target_site} tab. "
            f"If no matching tab exists, open {target_site} in a new tab.]"
        )

    def _proto_to_python(self, obj: Any) -> Any:
        """Recursively convert Gemini proto MapComposite/ListComposite to plain Python dicts/lists.
        Prevents PydanticSerializationError when nested objects are passed between the agent brain
        and tool handlers (e.g. the `fields` dict in browser_fill_form).
        """
        # Import lazily so it doesn't blow up if the proto package changes
        try:
            from proto.marshal.collections.maps import MapComposite
            from proto.marshal.collections.repeated import RepeatedComposite
            if isinstance(obj, MapComposite):
                return {k: self._proto_to_python(v) for k, v in obj.items()}
            if isinstance(obj, RepeatedComposite):
                return [self._proto_to_python(v) for v in obj]
        except ImportError:
            pass
        if isinstance(obj, dict):
            return {k: self._proto_to_python(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._proto_to_python(v) for v in obj]
        return obj

    async def process_command(self, command: str, session_id: str = "default", context: Optional[str] = None) -> Dict[str, Any]:
        """
        Async entrypoint for FastAPI. Runs the sync ReAct loop in a worker thread
        so Playwright sync API and other blocking tools are not on the asyncio loop.
        """
        return await asyncio.to_thread(self.process_command_sync, command, session_id, context)

    def _get_session_history(self, session_id: str) -> List[Dict]:
        """Return (creating if needed) the conversation history for a session."""
        if session_id not in self._histories:
            self._histories[session_id] = []
        return self._histories[session_id]

    def _get_browser_state(self, session_id: str) -> Dict:
        """Return (creating if needed) the browser state for a session."""
        if session_id not in self._browser_states:
            self._browser_states[session_id] = {
                "is_open": False,
                "profile": "",
                "driver": "",
                "transport": "",
                "current_url": "",
                "current_title": "",
                "tab_id": "",
                "last_snapshot_mode": "",
                "last_action_summary": "",
                "last_observation_excerpt": "",
            }
        return self._browser_states[session_id]

    def _get_browser_context_prefix(self, session_id: str) -> str:
        """Return a context block prepended to every command when the browser is open."""
        state = self._get_browser_state(session_id)
        if not state["is_open"]:
            return ""
        lines = [
            "[BROWSER CONTEXT: The browser is currently open and ready to use.",
            f" URL: {state['current_url']}",
        ]
        if state["current_title"]:
            lines.append(f" Page title: {state['current_title']}")
        if state.get("profile"):
            lines.append(f" Profile: {state['profile']}")
        if state.get("driver"):
            lines.append(f" Driver: {state['driver']}")
        if state.get("transport"):
            lines.append(f" Transport: {state['transport']}")
        if state.get("tab_id"):
            lines.append(f" Active tab: {state['tab_id']}")
        if state.get("last_snapshot_mode"):
            lines.append(f" Last snapshot mode: {state['last_snapshot_mode']}")
        if state["last_action_summary"]:
            lines.append(f" Last action: {state['last_action_summary']}")
        if state.get("last_observation_excerpt"):
            lines.append(f" Recent visible content: {state['last_observation_excerpt']}")
        lines.append(
            " The user's follow-up command likely refers to what is currently visible in this browser."
            " Do NOT open a new browser window — use the live browser directly.]"
        )
        return "\n".join(lines)

    def _update_browser_state_from_result(
        self, tool_name: str, result: Dict, session_id: str
    ) -> None:
        """Update _browser_state when a browser tool returns url/title data."""
        state = self._get_browser_state(session_id)
        is_browser_tool = self._is_browser_tool_name(tool_name)
        observed = result.get("observed_state", {}) or {}
        if isinstance(observed, dict):
            for key in (
                "is_open",
                "profile",
                "driver",
                "transport",
                "current_url",
                "current_title",
                "tab_id",
                "last_snapshot_mode",
                "last_action_summary",
                "last_observation_excerpt",
            ):
                value = observed.get(key)
                if value not in (None, ""):
                    state[key] = value
        inner = result.get("result", {})
        if is_browser_tool and isinstance(inner, dict):
            url = inner.get("url", "")
            title = inner.get("title", "")
            if url:
                state["is_open"] = True
                state["current_url"] = url
            if title:
                state["current_title"] = title
            tab_id = inner.get("tab_id") or inner.get("target_id")
            if tab_id:
                state["tab_id"] = tab_id
            for observation_key in ("visible_text", "text", "body_text", "ocr_text"):
                observation_value = inner.get(observation_key, "")
                if observation_value:
                    excerpt = " ".join(str(observation_value).split())[:700]
                    if excerpt:
                        state["last_observation_excerpt"] = excerpt
                    break

    def _is_browser_tool_name(self, tool_name: str) -> bool:
        return tool_name == "browser" or tool_name.startswith("browser_") or tool_name in {
            "open_browser",
            "navigate_to",
            "close_browser",
            "leetcode_open_problem",
        }

    def _update_last_browser_action_summary(self, session_id: str, actions_taken: List[Dict]) -> None:
        state = self._get_browser_state(session_id)
        browser_tools = [a["tool"] for a in actions_taken if self._is_browser_tool_name(str(a.get("tool", "")))]
        if browser_tools:
            state["last_action_summary"] = "; ".join(browser_tools[-2:])

    def reset_browser_state(self, session_id: str = "default") -> None:
        """Clear browser state for a session (called on close_browser)."""
        self._browser_states[session_id] = {
            "is_open": False,
            "profile": "",
            "driver": "",
            "transport": "",
            "current_url": "",
            "current_title": "",
            "tab_id": "",
            "last_snapshot_mode": "",
            "last_action_summary": "",
            "last_observation_excerpt": "",
        }
        self._browser_visual_state[session_id] = {
            "image_base64": "",
            "visible_text": "",
            "ocr_text": "",
            "observation_mode": "",
            "url": "",
            "title": "",
        }

    def _save_pending_input(
        self,
        session_id: str,
        original_task: str,
        actions_taken: List[Dict],
        pending_type: str,  # 'user_input' | 'clarification'
        field_description: str = "",
        reason: str = "",
        input_type: str = "text",
        question: str = "",
        options: List[str] = None,
    ) -> None:
        """Save what the agent is waiting for so the next reply can resume the task."""
        self._pending_input_states[session_id] = {
            "original_task": original_task,
            "actions_taken": list(actions_taken),
            "pending_type": pending_type,
            "field_description": field_description,
            "reason": reason,
            "input_type": input_type,
            "question": question,
            "options": options or [],
        }
        logger.info(f"💾 Saved pending state [{session_id}]: type={pending_type}, waiting_for={field_description or question}")

    def _build_pending_input_payload(
        self,
        session_id: str,
        field_description: str,
        input_type: str,
        reason: str,
    ) -> Dict[str, Any]:
        """Return a session-aware payload for the API layer to wrap with a request ID."""
        return {
            "session_id": session_id,
            "field_description": field_description,
            "input_type": input_type,
            "reason": reason,
        }

    def _build_resume_prompt(self, session_id: str, user_reply: str) -> Optional[str]:
        """
        If there is a pending input state for this session, build a resume prompt
        that tells the model:
          1. What it was originally doing
          2. What actions it had taken
          3. What it asked the user for
          4. What the user just answered
          5. That it must now CONTINUE the original task using this answer

        Returns None if there is no pending state.
        Clears the pending state after building the prompt.
        """
        state = self._pending_input_states.pop(session_id, None)
        if not state:
            return None

        lines = [
            "[TASK RESUME]",
            f"You were executing the task: \"{state['original_task']}\"",
        ]

        if state["actions_taken"]:
            done = ", ".join(a["tool"] for a in state["actions_taken"][-6:])
            lines.append(f"Actions already completed: {done}")

        if state["pending_type"] == "user_input":
            lines.append(
                f"You paused because you needed the user to provide: {state['field_description']}"
                + (f" (reason: {state['reason']})" if state.get('reason') else "")
            )
            lines.append(f"The user has now provided the answer: {user_reply}")
            lines.append(
                "IMPORTANT: Use this exact value to fill in the required field in the browser. "
                "Do NOT ask for it again. Do NOT call browser_request_user_input. "
                "Proceed directly with browser_type or browser_fill_form to enter the value."
            )
        elif state["pending_type"] == "clarification":
            lines.append(f"You asked: {state['question']}")
            if state["options"]:
                lines.append(f"Options offered: {', '.join(state['options'])}")
            lines.append(f"The user chose / answered: {user_reply}")
            lines.append(
                "IMPORTANT: Now continue the original task using this answer. "
                "Do NOT ask for clarification again."
            )

        lines.append(
            "Continue the original task to completion from where you left off. "
            "The browser is still open at its current page."
        )
        resume = "\n".join(lines)
        logger.info(f"🔄 Built resume prompt for session [{session_id}]: {resume[:120]}...")
        return resume

    def process_command_sync(self, command: str, session_id: str = "default", context: Optional[str] = None) -> Dict[str, Any]:
        """
        Process a natural language command through the ReAct loop (blocking).

        Args:
            command:    Natural language command from the user
            session_id: Per-user session identifier (default: 'default')
            context:    Optional conversation context block prepended to the command

        Returns:
            Dict with:
            - response: str — final text response
            - actions_taken: list — tools that were called
            - success: bool
            - browser_state: dict — current browser state
            - requires_clarification: bool
            - question: str (when requires_clarification is True)
            - options: list (when requires_clarification is True)
        """
        if not self.model:
            return {
                "response": "Agent brain not initialized. Please set GOOGLE_API_KEY in .env.desktop or .env",
                "actions_taken": [],
                "success": False,
                "browser_state": {},
                "requires_clarification": False,
            }

        actions_taken = []
        gemini_tools = self._build_tools()

        # ── Check for pending input state (user replied to agent request) ──
        resume_prompt = self._build_resume_prompt(session_id, command)
        inferred_resume_prompt = None if resume_prompt else self._infer_resume_prompt_from_recent_browser_question(
            session_id,
            command,
        )

        # ── Prepend browser context + resume/context block ──
        browser_prefix = self._get_browser_context_prefix(session_id)
        site_guidance_prefix = self._get_browser_site_guidance_prefix(session_id, command)
        if resume_prompt:
            # Resume takes priority: tells the model exactly what to do next
            full_command = resume_prompt
            if browser_prefix:
                full_command = f"{browser_prefix}\n\n{full_command}"
        elif inferred_resume_prompt:
            full_command = inferred_resume_prompt
            if browser_prefix:
                full_command = f"{browser_prefix}\n\n{full_command}"
        else:
            full_command = command
            if context:
                full_command = f"{context}\n\nCurrent task: {command}"
            if browser_prefix:
                full_command = f"{browser_prefix}\n\n{full_command}"
            if site_guidance_prefix:
                full_command = f"{site_guidance_prefix}\n\n{full_command}"

        logger.info(f"🧠 Processing command [{session_id}]: {command}")
        logger.info(f"📦 Available tools: {len(gemini_tools)}")

        # Build tool config for Gemini
        tool_config = None
        tools_param = None
        if gemini_tools:
            tools_param = [genai.protos.Tool(
                function_declarations=[
                    genai.protos.FunctionDeclaration(
                        name=t["name"],
                        description=t["description"],
                        parameters=self._convert_to_proto_schema(t["parameters"]),
                    )
                    for t in gemini_tools
                ]
            )]

        # Start a chat with this session's history
        chat = self.model.start_chat(history=self._get_chat_history(session_id))

        try:
            # Send the user's message (with context prefix if any)
            response = chat.send_message(
                self._build_user_message_content(full_command, session_id),
                tools=tools_param,
            )

            # ReAct loop — keep executing tool calls until the model gives a text response
            max_iterations = 30
            iteration = 0

            while iteration < max_iterations:
                iteration += 1

                # Check if the model wants to call tools
                if not response.candidates:
                    break

                candidate = response.candidates[0]
                parts = candidate.content.parts

                # Collect all function calls from this response
                function_calls = [p for p in parts if p.function_call.name]

                if not function_calls:
                    # No more tool calls — we have the final text response
                    break

                # Execute each function call
                function_responses = []
                for part in function_calls:
                    fn_call = part.function_call
                    tool_name = fn_call.name
                    tool_args = self._proto_to_python(dict(fn_call.args) if fn_call.args else {})
                    if tool_name == "browser" or tool_name.startswith("browser_") or tool_name in {
                        "open_browser",
                        "navigate_to",
                        "close_browser",
                        "leetcode_open_problem",
                        "ask_user_question",
                    }:
                        tool_args.setdefault("session_id", session_id)

                    logger.info(f"🔧 Tool call [{iteration}]: {tool_name}({tool_args})")

                    # Execute via registry
                    result = registry.execute_tool(tool_name, tool_args)
                    preview = result.get("result", "")
                    if not result.get("success") and result.get("error"):
                        preview = result.get("error")
                    actions_taken.append({
                        "tool": tool_name,
                        "args": tool_args,
                        "success": result.get("success", False),
                        "error_code": result.get("error_code"),
                        "observed_state": result.get("observed_state") or {},
                        "result_preview": str(preview)[:200],
                    })

                    logger.info(
                        f"{'✅' if result.get('success') else '❌'} "
                        f"{tool_name} → {str(result)[:100]}"
                    )

                    # ── Update browser state from result ─────────────
                    self._update_browser_state_from_result(tool_name, result, session_id)

                    # ── Reset browser state on close ─────────────────
                    if tool_name == "close_browser" or (
                        tool_name == "browser" and tool_args.get("command") == "stop"
                    ):
                        self.reset_browser_state(session_id)

                    # ── Handle browser_request_user_input pause ───────
                    if (
                        result.get("error_code") == "user_input_required"
                        or "USER_INPUT_REQUIRED" in str(result.get("error", ""))
                    ):
                        obs = result.get("observed_state", {}) or {}
                        field_desc = obs.get("field_description", tool_args.get("field_description", "input"))
                        reason = obs.get("reason", tool_args.get("reason", ""))
                        input_type = obs.get("input_type", tool_args.get("input_type", "text"))
                        # Save pending state so the next user message can resume
                        self._save_pending_input(
                            session_id,
                            original_task=command,
                            actions_taken=list(actions_taken),
                            pending_type="user_input",
                            field_description=field_desc,
                            reason=reason,
                            input_type=input_type,
                        )
                        ask_msg = f"Please provide your {field_desc}."
                        if reason:
                            ask_msg += f" ({reason})"
                        return {
                            "response": ask_msg,
                            "actions_taken": actions_taken,
                            "success": False,
                            "browser_state": dict(self._get_browser_state(session_id)),
                            "requires_clarification": False,
                            "user_input_required": True,
                            "pending_input": self._build_pending_input_payload(
                                session_id=session_id,
                                field_description=field_desc,
                                input_type=input_type,
                                reason=reason,
                            ),
                            "question": ask_msg,
                            "options": [],
                            "pending_type": "user_input",
                        }

                    # ── Handle ask_user_question clarification signal ─
                    if result.get("requires_clarification"):
                        # Save per-session clarification state so the next reply
                        # is routed through _build_resume_prompt correctly
                        self._save_pending_input(
                            session_id,
                            original_task=command,
                            actions_taken=list(actions_taken),
                            pending_type="clarification",
                            question=result.get("question", ""),
                            options=result.get("options", []),
                        )
                        # Also keep the old global field for backwards compat
                        self._pending_clarification = {
                            "question": result.get("question", ""),
                            "options": result.get("options", []),
                            "context": result.get("context", ""),
                            "partial_actions": list(actions_taken),
                        }
                        return {
                            "response": result.get("question", "I need clarification to continue."),
                            "actions_taken": actions_taken,
                            "success": False,
                            "browser_state": dict(self._get_browser_state(session_id)),
                            "requires_clarification": True,
                            "question": result.get("question", ""),
                            "options": result.get("options", []),
                            "context": result.get("context", ""),
                            "pending_type": "clarification",
                        }


                    # ── Update last_action_summary ────────────────────
                    if actions_taken:
                        self._update_last_browser_action_summary(session_id, actions_taken)
                        latest_state = actions_taken[-1].get("observed_state") or {}
                        if (
                            self._is_browser_tool_name(tool_name)
                            and isinstance(latest_state, dict)
                            and latest_state.get("last_action_summary")
                        ):
                            self._get_browser_state(session_id)["last_action_summary"] = latest_state["last_action_summary"]

                    function_responses.extend(
                        self._build_tool_feedback_parts(
                            tool_name=tool_name,
                            tool_args=tool_args,
                            result=result,
                            session_id=session_id,
                        )
                    )

                # Send tool results back to the model
                response = chat.send_message(
                    genai.protos.Content(parts=function_responses),
                    tools=tools_param,
                )

            # Extract final text response
            final_text = ""
            if response.candidates:
                for part in response.candidates[0].content.parts:
                    if part.text:
                        final_text += part.text

            if not final_text:
                final_text = "Done." if actions_taken else "I couldn't understand that command."

            any_fail = any(not a.get("success") for a in actions_taken)
            if any_fail and "leetcode" in command.lower():
                final_text = (
                    f"{final_text}\n\n"
                    "(Some steps failed. For LeetCode by problem number, use leetcode_open_problem.)"
                )

            if self._should_convert_browser_text_to_clarification(
                final_text=final_text,
                session_id=session_id,
                actions_taken=actions_taken,
            ):
                clarification_question = final_text.strip()
                self._save_pending_input(
                    session_id,
                    original_task=command,
                    actions_taken=list(actions_taken),
                    pending_type="clarification",
                    question=clarification_question,
                    options=[],
                )
                self._pending_clarification = {
                    "question": clarification_question,
                    "options": [],
                    "context": "",
                    "partial_actions": list(actions_taken),
                }
                logger.info(
                    f"Converted free-text browser question into structured clarification [{session_id}]"
                )
                return {
                    "response": clarification_question,
                    "actions_taken": actions_taken,
                    "success": False,
                    "browser_state": dict(self._get_browser_state(session_id)),
                    "requires_clarification": True,
                    "question": clarification_question,
                    "options": [],
                    "context": "",
                    "pending_type": "clarification",
                    "user_input_required": False,
                }

            # Update this session's conversation history
            self._add_to_history("user", command, session_id)
            self._add_to_history("model", final_text, session_id)

            logger.info(f"🧠 Response: {final_text[:100]}...")
            return {
                "response": final_text,
                "actions_taken": actions_taken,
                "success": not any_fail,
                "browser_state": dict(self._get_browser_state(session_id)),
                "requires_clarification": False,
                "user_input_required": False,
            }

        except Exception as e:
            logger.error(f"🧠 Brain error: {e}")
            return {
                "response": f"I encountered an error: {str(e)}",
                "actions_taken": actions_taken,
                "success": False,
                "browser_state": dict(self._get_browser_state(session_id)),
                "requires_clarification": False,
                "user_input_required": False,
            }

    def _convert_to_proto_schema(self, schema: Dict) -> Any:
        """Convert JSON Schema to Gemini proto Schema"""
        if not schema or not schema.get("properties"):
            return genai.protos.Schema(type=genai.protos.Type.OBJECT)

        properties = {}
        for prop_name, prop_def in schema.get("properties", {}).items():
            prop_type = prop_def.get("type", "string").upper()
            type_map = {
                "STRING": genai.protos.Type.STRING,
                "INTEGER": genai.protos.Type.INTEGER,
                "NUMBER": genai.protos.Type.NUMBER,
                "BOOLEAN": genai.protos.Type.BOOLEAN,
                "ARRAY": genai.protos.Type.ARRAY,
                "OBJECT": genai.protos.Type.OBJECT,
            }
            proto_type = type_map.get(prop_type, genai.protos.Type.STRING)

            prop_schema = genai.protos.Schema(
                type=proto_type,
                description=prop_def.get("description", ""),
            )

            # Handle enum values
            if "enum" in prop_def:
                prop_schema.enum[:] = prop_def["enum"]

            # Handle array items
            if prop_type == "ARRAY" and "items" in prop_def:
                items_type = prop_def["items"].get("type", "string").upper()
                item_proto_type = type_map.get(items_type, genai.protos.Type.STRING)
                prop_schema.items = genai.protos.Schema(type=item_proto_type)

            properties[prop_name] = prop_schema

        return genai.protos.Schema(
            type=genai.protos.Type.OBJECT,
            properties=properties,
            required=schema.get("required", []),
        )

    def _get_chat_history(self, session_id: str = "default") -> list:
        """Get recent conversation history for a session, formatted for Gemini."""
        history = []
        session_hist = self._get_session_history(session_id)
        for msg in session_hist[-self._max_history:]:
            role = msg["role"]
            # Gemini uses 'model', not 'assistant'
            if role == "assistant":
                role = "model"
            history.append(
                genai.protos.Content(
                    role=role,
                    parts=[genai.protos.Part(text=msg["content"])],
                )
            )
        return history

    def _add_to_history(self, role: str, content: str, session_id: str = "default"):
        """Add a message to the session's conversation history."""
        session_hist = self._get_session_history(session_id)
        session_hist.append({"role": role, "content": content})
        # Trim old messages
        if len(session_hist) > self._max_history * 2:
            self._histories[session_id] = session_hist[-self._max_history:]

    def clear_history(self, session_id: Optional[str] = None):
        """Clear conversation history for a session (or all sessions)."""
        if session_id:
            self._histories.pop(session_id, None)
            self._browser_states.pop(session_id, None)
            self._browser_visual_state.pop(session_id, None)
            self._pending_input_states.pop(session_id, None)
            logger.info(f"🧠 Conversation history cleared for session: {session_id}")
        else:
            self._histories.clear()
            self._browser_states.clear()
            self._browser_visual_state.clear()
            self._pending_input_states.clear()
            self._pending_clarification = None
            logger.info("🧠 All conversation history cleared")


# Global instance
brain = AgentBrain()
