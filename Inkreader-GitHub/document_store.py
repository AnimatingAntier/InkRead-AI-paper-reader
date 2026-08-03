from __future__ import annotations

import hashlib
import base64
import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

import fitz

from config import DOCUMENT_DIR, MANIFEST_FILE

LOCK = RLock()
SUPPORTED = {".pdf": "pdf", ".md": "markdown", ".markdown": "markdown"}


def _read_manifest() -> list[dict]:
    if not MANIFEST_FILE.is_file():
        return []
    try:
        return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _write_manifest(items: list[dict]) -> None:
    MANIFEST_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _slug_title(filename: str) -> str:
    return Path(filename).stem.replace("_", " ").replace("-", " ").strip()


def _markdown_sections(text: str) -> list[dict]:
    sections: list[dict] = []
    matches = list(re.finditer(r"(?m)^(#{1,4})\s+(.+?)\s*$", text))
    if not matches:
        return [{"id": "document", "title": "全文", "level": 1, "text": text, "order": 0}]
    if matches[0].start() > 0 and text[: matches[0].start()].strip():
        sections.append(
            {"id": "preamble", "title": "摘要", "level": 1,
             "text": text[: matches[0].start()].strip(), "order": 0}
        )
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        title = re.sub(r"\s+#+$", "", match.group(2)).strip()
        sections.append({
            "id": f"section-{index + 1}",
            "title": title,
            "level": len(match.group(1)),
            "text": text[match.end():end].strip(),
            "order": len(sections),
        })
    return sections


def _pdf_extract(path: Path) -> tuple[str, list[dict], int]:
    pages: list[str] = []
    sections: list[dict] = []
    with fitz.open(path) as document:
        for page_index, page in enumerate(document):
            text = page.get_text("text", sort=True).strip()
            pages.append(text)
            blocks = page.get_text("dict", sort=True).get("blocks", [])
            candidates: list[tuple[float, str]] = []
            for block in blocks:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        value = " ".join(span.get("text", "").split())
                        if 3 <= len(value) <= 100:
                            candidates.append((float(span.get("size", 0)), value))
            if candidates:
                median = sorted(size for size, _ in candidates)[len(candidates) // 2]
                heading = next(
                    (value for size, value in candidates if size >= median * 1.25),
                    f"第 {page_index + 1} 页",
                )
            else:
                heading = f"第 {page_index + 1} 页"
            sections.append({
                "id": f"page-{page_index + 1}",
                "title": heading,
                "level": 1,
                "page": page_index + 1,
                "text": text,
                "order": page_index,
            })
        return "\n\n".join(pages), sections, document.page_count


def import_bytes(filename: str, payload: bytes) -> dict:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError("仅支持 PDF 与 Markdown（.md / .markdown）")
    digest = hashlib.sha256(payload).hexdigest()
    with LOCK:
        for existing in _read_manifest():
            if existing.get("sha256") == digest:
                return existing
        document_id = uuid.uuid4().hex[:16]
        doc_dir = DOCUMENT_DIR / document_id
        doc_dir.mkdir(parents=True, exist_ok=False)
        source_path = doc_dir / f"source{suffix}"
        source_path.write_bytes(payload)
        kind = SUPPORTED[suffix]
        if kind == "pdf":
            text, sections, page_count = _pdf_extract(source_path)
        else:
            text = payload.decode("utf-8-sig", errors="replace")
            sections = _markdown_sections(text)
            page_count = 0
        extracted = {
            "id": document_id,
            "text": text,
            "sections": sections,
        }
        (doc_dir / "content.json").write_text(
            json.dumps(extracted, ensure_ascii=False), encoding="utf-8"
        )
        item = {
            "id": document_id,
            "name": filename,
            "title": _slug_title(filename),
            "kind": kind,
            "extension": suffix,
            "sha256": digest,
            "pageCount": page_count,
            "charCount": len(text),
            "sectionCount": len(sections),
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "lastOpenedAt": datetime.now(timezone.utc).isoformat(),
            "progress": 0,
        }
        items = _read_manifest()
        items.insert(0, item)
        _write_manifest(items)
        return item


def list_documents() -> list[dict]:
    with LOCK:
        return _read_manifest()


def get_document(document_id: str, touch: bool = False) -> dict:
    with LOCK:
        items = _read_manifest()
        item = next((entry for entry in items if entry["id"] == document_id), None)
        if not item:
            raise FileNotFoundError("文档不存在")
        if touch:
            item["lastOpenedAt"] = datetime.now(timezone.utc).isoformat()
            _write_manifest(items)
        content_file = DOCUMENT_DIR / document_id / "content.json"
        content = json.loads(content_file.read_text(encoding="utf-8"))
        return {**item, **content}


def source_path(document_id: str) -> Path:
    document = get_document(document_id)
    path = DOCUMENT_DIR / document_id / f"source{document['extension']}"
    if not path.is_file():
        raise FileNotFoundError("源文件不存在")
    return path


def _annotation_path(document_id: str) -> Path:
    get_document(document_id)
    return DOCUMENT_DIR / document_id / "annotations.json"


def load_annotations(document_id: str) -> dict:
    path = _annotation_path(document_id)
    if not path.is_file():
        return {"highlights": [], "doodles": [], "comments": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"highlights": [], "doodles": [], "comments": []}
    return {
        "highlights": payload.get("highlights", []),
        "doodles": payload.get("doodles", []),
        "comments": payload.get("comments", []),
    }


def _clean_annotations(payload: dict) -> dict:
    highlights: list[dict] = []
    for item in list(payload.get("highlights") or [])[:5000]:
        if not isinstance(item, dict):
            continue
        try:
            page = max(1, int(item.get("page") or 1))
            start = max(0, int(item.get("start") or 0))
            end = max(start + 1, int(item.get("end") or start + 1))
        except (TypeError, ValueError):
            continue
        color = str(item.get("color") or "yellow")
        if color not in {"yellow", "green", "blue", "pink", "orange"}:
            color = "yellow"
        highlights.append({
            "id": str(item.get("id") or uuid.uuid4().hex),
            "page": page,
            "start": start,
            "end": end,
            "text": str(item.get("text") or "")[:12_000],
            "color": color,
            "createdAt": int(item.get("createdAt") or 0),
        })

    doodles: list[dict] = []
    for item in list(payload.get("doodles") or [])[:3000]:
        if not isinstance(item, dict):
            continue
        points: list[dict] = []
        for point in list(item.get("points") or [])[:8000]:
            if not isinstance(point, dict):
                continue
            try:
                x = max(0.0, min(1.0, float(point.get("x") or 0)))
                y = max(0.0, min(1.0, float(point.get("y") or 0)))
            except (TypeError, ValueError):
                continue
            points.append({"x": round(x, 6), "y": round(y, 6)})
        if not points:
            continue
        tool = str(item.get("tool") or "brush")
        if tool not in {"brush", "eraser"}:
            tool = "brush"
        try:
            size = max(0.0005, min(0.12, float(item.get("size") or 0.004)))
            opacity = max(0.1, min(1.0, float(item.get("opacity") or 1)))
            page = max(1, int(item.get("page") or 1))
        except (TypeError, ValueError):
            continue
        color = str(item.get("color") or "#9f3341")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            color = "#9f3341"
        doodles.append({
            "id": str(item.get("id") or uuid.uuid4().hex),
            "page": page,
            "tool": tool,
            "color": color,
            "size": round(size, 6),
            "opacity": round(opacity, 3),
            "points": points,
            "createdAt": int(item.get("createdAt") or 0),
        })
    comments: list[dict] = []
    for item in list(payload.get("comments") or [])[:2000]:
        if not isinstance(item, dict):
            continue
        try:
            page = max(1, int(item.get("page") or 1))
            start = max(0, int(item.get("start") or 0))
            end = max(start + 1, int(item.get("end") or start + 1))
            created_at = max(0, int(item.get("createdAt") or 0))
            updated_at = max(created_at, int(item.get("updatedAt") or created_at))
        except (TypeError, ValueError):
            continue
        kind = str(item.get("kind") or "pdf")
        if kind not in {"pdf", "markdown"}:
            kind = "pdf"
        source = str(item.get("source") or "manual")
        if source not in {"manual", "ai"}:
            source = "manual"
        comments.append({
            "id": str(item.get("id") or uuid.uuid4().hex),
            "kind": kind,
            "page": page,
            "start": start,
            "end": end,
            "text": str(item.get("text") or "")[:12_000],
            "content": str(item.get("content") or "")[:20_000],
            "source": source,
            "createdAt": created_at,
            "updatedAt": updated_at,
        })
    return {"highlights": highlights, "doodles": doodles, "comments": comments}


def save_annotations(document_id: str, payload: dict) -> dict:
    path = _annotation_path(document_id)
    cleaned = _clean_annotations(payload)
    temporary = path.with_suffix(".json.tmp")
    with LOCK:
        temporary.write_text(
            json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(path)
    return cleaned


def _annotate_pdf_columns(
    words: list[dict],
    page_width: float,
) -> tuple[list[dict], float | None]:
    if not words or page_width <= 0:
        return words, None

    blocks: dict[int, dict] = {}
    for index, word in enumerate(words):
        block_id = int(word.get("block") or 0)
        x0 = float(word["x"])
        y0 = float(word["y"])
        x1 = x0 + float(word["w"])
        y1 = y0 + float(word["h"])
        block = blocks.setdefault(block_id, {
            "x0": x0,
            "y0": y0,
            "x1": x1,
            "y1": y1,
            "count": 0,
            "indices": [],
        })
        block["x0"] = min(block["x0"], x0)
        block["y0"] = min(block["y0"], y0)
        block["x1"] = max(block["x1"], x1)
        block["y1"] = max(block["y1"], y1)
        block["count"] += 1
        block["indices"].append(index)

    midpoint = page_width / 2
    left_blocks: set[int] = set()
    right_blocks: set[int] = set()
    for block_id, block in blocks.items():
        width = block["x1"] - block["x0"]
        center = (block["x0"] + block["x1"]) / 2
        if width > page_width * 0.6:
            continue
        if center < midpoint and block["x1"] <= midpoint + page_width * 0.08:
            left_blocks.add(block_id)
        elif center > midpoint and block["x0"] >= midpoint - page_width * 0.08:
            right_blocks.add(block_id)

    left_count = sum(blocks[value]["count"] for value in left_blocks)
    right_count = sum(blocks[value]["count"] for value in right_blocks)
    minimum_words = max(12, round(len(words) * 0.12))
    if left_count < minimum_words or right_count < minimum_words:
        for word in words:
            word["column"] = "shared"
        return words, None

    left_edges = [
        blocks[value]["x1"]
        for value in left_blocks
        if blocks[value]["x1"] >= page_width * 0.3
    ]
    right_edges = [
        blocks[value]["x0"]
        for value in right_blocks
        if blocks[value]["x0"] <= page_width * 0.7
    ]
    left_edge = max(left_edges) if left_edges else midpoint - page_width * 0.02
    right_edge = min(right_edges) if right_edges else midpoint + page_width * 0.02
    split = (
        (left_edge + right_edge) / 2
        if left_edge < right_edge
        else midpoint
    )

    first_column_y = min(
        blocks[value]["y0"] for value in [*left_blocks, *right_blocks]
    )
    ordering: list[tuple[tuple, dict]] = []
    for index, word in enumerate(words):
        block_id = int(word.get("block") or 0)
        block = blocks[block_id]
        if block_id in left_blocks:
            column = "left"
            group = 1
        elif block_id in right_blocks:
            column = "right"
            group = 2
        else:
            column = "shared"
            group = 0 if block["y1"] <= first_column_y + 6 else 3
        word["column"] = column
        ordering.append((
            (
                group,
                float(word["y"]),
                float(word["x"]),
                int(word.get("line") or 0),
                int(word.get("word") or 0),
                index,
            ),
            word,
        ))
    ordered = [word for _, word in sorted(ordering, key=lambda value: value[0])]
    return ordered, round(split, 2)


def render_pdf_page(document_id: str, page_number: int, scale: float = 1.5) -> dict:
    document = get_document(document_id)
    if document["kind"] != "pdf":
        raise ValueError("当前文档不是 PDF")
    path = source_path(document_id)
    scale = max(0.65, min(3.0, float(scale)))
    with fitz.open(path) as pdf:
        if page_number < 1 or page_number > pdf.page_count:
            raise ValueError(f"页码超出范围：1-{pdf.page_count}")
        page = pdf[page_number - 1]
        matrix = fitz.Matrix(scale, scale)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        words = []
        for item in page.get_text("words", sort=True):
            x0, y0, x1, y1, text, block_no, line_no, word_no = item
            if not str(text).strip():
                continue
            words.append({
                "text": str(text),
                "x": round(x0 * scale, 2),
                "y": round(y0 * scale, 2),
                "w": round((x1 - x0) * scale, 2),
                "h": round((y1 - y0) * scale, 2),
                "block": int(block_no),
                "line": int(line_no),
                "word": int(word_no),
            })
        words, column_split = _annotate_pdf_columns(words, pixmap.width)
        image = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
        return {
            "image": f"data:image/png;base64,{image}",
            "width": pixmap.width,
            "height": pixmap.height,
            "words": words,
            "columnSplit": column_split,
            "pageText": page.get_text("text", sort=True).strip(),
            "pageCount": pdf.page_count,
        }


def update_progress(document_id: str, progress: float) -> dict:
    with LOCK:
        items = _read_manifest()
        item = next((entry for entry in items if entry["id"] == document_id), None)
        if not item:
            raise FileNotFoundError("文档不存在")
        item["progress"] = max(0, min(100, round(float(progress), 1)))
        item["lastOpenedAt"] = datetime.now(timezone.utc).isoformat()
        _write_manifest(items)
        return item


def delete_document(document_id: str) -> None:
    with LOCK:
        items = _read_manifest()
        retained = [entry for entry in items if entry["id"] != document_id]
        if len(retained) == len(items):
            raise FileNotFoundError("文档不存在")
        _write_manifest(retained)
        folder = (DOCUMENT_DIR / document_id).resolve()
        if folder.parent != DOCUMENT_DIR.resolve():
            raise RuntimeError("拒绝删除非文库目录")
        shutil.rmtree(folder, ignore_errors=True)
