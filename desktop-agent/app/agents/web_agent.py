"""
Web Agent — Quick headless web lookups, search, downloads
No browser needed — uses HTTP requests.
"""
import os
import re
from typing import Dict, Any, List
from datetime import datetime
from loguru import logger
from agents.base_agent import BaseAgent

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    from duckduckgo_search import DDGS
    HAS_DDG = True
except ImportError:
    HAS_DDG = False


class WebAgent(BaseAgent):
    """Agent for quick headless web lookups"""

    def __init__(self):
        super().__init__(
            name="web_agent",
            description="Quick web searches, fetch web pages, download files, get current time — no browser needed",
        )

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "web_search",
                "description": "Search the web using DuckDuckGo and return top results. Good for finding information, news, etc.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Number of results (default: 5, max: 10)",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "fetch_webpage",
                "description": "Fetch a webpage URL and extract its text content (no JavaScript)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL to fetch",
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "Maximum characters to return (default: 3000)",
                        },
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "download_file",
                "description": "Download a file from a URL to the local disk",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL to download from",
                        },
                        "save_path": {
                            "type": "string",
                            "description": "Local path to save the file. Default: Downloads folder.",
                        },
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "get_current_datetime",
                "description": "Get the current date and time",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "check_website",
                "description": "Check if a website is up and reachable",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL to check",
                        },
                    },
                    "required": ["url"],
                },
            },
        ]

    def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        handlers = {
            "web_search": lambda: self._search(
                args.get("query", ""), args.get("max_results", 5)
            ),
            "fetch_webpage": lambda: self._fetch(
                args.get("url", ""), args.get("max_chars", 3000)
            ),
            "download_file": lambda: self._download(
                args.get("url", ""), args.get("save_path")
            ),
            "get_current_datetime": lambda: self._get_datetime(),
            "check_website": lambda: self._check_site(args.get("url", "")),
        }
        handler = handlers.get(tool_name)
        if handler:
            return handler()
        return self._error(f"Unknown tool: {tool_name}")

    def _search(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        if not HAS_DDG:
            return self._error(
                "duckduckgo-search not installed. Run: pip install duckduckgo-search"
            )
        try:
            max_results = min(max_results, 10)
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))

            formatted = []
            for r in results:
                formatted.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", r.get("link", "")),
                    "snippet": r.get("body", r.get("snippet", "")),
                })
            return self._success(
                {"query": query, "results": formatted, "count": len(formatted)},
                f"Found {len(formatted)} results for '{query}'",
            )
        except Exception as e:
            return self._error(f"Search failed: {e}")

    def _fetch(self, url: str, max_chars: int = 3000) -> Dict[str, Any]:
        if not HAS_REQUESTS:
            return self._error("requests not installed")

        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            resp = requests.get(
                url,
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0 DesktopAgent/2.0"},
            )
            resp.raise_for_status()

            if HAS_BS4:
                soup = BeautifulSoup(resp.text, "html.parser")
                # Remove scripts and styles
                for tag in soup(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                text = soup.get_text(separator="\n", strip=True)
            else:
                # Basic HTML stripping
                text = re.sub(r"<[^>]+>", "", resp.text)

            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            return self._success(
                {
                    "url": url,
                    "title": soup.title.string if HAS_BS4 and soup.title else "",
                    "content": text[:max_chars],
                    "total_chars": len(text),
                    "truncated": len(text) > max_chars,
                },
                f"Fetched {url}",
            )
        except Exception as e:
            return self._error(f"Failed to fetch {url}: {e}")

    def _download(self, url: str, save_path: str = None) -> Dict[str, Any]:
        if not HAS_REQUESTS:
            return self._error("requests not installed")

        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        if not save_path:
            filename = url.split("/")[-1].split("?")[0] or "download"
            save_path = os.path.join(os.path.expanduser("~/Downloads"), filename)

        try:
            resp = requests.get(url, stream=True, timeout=60)
            resp.raise_for_status()

            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            total = 0
            with open(save_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
                    total += len(chunk)

            return self._success(
                {
                    "url": url,
                    "saved_to": save_path,
                    "size_bytes": total,
                    "size": f"{total / (1024*1024):.1f} MB" if total > 1024*1024 else f"{total / 1024:.1f} KB",
                },
                f"Downloaded to {save_path}",
            )
        except Exception as e:
            return self._error(f"Download failed: {e}")

    def _get_datetime(self) -> Dict[str, Any]:
        now = datetime.now()
        return self._success(
            {
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M:%S"),
                "day": now.strftime("%A"),
                "full": now.strftime("%A, %B %d, %Y at %I:%M %p"),
            },
            f"Current time: {now.strftime('%I:%M %p on %A, %B %d, %Y')}",
        )

    def _check_site(self, url: str) -> Dict[str, Any]:
        if not HAS_REQUESTS:
            return self._error("requests not installed")

        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            resp = requests.head(url, timeout=10, allow_redirects=True)
            return self._success(
                {
                    "url": url,
                    "is_up": True,
                    "status_code": resp.status_code,
                    "response_time_ms": round(resp.elapsed.total_seconds() * 1000),
                },
                f"{url} is UP (status {resp.status_code})",
            )
        except requests.ConnectionError:
            return self._success(
                {"url": url, "is_up": False, "error": "Connection refused"},
                f"{url} is DOWN",
            )
        except Exception as e:
            return self._error(f"Check failed: {e}")


# Global instance
web_agent = WebAgent()
