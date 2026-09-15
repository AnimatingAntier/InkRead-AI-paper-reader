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

    def test_model_cache_is_backend_owned_and_survives_saves(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps(settings_store.DEFAULTS), encoding="utf-8")
            models = [{"id": "m1", "name": "M1", "free": True, "vision": False}]
            with (
                patch.object(settings_store, "SETTINGS_FILE", path),
                patch.dict(os.environ, {"INKREAD_NO_LEGACY_IMPORT": "1"}),
            ):
                entry = settings_store.remember_models("openrouter", models)
                self.assertEqual(entry["models"], models)
                self.assertGreater(entry["fetched_at"], 0)

                # A regular save from the form must not wipe or overwrite the cache.
                settings_store.update({"model": "m1", "model_cache": {"openrouter": "junk"}})
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(saved["model_cache"]["openrouter"]["models"], models)
                self.assertEqual(saved["model"], "m1")

                # And it is exposed to the frontend unmasked.
                self.assertEqual(settings_store.public()["model_cache"]["openrouter"]["models"], models)

    def test_settings_saved_for_a_removed_provider_fall_back_to_the_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                json.dumps({
                    **settings_store.DEFAULTS,
                    "provider": "opencode_zen",
                    "model": "nemotron-3-ultra-free",
                    "api_key": "zen-key",
                    "base_url": "https://opencode.ai/zen/v1",
                    "api_keys": {"opencode_zen": "zen-key", "openrouter": "or-key"},
                    "model_cache": {"opencode_zen": {"fetched_at": 1, "models": []}},
                }),
                encoding="utf-8",
            )
            with (
                patch.object(settings_store, "SETTINGS_FILE", path),
                patch.dict(os.environ, {"INKREAD_NO_LEGACY_IMPORT": "1", "OPENROUTER_API_KEY": ""}),
            ):
                loaded = settings_store.load()
                self.assertEqual(loaded["provider"], "openrouter")
                self.assertEqual(loaded["model"], "openrouter/free")
                self.assertEqual(loaded["api_key"], "or-key")
                self.assertEqual(loaded["base_url"], "")
                self.assertNotIn("opencode_zen", loaded["model_cache"])
                self.assertTrue(settings_store.public()["configured"])


if __name__ == "__main__":
    unittest.main()
