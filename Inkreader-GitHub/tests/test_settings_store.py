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


if __name__ == "__main__":
    unittest.main()
