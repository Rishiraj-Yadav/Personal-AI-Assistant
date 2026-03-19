"""
Browser Agent — Live visible browser automation (Perplexity Comet-style).

Opens a REAL browser on the user's desktop so they can watch the AI navigate,
click, type, and interact with web pages in real-time.

Sensitive action detection blocks interactions with password fields,
payment forms, and login pages until the user explicitly approves.
"""
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from typing import Dict, Any, List, Optional

from loguru import logger
from agents.base_agent import BaseAgent

_pw_module = None


def _get_playwright_module():
    """Lazy-import playwright so it works even if installed after the agent starts."""
    global _pw_module
    if _pw_module is not None:
        return _pw_module
    try:
        import importlib
        importlib.invalidate_caches()
        mod = importlib.import_module("playwright.sync_api")
        _pw_module = mod
        logger.info("Playwright loaded successfully")
        return mod
    except (ImportError, ModuleNotFoundError):
        return None


SENSITIVE_URL_KEYWORDS = [
    "login", "signin", "sign-in", "sign_in", "auth",
    "checkout", "payment", "billing", "pay.",
    "bank", "account/security", "password",
    "oauth", "sso", "2fa", "mfa",
]


class BrowserAgent(BaseAgent):
    """Live visible browser agent for real-time web automation."""

    def __init__(self):
        super().__init__(
            name="browser_agent",
            description=(
                "Control a live visible browser on the user's screen. "
                "Navigate, click, type, scroll, read page content, and take screenshots. "
                "Blocks sensitive actions (passwords, payments) until user approves."
            ),
        )
        self._playwright: Optional["Playwright"] = None
        self._browser: Optional["Browser"] = None
        self._context: Optional["BrowserContext"] = None
        self._page: Optional["Page"] = None
        self._screenshots: List[str] = []

    # ── Browser lifecycle ────────────────────────────────────────────

    def _ensure_browser(self) -> "Page":
        if self._page and not self._page.is_closed():
            return self._page

        pw = _get_playwright_module()
        if pw is None:
            raise RuntimeError(
                "Playwright is not installed. "
                "Run: pip install playwright && playwright install chromium"
            )

        logger.info("Launching visible browser...")
        self._playwright = pw.sync_playwright().start()

        headed = os.environ.get("PLAYWRIGHT_HEADED", "1").strip().lower() not in (
            "0", "false", "no", "off",
        )
        launch_args = [
            "--disable-blink-features=AutomationControlled",
        ]
        if headed:
            launch_args.append("--start-maximized")

        # Playwright adds --enable-automation by default; Chrome then shows
        # "controlled by automated test software". Dropping that flag reduces
        # the scary banner (automation still works via CDP).
        launch_kwargs: Dict[str, Any] = {
            "headless": not headed,
            "args": launch_args,
            "ignore_default_args": ["--enable-automation"],
        }

        # Try bundled Chromium first (works after `playwright install chromium`).
        # Channel=chrome/msedge only works if that browser is installed.
        for channel in (None, "chrome", "msedge"):
            try:
                if channel:
                    self._browser = self._playwright.chromium.launch(
                        channel=channel, **launch_kwargs
                    )
                else:
                    self._browser = self._playwright.chromium.launch(**launch_kwargs)
                logger.info(f"Browser launched via {channel or 'bundled chromium'} (headed={headed})")
                break
            except Exception as exc:
                logger.warning(f"Could not launch {channel or 'chromium'}: {exc}")

        if not self._browser and headed:
            logger.info("Headed launch failed; retrying headless (no visible window)...")
            launch_kwargs["headless"] = True
            launch_kwargs["args"] = ["--disable-blink-features=AutomationControlled"]
            launch_kwargs["ignore_default_args"] = ["--enable-automation"]
            for channel in (None, "chrome", "msedge"):
                try:
                    if channel:
                        self._browser = self._playwright.chromium.launch(
                            channel=channel, **launch_kwargs
                        )
                    else:
                        self._browser = self._playwright.chromium.launch(**launch_kwargs)
                    logger.info(f"Browser launched headless via {channel or 'bundled chromium'}")
                    break
                except Exception as exc:
                    logger.warning(f"Headless retry failed ({channel or 'chromium'}): {exc}")

        if not self._browser:
            raise RuntimeError(
                "No usable browser found. On the host run:\n"
                "  pip install playwright\n"
                "  python -m playwright install chromium\n"
                "Or install Google Chrome / Microsoft Edge for channel launch."
            )

        # Do not pass both viewport= and no_viewport=True (Playwright can misbehave).
        self._context = self._browser.new_context(no_viewport=True)
        self._page = self._context.new_page()
        self._page.set_default_timeout(15_000)
        return self._page

    def _take_screenshot(self) -> str:
        if not self._page or self._page.is_closed():
            return ""
        try:
            raw = self._page.screenshot(type="png", full_page=False)
            b64 = base64.b64encode(raw).decode("utf-8")
            self._screenshots.append(b64)
            if len(self._screenshots) > 5:
                self._screenshots = self._screenshots[-5:]
            return b64
        except Exception as exc:
            logger.warning(f"Screenshot failed: {exc}")
            return ""

    # ── Sensitivity detection ────────────────────────────────────────

    def _detect_sensitive_context(self) -> Dict[str, Any]:
        if not self._page or self._page.is_closed():
            return {"sensitive": False}

        try:
            url = self._page.url.lower()

            url_sensitive = any(kw in url for kw in SENSITIVE_URL_KEYWORDS)

            sensitive_fields = self._page.evaluate("""() => {
                const found = [];
                for (const el of document.querySelectorAll('input')) {
                    const t = (el.type || '').toLowerCase();
                    const n = (el.name || '').toLowerCase();
                    const p = (el.placeholder || '').toLowerCase();
                    const ac = (el.autocomplete || '').toLowerCase();
                    if (
                        t === 'password' ||
                        ac.includes('cc-') || ac.includes('card') ||
                        n.includes('password') || n.includes('card') ||
                        n.includes('cvv') || n.includes('ssn') ||
                        p.includes('password') || p.includes('card number')
                    ) {
                        found.push({ type: t, name: n, placeholder: p });
                    }
                }
                return found;
            }""")

            is_sensitive = url_sensitive or len(sensitive_fields) > 0
            reason = ""
            if sensitive_fields:
                kinds = list({f.get("type", "text") for f in sensitive_fields})
                reason = f"Page contains sensitive input fields ({', '.join(kinds)})"
            elif url_sensitive:
                reason = f"URL appears to be a sensitive page ({url[:120]})"

            return {
                "sensitive": is_sensitive,
                "reason": reason,
                "fields": sensitive_fields,
                "url": self._page.url,
            }
        except Exception as exc:
            logger.warning(f"Sensitivity detection error: {exc}")
            return {"sensitive": False}

    # ── Page content extraction ──────────────────────────────────────

    def _read_page_content(self) -> Dict[str, Any]:
        if not self._page or self._page.is_closed():
            return {"error": "No browser page open"}
        try:
            return self._page.evaluate("""() => {
                const txt = el => (el?.textContent || '').trim().slice(0, 200);
                return {
                    title: document.title,
                    url: window.location.href,
                    headings: Array.from(document.querySelectorAll('h1,h2,h3'))
                        .slice(0, 10).map(h => ({ tag: h.tagName, text: txt(h) })),
                    links: Array.from(document.querySelectorAll('a[href]'))
                        .slice(0, 20).map(a => ({ text: txt(a), href: a.href })),
                    buttons: Array.from(document.querySelectorAll(
                        'button, input[type="submit"], input[type="button"]'
                    )).slice(0, 15).map(b => ({
                        text: txt(b) || b.value || '', type: b.type || 'button',
                    })),
                    inputs: Array.from(document.querySelectorAll(
                        'input:not([type="hidden"]), textarea, select'
                    )).slice(0, 15).map(i => ({
                        type: i.type || i.tagName.toLowerCase(),
                        name: i.name,
                        placeholder: i.placeholder || '',
                        value: i.type === 'password' ? '***' : (i.value || '').slice(0, 100),
                    })),
                    body_text: document.body?.innerText?.slice(0, 2000) || '',
                };
            }""")
        except Exception as exc:
            return {"error": str(exc)}

    # ── Tool definitions ─────────────────────────────────────────────

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "open_browser",
                "description": (
                    "Open a live visible browser on the user's screen and navigate to a URL. "
                    "The user can watch the browser in real-time."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL to open (default: https://www.google.com)",
                        },
                    },
                },
            },
            {
                "name": "navigate_to",
                "description": "Navigate the live browser to a URL",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL to navigate to",
                        },
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "browser_click",
                "description": "Click an element on the page by its visible text or CSS selector",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Visible text of the element to click",
                        },
                        "selector": {
                            "type": "string",
                            "description": "CSS selector of the element to click",
                        },
                    },
                },
            },
            {
                "name": "browser_type",
                "description": (
                    "Type into an input/search field. If a selector times out, fallbacks run "
                    "automatically (search inputs, / or Ctrl+K command palette). "
                    "For LeetCode problems by NUMBER, prefer leetcode_open_problem instead of guessing selectors."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Text to type",
                        },
                        "selector": {
                            "type": "string",
                            "description": "CSS selector of the input (optional)",
                        },
                        "press_enter": {
                            "type": "boolean",
                            "description": "Press Enter after typing (default: false)",
                        },
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "leetcode_open_problem",
                "description": (
                    "Open a LeetCode problem by its on-site number (e.g. 150 = Evaluate Reverse Polish Notation). "
                    "Uses LeetCode's public API to resolve the slug and navigates straight to the problem page. "
                    "Use this when the user asks for a problem by number — do not rely on textarea[placeholder=Search] on the homepage."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "problem_number": {
                            "type": "integer",
                            "description": "Problem number as shown on LeetCode (e.g. 150)",
                        },
                    },
                    "required": ["problem_number"],
                },
            },
            {
                "name": "browser_press_key",
                "description": "Press a keyboard key (Enter, Tab, Escape, ArrowDown, etc.)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Key name (e.g. 'Enter', 'Tab', 'Escape')",
                        },
                    },
                    "required": ["key"],
                },
            },
            {
                "name": "browser_scroll",
                "description": "Scroll the page up or down",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "direction": {
                            "type": "string",
                            "description": "'up' or 'down'",
                        },
                        "amount": {
                            "type": "integer",
                            "description": "Pixels to scroll (default: 500)",
                        },
                    },
                    "required": ["direction"],
                },
            },
            {
                "name": "browser_read_page",
                "description": (
                    "Read the current page content: title, URL, headings, links, "
                    "buttons, input fields, and body text. Call this to understand "
                    "the page before interacting."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "browser_screenshot",
                "description": "Take a screenshot of the live browser",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "browser_go_back",
                "description": "Navigate back to the previous page",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "browser_check_sensitive",
                "description": (
                    "Check whether the current page has sensitive elements "
                    "(password fields, payment forms, login pages). "
                    "Call this BEFORE interacting with any page that might be sensitive."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "close_browser",
                "description": "Close the live browser",
                "parameters": {"type": "object", "properties": {}},
            },
        ]

    # ── Tool dispatch ────────────────────────────────────────────────

    def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        handlers = {
            "open_browser": lambda: self._open_browser(args.get("url", "https://www.google.com")),
            "navigate_to": lambda: self._navigate(args.get("url", "")),
            "browser_click": lambda: self._click(args.get("text"), args.get("selector")),
            "browser_type": lambda: self._type_text(
                args.get("text", ""),
                args.get("selector"),
                args.get("press_enter", False),
            ),
            "leetcode_open_problem": lambda: self._leetcode_open_problem(
                int(float(args.get("problem_number", 0))),
            ),
            "browser_press_key": lambda: self._press_key(args.get("key", "Enter")),
            "browser_scroll": lambda: self._scroll(
                args.get("direction", "down"), args.get("amount", 500)
            ),
            "browser_read_page": lambda: self._read_page(),
            "browser_screenshot": lambda: self._screenshot(),
            "browser_go_back": lambda: self._go_back(),
            "browser_check_sensitive": lambda: self._check_sensitive(),
            "close_browser": lambda: self._close(),
        }
        handler = handlers.get(tool_name)
        if handler:
            return handler()
        return self._error(f"Unknown tool: {tool_name}")

    # ── Tool implementations ─────────────────────────────────────────

    def _open_system_default_browser(self, url: str) -> bool:
        """Last resort: open the user's default OS browser (no Playwright automation)."""
        if not url or not str(url).strip():
            url = "https://www.google.com"
        u = str(url).strip()
        if not u.startswith(("http://", "https://")):
            u = f"https://{u}"
        try:
            if sys.platform == "win32":
                os.startfile(u)  # type: ignore[attr-defined]
            else:
                webbrowser.open(u, new=1)
            logger.info(f"Opened system default browser: {u}")
            return True
        except Exception as exc:
            logger.warning(f"System default browser open failed: {exc}")
            return False

    def _open_browser(self, url: str) -> Dict[str, Any]:
        try:
            page = self._ensure_browser()
            if url:
                page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                try:
                    page.wait_for_load_state("networkidle", timeout=8_000)
                except Exception:
                    pass
            ss = self._take_screenshot()
            return self._success(
                {"url": page.url, "title": page.title(), "screenshot": ss},
                f"Browser opened at {page.url}",
                evidence=[{"type": "screenshot", "image_base64": ss}] if ss else [],
            )
        except Exception as exc:
            logger.error(f"Playwright browser launch failed: {exc}")
            fallback_url = url or "https://www.google.com"
            if self._open_system_default_browser(fallback_url):
                return self._success(
                    {
                        "url": fallback_url,
                        "mode": "system_default_browser",
                        "playwright_error": str(exc),
                    },
                    (
                        "Opened your default web browser (Windows/ OS handler). "
                        "Playwright could not start for full automation — run on the host: "
                        "`pip install playwright` then `python -m playwright install chromium`, "
                        "then restart the Desktop Agent."
                    ),
                    evidence=[],
                )
            return self._error(
                f"Failed to open browser: {exc}. "
                "Install Playwright in the SAME Python you use to start desktop_agent.py, "
                "then run: python -m playwright install chromium",
                retryable=True,
            )

    def _navigate(self, url: str) -> Dict[str, Any]:
        if not url:
            return self._error("No URL provided")
        try:
            page = self._ensure_browser()
            if not url.startswith(("http://", "https://")):
                url = f"https://{url}"
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            try:
                page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:
                pass
            ss = self._take_screenshot()
            return self._success(
                {"url": page.url, "title": page.title(), "screenshot": ss},
                f"Navigated to {page.url}",
                evidence=[{"type": "screenshot", "image_base64": ss}] if ss else [],
            )
        except Exception as exc:
            return self._error(f"Navigation failed: {exc}", retryable=True)

    def _click(
        self, text: Optional[str] = None, selector: Optional[str] = None
    ) -> Dict[str, Any]:
        try:
            page = self._ensure_browser()

            sensitivity = self._detect_sensitive_context()
            if sensitivity.get("sensitive"):
                return self._error(
                    f"SENSITIVE_ACTION_BLOCKED: {sensitivity.get('reason', 'Sensitive page detected')}. "
                    "User approval is required before interacting with this page.",
                    error_code="sensitive_action_blocked",
                    retryable=False,
                    observed_state=sensitivity,
                )

            if text:
                element = page.get_by_text(text, exact=False).first
                element.click(timeout=5_000)
            elif selector:
                page.click(selector, timeout=5_000)
            else:
                return self._error("Provide 'text' or 'selector' to click")

            time.sleep(0.2)
            try:
                page.wait_for_load_state("networkidle", timeout=4_000)
            except Exception:
                pass

            ss = self._take_screenshot()
            target = text or selector
            return self._success(
                {"clicked": target, "url": page.url, "title": page.title(), "screenshot": ss},
                f"Clicked: {target}",
                evidence=[{"type": "screenshot", "image_base64": ss}] if ss else [],
            )
        except Exception as exc:
            if "sensitive_action_blocked" in str(exc).lower():
                raise
            return self._error(f"Click failed: {exc}", retryable=True)

    def _leetcode_slug_for_number(self, n: int) -> Optional[str]:
        """Resolve title slug from LeetCode's public problems list (frontend_question_id)."""
        try:
            req = urllib.request.Request(
                "https://leetcode.com/api/problems/all/",
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                },
            )
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = json.loads(resp.read().decode())
            for pair in data.get("stat_status_pairs") or []:
                st = pair.get("stat") or {}
                if st.get("frontend_question_id") == n:
                    return st.get("question__title_slug")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            logger.warning(f"LeetCode API slug lookup failed: {e}")
        return None

    def _leetcode_open_problem(self, problem_number: int) -> Dict[str, Any]:
        if problem_number <= 0:
            return self._error("problem_number must be a positive integer")
        try:
            page = self._ensure_browser()
            slug = self._leetcode_slug_for_number(problem_number)
            if slug:
                url = f"https://leetcode.com/problems/{slug}/"
            else:
                url = f"https://leetcode.com/problemset/all/?search={problem_number}"
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            try:
                page.wait_for_load_state("networkidle", timeout=12_000)
            except Exception:
                pass
            return self._success(
                {
                    "url": page.url,
                    "title": page.title(),
                    "problem_number": problem_number,
                    "resolved_slug": slug,
                },
                f"Opened LeetCode #{problem_number} → {page.url}",
                evidence=[],
            )
        except Exception as exc:
            return self._error(f"leetcode_open_problem failed: {exc}", retryable=True)

    def _try_type_visible_search_fields(
        self, page, text: str, press_enter: bool
    ) -> bool:
        selectors = [
            "input[type='search']",
            "[role='searchbox']",
            "[role='combobox']",
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                loc.wait_for(state="visible", timeout=2_000)
                loc.fill(text, timeout=12_000)
                if press_enter:
                    page.keyboard.press("Enter")
                return True
            except Exception:
                continue
        for rx in (
            re.compile(r"search", re.I),
            re.compile(r"type to search", re.I),
            re.compile(r"filter", re.I),
        ):
            try:
                loc = page.get_by_placeholder(rx).first
                loc.wait_for(state="visible", timeout=2_000)
                loc.click()
                loc.fill(text, timeout=12_000)
                if press_enter:
                    page.keyboard.press("Enter")
                return True
            except Exception:
                continue
        try:
            loc = page.locator("input[type='text'], textarea").first
            loc.wait_for(state="visible", timeout=2_000)
            loc.fill(text, timeout=12_000)
            if press_enter:
                page.keyboard.press("Enter")
            return True
        except Exception:
            pass
        return False

    def _try_type_command_palette(self, page, text: str, press_enter: bool, delay_ms: int) -> bool:
        for key in ("Slash", "Control+k"):
            try:
                page.keyboard.press(key)
                time.sleep(0.1)
                page.keyboard.type(text, delay=delay_ms)
                if press_enter:
                    page.keyboard.press("Enter")
                time.sleep(0.15)
                return True
            except Exception:
                continue
        return False

    def _type_text(
        self,
        text: str,
        selector: Optional[str] = None,
        press_enter: bool = False,
    ) -> Dict[str, Any]:
        TYPE_DELAY_MS = 20
        FILL_TIMEOUT_MS = 15_000
        try:
            page = self._ensure_browser()
            used_fallback = False
            enter_sent = False

            if selector:
                is_password = page.evaluate(
                    "(sel) => { const e = document.querySelector(sel); return e && e.type === 'password'; }",
                    selector,
                )
                if is_password:
                    return self._error(
                        "SENSITIVE_ACTION_BLOCKED: Cannot type into a password field "
                        "without user approval.",
                        error_code="sensitive_action_blocked",
                        retryable=False,
                    )
                try:
                    page.fill(selector, text, timeout=FILL_TIMEOUT_MS)
                    if press_enter:
                        time.sleep(0.08)
                        page.keyboard.press("Enter")
                        enter_sent = True
                except Exception as exc:
                    logger.warning(
                        f"browser_type: selector fill failed ({exc}), trying fallbacks"
                    )
                    if self._try_type_visible_search_fields(page, text, press_enter):
                        used_fallback = True
                        enter_sent = bool(press_enter)
                    elif self._try_type_command_palette(
                        page, text, press_enter, TYPE_DELAY_MS
                    ):
                        used_fallback = True
                        enter_sent = bool(press_enter)
                    else:
                        return self._error(
                            f"Type failed: selector not found or not fillable ({exc}). "
                            "For LeetCode by problem number use leetcode_open_problem.",
                            retryable=True,
                        )
            else:
                sensitivity = self._detect_sensitive_context()
                if sensitivity.get("sensitive") and any(
                    f.get("type") == "password" for f in sensitivity.get("fields", [])
                ):
                    return self._error(
                        "SENSITIVE_ACTION_BLOCKED: Page has password fields. "
                        "User approval required before typing.",
                        error_code="sensitive_action_blocked",
                        retryable=False,
                        observed_state=sensitivity,
                    )
                if self._try_type_visible_search_fields(page, text, press_enter):
                    enter_sent = bool(press_enter)
                elif self._try_type_command_palette(
                    page, text, press_enter, TYPE_DELAY_MS
                ):
                    enter_sent = bool(press_enter)
                else:
                    page.keyboard.type(text, delay=TYPE_DELAY_MS)
                    if press_enter:
                        time.sleep(0.08)
                        page.keyboard.press("Enter")
                        enter_sent = True

            if enter_sent:
                try:
                    page.wait_for_load_state("networkidle", timeout=7_000)
                except Exception:
                    pass
            else:
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=2_500)
                except Exception:
                    pass

            ss = self._take_screenshot()
            return self._success(
                {
                    "typed": text[:80],
                    "selector": selector,
                    "used_fallback": used_fallback,
                    "url": page.url,
                    "screenshot": ss,
                },
                f"Typed text{' (with fallback)' if used_fallback else ''}",
                evidence=[{"type": "screenshot", "image_base64": ss}] if ss else [],
            )
        except Exception as exc:
            return self._error(f"Type failed: {exc}", retryable=True)

    def _press_key(self, key: str) -> Dict[str, Any]:
        try:
            page = self._ensure_browser()
            page.keyboard.press(key)
            time.sleep(0.18)
            ss = self._take_screenshot()
            return self._success(
                {"key": key, "url": page.url, "screenshot": ss},
                f"Pressed {key}",
                evidence=[{"type": "screenshot", "image_base64": ss}] if ss else [],
            )
        except Exception as exc:
            return self._error(f"Key press failed: {exc}", retryable=True)

    def _scroll(self, direction: str, amount: int = 500) -> Dict[str, Any]:
        try:
            page = self._ensure_browser()
            delta = -amount if direction == "up" else amount
            page.mouse.wheel(0, delta)
            time.sleep(0.15)
            ss = self._take_screenshot()
            return self._success(
                {"direction": direction, "amount": amount, "screenshot": ss},
                f"Scrolled {direction}",
                evidence=[{"type": "screenshot", "image_base64": ss}] if ss else [],
            )
        except Exception as exc:
            return self._error(f"Scroll failed: {exc}", retryable=True)

    def _read_page(self) -> Dict[str, Any]:
        try:
            content = self._read_page_content()
            if "error" in content:
                return self._error(content["error"])
            return self._success(content, f"Read page: {content.get('title', 'unknown')}")
        except Exception as exc:
            return self._error(f"Failed to read page: {exc}")

    def _screenshot(self) -> Dict[str, Any]:
        try:
            ss = self._take_screenshot()
            if not ss:
                return self._error("Failed to capture screenshot")
            page = self._ensure_browser()
            return self._success(
                {"url": page.url, "title": page.title(), "screenshot": ss},
                "Screenshot captured",
                evidence=[{"type": "screenshot", "image_base64": ss}],
            )
        except Exception as exc:
            return self._error(f"Screenshot failed: {exc}")

    def _go_back(self) -> Dict[str, Any]:
        try:
            page = self._ensure_browser()
            page.go_back(timeout=10_000)
            try:
                page.wait_for_load_state("networkidle", timeout=5_000)
            except Exception:
                pass
            ss = self._take_screenshot()
            return self._success(
                {"url": page.url, "title": page.title(), "screenshot": ss},
                f"Navigated back to {page.url}",
                evidence=[{"type": "screenshot", "image_base64": ss}] if ss else [],
            )
        except Exception as exc:
            return self._error(f"Go back failed: {exc}", retryable=True)

    def _check_sensitive(self) -> Dict[str, Any]:
        result = self._detect_sensitive_context()
        label = "SENSITIVE" if result.get("sensitive") else "safe"
        return self._success(result, f"Page sensitivity: {label}")

    def _close(self) -> Dict[str, Any]:
        try:
            if self._page and not self._page.is_closed():
                self._page.close()
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None
            self._screenshots = []
            return self._success({"closed": True}, "Browser closed")
        except Exception as exc:
            return self._error(f"Close failed: {exc}")

    def get_recent_screenshots(self) -> List[str]:
        return list(self._screenshots[-3:])


browser_agent = BrowserAgent()
