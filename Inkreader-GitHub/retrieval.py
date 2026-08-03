from __future__ import annotations

import math
import re
from collections import Counter

from document_store import get_document


def tokenize(text: str) -> list[str]:
    latin = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{1,}", text.lower())
    cjk_runs = re.findall(r"[\u3400-\u9fff]+", text)
    cjk: list[str] = []
    for run in cjk_runs:
        cjk.extend(run[i:i + 2] for i in range(max(1, len(run) - 1)))
    return latin + cjk


def retrieve(document_ids: list[str], query: str, limit: int = 8) -> list[dict]:
    query_tokens = tokenize(query)
    if not query_tokens:
        query_tokens = tokenize("摘要 方法 结论 实验")
    query_counts = Counter(query_tokens)
    candidates: list[dict] = []
    for document_id in document_ids:
        document = get_document(document_id)
        sections = document.get("sections") or [{
            "title": "全文", "text": document.get("text", ""), "order": 0
        }]
        for section in sections:
            text = section.get("text", "")
            tokens = tokenize(section.get("title", "") + "\n" + text)
            if not tokens:
                continue
            counts = Counter(tokens)
            overlap = sum(min(counts[token], count) for token, count in query_counts.items())
            density = overlap / math.sqrt(max(1, len(tokens)))
            title_bonus = sum(
                1.4 for token in query_counts if token in tokenize(section.get("title", ""))
            )
            score = density + title_bonus
            candidates.append({
                "source_type": "paper_internal",
                "document_id": document_id,
                "document_title": document["title"],
                "section": section.get("title") or "全文",
                "page": section.get("page"),
                "content": text[:6000],
                "relevance_score": round(score, 4),
            })
    candidates.sort(key=lambda item: item["relevance_score"], reverse=True)
    selected = candidates[:limit]
    if selected and all(item["relevance_score"] == 0 for item in selected):
        selected = candidates[: min(3, len(candidates))]
    return selected
