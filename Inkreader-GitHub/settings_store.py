from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock

from config import SETTINGS_FILE
from provider_catalog import (
    get_catalog_entry,
    public_catalog,
    resolve_base_url,
)

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
    "providers": {},
}


def _masked(value: object) -> str:
    secret = str(value or "")
    return MASK_CHAR * len(secret)


def _is_mask(value: object) -> bool:
    text = str(value or "")
    return bool(text) and set(text) == {MASK_CHAR}


def _empty_slot() -> dict:
    return {
        "api_key": "",
        "model": "",
        "base_url": "",
        "models": [],
        "models_updated_at": "",
    }


def _normalize_models(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        return []
    models: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            model_id = item.strip()
            name = model_id
        elif isinstance(item, dict):
            model_id = str(item.get("id") or "").strip()
            name = str(item.get("name") or model_id).strip() or model_id
        else:
            continue
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        models.append({"id": model_id, "name": name})
    return models


def _normalize_slot(raw: object) -> dict:
    slot = _empty_slot()
    if not isinstance(raw, dict):
        return slot
    slot["api_key"] = str(raw.get("api_key") or "")
    slot["model"] = str(raw.get("model") or "")
    slot["base_url"] = str(raw.get("base_url") or "")
    slot["models"] = _normalize_models(raw.get("models"))
    slot["models_updated_at"] = str(raw.get("models_updated_at") or "")
    return slot


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


def _apply_catalog_base(provider_id: str, slot: dict) -> None:
    entry = get_catalog_entry(provider_id)
    if entry and not entry.get("needs_base_url"):
        slot["base_url"] = str(entry.get("base_url") or "")


def _migrate_providers(data: dict) -> tuple[dict, bool]:
    """Copy legacy top-level vendor fields into providers[provider] when missing."""
    changed = False
    raw_providers = data.get("providers")
    if not isinstance(raw_providers, dict):
        raw_providers = {}
        changed = True
    providers = {
        str(pid): _normalize_slot(slot) for pid, slot in raw_providers.items()
    }
    provider_id = str(data.get("provider") or DEFAULTS["provider"])
    if provider_id not in providers:
        slot = _empty_slot()
        slot["api_key"] = str(data.get("api_key") or "")
        slot["model"] = str(data.get("model") or "")
        slot["base_url"] = str(data.get("base_url") or "")
        _apply_catalog_base(provider_id, slot)
        providers[provider_id] = slot
        changed = True
    else:
        _apply_catalog_base(provider_id, providers[provider_id])
    data["providers"] = providers
    entry = get_catalog_entry(provider_id)
    if entry and not entry.get("needs_base_url"):
        catalog_url = str(entry.get("base_url") or "")
        if catalog_url and data.get("base_url") != catalog_url:
            data["base_url"] = catalog_url
            providers[provider_id]["base_url"] = catalog_url
            changed = True
    return data, changed


def _write(data: dict) -> None:
    payload = {key: data[key] for key in DEFAULTS if key in data}
    stored = {**DEFAULTS, **payload}
    stored["providers"] = {
        str(pid): _normalize_slot(slot)
        for pid, slot in (data.get("providers") or {}).items()
    }
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load() -> dict:
    with LOCK:
        data: dict = {}
        existed = SETTINGS_FILE.is_file()
        had_providers = False
        if existed:
            try:
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            had_providers = isinstance(data.get("providers"), dict)
        elif not os.getenv("INKREAD_NO_LEGACY_IMPORT"):
            data = _legacy_settings()
            if data:
                data, _ = _migrate_providers({**DEFAULTS, **data})
                _write(data)
                existed = True
                had_providers = True
        result = {**DEFAULTS, **data}
        result, migrated = _migrate_providers(result)
        if existed and (migrated and not had_providers):
            _write(result)
    result["api_key"] = result.get("api_key") or os.getenv("OPENROUTER_API_KEY", "")
    result["serpapi_key"] = result.get("serpapi_key") or os.getenv("SERPAPI_API_KEY", "")
    result["baidu_translate_appid"] = (
        result.get("baidu_translate_appid") or os.getenv("BAIDU_TRANSLATE_APPID", "")
    )
    result["baidu_translate_api_key"] = (
        result.get("baidu_translate_api_key") or os.getenv("BAIDU_TRANSLATE_API_KEY", "")
    )
    return result


def _public_providers(settings: dict) -> dict:
    stored = settings.get("providers") if isinstance(settings.get("providers"), dict) else {}
    public: dict = {}
    for entry in public_catalog():
        pid = entry["id"]
        slot = _normalize_slot(stored.get(pid))
        if pid in stored:
            slot = _normalize_slot(stored[pid])
        key = str(slot.get("api_key") or "")
        base = resolve_base_url(pid, slot.get("base_url") or "")
        public[pid] = {
            "has_key": bool(key),
            "api_key": _masked(key),
            "model": slot.get("model") or "",
            "base_url": base,
            "models": slot.get("models") or [],
            "models_updated_at": slot.get("models_updated_at") or "",
        }
    for pid, slot in stored.items():
        if pid in public:
            continue
        key = str(slot.get("api_key") or "")
        public[pid] = {
            "has_key": bool(key),
            "api_key": _masked(key),
            "model": slot.get("model") or "",
            "base_url": slot.get("base_url") or "",
            "models": slot.get("models") or [],
            "models_updated_at": slot.get("models_updated_at") or "",
        }
    return public


def public() -> dict:
    settings = load()
    out = {
        key: settings.get(key, DEFAULTS.get(key))
        for key in DEFAULTS
        if key != "providers"
    }
    out["api_key"] = _masked(settings.get("api_key"))
    out["serpapi_key"] = _masked(settings.get("serpapi_key"))
    out["baidu_translate_api_key"] = _masked(
        settings.get("baidu_translate_api_key")
    )
    out["catalog"] = public_catalog()
    out["providers"] = _public_providers(settings)
    out["configured"] = bool(settings.get("api_key"))
    out["translation_configured"] = bool(
        settings.get("baidu_translate_appid") and settings.get("baidu_translate_api_key")
    )
    return out


def _slot_for(current: dict, provider_id: str) -> dict:
    providers = current.setdefault("providers", {})
    if not isinstance(providers, dict):
        providers = {}
        current["providers"] = providers
    slot = providers.get(provider_id)
    if not isinstance(slot, dict):
        slot = _empty_slot()
        providers[provider_id] = slot
    else:
        slot = _normalize_slot(slot)
        providers[provider_id] = slot
    return slot


def update(values: dict) -> dict:
    allowed = set(DEFAULTS)
    current = load()
    with LOCK:
        posted_provider = values.get("provider")
        if posted_provider is not None:
            provider_id = str(posted_provider or DEFAULTS["provider"])
        else:
            provider_id = str(current.get("provider") or DEFAULTS["provider"])
        previous_provider = str(current.get("provider") or DEFAULTS["provider"])
        switching = provider_id != previous_provider

        for key, value in values.items():
            if key not in allowed or key == "providers":
                continue
            if key in SECRET_FIELDS and _is_mask(value):
                continue
            if key == "api_key":
                continue
            if key == "comment_idle_opacity":
                try:
                    value = max(0.15, min(1.0, float(value)))
                except (TypeError, ValueError):
                    value = DEFAULTS["comment_idle_opacity"]
            current[key] = value

        current["provider"] = provider_id
        slot = _slot_for(current, provider_id)

        posted_key = values.get("api_key") if "api_key" in values else None
        if posted_key is None:
            if switching:
                current["api_key"] = slot.get("api_key") or ""
            else:
                current["api_key"] = current.get("api_key") or slot.get("api_key") or ""
        elif _is_mask(posted_key) or not str(posted_key or "").strip():
            stored = slot.get("api_key") or ""
            if switching:
                current["api_key"] = stored
            elif stored:
                current["api_key"] = stored
            elif _is_mask(posted_key):
                current["api_key"] = current.get("api_key") or ""
            else:
                current["api_key"] = stored or current.get("api_key") or ""
        else:
            current["api_key"] = posted_key

        if "model" in values:
            slot["model"] = str(current.get("model") or "")
        elif switching and slot.get("model"):
            current["model"] = slot["model"]
        else:
            slot["model"] = str(current.get("model") or slot.get("model") or "")

        entry = get_catalog_entry(provider_id)
        if entry and not entry.get("needs_base_url"):
            current["base_url"] = str(entry.get("base_url") or "")
            slot["base_url"] = current["base_url"]
        elif "base_url" in values:
            slot["base_url"] = str(current.get("base_url") or "")
        elif switching and slot.get("base_url"):
            current["base_url"] = slot["base_url"]
        else:
            slot["base_url"] = str(current.get("base_url") or slot.get("base_url") or "")

        slot["api_key"] = str(current.get("api_key") or "")

        if isinstance(values.get("providers"), dict):
            for pid, incoming in values["providers"].items():
                if not isinstance(incoming, dict):
                    continue
                dest = _slot_for(current, str(pid))
                if "api_key" in incoming:
                    incoming_key = incoming.get("api_key")
                    if incoming_key and not _is_mask(incoming_key):
                        dest["api_key"] = str(incoming_key)
                if "model" in incoming and incoming.get("model") is not None:
                    dest["model"] = str(incoming.get("model") or "")
                if "base_url" in incoming and incoming.get("base_url") is not None:
                    dest["base_url"] = str(incoming.get("base_url") or "")
                    other = get_catalog_entry(str(pid))
                    if other and not other.get("needs_base_url"):
                        dest["base_url"] = str(other.get("base_url") or "")

        active_slot = _slot_for(current, provider_id)
        active_slot["api_key"] = str(current.get("api_key") or "")
        active_slot["model"] = str(current.get("model") or "")
        _apply_catalog_base(provider_id, active_slot)
        if entry and not entry.get("needs_base_url"):
            current["base_url"] = active_slot["base_url"]
        else:
            active_slot["base_url"] = str(current.get("base_url") or "")

        _write(current)
    return public()


def merge_fetched_models(fetched: dict[str, list[dict]], updated_at: str = "") -> None:
    """Write refreshed model lists without touching stored API keys."""
    if not fetched:
        return
    with LOCK:
        current = load()
        providers = current.setdefault("providers", {})
        if not isinstance(providers, dict):
            providers = {}
            current["providers"] = providers
        for pid, models in fetched.items():
            if not models:
                continue
            slot = _slot_for(current, str(pid))
            slot["models"] = _normalize_models(models)
            if updated_at:
                slot["models_updated_at"] = updated_at
            _apply_catalog_base(str(pid), slot)
        _write(current)
