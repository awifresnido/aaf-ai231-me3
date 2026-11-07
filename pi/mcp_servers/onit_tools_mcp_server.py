"""Lean OnIt-compatible knowledge tools for the voice agent (MCP stdio).

Two tools, matching OnIt's `search` and `fetch_content` names and argument
shapes so the 4-tier router can hand them to the escalation LLM unchanged.
Document/file tools (local_search, search_document, read_file, grep, …) are
intentionally omitted from this first voice profile — add them later.

Backends are key-free and dependency-light (only stdlib + httpx, both already
present in the Pi venv):

  search        — DuckDuckGo HTML endpoint, parsed with a small regex
  fetch_content — urllib + stdlib HTMLParser text extraction

Run: .venv/bin/python onit_tools_mcp_server.py   (stdio transport)
"""
from __future__ import annotations

import html as html_mod
import json
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from mcp.server.mcpserver import MCPServer

server = MCPServer(
    name="onit-tools",
    version="0.1.0",
    instructions=(
        "Knowledge tools for the voice agent: web search and URL fetching. "
        "Call one tool per user request; both return a short dict safe to "
        "speak back to the user."
    ),
)

MAX_RESULTS = 5
MAX_FETCH_CHARS = 6000
_UA = {"User-Agent": "me3-voice-agent/0.1 (+https://github.com/awifresnido/aaf-ai231-me3)"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "head"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "head") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _strip_tags(fragment):
    return html_mod.unescape(re.sub(r"<[^>]+>", " ", fragment))


def _clean(fragment):
    return re.sub(r"\s+", " ", _strip_tags(fragment)).strip()


def _real_url(href):
    # DuckDuckGo wraps the destination in a /l/?uddg=... redirect.
    match = re.search(r"uddg=([^&]+)", href)
    return urllib.parse.unquote(match.group(1)) if match else href


def _search_results(query, limit):
    """Return a list of {title, url, snippet} dicts, empty on failure."""
    try:
        from ddgs import DDGS
        rows = DDGS().news(query, max_results=limit) if False else DDGS().text(query, max_results=limit)
        return [{"title": (r.get("title") or "").strip(),
                 "url": r.get("href") or "",
                 "snippet": (r.get("body") or "").strip()} for r in rows if r.get("href")]
    except Exception:
        return []


def _instant_answers(query):
    """Key-free DuckDuckGo Instant Answer API fallback."""
    url = ("https://api.duckduckgo.com/?format=json&no_html=1&skip_disambig=1&q="
           + urllib.parse.quote(query))
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return []
    out = []
    if data.get("AbstractText"):
        out.append({"title": "DuckDuckGo Abstract", "url": data.get("AbstractURL") or "",
                    "snippet": data["AbstractText"]})
    if data.get("Answer"):
        out.append({"title": "DuckDuckGo Answer", "url": "", "snippet": str(data["Answer"])})
    for topic in (data.get("RelatedTopics") or [])[:limit_default()]:
        if isinstance(topic, dict) and topic.get("Text"):
            out.append({"title": topic.get("Text", "")[:80], "url": topic.get("FirstURL") or "",
                        "snippet": topic.get("Text", "")})
    return out[:5]


def limit_default():
    return 5


@server.tool(
    name="search",
    description=(
        "Search the web for current facts, news, or general information. "
        "Returns a list of results with title, URL, and snippet. No API key."
    ),
)
def search(query: str = "", type: str = "web", max_results: int = MAX_RESULTS) -> dict:
    query = (query or "").strip()
    if not query:
        return {"ok": False, "spoken": "I need something to search for.", "results": []}
    limit = max(1, min(int(max_results or MAX_RESULTS), 10))
    results = _search_results(query, limit)
    if not results:
        results = _instant_answers(query)
    if not results:
        return {"ok": True, "spoken": "I couldn't find any web results for that.", "results": []}
    return {"ok": True, "spoken": f"Found {len(results)} results.", "results": results}


@server.tool(
    name="fetch_content",
    description=(
        "Fetch a URL and extract its readable text, stripping HTML. "
        "Use to read a page the user names, or a result URL from search."
    ),
)
def fetch_content(url: str = "", max_chars: int = MAX_FETCH_CHARS) -> dict:
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return {"ok": False, "spoken": "That doesn't look like a web address."}
    cap = max(500, min(int(max_chars or MAX_FETCH_CHARS), 20000))
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            content_type = resp.headers.get("Content-Type", "")
        decoded = raw.decode("utf-8", "replace")
        title_match = re.search(r"<title[^>]*>(.*?)</title>", decoded, re.I | re.S)
        title = _clean(title_match.group(1)) if title_match else ""
        if "html" in content_type.lower() or "<" in decoded[:500]:
            extractor = _TextExtractor()
            extractor.feed(decoded)
            text = " ".join(extractor.parts)
        else:
            text = decoded
        text = re.sub(r"\s+", " ", text).strip()
        truncated = text[:cap]
        return {"ok": True, "spoken": f"Read {len(truncated)} characters.",
                "title": title, "text": truncated}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "spoken": "I couldn't fetch that page.", "error": exc.__class__.__name__}


if __name__ == "__main__":
    server.run("stdio")
