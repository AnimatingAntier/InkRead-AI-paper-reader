from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock

from config import SETTINGS_FILE

LOCK = RLock()
MASK_CHAR = "•"
SECRET_FIELDS = {"api_key", "serpapi_key", "baidu_translate_api_key"}
DEFAULTS = {
    "provider": "openrouter",
    "api_key": "",
    "model": "openrouter/free",
    "base_url": "https://openrouter.ai/api/v1",
    "serpapi_key": "",
    "baidu_translate_appid": "",
    "baidu_translate_api_key": "",
    "comment_idle_opacity": 0.58,
    "web_search": True,
    "fact_check": True,
}


def _masked(value: object) -> str:
    secret = str(value or "")
    return MASK_CHAR * len(secret)


def _is_mask(value: object) -> bool:
    text = str(value or "")
    return bool(text) and set(text) == {MASK_CHAR}


def _legacy_settings() -> dict:
    # Never search neighbouring folders for credentials. Migration is opt-in and
    # accepts only the exact file explicitly supplied by the user/developer.
    seed_path = os.getenv("INKREAD_SEED_SETTINGS", "").strip()
    if not seed_path:
        return {}
    candidate = Path(seed_path).expanduser()
    if not candidate.is_file() or candidate.resolve() == SETTINGS_FILE.resolve():
        return {}
    try:
        old = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not old:
        return {}
    current_schema_fields = {
        "api_key",
        "serpapi_key",
        "model",
        "base_url",
        "baidu_translate_appid",
        "baidu_translate_api_key",
    }
    if current_schema_fields.intersection(old):
        return {key: old[key] for key in DEFAULTS if key in old}
    provider = old.get("provider", "openrouter")
    if provider == "opencode_zen":
        return {
            "provider": provider,
            "api_key": old.get("opencode_zen_api_key", ""),
            "model": old.get("opencode_zen_model", "deepseek-v4-flash-free"),
            "base_url": old.get("opencode_zen_url", "https://opencode.ai/zen/v1"),
        }
    return {
        "provider": "openrouter",
        "api_key": old.get("openrouter_api_key", ""),
        "model": old.get("openrouter_model", "openrouter/free"),
        "base_url": "https://openrouter.ai/api/v1",
    }


def load() -> dict:
    with LOCK:
        data: dict = {}
        if SETTINGS_FILE.is_file():
            try:
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        elif not os.getenv("INKREAD_NO_LEGACY_IMPORT"):
            data = _legacy_settings()
            if data:
                SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
                SETTINGS_FILE.write_text(
                    json.dumps({**DEFAULTS, **data}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        result = {**DEFAULTS, **data}
    result["api_key"] = result.get("api_key") or os.getenv("OPENROUTER_API_KEY", "")
    result["serpapi_key"] = result.get("serpapi_key") or os.getenv("SERPAPI_API_KEY", "")
    result["baidu_translate_appid"] = (
        result.get("baidu_translate_appid") or os.getenv("BAIDU_TRANSLATE_APPID", "")
    )
    result["baidu_translate_api_key"] = (
        result.get("baidu_translate_api_key") or os.getenv("BAIDU_TRANSLATE_API_KEY", "")
    )
    return result


def public() -> dict:
    settings = load()
    settings["api_key"] = _masked(settings.get("api_key"))
    settings["serpapi_key"] = _masked(settings.get("serpapi_key"))
    settings["baidu_translate_api_key"] = _masked(
        settings.get("baidu_translate_api_key")
    )
    settings["configured"] = bool(load().get("api_key"))
    settings["translation_configured"] = bool(
        load().get("baidu_translate_appid") and load().get("baidu_translate_api_key")
    )
    return settings


def update(values: dict) -> dict:
    allowed = set(DEFAULTS)
    current = load()
    with LOCK:
        for key, value in values.items():
            if key not in allowed:
                continue
            if key in SECRET_FIELDS and _is_mask(value):
                continue
            if key == "comment_idle_opacity":
                try:
                    value = max(0.15, min(1.0, float(value)))
                except (TypeError, ValueError):
                    value = DEFAULTS["comment_idle_opacity"]
            current[key] = value
        SETTINGS_FILE.write_text(
            json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return public()
