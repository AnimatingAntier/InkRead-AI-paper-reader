from __future__ import annotations

import base64
import unittest
from unittest.mock import patch

from agent_service import _prepare_api_messages, run_agent
from ocr_service import clean_image_data_url, image_mode, windows_ocr


class ScreenshotAiTests(unittest.TestCase):
    def test_image_model_detection(self) -> None:
        self.assertEqual(image_mode("gpt-4o-mini"), "vision")
        self.assertEqual(image_mode("claude-3.7-sonnet"), "vision")
        self.assertEqual(image_mode("openrouter/free"), "ocr")
        self.assertEqual(image_mode("deepseek-r1"), "ocr")
        self.assertEqual(image_mode("future-vision-model"), "vision")

    def test_image_data_url_is_validated(self) -> None:
        raw = b"\x89PNG\r\n\x1a\n" + b"test"
        data_url = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
        self.assertEqual(clean_image_data_url(data_url), data_url)
        with self.assertRaises(ValueError):
            clean_image_data_url("data:text/plain;base64,dGVzdA==")

    def test_multimodal_messages_match_both_api_formats(self) -> None:
        messages = [
            {
                "role": "user",
                "content": "解释截图",
                "image_data_url": "data:image/png;base64,AAAA",
            }
        ]
        responses = _prepare_api_messages(messages, True)
        chat = _prepare_api_messages(messages, False)
        self.assertEqual(responses[0]["content"][1]["type"], "input_image")
        self.assertEqual(chat[0]["content"][1]["type"], "image_url")

    @patch("ocr_service.subprocess.run", side_effect=OSError("unavailable"))
    def test_windows_ocr_uses_dom_text_fallback(self, _run) -> None:
        data_url = "data:image/png;base64," + base64.b64encode(b"png").decode("ascii")
        self.assertEqual(windows_ocr(data_url, "  fallback   paper text  "), "fallback paper text")

    @patch("agent_service._openai_stream", return_value=iter(["OCR 回答 [P1]"]))
    @patch("agent_service.windows_ocr", return_value="Detected formula and table")
    @patch("agent_service.retrieve", return_value=[])
    @patch("agent_service.get_document", return_value={"title": "Paper"})
    @patch("agent_service.settings_store.load")
    def test_text_model_routes_screenshot_through_ocr(
        self,
        load_settings,
        _get_document,
        _retrieve,
        run_ocr,
        openai_stream,
    ) -> None:
        load_settings.return_value = {
            "model": "openrouter/free",
            "api_key": "test-key",
            "web_search": False,
        }
        data_url = "data:image/png;base64," + base64.b64encode(b"png").decode("ascii")

        events = list(
            run_agent(
                {
                    "message": "解释截图",
                    "document_ids": ["paper"],
                    "image_data_url": data_url,
                    "image_ocr_text": "DOM fallback",
                }
            )
        )

        run_ocr.assert_called_once()
        source_event = next(event for event in events if event["type"] == "sources")
        self.assertEqual(source_event["paper"][0]["section"], "截图 OCR 文字")
        sent_messages = openai_stream.call_args.args[0]
        self.assertNotIn("image_data_url", sent_messages[-1])

    @patch("agent_service._openai_stream", return_value=iter(["视觉回答"]))
    @patch("agent_service.windows_ocr")
    @patch("agent_service.retrieve", return_value=[])
    @patch("agent_service.get_document", return_value={"title": "Paper"})
    @patch("agent_service.settings_store.load")
    def test_vision_model_receives_original_screenshot(
        self,
        load_settings,
        _get_document,
        _retrieve,
        run_ocr,
        openai_stream,
    ) -> None:
        load_settings.return_value = {
            "model": "gpt-4o-mini",
            "api_key": "test-key",
            "web_search": False,
        }
        data_url = "data:image/png;base64," + base64.b64encode(b"png").decode("ascii")

        list(
            run_agent(
                {
                    "message": "解释截图",
                    "document_ids": ["paper"],
                    "image_data_url": data_url,
                }
            )
        )

        run_ocr.assert_not_called()
        sent_messages = openai_stream.call_args.args[0]
        self.assertEqual(sent_messages[-1]["image_data_url"], data_url)


if __name__ == "__main__":
    unittest.main()
