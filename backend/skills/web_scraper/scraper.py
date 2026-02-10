#!/usr/bin/env python3
"""
Web Scraper Skill
Scrapes content from web pages using Playwright
"""
import os
import json
import sys
import asyncio
from playwright.async_api import async_playwright


async def scrape_page(url: str, selector: str = None):
    """
    Scrape content from a web page
    
    Args:
        url: URL to scrape
        selector: Optional CSS selector for specific content
        
    Returns:
        Dict with scraped content
    """
    async with async_playwright() as p:
        # Launch browser in headless mode
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        try:
            # Navigate to URL
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            
            # Wait a moment for dynamic content
            await page.wait_for_timeout(1000)
            
            # Extract content
            result = {
                "url": url,
                "title": await page.title(),
            }
            
            # Get meta description
            meta_desc = await page.query_selector('meta[name="description"]')
            if meta_desc:
                result["description"] = await meta_desc.get_attribute("content")
            
            # Get specific content if selector provided
            if selector:
                elements = await page.query_selector_all(selector)
                result["selected_content"] = []
                for element in elements[:10]:  # Limit to 10 elements
                    text = await element.inner_text()
                    result["selected_content"].append(text.strip())
            else:
                # Get body text
                body = await page.query_selector("body")
                if body:
                    body_text = await body.inner_text()
                    # Limit to first 5000 characters
                    result["content"] = body_text[:5000].strip()
            
            # Get headings
            headings = await page.query_selector_all("h1, h2, h3")
            result["headings"] = []
            for heading in headings[:10]:  # Limit to 10 headings
                text = await heading.inner_text()
                tag = await heading.evaluate("el => el.tagName")
                result["headings"].append({
                    "level": tag.lower(),
                    "text": text.strip()
                })
            
            return result
            
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
        
        selector = params.get("selector")
        
        # Run scraper
        result = asyncio.run(scrape_page(url, selector))
        
        # Output result as JSON
        print(json.dumps(result, indent=2))
        
    except Exception as e:
        print(json.dumps({
            "error": str(e)
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()