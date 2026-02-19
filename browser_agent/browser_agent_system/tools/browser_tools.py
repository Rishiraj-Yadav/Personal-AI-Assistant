"""
Browser Tools for the Browser Agent
All Playwright-based browser interactions are defined here.
Each tool returns a string result that goes back to the LLM.
"""

from __future__ import annotations
import asyncio
import base64
from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

# ─── Global browser state ───────────────────────────────────────────────────

_playwright = None
_browser: Optional[Browser] = None
_context: Optional[BrowserContext] = None
_page: Optional[Page] = None


async def _get_page() -> Page:
    """Get (or lazily create) the shared browser page."""
    global _playwright, _browser, _context, _page

    if _page is None:
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(headless=False)
        _context = await _browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )
        _page = await _context.new_page()
        print("[Browser] Launched Chromium browser.")

    return _page


async def close_browser():
    """Close the browser and clean up."""
    global _playwright, _browser, _context, _page
    if _browser:
        await _browser.close()
    if _playwright:
        await _playwright.stop()
    _playwright = _browser = _context = _page = None
    return "Browser closed."


# ─── Tool Implementations ────────────────────────────────────────────────────

async def navigate(url: str) -> str:
    """Navigate to a URL and return page title + URL."""
    try:
        page = await _get_page()
        response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        title = await page.title()
        status = response.status if response else "unknown"
        return f"Navigated to: {url}\nPage title: {title}\nHTTP status: {status}"
    except Exception as e:
        return f"Navigation error: {e}"


async def click(selector: str, description: str = "") -> str:
    """Click an element by CSS selector or text."""
    try:
        page = await _get_page()
        # Try CSS selector first, then text-based
        try:
            await page.click(selector, timeout=5000)
        except Exception:
            await page.click(f"text={selector}", timeout=5000)
        label = description or selector
        return f"Clicked: {label}"
    except Exception as e:
        return f"Click error on '{selector}': {e}"


async def type_text(selector: str, text: str, clear_first: bool = True) -> str:
    """Type text into an input field."""
    try:
        page = await _get_page()
        await page.click(selector, timeout=5000)
        if clear_first:
            await page.fill(selector, "")
        await page.type(selector, text, delay=50)
        return f"Typed '{text}' into '{selector}'"
    except Exception as e:
        return f"Type error: {e}"


async def get_text(selector: str = "body") -> str:
    """Get visible text content from an element (default: whole page)."""
    try:
        page = await _get_page()
        element = await page.query_selector(selector)
        if not element:
            return f"No element found for selector: {selector}"
        text = await element.inner_text()
        # Truncate to avoid huge LLM context
        if len(text) > 6000:
            text = text[:6000] + "\n...[truncated]"
        return text
    except Exception as e:
        return f"Get text error: {e}"


async def get_page_info() -> str:
    """Get current page URL, title, and a summary of interactive elements."""
    try:
        page = await _get_page()
        url = page.url
        title = await page.title()

        # Find key interactive elements
        inputs = await page.query_selector_all("input, textarea, select")
        buttons = await page.query_selector_all("button, [role='button'], a[href]")
        links = await page.query_selector_all("a[href]")

        input_info = []
        for el in inputs[:10]:
            name = await el.get_attribute("name") or await el.get_attribute("id") or await el.get_attribute("placeholder") or "unnamed"
            el_type = await el.get_attribute("type") or "text"
            input_info.append(f"  [{el_type}] name='{name}'")

        button_info = []
        for el in buttons[:10]:
            text = (await el.inner_text()).strip()[:50]
            if text:
                button_info.append(f"  '{text}'")

        result = f"URL: {url}\nTitle: {title}\n"
        result += f"Inputs ({len(inputs)}):\n" + "\n".join(input_info[:10]) + "\n" if input_info else ""
        result += f"Buttons/Links ({len(buttons)}):\n" + "\n".join(button_info[:10]) + "\n" if button_info else ""
        return result
    except Exception as e:
        return f"Page info error: {e}"


async def screenshot(filename: str = "") -> str:
    """Take a screenshot of the current page. Returns base64 if no filename given."""
    try:
        page = await _get_page()
        if filename:
            await page.screenshot(path=filename, full_page=False)
            return f"Screenshot saved to: {filename}"
        else:
            img_bytes = await page.screenshot(full_page=False)
            b64 = base64.b64encode(img_bytes).decode()
            return f"data:image/png;base64,{b64}"
    except Exception as e:
        return f"Screenshot error: {e}"


async def scroll(direction: str = "down", amount: int = 300) -> str:
    """Scroll the page up or down."""
    try:
        page = await _get_page()
        delta = amount if direction == "down" else -amount
        await page.evaluate(f"window.scrollBy(0, {delta})")
        return f"Scrolled {direction} by {amount}px"
    except Exception as e:
        return f"Scroll error: {e}"


async def wait_for_element(selector: str, timeout: int = 10000) -> str:
    """Wait for an element to appear on the page."""
    try:
        page = await _get_page()
        await page.wait_for_selector(selector, timeout=timeout)
        return f"Element '{selector}' is now visible."
    except Exception as e:
        return f"Wait error: element '{selector}' not found within {timeout}ms. {e}"


async def extract_links() -> str:
    """Extract all links from the current page."""
    try:
        page = await _get_page()
        links = await page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href]'))
                .map(a => ({ text: a.innerText.trim(), href: a.href }))
                .filter(l => l.href && l.href.startsWith('http'))
                .slice(0, 30)
        """)
        if not links:
            return "No links found on the page."
        lines = [f"  {l['text'][:60] or '(no text)'} → {l['href']}" for l in links]
        return f"Links found ({len(links)}):\n" + "\n".join(lines)
    except Exception as e:
        return f"Extract links error: {e}"


async def execute_script(script: str) -> str:
    """Run JavaScript in the browser page context."""
    try:
        page = await _get_page()
        result = await page.evaluate(script)
        return f"Script result: {result}"
    except Exception as e:
        return f"Script error: {e}"


async def select_option(selector: str, value: str) -> str:
    """Select an option from a <select> dropdown."""
    try:
        page = await _get_page()
        await page.select_option(selector, value=value)
        return f"Selected '{value}' in '{selector}'"
    except Exception as e:
        return f"Select error: {e}"


async def press_key(key: str) -> str:
    """Press a keyboard key (e.g. Enter, Tab, Escape, ArrowDown)."""
    try:
        page = await _get_page()
        await page.keyboard.press(key)
        return f"Pressed key: {key}"
    except Exception as e:
        return f"Key press error: {e}"


async def go_back() -> str:
    """Go back to the previous page."""
    try:
        page = await _get_page()
        await page.go_back(wait_until="domcontentloaded")
        title = await page.title()
        return f"Went back. Current page: {title}"
    except Exception as e:
        return f"Go back error: {e}"


async def get_html(selector: str = "body") -> str:
    """Get the raw HTML of an element (useful for scraping structured data)."""
    try:
        page = await _get_page()
        html = await page.inner_html(selector)
        if len(html) > 8000:
            html = html[:8000] + "\n...[truncated]"
        return html
    except Exception as e:
        return f"Get HTML error: {e}"
