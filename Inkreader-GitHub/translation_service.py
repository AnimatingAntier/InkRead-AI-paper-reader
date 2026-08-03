from __future__ import annotations

import os
import re
from collections import OrderedDict
from pathlib import Path
from threading import RLock
from typing import Any

import requests

import settings_store
from config import DATA_DIR

BAIDU_TRANSLATE_URL = "https://fanyi-api.baidu.com/ait/api/aiTextTranslate"
MAX_SELECTION_CHARS = 12_000
MAX_BAIDU_CHUNK_CHARS = 4_500
MAX_LOCAL_CHUNK_CHARS = 1_200

LOCAL_MODEL_REPOSITORY = "gaudi/opus-mt-en-zh-ctranslate2"
LOCAL_MODEL_REVISION = "dcd22168f08b99dd34c62bc2195e31dc2f04e90b"
LOCAL_MODEL_DIR = DATA_DIR / "models" / "opus-mt-en-zh-ctranslate2"
LOCAL_MODEL_FILES = {
    "config.json": 100,
    "model.bin": 150_000_000,
    "shared_vocabulary.json": 1_000_000,
    "source.spm": 750_000,
    "target.spm": 750_000,
}
LOCAL_MODEL_TOTAL_BYTES = 159_000_000

QUOTA_ERROR_CODES = {"54004", "58003", "58004", "90108", "100006"}
QUOTA_ERROR_WORDS = ("额度", "超出", "quota", "balance", "余额", "欠费", "limit exceeded")

_STATUS_LOCK = RLock()
_DOWNLOAD_LOCK = RLock()
_MODEL_LOCK = RLock()
_TRANSLATION_LOCK = RLock()
_TRANSLATION_CACHE: OrderedDict[str, dict[str, str]] = OrderedDict()
TRANSLATION_CACHE_LIMIT = 128
_BAIDU_STATE: dict[str, Any] = {
    "checked": False,
    "available": False,
    "reason": "尚未检测",
    "quota_exhausted": False,
}
_DOWNLOAD_STATE: dict[str, Any] = {
    "state": "ready" if all(
        (LOCAL_MODEL_DIR / name).is_file()
        and (LOCAL_MODEL_DIR / name).stat().st_size >= minimum
        for name, minimum in LOCAL_MODEL_FILES.items()
    ) else "missing",
    "progress": 100 if all(
        (LOCAL_MODEL_DIR / name).is_file()
        and (LOCAL_MODEL_DIR / name).stat().st_size >= minimum
        for name, minimum in LOCAL_MODEL_FILES.items()
    ) else 0,
    "error": "",
}
_LOCAL_TRANSLATOR: Any = None
_SOURCE_PROCESSOR: Any = None
_TARGET_PROCESSOR: Any = None


class BaiduTranslationError(RuntimeError):
    def __init__(self, message: str, code: str = "", quota_exhausted: bool = False):
        super().__init__(message)
        self.code = code
        self.quota_exhausted = quota_exhausted


def _clean_source(source: str) -> str:
    return " ".join(source.split()) if "\n" not in source else source.strip()


def _split_text(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    remaining = text.strip()
    while len(remaining) > limit:
        lower_bound = max(1, limit - min(1_000, limit // 3))
        cut = max(
            remaining.rfind("\n", lower_bound, limit),
            remaining.rfind(". ", lower_bound, limit),
            remaining.rfind("? ", lower_bound, limit),
            remaining.rfind("! ", lower_bound, limit),
            remaining.rfind("; ", lower_bound, limit),
            remaining.rfind(" ", lower_bound, limit),
        )
        if cut < lower_bound:
            cut = limit
        elif remaining[cut : cut + 2] in {". ", "? ", "! ", "; "}:
            cut += 1
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _is_quota_error(code: str, message: str) -> bool:
    lowered = message.lower()
    return code in QUOTA_ERROR_CODES or any(word in lowered for word in QUOTA_ERROR_WORDS)


def _error_message(payload: dict[str, Any]) -> tuple[str, str, bool]:
    code = str(payload.get("error_code") or "")
    message = str(payload.get("error_msg") or "未知错误")
    quota_exhausted = _is_quota_error(code, message)
    if quota_exhausted:
        return "百度翻译本月额度已用尽，已自动切换为本地翻译", code, True
    if code in {"54000", "54001"}:
        return (
            "百度翻译鉴权失败，请检查 APP ID 与 API Key 是否匹配，并确认已开通大模型文本翻译",
            code,
            False,
        )
    if code == "54003":
        return "百度翻译调用过于频繁，已临时切换为本地翻译", code, False
    return f"百度翻译失败（{code or '未知代码'}）：{message}", code, False


def _translate_baidu_chunk(
    text: str, appid: str, api_key: str, timeout: int = 25
) -> tuple[str, str]:
    try:
        response = requests.post(
            BAIDU_TRANSLATE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json;charset=utf-8",
            },
            json={"appid": appid, "q": text, "from": "en", "to": "zh"},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise BaiduTranslationError(
            "无法连接百度翻译，已自动切换为本地翻译"
        ) from exc
    except ValueError as exc:
        raise BaiduTranslationError(
            "百度翻译返回了无法解析的结果，已自动切换为本地翻译"
        ) from exc

    if payload.get("error_code"):
        message, code, quota_exhausted = _error_message(payload)
        raise BaiduTranslationError(message, code, quota_exhausted)
    results = payload.get("trans_result") or []
    translated = "\n".join(
        str(item.get("dst", "")).strip()
        for item in results
        if isinstance(item, dict) and item.get("dst")
    ).strip()
    if not translated:
        raise BaiduTranslationError("百度翻译未返回译文，已自动切换为本地翻译")
    return translated, str(payload.get("from") or "en")


def _translate_baidu(text: str, appid: str, api_key: str) -> dict[str, str]:
    translations: list[str] = []
    detected_from = "en"
    for chunk in _split_text(text, MAX_BAIDU_CHUNK_CHARS):
        translated, detected_from = _translate_baidu_chunk(chunk, appid, api_key)
        translations.append(translated)
    return {
        "source": text,
        "translation": "\n".join(translations),
        "from": detected_from,
        "to": "zh",
        "provider": "baidu",
        "fallback_reason": "",
    }


def _model_is_ready() -> bool:
    return all(
        (LOCAL_MODEL_DIR / name).is_file()
        and (LOCAL_MODEL_DIR / name).stat().st_size >= minimum
        for name, minimum in LOCAL_MODEL_FILES.items()
    )


def _update_download_state(**values: Any) -> None:
    with _STATUS_LOCK:
        _DOWNLOAD_STATE.update(values)


def _download_file(name: str, downloaded_before: int) -> int:
    destination = LOCAL_MODEL_DIR / name
    minimum = LOCAL_MODEL_FILES[name]
    if destination.is_file() and destination.stat().st_size >= minimum:
        return destination.stat().st_size

    part_path = destination.with_suffix(destination.suffix + ".part")
    bases = (
        "https://huggingface.co",
        "https://hf-mirror.com",
    )
    last_error: Exception | None = None
    for base in bases:
        url = (
            f"{base}/{LOCAL_MODEL_REPOSITORY}/resolve/"
            f"{LOCAL_MODEL_REVISION}/{name}?download=true"
        )
        try:
            with requests.get(url, stream=True, timeout=(12, 120)) as response:
                response.raise_for_status()
                expected = int(response.headers.get("Content-Length") or 0)
                written = 0
                with part_path.open("wb") as target:
                    for block in response.iter_content(chunk_size=1024 * 1024):
                        if not block:
                            continue
                        target.write(block)
                        written += len(block)
                        progress = min(
                            99,
                            int(((downloaded_before + written) / LOCAL_MODEL_TOTAL_BYTES) * 100),
                        )
                        _update_download_state(state="downloading", progress=progress, error="")
                if written < minimum or (expected and written != expected):
                    raise RuntimeError(f"{name} 下载不完整")
                part_path.replace(destination)
                return written
        except Exception as exc:
            last_error = exc
            try:
                part_path.unlink(missing_ok=True)
            except OSError:
                pass
    raise RuntimeError(f"本地翻译模型下载失败（{name}）") from last_error


def _ensure_local_model() -> None:
    if _model_is_ready():
        _update_download_state(state="ready", progress=100, error="")
        return
    with _DOWNLOAD_LOCK:
        if _model_is_ready():
            _update_download_state(state="ready", progress=100, error="")
            return
        LOCAL_MODEL_DIR.mkdir(parents=True, exist_ok=True)
        _update_download_state(state="downloading", progress=0, error="")
        downloaded = 0
        try:
            for name in LOCAL_MODEL_FILES:
                size = _download_file(name, downloaded)
                downloaded += size
            if not _model_is_ready():
                raise RuntimeError("本地翻译模型文件不完整")
            _update_download_state(state="ready", progress=100, error="")
        except Exception as exc:
            message = f"{exc}，请检查网络后重试"
            _update_download_state(state="error", error=message)
            raise RuntimeError(message) from exc


def _load_local_runtime() -> tuple[Any, Any, Any]:
    global _LOCAL_TRANSLATOR, _SOURCE_PROCESSOR, _TARGET_PROCESSOR
    if _LOCAL_TRANSLATOR is not None:
        return _LOCAL_TRANSLATOR, _SOURCE_PROCESSOR, _TARGET_PROCESSOR
    with _MODEL_LOCK:
        if _LOCAL_TRANSLATOR is not None:
            return _LOCAL_TRANSLATOR, _SOURCE_PROCESSOR, _TARGET_PROCESSOR
        _ensure_local_model()
        try:
            import ctranslate2
            import sentencepiece as sentencepiece
        except ImportError as exc:
            raise RuntimeError("本地翻译组件未正确安装，请重新安装 InkRead") from exc
        cpu_threads = max(1, min(4, os.cpu_count() or 2))
        _LOCAL_TRANSLATOR = ctranslate2.Translator(
            str(LOCAL_MODEL_DIR),
            device="cpu",
            compute_type="int8",
            inter_threads=1,
            intra_threads=cpu_threads,
        )
        _SOURCE_PROCESSOR = sentencepiece.SentencePieceProcessor(
            model_file=str(LOCAL_MODEL_DIR / "source.spm")
        )
        _TARGET_PROCESSOR = sentencepiece.SentencePieceProcessor(
            model_file=str(LOCAL_MODEL_DIR / "target.spm")
        )
        return _LOCAL_TRANSLATOR, _SOURCE_PROCESSOR, _TARGET_PROCESSOR


def _normalize_local_source(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _translate_local(text: str, fallback_reason: str) -> dict[str, str]:
    translator, source_processor, target_processor = _load_local_runtime()
    translations: list[str] = []
    for chunk in _split_text(text, MAX_LOCAL_CHUNK_CHARS):
        source_tokens = source_processor.encode(
            _normalize_local_source(chunk), out_type=str
        )
        results = translator.translate_batch(
            [source_tokens],
            beam_size=3,
            max_decoding_length=512,
        )
        if not results or not results[0].hypotheses:
            raise RuntimeError("本地翻译未返回译文")
        translations.append(target_processor.decode(results[0].hypotheses[0]).strip())
    return {
        "source": text,
        "translation": "\n".join(translations),
        "from": "en",
        "to": "zh",
        "provider": "local",
        "fallback_reason": fallback_reason,
    }


def reset_translation_status() -> None:
    with _STATUS_LOCK:
        _BAIDU_STATE.update(
            checked=False,
            available=False,
            reason="尚未检测",
            quota_exhausted=False,
        )
    with _TRANSLATION_LOCK:
        _TRANSLATION_CACHE.clear()


def _set_baidu_unavailable(error: BaiduTranslationError) -> None:
    with _STATUS_LOCK:
        _BAIDU_STATE.update(
            checked=True,
            available=False,
            reason=str(error),
            quota_exhausted=error.quota_exhausted,
        )


def translation_status(force: bool = False) -> dict[str, Any]:
    with _STATUS_LOCK:
        already_checked = bool(_BAIDU_STATE["checked"])
    if force or not already_checked:
        settings = settings_store.load()
        appid = str(settings.get("baidu_translate_appid") or "").strip()
        api_key = str(settings.get("baidu_translate_api_key") or "").strip()
        if not appid or not api_key:
            missing = "APP ID" if not appid else "API Key"
            with _STATUS_LOCK:
                _BAIDU_STATE.update(
                    checked=True,
                    available=False,
                    reason=f"百度翻译缺少 {missing}，当前使用本地翻译",
                    quota_exhausted=False,
                )
        else:
            try:
                _translate_baidu_chunk("Hello", appid, api_key, timeout=12)
            except BaiduTranslationError as exc:
                _set_baidu_unavailable(exc)
            else:
                with _STATUS_LOCK:
                    _BAIDU_STATE.update(
                        checked=True,
                        available=True,
                        reason="百度翻译可用",
                        quota_exhausted=False,
                    )
    with _STATUS_LOCK:
        baidu = dict(_BAIDU_STATE)
        download = dict(_DOWNLOAD_STATE)
    return {
        "checked": baidu["checked"],
        "provider": "baidu" if baidu["available"] else "local",
        "baidu_available": baidu["available"],
        "baidu_reason": baidu["reason"],
        "quota_exhausted": baidu["quota_exhausted"],
        "local_model_state": download["state"],
        "local_model_progress": download["progress"],
        "local_model_error": download["error"],
    }


def translate_to_chinese(source: str) -> dict[str, str]:
    text = _clean_source(source)
    if len(text) < 2:
        raise ValueError("请选择需要翻译的英文")
    if len(text) > MAX_SELECTION_CHARS:
        raise ValueError(f"单次最多翻译 {MAX_SELECTION_CHARS:,} 个字符")

    with _TRANSLATION_LOCK:
        cached = _TRANSLATION_CACHE.get(text)
        if cached is not None:
            _TRANSLATION_CACHE.move_to_end(text)
            return dict(cached)

        status = translation_status()
        settings = settings_store.load()
        appid = str(settings.get("baidu_translate_appid") or "").strip()
        api_key = str(settings.get("baidu_translate_api_key") or "").strip()
        if status["baidu_available"] and appid and api_key:
            try:
                result = _translate_baidu(text, appid, api_key)
            except BaiduTranslationError as exc:
                _set_baidu_unavailable(exc)
                result = _translate_local(text, str(exc))
        else:
            result = _translate_local(text, str(status["baidu_reason"]))

        _TRANSLATION_CACHE[text] = dict(result)
        _TRANSLATION_CACHE.move_to_end(text)
        while len(_TRANSLATION_CACHE) > TRANSLATION_CACHE_LIMIT:
            _TRANSLATION_CACHE.popitem(last=False)
        return result
