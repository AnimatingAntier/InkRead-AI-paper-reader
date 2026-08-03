from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Iterable

import settings_store

USER_AGENT = "InkRead/1.0 academic reading assistant"


def _json_get(url: str, timeout: int = 16) -> dict:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _crossref(query: str, limit: int) -> list[dict]:
    params = urllib.parse.urlencode({"query.bibliographic": query, "rows": limit})
    data = _json_get(f"https://api.crossref.org/works?{params}")
    results = []
    for item in data.get("message", {}).get("items", []):
        title = (item.get("title") or [""])[0]
        url = item.get("URL") or ""
        abstract = item.get("abstract") or item.get("publisher") or ""
        if title and url:
            results.append({
                "source_type": "web_search",
                "title": title,
                "url": url,
                "content": str(abstract)[:900],
                "provider": "Crossref",
                "relevance_score": 0.8,
            })
    return results


def _semantic_scholar(query: str, limit: int) -> list[dict]:
    params = urllib.parse.urlencode({
        "query": query,
        "limit": limit,
        "fields": "title,abstract,url,year,citationCount,authors",
    })
    data = _json_get(f"https://api.semanticscholar.org/graph/v1/paper/search?{params}")
    results = []
    for item in data.get("data", []):
        if not item.get("url"):
            continue
        authors = ", ".join(author.get("name", "") for author in item.get("authors", [])[:4])
        summary = f"{authors} · {item.get('year') or 'n.d.'} · 引用 {item.get('citationCount', 0)}。"
        if item.get("abstract"):
            summary += " " + item["abstract"]
        results.append({
            "source_type": "web_search",
            "title": item.get("title") or "Untitled",
            "url": item["url"],
            "content": summary[:1100],
            "provider": "Semantic Scholar",
            "relevance_score": 0.92,
        })
    return results


def _serpapi(query: str, limit: int, api_key: str) -> list[dict]:
    from serpapi import GoogleSearch

    response = GoogleSearch({
        "engine": "google_scholar",
        "q": query,
        "api_key": api_key,
        "num": limit,
        "hl": "zh-cn",
    }).get_dict()
    results = []
    for item in response.get("organic_results", [])[:limit]:
        link = item.get("link") or (item.get("resources") or [{}])[0].get("link")
        if not link:
            continue
        results.append({
            "source_type": "web_search",
            "title": item.get("title") or "Untitled",
            "url": link,
            "content": item.get("snippet") or item.get("publication_info", {}).get("summary", ""),
            "provider": "Google Scholar · SerpApi",
            "relevance_score": 0.9,
        })
    return results


def academic_search(query: str, limit: int = 6) -> tuple[list[dict], list[str]]:
    settings = settings_store.load()
    results: list[dict] = []
    errors: list[str] = []
    providers: Iterable = (
        lambda: _semantic_scholar(query, limit),
        lambda: _crossref(query, limit),
    )
    if settings.get("serpapi_key"):
        providers = (lambda: _serpapi(query, limit, settings["serpapi_key"]), *providers)
    for provider in providers:
        try:
            results.extend(provider())
        except Exception as exc:
            errors.append(str(exc))
        if len(results) >= limit:
            break
    unique: list[dict] = []
    seen: set[str] = set()
    for item in results:
        key = item.get("url", "").lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:limit], errors
