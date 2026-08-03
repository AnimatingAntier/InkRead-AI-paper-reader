from __future__ import annotations

import json
import mimetypes
import os
import re
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent_service import generate_margin_comment, run_agent
from config import DIST_DIR, PORT
from document_store import (
    delete_document,
    get_document,
    import_bytes,
    list_documents,
    load_annotations,
    render_pdf_page,
    save_annotations,
    source_path,
    update_progress,
)
import settings_store
from translation_service import (
    reset_translation_status,
    translate_to_chinese,
    translation_status,
)


class InkReadHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "InkRead/1.0"

    def log_message(self, format: str, *args) -> None:
        return

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin", "").strip()
        if not origin:
            return True
        port = self.server.server_port
        allowed = {
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
            "http://127.0.0.1:5178",
            "http://localhost:5178",
        }
        configured = os.getenv("INKREAD_DEV_ORIGIN", "")
        allowed.update(item.strip() for item in configured.split(",") if item.strip())
        return origin in allowed

    def _reject_foreign_api_origin(self) -> bool:
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/") and not self._origin_allowed():
            self.send_json({"error": "拒绝非 InkRead 来源的本地 API 请求"}, 403)
            return True
        return False

    def send_json(self, payload: object, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 250 * 1024 * 1024:
            raise ValueError("文件超过 250MB 限制")
        return self.rfile.read(length) if length else b""

    def read_json(self) -> dict:
        raw = self.read_body()
        return json.loads(raw.decode("utf-8")) if raw else {}

    def do_OPTIONS(self) -> None:
        if self._reject_foreign_api_origin():
            return
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        if self._reject_foreign_api_origin():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/health":
                self.send_json({
                    "status": "ok",
                    "documents": len(list_documents()),
                    "aiConfigured": settings_store.public()["configured"],
                })
            elif path == "/api/documents":
                self.send_json({"documents": list_documents()})
            elif path == "/api/settings":
                self.send_json(settings_store.public())
            elif path == "/api/translation/status":
                query = urllib.parse.parse_qs(parsed.query)
                force = (query.get("force") or ["0"])[0] == "1"
                self.send_json(translation_status(force=force))
            elif re.fullmatch(r"/api/documents/[a-f0-9]+/annotations", path):
                document_id = path.split("/")[-2]
                self.send_json(load_annotations(document_id))
            elif re.fullmatch(r"/api/documents/[a-f0-9]+", path):
                document_id = path.rsplit("/", 1)[-1]
                self.send_json(get_document(document_id, touch=True))
            elif re.fullmatch(r"/api/documents/[a-f0-9]+/file", path):
                document_id = path.split("/")[-2]
                file_path = source_path(document_id)
                self.send_file(file_path, cache=False)
            elif re.fullmatch(r"/api/documents/[a-f0-9]+/page/\d+", path):
                parts = path.split("/")
                document_id = parts[-3]
                page_number = int(parts[-1])
                query = urllib.parse.parse_qs(parsed.query)
                scale = float((query.get("scale") or ["1.5"])[0])
                self.send_json(render_pdf_page(document_id, page_number, scale))
            else:
                self.send_static(path)
        except FileNotFoundError as exc:
            self.send_json({"error": str(exc)}, 404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    def do_POST(self) -> None:
        if self._reject_foreign_api_origin():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/documents/import":
                query = urllib.parse.parse_qs(parsed.query)
                filename = (query.get("name") or [""])[0]
                if not filename:
                    raise ValueError("缺少文件名")
                self.send_json(import_bytes(filename, self.read_body()), 201)
            elif path == "/api/settings":
                updated = settings_store.update(self.read_json())
                reset_translation_status()
                self.send_json(updated)
            elif path == "/api/translate":
                self.send_json(translate_to_chinese(str(self.read_json().get("text") or "")))
            elif path == "/api/annotations/generate":
                body = self.read_json()
                self.send_json({
                    "content": generate_margin_comment(
                        str(body.get("document_id") or ""),
                        str(body.get("selected_text") or ""),
                    )
                })
            elif re.fullmatch(r"/api/documents/[a-f0-9]+/annotations", path):
                document_id = path.split("/")[-2]
                self.send_json(save_annotations(document_id, self.read_json()))
            elif path == "/api/chat/stream":
                self.stream_agent(self.read_json())
            else:
                self.send_json({"error": "接口不存在"}, 404)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            traceback.print_exc()
            self.send_json({"error": str(exc)}, 500)

    def do_PATCH(self) -> None:
        if self._reject_foreign_api_origin():
            return
        path = urllib.parse.urlparse(self.path).path
        try:
            match = re.fullmatch(r"/api/documents/([a-f0-9]+)/progress", path)
            if not match:
                self.send_json({"error": "接口不存在"}, 404)
                return
            body = self.read_json()
            self.send_json(update_progress(match.group(1), body.get("progress", 0)))
        except Exception as exc:
            self.send_json({"error": str(exc)}, 400)

    def do_DELETE(self) -> None:
        if self._reject_foreign_api_origin():
            return
        path = urllib.parse.urlparse(self.path).path
        try:
            match = re.fullmatch(r"/api/documents/([a-f0-9]+)", path)
            if not match:
                self.send_json({"error": "接口不存在"}, 404)
                return
            delete_document(match.group(1))
            self.send_json({"ok": True})
        except FileNotFoundError as exc:
            self.send_json({"error": str(exc)}, 404)

    def send_file(self, path: Path, cache: bool = True) -> None:
        data = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600" if cache else "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def send_static(self, request_path: str) -> None:
        path = request_path.lstrip("/") or "index.html"
        candidate = (DIST_DIR / path).resolve()
        if DIST_DIR.resolve() not in candidate.parents and candidate != DIST_DIR.resolve():
            self.send_json({"error": "非法路径"}, 403)
            return
        if not candidate.is_file():
            candidate = DIST_DIR / "index.html"
        if not candidate.is_file():
            self.send_json({"error": "前端尚未构建，请运行 npm run build"}, 503)
            return
        self.send_file(candidate)

    def _write_chunk(self, data: bytes) -> None:
        self.wfile.write(f"{len(data):X}\r\n".encode("ascii"))
        self.wfile.write(data)
        self.wfile.write(b"\r\n")
        self.wfile.flush()

    def stream_agent(self, body: dict) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            for event in run_agent(body):
                packet = f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")
                self._write_chunk(packet)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            packet = f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n".encode("utf-8")
            self._write_chunk(packet)
        finally:
            try:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except Exception:
                pass


def start_server(port: int = PORT) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), InkReadHandler)
    server.daemon_threads = True
    server.serve_forever()
