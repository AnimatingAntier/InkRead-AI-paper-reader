from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from translation_service import reset_translation_status, translate_to_chinese, translation_status


def local_result(text: str, reason: str) -> dict[str, str]:
    return {
        "source": text,
        "translation": "本地译文",
        "from": "en",
        "to": "zh",
        "provider": "local",
        "fallback_reason": reason,
    }


class TranslationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_translation_status()

    @patch("translation_service.requests.post")
    @patch("translation_service.settings_store.load")
    def test_baidu_is_checked_then_used_first(self, load_settings: Mock, post: Mock) -> None:
        load_settings.return_value = {
            "baidu_translate_appid": "test-appid",
            "baidu_translate_api_key": "test-" + "api-key",
        }
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "from": "en",
            "to": "zh",
            "trans_result": [{"src": "paper", "dst": "论文"}],
        }
        post.return_value = response

        result = translate_to_chinese("paper")

        self.assertEqual(result["translation"], "论文")
        self.assertEqual(result["provider"], "baidu")
        self.assertEqual(post.call_count, 2)
        request = post.call_args
        self.assertEqual(request.kwargs["json"]["appid"], "test-appid")
        self.assertEqual(request.kwargs["headers"]["Authorization"], "Bearer test-api-key")

    @patch("translation_service.requests.post")
    @patch("translation_service.settings_store.load")
    def test_identical_text_uses_session_cache(
        self, load_settings: Mock, post: Mock
    ) -> None:
        load_settings.return_value = {
            "baidu_translate_appid": "test-appid",
            "baidu_translate_api_key": "test-" + "api-key",
        }
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "from": "en",
            "to": "zh",
            "trans_result": [{"src": "paper", "dst": "论文"}],
        }
        post.return_value = response

        first = translate_to_chinese("paper")
        second = translate_to_chinese("paper")

        self.assertEqual(first, second)
        self.assertEqual(first["translation"], "论文")
        self.assertEqual(post.call_count, 2)

    @patch("translation_service._translate_local", side_effect=local_result)
    @patch("translation_service.settings_store.load")
    def test_missing_appid_uses_local_translation(
        self, load_settings: Mock, translate_local: Mock
    ) -> None:
        load_settings.return_value = {
            "baidu_translate_appid": "",
            "baidu_translate_api_key": "test-" + "api-key",
        }

        result = translate_to_chinese("paper")

        self.assertEqual(result["provider"], "local")
        self.assertIn("APP ID", result["fallback_reason"])
        translate_local.assert_called_once()

    @patch("translation_service._translate_local", side_effect=local_result)
    @patch("translation_service.requests.post")
    @patch("translation_service.settings_store.load")
    def test_auth_error_is_detected_and_uses_local(
        self, load_settings: Mock, post: Mock, translate_local: Mock
    ) -> None:
        load_settings.return_value = {
            "baidu_translate_appid": "test-appid",
            "baidu_translate_api_key": "bad-key",
        }
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"error_code": 54001, "error_msg": "invalid token"}
        post.return_value = response

        result = translate_to_chinese("paper")

        self.assertEqual(result["provider"], "local")
        self.assertIn("鉴权失败", result["fallback_reason"])
        translate_local.assert_called_once()

    @patch("translation_service._translate_local", side_effect=local_result)
    @patch("translation_service.requests.post")
    @patch("translation_service.settings_store.load")
    def test_monthly_quota_switches_to_local_for_the_session(
        self, load_settings: Mock, post: Mock, translate_local: Mock
    ) -> None:
        load_settings.return_value = {
            "baidu_translate_appid": "test-appid",
            "baidu_translate_api_key": "test-" + "api-key",
        }
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "error_code": 54004,
            "error_msg": "monthly quota exceeded",
        }
        post.return_value = response

        first = translate_to_chinese("paper")
        second = translate_to_chinese("another paper")
        status = translation_status()

        self.assertEqual(first["provider"], "local")
        self.assertEqual(second["provider"], "local")
        self.assertTrue(status["quota_exhausted"])
        self.assertEqual(post.call_count, 1)
        self.assertEqual(translate_local.call_count, 2)

    @patch("translation_service.requests.post")
    @patch("translation_service.settings_store.load")
    def test_startup_status_probe_is_cached(self, load_settings: Mock, post: Mock) -> None:
        load_settings.return_value = {
            "baidu_translate_appid": "test-appid",
            "baidu_translate_api_key": "test-" + "api-key",
        }
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "from": "en",
            "trans_result": [{"src": "Hello", "dst": "你好"}],
        }
        post.return_value = response

        first = translation_status(force=True)
        second = translation_status()

        self.assertTrue(first["baidu_available"])
        self.assertEqual(second["provider"], "baidu")
        self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
