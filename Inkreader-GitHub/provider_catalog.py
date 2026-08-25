from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

USER_AGENT = "InkRead/1.1"
MODELS_TIMEOUT_SECONDS = 8

# Official vendor catalog. Base URLs are built-in so users only paste an API key.
# key_url is the official page to create/copy a key; empty for custom endpoints.
CATALOG: list[dict] = [
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_style": "chat_completions",
        "key_url": "https://openrouter.ai/settings/keys",
        "needs_base_url": False,
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "api_style": "chat_completions",
        "key_url": "https://platform.openai.com/api-keys",
        "needs_base_url": False,
    },
    {
        "id": "opencode_zen",
        "name": "OpenCode Zen",
        "base_url": "https://opencode.ai/zen/v1",
        "api_style": "responses",
        "key_url": "https://opencode.ai/auth",
        "needs_base_url": False,
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "api_style": "chat_completions",
        "key_url": "https://platform.deepseek.com/api_keys",
        "needs_base_url": False,
    },
    {
        "id": "moonshot",
        "name": "Moonshot / Kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "api_style": "chat_completions",
        "key_url": "https://platform.moonshot.cn/console/api-keys",
        "needs_base_url": False,
    },
    {
        "id": "dashscope",
        "name": "阿里云百炼 / Qwen",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_style": "chat_completions",
        "key_url": "https://bailian.console.aliyun.com/?tab=model#/api-key",
        "needs_base_url": False,
    },
    {
        "id": "zhipu",
        "name": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_style": "chat_completions",
        "key_url": "https://open.bigmodel.cn/usercenter/apikeys",
        "needs_base_url": False,
    },
    {
        "id": "siliconflow",
        "name": "SiliconFlow",
        "base_url": "https://api.siliconflow.cn/v1",
        "api_style": "chat_completions",
        "key_url": "https://cloud.siliconflow.cn/account/ak",
        "needs_base_url": False,
    },
    {
        "id": "groq",
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "api_style": "chat_completions",
        "key_url": "https://console.groq.com/keys",
        "needs_base_url": False,
    },
    {
        "id": "xai",
        "name": "xAI Grok",
        "base_url": "https://api.x.ai/v1",
        "api_style": "chat_completions",
        "key_url": "https://console.x.ai/",
        "needs_base_url": False,
    },
    {
        "id": "gemini",
        "name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_style": "chat_completions",
        "key_url": "https://aistudio.google.com/apikey",
        "needs_base_url": False,
    },
    {
        "id": "openai_compatible",
        "name": "自定义 OpenAI 兼容",
        "base_url": "",
        "api_style": "chat_completions",
        "key_url": "",
        "needs_base_url": True,
    },
]

CATALOG_BY_ID = {entry["id"]: entry for entry in CATALOG}

_JUNK_TOKENS = (
    "text-embedding",
    "whisper",
    "tts",
    "dall-e",
    "dall.e",
    "dall_e",
    "babbage",
)

_refresh_lock = threading.Lock()
_refresh_thread: threading.Thread | None = None


def get_catalog_entry(provider_id: str) -> dict | None:
    return CATALOG_BY_ID.get(str(provider_id or ""))


def catalog_base_url(provider_id: str) -> str:
    entry = get_catalog_entry(provider_id)
    return str((entry or {}).get("base_url") or "")


def public_catalog() -> list[dict]:
    return [
        {
            "id": entry["id"],
            "name": entry["name"],
            "base_url": entry["base_url"],
            "key_url": entry["key_url"],
            "api_style": entry["api_style"],
            "needs_base_url": bool(entry["needs_base_url"]),
        }
        for entry in CATALOG
    ]


def resolve_base_url(provider_id: str, stored_base_url: str = "") -> str:
    entry = get_catalog_entry(provider_id)
    if entry and not entry.get("needs_base_url"):
        return str(entry.get("base_url") or "")
    return str(stored_base_url or (entry or {}).get("base_url") or "").rstrip("/")


def _is_junk_model(model_id: str) -> bool:
    low = str(model_id or "").lower()
    if not low:
        return True
    if "embedding" in low:
        return True
    if any(token in low for token in _JUNK_TOKENS):
        return True
    if low == "ada" or low.startswith("ada-") or "-ada-" in low or low.endswith("-ada"):
        return True
    return False


def _parse_models_payload(payload: object) -> list[dict]:
    if isinstance(payload, dict):
        data = payload.get("data")
        if data is None:
            data = payload.get("models")
        if data is None and payload.get("id"):
            data = [payload]
    else:
        data = payload
    if isinstance(data, dict):
        data = list(data.values()) if data else []
    if not isinstance(data, list):
        return []
    models: list[dict] = []
    seen: set[str] = set()
    for item in data:
        if isinstance(item, str):
            model_id = item.strip()
            name = model_id
        elif isinstance(item, dict):
            model_id = str(item.get("id") or item.get("model") or "").strip()
            name = str(item.get("name") or model_id).strip() or model_id
        else:
            continue
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        models.append({"id": model_id, "name": name or model_id})
    return models


def fetch_models(provider_id: str, api_key: str, base_url: str = "") -> list[dict]:
    """GET {base}/models with Bearer auth. Never logs the API key."""
    key = str(api_key or "").strip()
    base = resolve_base_url(provider_id, base_url).rstrip("/")
    if not key or not base:
        return []
    url = base + "/models"
    headers = {
        "Authorization": "Bearer " + key,
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=MODELS_TIMEOUT_SECONDS) as response:
            raw = response.read()
        payload = json.loads(raw.decode("utf-8", errors="replace") or "null")
    except urllib.error.HTTPError as exc:
        # 401: leave cache and do not wipe the key. Body may contain vendor messages;
        # never include the request headers (they hold the key).
        logger.info("model list request failed for %s (HTTP %s)", provider_id, exc.code)
        return []
    except Exception as exc:
        logger.info("model list request failed for %s (%s)", provider_id, type(exc).__name__)
        return []
    models = _parse_models_payload(payload)
    filtered = [item for item in models if not _is_junk_model(item["id"])]
    if filtered:
        return filtered
    return models


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def refresh_all_keyed_providers() -> dict[str, list[dict]]:
    """Refresh model lists for every vendor that already has a saved API key.

    On failure the previous cache is kept. Keys are never logged or removed.
    """
    import settings_store

    snapshot = settings_store.load()
    providers = snapshot.get("providers") or {}
    jobs: dict[str, tuple[str, str]] = {}
    if isinstance(providers, dict):
        for pid, slot in providers.items():
            if not isinstance(slot, dict):
                continue
            key = str(slot.get("api_key") or "").strip()
            if not key:
                continue
            jobs[str(pid)] = (key, str(slot.get("base_url") or ""))
    active = str(snapshot.get("provider") or "")
    active_key = str(snapshot.get("api_key") or "").strip()
    if active and active_key:
        jobs.setdefault(active, (active_key, str(snapshot.get("base_url") or "")))

    fetched: dict[str, list[dict]] = {}
    for pid, (key, stored_base) in jobs.items():
        models = fetch_models(pid, key, stored_base)
        if models:
            fetched[pid] = models
    if fetched:
        settings_store.merge_fetched_models(fetched, updated_at=_utc_now())
    return fetched


def kick_model_refresh() -> None:
    """Spawn a daemon thread so startup / settings GET is not blocked."""
    global _refresh_thread

    def _run() -> None:
        try:
            refresh_all_keyed_providers()
        except Exception:
            logger.info("background model refresh failed")
        finally:
            _refresh_lock.release()

    if not _refresh_lock.acquire(blocking=False):
        return
    _refresh_thread = threading.Thread(
        target=_run, name="inkread-model-refresh", daemon=True
    )
    _refresh_thread.start()
