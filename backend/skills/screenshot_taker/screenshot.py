#!/usr/bin/env python3
"""
Screenshot Taker Skill
Captures screenshots of web pages using Playwright
"""
import os
import json
import sys
import asyncio
import base64
from playwright.async_api import async_playwright


async def take_screenshot(url: str, full_page: bool = False, width: int = 1280, height: int = 720):
    """
    Take a screenshot of a web page
    
    Args:
        url: URL to screenshot
        full_page: Capture full page or just viewport
        width: Viewport width
        height: Viewport height
        
    Returns:
        Dict with screenshot data
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        # Set viewport size
        context = await browser.new_context(
            viewport={"width": width, "height": height}
        )
        page = await context.new_page()
        
        try:
            # Navigate to URL
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            
            # Wait for page to stabilize
            await page.wait_for_timeout(2000)
            
            # Take screenshot
            screenshot_bytes = await page.screenshot(
                full_page=full_page,
                type="png"
            )
            
            # Get page info
            title = await page.title()
            final_url = page.url
            
            # Encode screenshot as base64
            screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
            
            return {
                "url": url,
                "final_url": final_url,
                "title": title,
                "screenshot_base64": screenshot_base64,
                "viewport": {
                    "width": width,
                    "height": height
                },
                "full_page": full_page,
                "size_bytes": len(screenshot_bytes),
                "message": f"Screenshot captured successfully ({len(screenshot_bytes)} bytes)"
            }
            
        finally:
            await browser.close()


def main():
    """Main entry point"""
    try:
        # Get parameters from environment
        params_json = os.environ.get("SKILL_PARAMS", "{}")
        params = json.loads(params_json)
        
        url = params.get("url")
        if not url:
            print(json.dumps({
                "error": "Missing required parameter: url"
            }))
            sys.exit(1)
        
        full_page = params.get("full_page", False)
        width = params.get("width", 1280)
        height = params.get("height", 720)
        
        # Take screenshot
        result = asyncio.run(take_screenshot(url, full_page, width, height))
        
        # Output result as JSON
        print(json.dumps(result, indent=2))
        
    except Exception as e:
        print(json.dumps({
            "error": str(e)
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()