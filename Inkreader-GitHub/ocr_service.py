from __future__ import annotations

import base64
import re
import subprocess
import tempfile
from pathlib import Path

from config import BASE_DIR

MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_OCR_CHARS = 16_000

MULTIMODAL_PATTERNS = (
    "gpt-4o",
    "gpt-4.1",
    "gpt-4-turbo",
    "gpt-4-vision",
    "gpt-5",
    "o1-",
    "o3-",
    "o4-",
    "claude-3",
    "claude-4",
    "claude-opus",
    "claude-sonnet",
    "claude-haiku",
    "gemini",
    "qwen-vl",
    "qwen2-vl",
    "qwen2.5-vl",
    "qvq",
    "llava",
    "cogvlm",
    "internvl",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "glm-4v",
    "glm-5",
    "kimi",
    "pixtral",
    "minimax-m2",
)

TEXT_ONLY_PATTERNS = (
    "openrouter/free",
    "gpt-3.5",
    "text-only",
    "deepseek-r1",
    "deepseek-v3",
    "deepseek-chat",
)


def image_mode(model: str) -> str:
    lowered = str(model or "").lower()
    if any(pattern in lowered for pattern in TEXT_ONLY_PATTERNS):
        return "ocr"
    if any(pattern in lowered for pattern in MULTIMODAL_PATTERNS):
        return "vision"
    # Unknown OpenAI-compatible models are allowed to receive images. This mirrors
    # Smareader and avoids incorrectly downgrading newly released vision models.
    return "vision"


def clean_image_data_url(value: object) -> str:
    data_url = str(value or "").strip()
    match = re.fullmatch(
        r"data:image/(png|jpeg|jpg|webp);base64,([A-Za-z0-9+/=\r\n]+)",
        data_url,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError("截图数据格式无效")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except ValueError as exc:
        raise ValueError("截图数据损坏") from exc
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("截图过大，请缩小框选区域后重试")
    mime = "jpeg" if match.group(1).lower() in {"jpg", "jpeg"} else match.group(1).lower()
    return f"data:image/{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _image_bytes(data_url: str) -> tuple[bytes, str]:
    header, encoded = data_url.split(",", 1)
    extension = ".jpg" if "jpeg" in header else f".{header.split('/')[1].split(';')[0]}"
    return base64.b64decode(encoded), extension


def _normalize_ocr(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()[:MAX_OCR_CHARS]


def windows_ocr(data_url: str, fallback_text: str = "") -> str:
    raw, extension = _image_bytes(data_url)
    script = BASE_DIR / "assets" / "windows_ocr.ps1"
    powershell = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    temporary_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as temporary:
            temporary.write(raw)
            temporary_path = temporary.name
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        completed = subprocess.run(
            [
                str(powershell),
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-ImagePath",
                temporary_path,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=40,
            startupinfo=startup,
            check=False,
        )
        recognized = _normalize_ocr(completed.stdout) if completed.returncode == 0 else ""
        return recognized or _normalize_ocr(fallback_text)
    except (OSError, subprocess.SubprocessError):
        return _normalize_ocr(fallback_text)
    finally:
        if temporary_path:
            try:
                Path(temporary_path).unlink(missing_ok=True)
            except OSError:
                pass
