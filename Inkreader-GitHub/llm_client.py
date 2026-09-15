"""Provider-agnostic streaming client for the AI providers in ``providers.py``.

Supports four wire protocols: OpenAI Chat Completions, OpenAI Responses,
Anthropic Messages and Google Gemini generateContent. Routing is decided per
request from the saved provider and model.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Generator
from dataclasses import dataclass
from uuid import uuid4

import providers
from providers import (
    CUSTOM_PROVIDER,
    PROTOCOL_ANTHROPIC,
    PROTOCOL_CHAT,
    PROTOCOL_GEMINI,
    PROTOCOL_RESPONSES,
)

USER_AGENT = "InkRead/1.0"
ANTHROPIC_VERSION = "2023-06-01"
# OpenCode routes and prompt-caches by session; keep one id for the process.
SESSION_ID = str(uuid4())


@dataclass
class Route:
    provider_id: str
    protocol: str
    base_url: str
    model: str
    api_key: str
    headers: dict[str, str]
    key_required: bool

    def url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"


def _normalize_base_url(value: str, protocol: str) -> str:
    base = str(value or "").strip().rstrip("/")
    if not base:
        return ""
    if protocol in {PROTOCOL_CHAT, PROTOCOL_RESPONSES} and not base.endswith("/v1"):
        # Users often paste the host only; every OpenAI-compatible service mounts /v1.
        if not base.split("/")[-1].startswith("v"):
            base += "/v1"
    return base


def resolve_route(settings: dict) -> Route:
    provider_id = str(settings.get("provider") or providers.DEFAULT_PROVIDER)
    if provider_id not in providers.PROVIDERS:
        provider_id = CUSTOM_PROVIDER
    provider = providers.get_provider(provider_id)
    model = str(settings.get("model") or provider.default_model or "").strip()
    protocol = provider.protocol_for(model) if model else provider.protocol
    if provider.custom_base_url:
        base_url = _normalize_base_url(str(settings.get("base_url") or provider.base_url), protocol)
    else:
        base_url = provider.base_url
    headers = dict(provider.headers)
    if provider.session_header:
        headers["x-opencode-session"] = SESSION_ID
    return Route(
        provider_id=provider_id,
        protocol=protocol,
        base_url=base_url,
        model=model,
        api_key=str(settings.get("api_key") or "").strip(),
        headers=headers,
        key_required=provider.key_required,
    )


def _auth_headers(route: Route) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream, application/json",
        "User-Agent": USER_AGENT,
        **route.headers,
    }
    if route.api_key:
        if route.protocol == PROTOCOL_ANTHROPIC:
            headers["x-api-key"] = route.api_key
            headers["Authorization"] = f"Bearer {route.api_key}"
        elif route.protocol == PROTOCOL_GEMINI:
            headers["x-goog-api-key"] = route.api_key
        else:
            headers["Authorization"] = f"Bearer {route.api_key}"
    if route.protocol == PROTOCOL_ANTHROPIC:
        headers["anthropic-version"] = ANTHROPIC_VERSION
    return headers


def _split_data_url(data_url: str) -> tuple[str, str]:
    header, encoded = data_url.split(",", 1)
    mime = header[5:].split(";", 1)[0] or "image/png"
    return mime, encoded


# ---------------------------------------------------------------------------
# Request builders
# ---------------------------------------------------------------------------


def _chat_messages(messages: list[dict]) -> list[dict]:
    prepared: list[dict] = []
    for message in messages:
        item = {"role": message.get("role"), "content": message.get("content", "")}
        image = str(message.get("image_data_url") or "")
        if image and item["role"] == "user":
            item["content"] = [
                {"type": "text", "text": str(item["content"] or "请解读这张论文截图")},
                {"type": "image_url", "image_url": {"url": image}},
            ]
        prepared.append(item)
    return prepared


def _responses_input(messages: list[dict]) -> tuple[str, list[dict]]:
    instructions: list[str] = []
    items: list[dict] = []
    for message in messages:
        role = message.get("role")
        content = str(message.get("content") or "")
        if role == "system":
            instructions.append(content)
            continue
        image = str(message.get("image_data_url") or "")
        if image and role == "user":
            items.append({
                "role": "user",
                "content": [
                    {"type": "input_text", "text": content or "请解读这张论文截图"},
                    {"type": "input_image", "image_url": image},
                ],
            })
        else:
            items.append({"role": role, "content": content})
    return "\n\n".join(instructions), items


def _anthropic_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    system: list[str] = []
    items: list[dict] = []
    for message in messages:
        role = message.get("role")
        content = str(message.get("content") or "")
        if role == "system":
            system.append(content)
            continue
        if role not in {"user", "assistant"}:
            continue
        image = str(message.get("image_data_url") or "")
        if image and role == "user":
            mime, encoded = _split_data_url(image)
            blocks = [
                {"type": "text", "text": content or "请解读这张论文截图"},
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": mime, "data": encoded},
                },
            ]
            items.append({"role": "user", "content": blocks})
        else:
            items.append({"role": role, "content": content})
    # Anthropic requires alternating roles starting with user.
    merged: list[dict] = []
    for item in items:
        if merged and merged[-1]["role"] == item["role"]:
            previous = merged[-1]
            previous_text = previous["content"] if isinstance(previous["content"], str) else ""
            current_text = item["content"] if isinstance(item["content"], str) else ""
            if isinstance(previous["content"], str) and isinstance(item["content"], str):
                previous["content"] = f"{previous_text}\n\n{current_text}"
                continue
        merged.append(item)
    if merged and merged[0]["role"] != "user":
        merged.insert(0, {"role": "user", "content": "（继续）"})
    return "\n\n".join(system), merged


def _gemini_contents(messages: list[dict]) -> tuple[str, list[dict]]:
    system: list[str] = []
    contents: list[dict] = []
    for message in messages:
        role = message.get("role")
        text = str(message.get("content") or "")
        if role == "system":
            system.append(text)
            continue
        if role not in {"user", "assistant"}:
            continue
        parts: list[dict] = [{"text": text or "请解读这张论文截图"}]
        image = str(message.get("image_data_url") or "")
        if image and role == "user":
            mime, encoded = _split_data_url(image)
            parts.append({"inlineData": {"mimeType": mime, "data": encoded}})
        contents.append({"role": "model" if role == "assistant" else "user", "parts": parts})
    return "\n\n".join(system), contents


def build_request(
    route: Route,
    messages: list[dict],
    *,
    max_tokens: int = 3500,
    temperature: float = 0.35,
    stream: bool = True,
) -> tuple[str, dict[str, str], dict]:
    headers = _auth_headers(route)
    if route.protocol == PROTOCOL_RESPONSES:
        instructions, items = _responses_input(messages)
        payload: dict = {
            "model": route.model,
            "input": items,
            "max_output_tokens": max_tokens,
            "stream": stream,
        }
        if instructions:
            payload["instructions"] = instructions
        if not route.model.lower().startswith(("gpt-5", "gpt-6", "o1", "o3", "o4")):
            payload["temperature"] = temperature
        return route.url("responses"), headers, payload
    if route.protocol == PROTOCOL_ANTHROPIC:
        system, items = _anthropic_messages(messages)
        payload = {
            "model": route.model,
            "messages": items,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }
        if system:
            payload["system"] = system
        return route.url("messages"), headers, payload
    if route.protocol == PROTOCOL_GEMINI:
        system, contents = _gemini_contents(messages)
        payload = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        action = "streamGenerateContent?alt=sse" if stream else "generateContent"
        model = urllib.parse.quote(route.model, safe="")
        return route.url(f"models/{model}:{action}"), headers, payload
    payload = {
        "model": route.model,
        "messages": _chat_messages(messages),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": stream,
    }
    return route.url("chat/completions"), headers, payload


# ---------------------------------------------------------------------------
# Stream parsers
# ---------------------------------------------------------------------------


def _responses_output_text(response: dict) -> str:
    parts: list[str] = []
    for item in response.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
    return "".join(parts)


def _parse_event(protocol: str, event: dict, state: dict) -> str:
    """Return streamed text for one SSE payload, recording terminal info in state."""
    if protocol == PROTOCOL_RESPONSES:
        event_type = event.get("type")
        if event_type in {"response.output_text.delta", "output_text.delta"}:
            return str(event.get("delta") or "")
        if event_type == "response.completed":
            state["completed_text"] = _responses_output_text(event.get("response") or {})
        elif event_type in {"response.failed", "response.incomplete", "error"}:
            failed = event.get("response") or {}
            error = failed.get("error") or event.get("error") or {}
            state["error"] = (
                (error.get("message") if isinstance(error, dict) else str(error))
                or (failed.get("incomplete_details") or {}).get("reason")
                or "AI 响应未完成"
            )
        return ""
    if protocol == PROTOCOL_ANTHROPIC:
        event_type = event.get("type")
        if event_type == "content_block_delta":
            delta = event.get("delta") or {}
            if delta.get("type") == "text_delta":
                return str(delta.get("text") or "")
        elif event_type == "error":
            error = event.get("error") or {}
            state["error"] = error.get("message") or "AI 响应失败"
        return ""
    if protocol == PROTOCOL_GEMINI:
        if event.get("error"):
            state["error"] = (event["error"] or {}).get("message") or "AI 响应失败"
            return ""
        parts: list[str] = []
        for candidate in event.get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                if isinstance(part, dict) and not part.get("thought") and isinstance(part.get("text"), str):
                    parts.append(part["text"])
        return "".join(parts)
    # Chat Completions. Reasoning models stream ``reasoning`` deltas with a null
    # ``content``; only the visible answer is forwarded.
    if event.get("error"):
        error = event["error"]
        state["error"] = error.get("message") if isinstance(error, dict) else str(error)
        return ""
    choices = event.get("choices") or []
    if not choices:
        return ""
    choice = choices[0] or {}
    delta = choice.get("delta") or {}
    content = delta.get("content")
    if isinstance(content, str) and content:
        return content
    # Some gateways answer non-streaming even when stream=true.
    message = choice.get("message") or {}
    if isinstance(message.get("content"), str):
        state["completed_text"] = message["content"]
    return ""


def _http_error_message(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        body = ""
    detail = ""
    try:
        data = json.loads(body) if body else {}
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, dict):
            detail = str(error.get("message") or error.get("type") or "")
        elif isinstance(error, str):
            detail = error
        elif isinstance(data, dict) and data.get("message"):
            detail = str(data["message"])
    except ValueError:
        detail = body.strip()[:300]
    if "free tier can only be used in OpenCode" in detail:
        detail = "OpenCode 免费模型需要会话标识，请更新到最新版本的砚读后重试"
    return f"HTTP {exc.code}: {detail or exc.reason}"


def stream(settings: dict, messages: list[dict], *, timeout: int = 180) -> Generator[str, None, str]:
    route = resolve_route(settings)
    if route.key_required and not route.api_key:
        raise RuntimeError("尚未配置 AI API Key")
    if not route.base_url:
        raise RuntimeError("尚未配置接口地址")
    if not route.model:
        raise RuntimeError("尚未选择模型")
    url, headers, payload = build_request(route, messages)
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    state: dict = {"completed_text": "", "error": ""}
    emitted = False
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = str(response.headers.get("Content-Type") or "")
            if "text/event-stream" not in content_type:
                body = response.read().decode("utf-8", errors="replace")
                try:
                    text = _non_stream_text(route.protocol, json.loads(body))
                except ValueError:
                    text = ""
                if text:
                    yield text
                    return route.model
                raise RuntimeError("AI 返回了空响应")
            for raw in response:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                text = _parse_event(route.protocol, event, state)
                if text:
                    emitted = True
                    yield text
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_http_error_message(exc)) from exc
    if not emitted and state["completed_text"]:
        yield state["completed_text"]
        emitted = True
    if not emitted:
        raise RuntimeError(state["error"] or "AI 返回了空响应")
    return route.model


def _non_stream_text(protocol: str, data: dict) -> str:
    if protocol == PROTOCOL_RESPONSES:
        return _responses_output_text(data)
    if protocol == PROTOCOL_ANTHROPIC:
        return "".join(
            block.get("text", "")
            for block in data.get("content") or []
            if isinstance(block, dict) and block.get("type") == "text"
        )
    if protocol == PROTOCOL_GEMINI:
        return "".join(
            part.get("text", "")
            for candidate in data.get("candidates") or []
            for part in (candidate.get("content") or {}).get("parts") or []
            if isinstance(part, dict) and not part.get("thought")
        )
    choices = data.get("choices") or []
    if choices:
        content = (choices[0].get("message") or {}).get("content")
        return content if isinstance(content, str) else ""
    return ""


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def test_connection(settings: dict) -> dict:
    """Send a minimal prompt and report latency plus the first reply characters."""
    started = time.perf_counter()
    route = resolve_route(settings)
    try:
        chunks: list[str] = []
        for chunk in stream(settings, [{"role": "user", "content": "请只回复两个字：你好"}], timeout=60):
            chunks.append(chunk)
            if sum(len(part) for part in chunks) >= 40:
                break
        reply = "".join(chunks).strip()
        return {
            "ok": True,
            "provider": route.provider_id,
            "model": route.model,
            "protocol": route.protocol,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "reply": reply[:80],
        }
    except (RuntimeError, urllib.error.URLError, OSError, ValueError) as exc:
        return {
            "ok": False,
            "provider": route.provider_id,
            "model": route.model,
            "protocol": route.protocol,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "error": str(exc)[:400],
        }


def list_models(settings: dict, *, timeout: int = 20) -> list[dict]:
    """Fetch the remote model list and merge it with the static catalog metadata."""
    route = resolve_route(settings)
    provider = providers.get_provider(route.provider_id)
    if not provider.supports_model_listing:
        raise RuntimeError("该供应商不提供模型列表接口")
    if not route.base_url:
        raise RuntimeError("尚未配置接口地址")
    if route.key_required and not route.api_key:
        raise RuntimeError("请先填写 API Key")
    protocol = provider.protocol
    listing_route = Route(**{**route.__dict__, "protocol": protocol})
    headers = _auth_headers(listing_route)
    headers.pop("Content-Type", None)
    headers["Accept"] = "application/json"
    request = urllib.request.Request(listing_route.url("models"), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_http_error_message(exc)) from exc
    items = data.get("data") if isinstance(data, dict) else None
    if items is None and isinstance(data, dict):
        items = data.get("models")
    if not isinstance(items, list):
        items = []
    result: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or item.get("name") or "").strip()
        if protocol == PROTOCOL_GEMINI:
            model_id = model_id.removeprefix("models/")
            methods = item.get("supportedGenerationMethods") or []
            if methods and "generateContent" not in methods:
                continue
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        known = provider.find_model(model_id)
        display = str(item.get("display_name") or item.get("displayName") or item.get("name") or "")
        if display.startswith("models/") or display == model_id:
            display = ""
        pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
        modalities = item.get("architecture", {}).get("input_modalities") if isinstance(item.get("architecture"), dict) else None
        free = (
            known.free if known
            else model_id.endswith(":free") or model_id.endswith("-free")
            or (bool(pricing) and str(pricing.get("prompt", "1")) in {"0", "0.0"})
        )
        vision = known.vision if known else bool(modalities and "image" in modalities)
        result.append({
            "id": model_id,
            "name": known.name if known else display or model_id,
            "vision": vision,
            "free": free,
        })
    result.sort(key=lambda entry: (not entry["free"], entry["id"].lower()))
    return result
