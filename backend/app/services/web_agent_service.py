"""
Autonomous Web Agent Service — Perplexity Comet-style browser automation.

Capabilities:
- Navigate to URLs, search the web
- Take screenshots to visually understand page content
- Read DOM / inspect elements for structured data
- Click, type, scroll, fill forms
- Extract information autonomously
- Ask user permission before sensitive actions (purchases, form submissions, logins)
- Multi-step task planning and execution with observe → think → act loop

Uses Playwright for browser control, Gemini/Groq for vision + reasoning.
"""

import asyncio
import base64
import json
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
from datetime import datetime, timezone

from loguru import logger

# Playwright is already in requirements.txt
from playwright.async_api import async_playwright, Browser, BrowserContext, Page


# Actions that require explicit user permission
SENSITIVE_ACTIONS = [
    "submit_form", "purchase", "payment", "login", "signup",
    "delete", "send_message", "post_comment", "download_file",
    "share", "publish", "authorize", "grant_access"
]


class WebAgentSession:
    """Manages a single browser session for a user."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.history: List[Dict] = []  # action history for this session
        self.created_at = datetime.now(timezone.utc)
        self._screenshots: List[str] = []  # base64 screenshots

    async def start(self):
        """Launch headless browser."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
            ]
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        self.page = await self.context.new_page()
        logger.info(f"🌐 Web session started for {self.user_id}")

    async def stop(self):
        """Clean up browser resources."""
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            logger.warning(f"⚠️ Browser cleanup error: {e}")
        logger.info(f"🌐 Web session ended for {self.user_id}")

    async def screenshot_base64(self) -> str:
        """Take a screenshot and return as base64."""
        if not self.page:
            return ""
        try:
            png_bytes = await self.page.screenshot(full_page=False, type="png")
            b64 = base64.b64encode(png_bytes).decode("utf-8")
            self._screenshots.append(b64)
            return b64
        except Exception as e:
            logger.error(f"Screenshot error: {e}")
            return ""

    async def get_page_info(self) -> Dict[str, Any]:
        """Extract structured info from current page via DOM inspection."""
        if not self.page:
            return {}
        try:
            info = await self.page.evaluate("""() => {
                // Basic page info
                const title = document.title || '';
                const url = window.location.href;
                const metaDesc = document.querySelector('meta[name="description"]');
                const description = metaDesc ? metaDesc.content : '';

                // Visible text content (truncated)
                const bodyText = document.body ? document.body.innerText.substring(0, 3000) : '';

                // Interactive elements
                const links = Array.from(document.querySelectorAll('a[href]')).slice(0, 20).map((a, i) => ({
                    index: i,
                    text: (a.innerText || a.title || '').trim().substring(0, 80),
                    href: a.href
                })).filter(l => l.text);

                const buttons = Array.from(document.querySelectorAll('button, [role="button"], input[type="submit"]'))
                    .slice(0, 15).map((b, i) => ({
                    index: i,
                    text: (b.innerText || b.value || b.title || b.ariaLabel || '').trim().substring(0, 80),
                    type: b.tagName.toLowerCase()
                })).filter(b => b.text);

                const inputs = Array.from(document.querySelectorAll('input:not([type="hidden"]), textarea, select'))
                    .slice(0, 15).map((inp, i) => ({
                    index: i,
                    type: inp.type || inp.tagName.toLowerCase(),
                    name: inp.name || inp.id || '',
                    placeholder: inp.placeholder || '',
                    value: inp.type === 'password' ? '***' : (inp.value || '').substring(0, 50),
                    label: inp.labels && inp.labels[0] ? inp.labels[0].innerText.trim() : ''
                }));

                // Headings for structure
                const headings = Array.from(document.querySelectorAll('h1, h2, h3')).slice(0, 10).map(h => ({
                    level: parseInt(h.tagName[1]),
                    text: h.innerText.trim().substring(0, 100)
                }));

                // Images with alt text
                const images = Array.from(document.querySelectorAll('img[alt]')).slice(0, 10).map(img => ({
                    alt: img.alt.substring(0, 100),
                    src: img.src.substring(0, 200)
                })).filter(img => img.alt);

                return {
                    title, url, description, bodyText,
                    links, buttons, inputs, headings, images,
                    scrollHeight: document.body.scrollHeight,
                    viewportHeight: window.innerHeight
                };
            }""")
            return info
        except Exception as e:
            logger.error(f"Page info extraction error: {e}")
            return {"error": str(e), "url": str(self.page.url)}

    async def navigate(self, url: str) -> Dict:
        """Navigate to URL."""
        try:
            # Basic URL validation
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            await self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await self.page.wait_for_timeout(1000)  # brief settle
            return {"success": True, "url": self.page.url}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def click_element(self, selector: str = None, text: str = None, index: int = None) -> Dict:
        """Click an element by selector, text content, or index."""
        try:
            if text:
                # Click by visible text
                locator = self.page.get_by_text(text, exact=False).first
                await locator.click(timeout=5000)
            elif selector:
                await self.page.click(selector, timeout=5000)
            elif index is not None:
                # Click nth clickable element
                clickable = await self.page.query_selector_all(
                    'a, button, [role="button"], input[type="submit"]'
                )
                if 0 <= index < len(clickable):
                    await clickable[index].click()
                else:
                    return {"success": False, "error": f"Element index {index} out of range (0-{len(clickable)-1})"}
            else:
                return {"success": False, "error": "No selector, text, or index provided"}
            await self.page.wait_for_timeout(1000)
            return {"success": True, "url": self.page.url}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def type_text(self, selector: str = None, text: str = "", name: str = None, index: int = None) -> Dict:
        """Type text into an input field."""
        try:
            if name:
                el = self.page.locator(f'input[name="{name}"], textarea[name="{name}"]').first
                await el.fill(text)
            elif selector:
                await self.page.fill(selector, text)
            elif index is not None:
                inputs = await self.page.query_selector_all('input:not([type="hidden"]), textarea')
                if 0 <= index < len(inputs):
                    await inputs[index].fill(text)
                else:
                    return {"success": False, "error": f"Input index {index} out of range"}
            else:
                return {"success": False, "error": "No selector, name, or index provided"}
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def press_key(self, key: str) -> Dict:
        """Press a keyboard key (Enter, Tab, Escape, etc.)."""
        try:
            await self.page.keyboard.press(key)
            await self.page.wait_for_timeout(500)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def scroll(self, direction: str = "down", amount: int = 500) -> Dict:
        """Scroll the page."""
        try:
            delta = amount if direction == "down" else -amount
            await self.page.mouse.wheel(0, delta)
            await self.page.wait_for_timeout(500)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def go_back(self) -> Dict:
        """Navigate back."""
        try:
            await self.page.go_back(timeout=10000)
            await self.page.wait_for_timeout(1000)
            return {"success": True, "url": self.page.url}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def extract_text(self, selector: str = None) -> Dict:
        """Extract text content from page or specific element."""
        try:
            if selector:
                el = await self.page.query_selector(selector)
                text = await el.inner_text() if el else ""
            else:
                text = await self.page.evaluate("() => document.body.innerText.substring(0, 5000)")
            return {"success": True, "text": text}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def wait_for_navigation(self, timeout: int = 10000) -> Dict:
        """Wait for page navigation/load."""
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=timeout)
            return {"success": True, "url": self.page.url}
        except Exception as e:
            return {"success": False, "error": str(e)}


class WebAgentService:
    """
    Autonomous web agent — observe, think, act loop.
    Uses LLM to reason about page content and decide actions.
    Asks user for permission on sensitive operations.
    """

    def __init__(self):
        self._sessions: Dict[str, WebAgentSession] = {}
        self._pending_permissions: Dict[str, Dict] = {}  # user_id -> pending action
        self.max_steps = 15  # max autonomous steps per task
        logger.info("✅ Web Agent Service initialized")

    async def get_or_create_session(self, user_id: str) -> WebAgentSession:
        """Get existing session or create new one."""
        if user_id not in self._sessions:
            session = WebAgentSession(user_id)
            await session.start()
            self._sessions[user_id] = session
        return self._sessions[user_id]

    async def close_session(self, user_id: str):
        """Close and clean up a user's session."""
        session = self._sessions.pop(user_id, None)
        if session:
            await session.stop()

    def set_permission_response(self, user_id: str, approved: bool):
        """User responds to a permission request."""
        if user_id in self._pending_permissions:
            self._pending_permissions[user_id]["approved"] = approved
            self._pending_permissions[user_id]["resolved"] = True

    async def execute_task(
        self,
        user_message: str,
        user_id: str,
        conversation_history: List[Dict] = None,
        user_context: str = "",
        message_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        Execute an autonomous web task.

        Returns:
            Dict with keys: success, output, screenshots, actions_taken, permission_needed
        """
        session = await self.get_or_create_session(user_id)
        actions_taken = []
        screenshots = []
        output_parts = []
        permission_needed = None

        try:
            # Import LLM here to avoid circular imports
            from app.core.llm import llm_adapter
            from app.models import Message, MessageRole

            # Step 1: Plan the task
            plan = await self._plan_task(
                llm_adapter, user_message, user_context,
                conversation_history or []
            )

            if message_callback:
                await message_callback({
                    "type": "web_agent_plan",
                    "message": f"🌐 **Web Agent Plan:**\n{plan['explanation']}",
                    "plan": plan
                })

            # Step 2: Execute observe→think→act loop
            for step in range(1, self.max_steps + 1):
                if message_callback:
                    await message_callback({
                        "type": "web_agent_step",
                        "message": f"🔄 Step {step}/{self.max_steps}...",
                        "step": step
                    })

                # OBSERVE: Get page state
                page_info = await session.get_page_info()
                screenshot_b64 = await session.screenshot_base64()
                if screenshot_b64:
                    screenshots.append(screenshot_b64)

                # THINK: Ask LLM what to do next
                action = await self._decide_next_action(
                    llm_adapter,
                    user_message=user_message,
                    page_info=page_info,
                    actions_taken=actions_taken,
                    step=step,
                    plan=plan,
                    user_context=user_context,
                )

                if action["type"] == "done":
                    # Task complete
                    output_parts.append(action.get("summary", "Task completed."))
                    if message_callback:
                        await message_callback({
                            "type": "web_agent_done",
                            "message": f"✅ {action.get('summary', 'Task completed.')}"
                        })
                    break

                if action["type"] == "error":
                    output_parts.append(f"❌ {action.get('error', 'Unknown error')}")
                    break

                # Check if action needs permission
                if self._needs_permission(action):
                    permission_needed = {
                        "action": action,
                        "description": action.get("description", "Perform a sensitive action"),
                        "step": step,
                    }
                    if message_callback:
                        await message_callback({
                            "type": "web_agent_permission",
                            "message": f"⚠️ **Permission Required:**\n{action.get('description', '')}",
                            "action": action
                        })
                    # Store pending permission
                    self._pending_permissions[user_id] = {
                        "action": action,
                        "approved": False,
                        "resolved": False,
                    }
                    # Wait for user response (with timeout)
                    approved = await self._wait_for_permission(user_id, timeout=60)
                    if not approved:
                        output_parts.append(
                            f"⏹️ Action skipped (not approved): {action.get('description', '')}"
                        )
                        actions_taken.append({
                            "step": step,
                            "action": action["type"],
                            "skipped": True,
                            "reason": "permission_denied"
                        })
                        continue

                # ACT: Execute the action
                result = await self._execute_action(session, action)
                actions_taken.append({
                    "step": step,
                    "action": action["type"],
                    "params": action.get("params", {}),
                    "result": result.get("success", False),
                    "url": result.get("url", ""),
                })

                if message_callback:
                    status = "✅" if result.get("success") else "❌"
                    await message_callback({
                        "type": "web_agent_action",
                        "message": f"{status} {action.get('description', action['type'])}",
                        "action": action["type"],
                        "success": result.get("success", False)
                    })

                if not result.get("success"):
                    output_parts.append(
                        f"⚠️ Action failed: {action['type']} — {result.get('error', 'unknown')}"
                    )

                # Small delay between steps
                await asyncio.sleep(0.5)
            else:
                output_parts.append(f"⚠️ Reached maximum steps ({self.max_steps}).")

            # Final observation
            final_info = await session.get_page_info()
            final_screenshot = await session.screenshot_base64()
            if final_screenshot:
                screenshots.append(final_screenshot)

            # Generate final summary
            summary = await self._generate_summary(
                llm_adapter,
                user_message=user_message,
                actions_taken=actions_taken,
                final_page_info=final_info,
                user_context=user_context,
            )
            output_parts.append(summary)

        except Exception as e:
            logger.error(f"❌ Web agent error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            output_parts.append(f"❌ Web agent error: {str(e)}")

        return {
            "success": len([a for a in actions_taken if a.get("result")]) > 0,
            "output": "\n\n".join(output_parts),
            "screenshots": screenshots[-3:],  # last 3 screenshots
            "actions_taken": actions_taken,
            "permission_needed": permission_needed,
            "current_url": session.page.url if session.page else "",
        }

    # ===== INTERNAL METHODS =====

    async def _plan_task(
        self, llm, user_message: str, user_context: str,
        conversation_history: List[Dict]
    ) -> Dict:
        """Use LLM to plan the web task."""
        from app.models import Message, MessageRole

        messages = [
            Message(
                role=MessageRole.SYSTEM,
                content="""You are a Web Agent Planner. Given a user's request, create a step-by-step plan for browsing the web to accomplish the task.

Think about:
1. What URL(s) to visit
2. What information to look for
3. What actions to take (click, type, scroll)
4. What information to extract and return

Respond in this EXACT JSON format:
{
    "explanation": "Brief description of the plan",
    "steps": [
        {"action": "navigate", "url": "https://...", "reason": "..."},
        {"action": "search", "query": "...", "reason": "..."},
        {"action": "extract", "target": "...", "reason": "..."}
    ],
    "needs_permission": false,
    "estimated_steps": 5
}

RULES:
- For search queries, use Google: https://www.google.com/search?q=<query>
- Keep plans concise (3-8 steps)
- Flag if the task needs user permission (purchases, form submissions, logins)
- If the task is just information retrieval, no permission needed
"""
            )
        ]

        if user_context:
            messages.append(Message(
                role=MessageRole.SYSTEM,
                content=f"User context: {user_context[:500]}"
            ))

        # Add recent conversation for context
        for msg in (conversation_history or [])[-3:]:
            if isinstance(msg, dict):
                role = MessageRole.USER if msg.get("role") == "user" else MessageRole.ASSISTANT
                messages.append(Message(role=role, content=msg.get("content", "")[:300]))

        messages.append(Message(
            role=MessageRole.USER,
            content=user_message
        ))

        result = await llm.generate_response(messages)
        response_text = result.get("response", "")

        # Parse JSON from response
        try:
            # Try to find JSON in the response
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                plan = json.loads(json_match.group())
                return plan
        except (json.JSONDecodeError, AttributeError):
            pass

        # Fallback plan
        return {
            "explanation": f"I'll browse the web to help with: {user_message[:100]}",
            "steps": [{"action": "navigate", "url": "https://www.google.com", "reason": "Start with search"}],
            "needs_permission": False,
            "estimated_steps": 5
        }

    async def _decide_next_action(
        self, llm, user_message: str, page_info: Dict,
        actions_taken: List[Dict], step: int, plan: Dict,
        user_context: str = ""
    ) -> Dict:
        """LLM decides the next action based on current page state."""
        from app.models import Message, MessageRole

        # Build compact page description
        page_desc = self._format_page_info(page_info)
        actions_desc = self._format_actions_taken(actions_taken)

        messages = [
            Message(
                role=MessageRole.SYSTEM,
                content=f"""You are an autonomous Web Agent. You are on step {step}/{self.max_steps}.

TASK: {user_message}
PLAN: {plan.get('explanation', '')}

CURRENT PAGE STATE:
{page_desc}

ACTIONS TAKEN SO FAR:
{actions_desc}

Based on the current page state and your progress, decide the NEXT action.

Available actions:
- navigate: Go to a URL. {{"type": "navigate", "url": "https://...", "description": "..."}}
- click: Click an element. {{"type": "click", "text": "button text", "description": "..."}} OR {{"type": "click", "index": 0, "description": "..."}}
- type: Type into input. {{"type": "type", "name": "field_name", "text": "value", "description": "..."}} OR {{"type": "type", "index": 0, "text": "value", "description": "..."}}
- press_key: Press keyboard key. {{"type": "press_key", "key": "Enter", "description": "..."}}
- scroll: Scroll page. {{"type": "scroll", "direction": "down", "amount": 500, "description": "..."}}
- go_back: Go to previous page. {{"type": "go_back", "description": "..."}}
- extract: Extract specific info. {{"type": "extract", "selector": "css_selector", "description": "..."}}
- submit_form: Submit a form (NEEDS PERMISSION). {{"type": "submit_form", "description": "..."}}
- done: Task is complete. {{"type": "done", "summary": "Here is what I found: ..."}}
- error: Something went wrong. {{"type": "error", "error": "Description of the problem"}}

RULES:
1. After navigating, observe the page before acting
2. If the task requires information, use "done" with the extracted info in "summary"
3. Prefer clicking by visible text over index
4. For search: navigate to google, type query in search input, press Enter
5. If stuck after 3 failed actions, try a different approach or report error
6. Mark submit_form, purchase, login actions as sensitive — they need permission
7. ALWAYS respond with valid JSON

Respond with EXACTLY ONE JSON action:"""
            ),
        ]

        result = await llm.generate_response(messages)
        response_text = result.get("response", "")

        # Parse action JSON
        try:
            json_match = re.search(r'\{[\s\S]*?\}', response_text)
            if json_match:
                action = json.loads(json_match.group())
                if "type" in action:
                    return action
        except (json.JSONDecodeError, AttributeError):
            pass

        # If we can't parse, try to infer
        lower = response_text.lower()
        if "done" in lower or "complete" in lower:
            return {"type": "done", "summary": response_text}
        return {"type": "error", "error": f"Could not parse action from LLM: {response_text[:200]}"}

    async def _execute_action(self, session: WebAgentSession, action: Dict) -> Dict:
        """Execute a single browser action."""
        action_type = action.get("type", "")

        try:
            if action_type == "navigate":
                return await session.navigate(action.get("url", ""))
            elif action_type == "click":
                return await session.click_element(
                    selector=action.get("selector"),
                    text=action.get("text"),
                    index=action.get("index"),
                )
            elif action_type == "type":
                return await session.type_text(
                    selector=action.get("selector"),
                    text=action.get("text", ""),
                    name=action.get("name"),
                    index=action.get("index"),
                )
            elif action_type == "press_key":
                return await session.press_key(action.get("key", "Enter"))
            elif action_type == "scroll":
                return await session.scroll(
                    direction=action.get("direction", "down"),
                    amount=action.get("amount", 500),
                )
            elif action_type == "go_back":
                return await session.go_back()
            elif action_type == "extract":
                return await session.extract_text(action.get("selector"))
            elif action_type == "submit_form":
                # Submit = press Enter or click submit button
                return await session.press_key("Enter")
            else:
                return {"success": False, "error": f"Unknown action: {action_type}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _generate_summary(
        self, llm, user_message: str, actions_taken: List[Dict],
        final_page_info: Dict, user_context: str = ""
    ) -> str:
        """Generate a final summary of what was accomplished."""
        from app.models import Message, MessageRole

        page_text = final_page_info.get("bodyText", "")[:2000]
        page_title = final_page_info.get("title", "")

        actions_desc = self._format_actions_taken(actions_taken)

        messages = [
            Message(
                role=MessageRole.SYSTEM,
                content="""You are a helpful assistant. Summarize the results of a web browsing task.
Be concise and informative. Extract the key information the user asked for.
If the page contains the requested information, include it in your summary.
Format nicely with markdown."""
            ),
            Message(
                role=MessageRole.USER,
                content=f"""ORIGINAL REQUEST: {user_message}

ACTIONS PERFORMED:
{actions_desc}

FINAL PAGE: {page_title}
PAGE CONTENT (excerpt):
{page_text}

Please provide a clear, helpful summary of what was found/accomplished."""
            )
        ]

        result = await llm.generate_response(messages)
        return result.get("response", "Task completed but could not generate summary.")

    def _needs_permission(self, action: Dict) -> bool:
        """Check if an action requires user permission."""
        action_type = action.get("type", "")
        description = action.get("description", "").lower()

        if action_type in SENSITIVE_ACTIONS:
            return True

        # Check description for sensitive keywords
        for keyword in SENSITIVE_ACTIONS:
            if keyword.replace("_", " ") in description:
                return True

        return False

    async def _wait_for_permission(self, user_id: str, timeout: int = 60) -> bool:
        """Wait for user to approve/deny a permission request."""
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            pending = self._pending_permissions.get(user_id, {})
            if pending.get("resolved"):
                approved = pending.get("approved", False)
                self._pending_permissions.pop(user_id, None)
                return approved
            await asyncio.sleep(0.5)
        # Timeout — deny by default
        self._pending_permissions.pop(user_id, None)
        return False

    def _format_page_info(self, info: Dict) -> str:
        """Format page info for LLM consumption."""
        parts = []
        parts.append(f"URL: {info.get('url', 'unknown')}")
        parts.append(f"Title: {info.get('title', 'unknown')}")

        if info.get("description"):
            parts.append(f"Description: {info['description']}")

        headings = info.get("headings", [])
        if headings:
            parts.append("Headings: " + " | ".join(
                f"H{h['level']}: {h['text']}" for h in headings[:5]
            ))

        links = info.get("links", [])
        if links:
            parts.append("Links:")
            for link in links[:10]:
                parts.append(f"  [{link['index']}] {link['text']} → {link['href'][:80]}")

        buttons = info.get("buttons", [])
        if buttons:
            parts.append("Buttons:")
            for btn in buttons[:8]:
                parts.append(f"  [{btn['index']}] {btn['text']}")

        inputs = info.get("inputs", [])
        if inputs:
            parts.append("Input Fields:")
            for inp in inputs[:8]:
                label = inp.get("label") or inp.get("placeholder") or inp.get("name") or "unnamed"
                parts.append(f"  [{inp['index']}] {label} (type={inp['type']}, name={inp.get('name', '')})")

        text = info.get("bodyText", "")
        if text:
            parts.append(f"Page Content (first 1000 chars):\n{text[:1000]}")

        return "\n".join(parts)

    def _format_actions_taken(self, actions: List[Dict]) -> str:
        """Format action history for LLM."""
        if not actions:
            return "No actions taken yet."
        lines = []
        for a in actions:
            status = "✅" if a.get("result") else "❌"
            skipped = " (SKIPPED - permission denied)" if a.get("skipped") else ""
            url = f" → {a['url']}" if a.get("url") else ""
            lines.append(f"Step {a['step']}: {status} {a['action']}{url}{skipped}")
        return "\n".join(lines)


# Global instance
web_agent_service = WebAgentService()
