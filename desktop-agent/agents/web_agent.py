"""
Web Agent — Quick headless web lookups, search, downloads
No browser needed — uses HTTP requests and DuckDuckGo.
"""
import concurrent.futures
import json
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


_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _fetch_page_text(url: str, max_chars: int = 6000) -> Dict[str, Any]:
    """
    Internal helper: fetch a URL and return structured content.
    Used by both read_full_page and parallel_read_pages.
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": _BROWSER_UA})
        resp.raise_for_status()
    except Exception as e:
        return {"url": url, "error": str(e)}

    title = ""
    text = ""
    tables = []

    if HAS_BS4:
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        text = soup.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        # Extract tables
        raw_tables = soup.find_all("table")
        for tbl in raw_tables[:5]:
            rows = tbl.find_all("tr")
            if not rows:
                continue
            header_cells = rows[0].find_all(["th", "td"])
            headers = [c.get_text(strip=True) for c in header_cells]
            data_rows = []
            for row in rows[1:101]:
                cells = row.find_all(["td", "th"])
                cell_texts = [c.get_text(strip=True) for c in cells]
                if headers and len(cell_texts) == len(headers):
                    data_rows.append(dict(zip(headers, cell_texts)))
                else:
                    data_rows.append(cell_texts)
            tables.append({"headers": headers, "rows": data_rows, "row_count": len(data_rows)})
    else:
        text = re.sub(r"<[^>]+>", "", resp.text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

    total_chars = len(text)
    return {
        "url": url,
        "title": title,
        "text": text[:max_chars],
        "tables": tables,
        "total_chars": total_chars,
        "truncated": total_chars > max_chars,
    }


class WebAgent(BaseAgent):
    """Agent for quick headless web lookups"""

    def __init__(self):
        super().__init__(
            name="web_agent",
            description=(
                "Quick web searches, fetch web pages, download files, get current time — no browser needed. "
                "Use internet_search for any live information question."
            ),
        )

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            # ── Original tools ──────────────────────────────────────────
            {
                "name": "web_search",
                "description": "Search the web using DuckDuckGo and return top results. Good for finding information, news, etc.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "max_results": {"type": "integer", "description": "Number of results (default: 5, max: 10)"},
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
                        "url": {"type": "string", "description": "URL to fetch"},
                        "max_chars": {"type": "integer", "description": "Maximum characters to return (default: 3000)"},
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
                        "url": {"type": "string", "description": "URL to download from"},
                        "save_path": {"type": "string", "description": "Local path to save the file. Default: Downloads folder."},
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
                    "properties": {"url": {"type": "string", "description": "URL to check"}},
                    "required": ["url"],
                },
            },
            # ── New fast internet tools ─────────────────────────────────
            {
                "name": "internet_search",
                "description": (
                    "Search the internet for any query and return top results with titles, URLs, and summaries. "
                    "Use this FIRST for any question that needs current or live information. "
                    "Works for news, prices, people, events, facts — anything."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "max_results": {
                            "type": "integer",
                            "description": "Number of results (default: 8, max: 15)",
                        },
                        "region": {
                            "type": "string",
                            "description": "Region for results: 'in-en' (India, default), 'us-en', 'uk-en', 'wt-wt' (worldwide)",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "read_full_page",
                "description": (
                    "Fetch and read the complete text content of any webpage. "
                    "Use after internet_search to read the full article, product page, or data source. "
                    "Also extracts all HTML tables as structured JSON automatically."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to fetch and read"},
                        "max_chars": {"type": "integer", "description": "Max characters to return (default: 6000)"},
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "get_news",
                "description": (
                    "Get the latest news articles on any topic from the last 24-48 hours. "
                    "Returns headlines, source names, publication dates, and article summaries."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "description": "News topic to search"},
                        "max_results": {"type": "integer", "description": "Number of articles (default: 5)"},
                    },
                    "required": ["topic"],
                },
            },
            {
                "name": "wikipedia_lookup",
                "description": (
                    "Look up any topic on Wikipedia and get a structured summary. "
                    "Best for definitions, background information, historical facts, biographies."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Topic to look up on Wikipedia"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "scrape_page_tables",
                "description": (
                    "Scrape all HTML tables from any webpage and return them as clean structured JSON. "
                    "Perfect for: flight prices, cricket scoreboards, stock screeners, comparison tables, "
                    "sports stats, e-commerce listings."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to scrape tables from"},
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "parallel_read_pages",
                "description": (
                    "Read multiple web pages simultaneously in parallel. "
                    "Use when you need to compare information from several sources at once. "
                    "Faster than reading pages one by one."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "urls": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of URLs to read (max 5)",
                        },
                    },
                    "required": ["urls"],
                },
            },
        ]

    def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        handlers = {
            # Original tools
            "web_search": lambda: self._search(args.get("query", ""), args.get("max_results", 5)),
            "fetch_webpage": lambda: self._fetch(args.get("url", ""), args.get("max_chars", 3000)),
            "download_file": lambda: self._download(args.get("url", ""), args.get("save_path")),
            "get_current_datetime": lambda: self._get_datetime(),
            "check_website": lambda: self._check_site(args.get("url", "")),
            # New tools
            "internet_search": lambda: self._internet_search(
                args.get("query", ""),
                args.get("max_results", 8),
                args.get("region", "in-en"),
            ),
            "read_full_page": lambda: self._read_full_page(
                args.get("url", ""),
                args.get("max_chars", 6000),
            ),
            "get_news": lambda: self._get_news(
                args.get("topic", ""),
                args.get("max_results", 5),
            ),
            "wikipedia_lookup": lambda: self._wikipedia_lookup(args.get("query", "")),
            "scrape_page_tables": lambda: self._scrape_page_tables(args.get("url", "")),
            "parallel_read_pages": lambda: self._parallel_read_pages(args.get("urls", [])),
        }
        handler = handlers.get(tool_name)
        if handler:
            return handler()
        return self._error(f"Unknown tool: {tool_name}")

    # ── Original implementations ────────────────────────────────────

    def _search(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        if not HAS_DDG:
            return self._error("duckduckgo-search not installed. Run: pip install duckduckgo-search")
        try:
            max_results = min(max_results, 10)
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
            formatted = [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", r.get("link", "")),
                    "snippet": r.get("body", r.get("snippet", "")),
                }
                for r in results
            ]
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
            resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 DesktopAgent/2.0"})
            resp.raise_for_status()
            if HAS_BS4:
                soup = BeautifulSoup(resp.text, "html.parser")
                for tag in soup(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                text = soup.get_text(separator="\n", strip=True)
            else:
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

    # ── New tool implementations ────────────────────────────────────

    def _internet_search(self, query: str, max_results: int = 8, region: str = "in-en") -> Dict[str, Any]:
        if not HAS_DDG:
            return self._error("duckduckgo-search not installed. Run: pip install duckduckgo-search")
        try:
            max_results = min(max_results, 15)
            with DDGS() as ddgs:
                raw = list(ddgs.text(query, region=region, max_results=max_results))
            results = [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", r.get("link", "")),
                    "snippet": r.get("body", r.get("snippet", ""))[:400],
                }
                for r in raw
            ]
            return self._success(
                {
                    "query": query,
                    "region": region,
                    "count": len(results),
                    "results": results,
                    "tip": "Call read_full_page on the most relevant URL to get full content.",
                },
                f"Found {len(results)} results for '{query}'",
            )
        except Exception as e:
            return self._error(f"internet_search failed: {e}")

    def _read_full_page(self, url: str, max_chars: int = 6000) -> Dict[str, Any]:
        if not HAS_REQUESTS:
            return self._error("requests not installed")
        try:
            data = _fetch_page_text(url, max_chars=max_chars)
            if "error" in data:
                return self._error(f"Failed to fetch {url}: {data['error']}")
            return self._success(data, f"Read {data.get('total_chars', 0)} chars from {url}")
        except Exception as e:
            return self._error(f"read_full_page failed: {e}")

    def _get_news(self, topic: str, max_results: int = 5) -> Dict[str, Any]:
        if not HAS_DDG:
            return self._error("duckduckgo-search not installed")
        try:
            max_results = min(max_results, 15)
            with DDGS() as ddgs:
                raw = list(ddgs.news(topic, max_results=max_results))
            articles = [
                {
                    "title": a.get("title", ""),
                    "url": a.get("url", a.get("link", "")),
                    "source": a.get("source", a.get("publisher", "")),
                    "date": a.get("date", ""),
                    "body": a.get("body", a.get("excerpt", ""))[:300],
                }
                for a in raw
            ]
            return self._success(
                {"topic": topic, "count": len(articles), "articles": articles},
                f"Found {len(articles)} news articles for '{topic}'",
            )
        except Exception as e:
            return self._error(f"get_news failed: {e}")

    def _wikipedia_lookup(self, query: str) -> Dict[str, Any]:
        if not HAS_REQUESTS:
            return self._error("requests not installed")
        try:
            base = "https://en.wikipedia.org/w/api.php"
            # Step 1: search for page
            search_resp = requests.get(
                base,
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "format": "json",
                    "srlimit": 1,
                },
                timeout=10,
                headers={"User-Agent": _BROWSER_UA},
            )
            search_resp.raise_for_status()
            search_data = search_resp.json()
            search_results = search_data.get("query", {}).get("search", [])
            if not search_results:
                return self._error(f"No Wikipedia article found for '{query}'")

            pageid = search_results[0]["pageid"]
            page_title = search_results[0]["title"]

            # Step 2: get extract
            extract_resp = requests.get(
                base,
                params={
                    "action": "query",
                    "pageids": pageid,
                    "prop": "extracts",
                    "exintro": True,
                    "exsentences": 8,
                    "format": "json",
                    "explaintext": True,
                },
                timeout=10,
                headers={"User-Agent": _BROWSER_UA},
            )
            extract_resp.raise_for_status()
            extract_data = extract_resp.json()
            page = extract_data.get("query", {}).get("pages", {}).get(str(pageid), {})
            raw_extract = page.get("extract", "")
            # Strip any residual HTML
            clean_text = re.sub(r"<[^>]+>", "", raw_extract).strip()
            wiki_url = f"https://en.wikipedia.org/wiki/{page_title.replace(' ', '_')}"

            return self._success(
                {
                    "title": page_title,
                    "summary": clean_text,
                    "url": wiki_url,
                },
                f"Wikipedia: {page_title}",
            )
        except Exception as e:
            return self._error(f"wikipedia_lookup failed: {e}")

    def _scrape_page_tables(self, url: str) -> Dict[str, Any]:
        if not HAS_REQUESTS:
            return self._error("requests not installed")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            resp = requests.get(url, timeout=15, headers={"User-Agent": _BROWSER_UA})
            resp.raise_for_status()
            if not HAS_BS4:
                return self._error("BeautifulSoup not installed. Run: pip install beautifulsoup4")

            soup = BeautifulSoup(resp.text, "html.parser")

            # Extract tables
            raw_tables = soup.find_all("table")
            tables = []
            for tbl in raw_tables[:10]:
                rows = tbl.find_all("tr")
                if not rows:
                    continue
                header_cells = rows[0].find_all(["th", "td"])
                headers = [c.get_text(strip=True) for c in header_cells]
                data_rows = []
                for row in rows[1:101]:
                    cells = row.find_all(["td", "th"])
                    cell_texts = [c.get_text(strip=True) for c in cells]
                    if headers and len(cell_texts) == len(headers):
                        data_rows.append(dict(zip(headers, cell_texts)))
                    else:
                        data_rows.append(cell_texts)
                tables.append({"headers": headers, "rows": data_rows, "row_count": len(data_rows)})

            # Extract JSON-LD structured data
            json_ld = []
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "")
                    json_ld.append(data)
                except Exception:
                    pass

            return self._success(
                {
                    "url": url,
                    "table_count": len(tables),
                    "tables": tables,
                    "json_ld": json_ld[:5],
                },
                f"Scraped {len(tables)} tables from {url}",
            )
        except Exception as e:
            return self._error(f"scrape_page_tables failed: {e}")

    def _parallel_read_pages(self, urls: List[str]) -> Dict[str, Any]:
        if not HAS_REQUESTS:
            return self._error("requests not installed")
        if not urls:
            return self._error("No URLs provided")
        urls = urls[:5]  # cap at 5

        def _read_one(url: str) -> Dict[str, Any]:
            try:
                return _fetch_page_text(url, max_chars=3000)
            except Exception as e:
                return {"url": url, "error": str(e)}

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                results = list(executor.map(_read_one, urls))
            return self._success(
                {"urls_read": len(results), "results": results},
                f"Read {len(results)} pages in parallel",
            )
        except Exception as e:
            return self._error(f"parallel_read_pages failed: {e}")


# Global instance
web_agent = WebAgent()
