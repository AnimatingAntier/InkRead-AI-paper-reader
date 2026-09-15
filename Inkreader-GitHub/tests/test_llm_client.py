from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import llm_client
import providers


class FakeResponse:
    def __init__(self, events: list[dict], content_type: str = "text/event-stream"):
        self.lines = [
            f"data: {json.dumps(event, ensure_ascii=False)}\n".encode("utf-8")
            for event in events
        ]
        self.headers = {"Content-Type": content_type}

    def __iter__(self):
        return iter(self.lines)

    def read(self) -> bytes:
        return b"".join(line[5:].strip() for line in self.lines)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class RoutingTests(unittest.TestCase):
    def test_preset_providers_do_not_need_a_user_supplied_url(self) -> None:
        route = llm_client.resolve_route({
            "provider": "opencode_go",
            "model": "glm-5.3-flash",
            "api_key": "k",
            "base_url": "https://stale.example/v1",
        })
        self.assertEqual(route.base_url, "https://opencode.ai/zen/go/v1")
        self.assertEqual(route.protocol, providers.PROTOCOL_CHAT)
        self.assertEqual(route.headers["x-opencode-session"], llm_client.SESSION_ID)

    def test_opencode_routes_each_model_family_to_its_native_protocol(self) -> None:
        cases = {
            "claude-sonnet-5": providers.PROTOCOL_ANTHROPIC,
            "gpt-5.6-luna": providers.PROTOCOL_RESPONSES,
            "grok-4.6": providers.PROTOCOL_RESPONSES,
            "muse-spark-1.3-contributor": providers.PROTOCOL_RESPONSES,
            "gemini-3.8-flash": providers.PROTOCOL_GEMINI,
            "mimo-v2.5": providers.PROTOCOL_CHAT,
            "minimax-m3": providers.PROTOCOL_ANTHROPIC,
            "brand-new-model": providers.PROTOCOL_CHAT,
        }
        for model, expected in cases.items():
            with self.subTest(model=model):
                route = llm_client.resolve_route({"provider": "opencode_go", "model": model})
                self.assertEqual(route.protocol, expected)

    def test_removed_provider_ids_fall_back_to_the_custom_preset(self) -> None:
        route = llm_client.resolve_route({"provider": "opencode_zen", "model": "x", "base_url": "http://h/v1"})
        self.assertEqual(route.base_url, "http://h/v1")

    def test_custom_provider_keeps_user_url_and_appends_v1(self) -> None:
        route = llm_client.resolve_route({
            "provider": "openai_compatible",
            "model": "local-model",
            "base_url": "http://localhost:8000/",
        })
        self.assertEqual(route.base_url, "http://localhost:8000/v1")
        self.assertFalse(route.key_required)

    def test_unknown_provider_falls_back_to_custom(self) -> None:
        route = llm_client.resolve_route({"provider": "nope", "base_url": "https://x.test/v1"})
        self.assertEqual(route.provider_id, providers.CUSTOM_PROVIDER)

    def test_default_provider_exists_and_has_a_free_default_model(self) -> None:
        provider = providers.get_provider(providers.DEFAULT_PROVIDER)
        model = provider.find_model(provider.default_model)
        self.assertIsNotNone(model)
        self.assertTrue(model.free)


class RequestBuilderTests(unittest.TestCase):
    def test_chat_completions_request(self) -> None:
        route = llm_client.resolve_route({"provider": "deepseek", "model": "deepseek-v4-flash", "api_key": "k"})
        url, headers, payload = llm_client.build_request(route, [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ])
        self.assertEqual(url, "https://api.deepseek.com/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer k")
        self.assertEqual(payload["messages"][0], {"role": "system", "content": "sys"})
        self.assertTrue(payload["stream"])

    def test_responses_request_moves_system_into_instructions(self) -> None:
        route = llm_client.resolve_route({"provider": "openai", "model": "gpt-5.4", "api_key": "k"})
        url, _headers, payload = llm_client.build_request(route, [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi", "image_data_url": "data:image/png;base64,AAAA"},
        ])
        self.assertEqual(url, "https://api.openai.com/v1/responses")
        self.assertEqual(payload["instructions"], "sys")
        self.assertEqual(payload["input"][0]["content"][1]["type"], "input_image")
        self.assertNotIn("temperature", payload)

    def test_anthropic_request(self) -> None:
        route = llm_client.resolve_route({"provider": "anthropic", "model": "claude-sonnet-5", "api_key": "k"})
        url, headers, payload = llm_client.build_request(route, [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b", "image_data_url": "data:image/jpeg;base64,QUJD"},
        ])
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(headers["x-api-key"], "k")
        self.assertEqual(headers["anthropic-version"], llm_client.ANTHROPIC_VERSION)
        self.assertEqual(payload["system"], "sys")
        self.assertEqual(payload["messages"][-1]["content"][1]["source"]["media_type"], "image/jpeg")

    def test_gemini_request(self) -> None:
        route = llm_client.resolve_route({"provider": "google", "model": "gemini-3.8-flash", "api_key": "k"})
        url, headers, payload = llm_client.build_request(route, [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "yo"},
        ])
        self.assertEqual(
            url,
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:streamGenerateContent?alt=sse",
        )
        self.assertEqual(headers["x-goog-api-key"], "k")
        self.assertEqual(payload["systemInstruction"]["parts"][0]["text"], "sys")
        self.assertEqual(payload["contents"][1]["role"], "model")


class StreamParsingTests(unittest.TestCase):
    def _stream(self, settings: dict, events: list[dict], **kwargs) -> list[str]:
        with patch("llm_client.urllib.request.urlopen", return_value=FakeResponse(events, **kwargs)):
            return list(llm_client.stream(settings, [{"role": "user", "content": "hi"}]))

    def test_chat_stream_skips_reasoning_deltas(self) -> None:
        events = [
            {"choices": [{"delta": {"reasoning": "thinking…", "content": None}}]},
            {"choices": [{"delta": {"content": "答"}}]},
            {"choices": [{"delta": {"content": "案"}}]},
        ]
        chunks = self._stream({"provider": "openrouter", "model": "openrouter/free", "api_key": "k"}, events)
        self.assertEqual(chunks, ["答", "案"])

    def test_anthropic_stream_collects_text_deltas(self) -> None:
        events = [
            {"type": "message_start"},
            {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "…"}},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "你好"}},
            {"type": "message_stop"},
        ]
        chunks = self._stream({"provider": "anthropic", "model": "claude-sonnet-5", "api_key": "k"}, events)
        self.assertEqual(chunks, ["你好"])

    def test_gemini_stream_skips_thought_parts(self) -> None:
        events = [
            {"candidates": [{"content": {"parts": [{"text": "思考", "thought": True}]}}]},
            {"candidates": [{"content": {"parts": [{"text": "回答"}]}}]},
        ]
        chunks = self._stream({"provider": "google", "model": "gemini-3.8-flash", "api_key": "k"}, events)
        self.assertEqual(chunks, ["回答"])

    def test_non_stream_json_body_is_accepted(self) -> None:
        events = [{"choices": [{"message": {"role": "assistant", "content": "一次性正文"}}]}]
        chunks = self._stream(
            {"provider": "openai_compatible", "model": "m", "base_url": "http://h/v1"},
            events,
            content_type="application/json",
        )
        self.assertEqual(chunks, ["一次性正文"])

    def test_missing_key_is_reported_before_any_request(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "API Key"):
            list(llm_client.stream({"provider": "openrouter", "model": "openrouter/free"}, []))

    def test_ollama_does_not_require_a_key(self) -> None:
        events = [{"choices": [{"delta": {"content": "ok"}}]}]
        chunks = self._stream({"provider": "ollama", "model": "qwen3:8b"}, events)
        self.assertEqual(chunks, ["ok"])


if __name__ == "__main__":
    unittest.main()
