from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import settings_store


class SettingsStoreTests(unittest.TestCase):
    def test_legacy_import_requires_an_explicit_seed_file(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(settings_store._legacy_settings(), {})

    def test_explicit_seed_file_can_be_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            path.write_text(
                json.dumps({"provider": "openrouter", "model": "example/model"}),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"INKREAD_SEED_SETTINGS": str(path)}, clear=True):
                migrated = settings_store._legacy_settings()
            self.assertEqual(migrated["provider"], "openrouter")
            self.assertEqual(migrated["model"], "example/model")

    def test_public_masks_keep_exact_secret_length_and_save_preserves_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            original = {
                **settings_store.DEFAULTS,
                "api_key": "a" * 37,
                "serpapi_key": "b" * 64,
                "baidu_translate_api_key": "c" * 71,
            }
            path.write_text(json.dumps(original), encoding="utf-8")
            with (
                patch.object(settings_store, "SETTINGS_FILE", path),
                patch.dict(os.environ, {"INKREAD_NO_LEGACY_IMPORT": "1"}),
            ):
                public = settings_store.public()
                self.assertEqual(len(public["api_key"]), 37)
                self.assertEqual(len(public["serpapi_key"]), 64)
                self.assertEqual(len(public["baidu_translate_api_key"]), 71)
                self.assertEqual(set(public["api_key"]), {"•"})

                settings_store.update(
                    {
                        "api_key": public["api_key"],
                        "serpapi_key": public["serpapi_key"],
                        "baidu_translate_api_key": public["baidu_translate_api_key"],
                    }
                )
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(saved["api_key"], original["api_key"])
                self.assertEqual(saved["serpapi_key"], original["serpapi_key"])
                self.assertEqual(
                    saved["baidu_translate_api_key"],
                    original["baidu_translate_api_key"],
                )

                settings_store.update({"comment_idle_opacity": 5})
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(saved["comment_idle_opacity"], 1.0)

                settings_store.update({"comment_idle_opacity": 0})
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(saved["comment_idle_opacity"], 0.15)

    def test_legacy_file_without_providers_map_is_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "provider": "openai",
                        "api_key": "sk-legacy-key",
                        "model": "gpt-4o",
                        "base_url": "https://user-typed.example/v1",
                        "serpapi_key": "",
                        "baidu_translate_appid": "",
                        "baidu_translate_api_key": "",
                        "comment_idle_opacity": 0.58,
                        "web_search": True,
                        "fact_check": True,
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(settings_store, "SETTINGS_FILE", path),
                patch.dict(os.environ, {"INKREAD_NO_LEGACY_IMPORT": "1"}, clear=False),
            ):
                loaded = settings_store.load()
            self.assertIn("openai", loaded["providers"])
            slot = loaded["providers"]["openai"]
            self.assertEqual(slot["api_key"], "sk-legacy-key")
            self.assertEqual(slot["model"], "gpt-4o")
            self.assertEqual(slot["base_url"], "https://api.openai.com/v1")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["providers"]["openai"]["api_key"], "sk-legacy-key")
            self.assertEqual(saved["base_url"], "https://api.openai.com/v1")

    def test_mask_does_not_overwrite_top_level_or_per_provider_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({**settings_store.DEFAULTS}), encoding="utf-8")
            with (
                patch.object(settings_store, "SETTINGS_FILE", path),
                patch.dict(os.environ, {"INKREAD_NO_LEGACY_IMPORT": "1"}, clear=False),
            ):
                settings_store.update(
                    {
                        "provider": "openai",
                        "api_key": "sk-openai-secret",
                        "model": "gpt-4o-mini",
                    }
                )
                settings_store.update(
                    {
                        "provider": "deepseek",
                        "api_key": "sk-deepseek-secret",
                        "model": "deepseek-chat",
                    }
                )
                public = settings_store.public()
                settings_store.update(
                    {
                        "provider": "openai",
                        "api_key": public["providers"]["openai"]["api_key"],
                        "model": public["providers"]["openai"]["model"],
                    }
                )
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(saved["provider"], "openai")
                self.assertEqual(saved["api_key"], "sk-openai-secret")
                self.assertEqual(saved["providers"]["openai"]["api_key"], "sk-openai-secret")
                self.assertEqual(
                    saved["providers"]["deepseek"]["api_key"], "sk-deepseek-secret"
                )
                self.assertEqual(saved["providers"]["deepseek"]["model"], "deepseek-chat")

                settings_store.update(
                    {
                        "provider": "deepseek",
                        "api_key": "",
                        "model": "",
                    }
                )
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(saved["api_key"], "sk-deepseek-secret")
                self.assertEqual(
                    saved["providers"]["deepseek"]["api_key"], "sk-deepseek-secret"
                )

    def test_catalog_base_url_is_used_so_user_need_not_type_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({**settings_store.DEFAULTS}), encoding="utf-8")
            with (
                patch.object(settings_store, "SETTINGS_FILE", path),
                patch.dict(os.environ, {"INKREAD_NO_LEGACY_IMPORT": "1"}, clear=False),
            ):
                public = settings_store.update(
                    {
                        "provider": "groq",
                        "api_key": "gsk-test",
                        "model": "llama-3.1-70b-versatile",
                    }
                )
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["base_url"], "https://api.groq.com/openai/v1")
            self.assertEqual(
                saved["providers"]["groq"]["base_url"],
                "https://api.groq.com/openai/v1",
            )
            groq = next(item for item in public["catalog"] if item["id"] == "groq")
            self.assertFalse(groq["needs_base_url"])
            self.assertEqual(groq["base_url"], "https://api.groq.com/openai/v1")

    def test_public_includes_key_url_when_api_key_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({**settings_store.DEFAULTS}), encoding="utf-8")
            with (
                patch.object(settings_store, "SETTINGS_FILE", path),
                patch.dict(os.environ, {"INKREAD_NO_LEGACY_IMPORT": "1"}, clear=False),
            ):
                public = settings_store.public()
            openai = next(item for item in public["catalog"] if item["id"] == "openai")
            self.assertEqual(
                openai["key_url"], "https://platform.openai.com/api-keys"
            )
            self.assertFalse(public["providers"]["openai"]["has_key"])
            self.assertEqual(public["providers"]["openai"]["api_key"], "")
            zen = next(item for item in public["catalog"] if item["id"] == "opencode_zen")
            self.assertEqual(zen["key_url"], "https://opencode.ai/auth")
            custom = next(
                item for item in public["catalog"] if item["id"] == "openai_compatible"
            )
            self.assertTrue(custom["needs_base_url"])
            self.assertEqual(custom["key_url"], "")


class ProviderRefreshTests(unittest.TestCase):
    def test_refresh_merges_models_into_cache_without_dropping_keys(self) -> None:
        from provider_catalog import fetch_models, refresh_all_keyed_providers

        class FakeResponse:
            def __init__(self, payload: dict):
                self._raw = json.dumps(payload).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return self._raw

        payload = {
            "object": "list",
            "data": [
                {"id": "gpt-4o", "owned_by": "openai", "name": "GPT-4o"},
                {"id": "text-embedding-3-small"},
                {"id": "whisper-1"},
                {"id": "tts-1"},
                {"id": "dall-e-3"},
                {"id": "babbage-002"},
                {"id": "text-ada-001"},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            original = {
                **settings_store.DEFAULTS,
                "provider": "openai",
                "api_key": "sk-keep-me",
                "model": "gpt-4o",
                "base_url": "https://api.openai.com/v1",
                "providers": {
                    "openai": {
                        "api_key": "sk-keep-me",
                        "model": "gpt-4o",
                        "base_url": "https://api.openai.com/v1",
                        "models": [{"id": "stale-model", "name": "stale-model"}],
                        "models_updated_at": "2020-01-01T00:00:00Z",
                    }
                },
            }
            path.write_text(json.dumps(original), encoding="utf-8")
            with (
                patch.object(settings_store, "SETTINGS_FILE", path),
                patch.dict(os.environ, {"INKREAD_NO_LEGACY_IMPORT": "1"}, clear=False),
                patch(
                    "provider_catalog.urllib.request.urlopen",
                    return_value=FakeResponse(payload),
                ),
            ):
                models = fetch_models("openai", "sk-keep-me", "https://api.openai.com/v1")
                self.assertEqual(models, [{"id": "gpt-4o", "name": "GPT-4o"}])
                refresh_all_keyed_providers()
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["api_key"], "sk-keep-me")
            slot = saved["providers"]["openai"]
            self.assertEqual(slot["api_key"], "sk-keep-me")
            self.assertEqual(slot["models"], [{"id": "gpt-4o", "name": "GPT-4o"}])
            self.assertNotEqual(slot["models_updated_at"], "2020-01-01T00:00:00Z")
            self.assertTrue(slot["models_updated_at"])

    def test_refresh_http_401_keeps_cache_and_key(self) -> None:
        import urllib.error
        from email.message import Message
        from io import BytesIO
        from provider_catalog import refresh_all_keyed_providers

        error = urllib.error.HTTPError(
            "https://api.openai.com/v1/models",
            401,
            "Unauthorized",
            Message(),
            BytesIO(b'{"error":"invalid_api_key"}'),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            original = {
                **settings_store.DEFAULTS,
                "provider": "openai",
                "api_key": "sk-still-valid-here",
                "model": "gpt-4o",
                "providers": {
                    "openai": {
                        "api_key": "sk-still-valid-here",
                        "model": "gpt-4o",
                        "base_url": "https://api.openai.com/v1",
                        "models": [{"id": "cached-model", "name": "Cached"}],
                        "models_updated_at": "2024-01-01T00:00:00Z",
                    }
                },
            }
            path.write_text(json.dumps(original), encoding="utf-8")
            with (
                patch.object(settings_store, "SETTINGS_FILE", path),
                patch.dict(os.environ, {"INKREAD_NO_LEGACY_IMPORT": "1"}, clear=False),
                patch("provider_catalog.urllib.request.urlopen", side_effect=error),
            ):
                refresh_all_keyed_providers()
            saved = json.loads(path.read_text(encoding="utf-8"))
            slot = saved["providers"]["openai"]
            self.assertEqual(slot["api_key"], "sk-still-valid-here")
            self.assertEqual(
                slot["models"], [{"id": "cached-model", "name": "Cached"}]
            )
            self.assertEqual(slot["models_updated_at"], "2024-01-01T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
