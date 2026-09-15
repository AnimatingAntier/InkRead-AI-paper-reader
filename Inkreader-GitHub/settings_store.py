from __future__ import annotations

import json
import os
import time
from pathlib import Path
from threading import RLock

import providers
from config import SETTINGS_FILE

LOCK = RLock()
MASK_CHAR = "•"
SECRET_FIELDS = {"api_key", "serpapi_key", "baidu_translate_api_key"}
DEFAULTS = {
    "provider": providers.DEFAULT_PROVIDER,
    "api_key": "",
    "model": providers.get_provider(providers.DEFAULT_PROVIDER).default_model,
    # Only used by providers that let the user supply their own endpoint.
    "base_url": "",
    # Keys remembered per provider so switching back does not require re-entry.
    "api_keys": {},
    # Last model list fetched from each provider: {provider: {"fetched_at": epoch, "models": [...]}}
    # Written only by the backend after a successful fetch; the form never edits it.
    "model_cache": {},
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
    return {
        "provider": "openrouter",
        "api_key": old.get("openrouter_api_key", ""),
        "model": old.get("openrouter_model", "openrouter/free"),
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
    if not isinstance(result.get("api_keys"), dict):
        result["api_keys"] = {}
    if not isinstance(result.get("model_cache"), dict):
        result["model_cache"] = {}
    _retire_removed_provider(result)
    result["api_key"] = result.get("api_key") or os.getenv("OPENROUTER_API_KEY", "")
    result["serpapi_key"] = result.get("serpapi_key") or os.getenv("SERPAPI_API_KEY", "")
    result["baidu_translate_appid"] = (
        result.get("baidu_translate_appid") or os.getenv("BAIDU_TRANSLATE_APPID", "")
    )
    result["baidu_translate_api_key"] = (
        result.get("baidu_translate_api_key") or os.getenv("BAIDU_TRANSLATE_API_KEY", "")
    )
    return result


def _retire_removed_provider(settings: dict) -> None:
    """Fall back to the default preset when the saved provider no longer exists.

    Presets can be dropped between releases (OpenCode Zen was removed in 1.2.0). Without
    this the stale id would silently resolve to the custom-endpoint preset and the user
    would see a bogus URL and a key that belongs to a different service.
    """
    provider = str(settings.get("provider") or "")
    if provider in providers.PROVIDERS:
        return
    default = providers.DEFAULT_PROVIDER
    settings["provider"] = default
    settings["model"] = providers.get_provider(default).default_model
    settings["base_url"] = ""
    settings["api_key"] = settings.get("api_keys", {}).get(default, "")
    settings["model_cache"].pop(provider, None)


def ai_configured(settings: dict) -> bool:
    import llm_client

    route = llm_client.resolve_route(settings)
    return bool(route.model and route.base_url and (route.api_key or not route.key_required))


def public() -> dict:
    settings = load()
    settings["configured"] = ai_configured(settings)
    settings["translation_configured"] = bool(
        settings.get("baidu_translate_appid") and settings.get("baidu_translate_api_key")
    )
    settings["api_key"] = _masked(settings.get("api_key"))
    settings["api_keys"] = {
        provider: _masked(key) for provider, key in settings.get("api_keys", {}).items() if key
    }
    settings["serpapi_key"] = _masked(settings.get("serpapi_key"))
    settings["baidu_translate_api_key"] = _masked(
        settings.get("baidu_translate_api_key")
    )
    return settings


def _apply(current: dict, values: dict) -> dict:
    """Overlay form values on stored settings; masked secrets mean "keep stored"."""
    previous_provider = str(current.get("provider") or "")
    stored_keys: dict = dict(current.get("api_keys") or {})
    env_key = os.getenv("OPENROUTER_API_KEY", "")
    if current.get("api_key") and previous_provider and current["api_key"] != env_key:
        stored_keys.setdefault(previous_provider, current["api_key"])
    key_supplied = False
    for key, value in (values or {}).items():
        if key not in DEFAULTS or key in ("api_keys", "model_cache"):
            continue
        if key in SECRET_FIELDS and _is_mask(value):
            continue
        if key == "api_key":
            key_supplied = True
        if key == "comment_idle_opacity":
            try:
                value = max(0.15, min(1.0, float(value)))
            except (TypeError, ValueError):
                value = DEFAULTS["comment_idle_opacity"]
        current[key] = value
    provider = str(current.get("provider") or "")
    if key_supplied:
        stored_keys[provider] = str(current.get("api_key") or "")
    elif provider != previous_provider or _is_mask(values.get("api_key")):
        current["api_key"] = stored_keys.get(provider, "")
    current["api_keys"] = {name: key for name, key in stored_keys.items() if key}
    return current


def merged(values: dict) -> dict:
    return _apply(load(), values)


def remember_models(provider: str, models: list[dict]) -> dict:
    """Persist a freshly fetched model list so the next settings visit renders it instantly."""
    entry = {"fetched_at": int(time.time()), "models": models}
    with LOCK:
        current = load()
        cache = dict(current.get("model_cache") or {})
        cache[provider] = entry
        current["model_cache"] = cache
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(
            json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return entry


def update(values: dict) -> dict:
    with LOCK:
        current = _apply(load(), values)
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(
            json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return public()
