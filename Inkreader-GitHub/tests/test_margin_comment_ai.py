from __future__ import annotations

import unittest
from unittest.mock import patch

import agent_service


class MarginCommentAiTests(unittest.TestCase):
    @patch("agent_service._openai_stream")
    @patch("agent_service.get_document")
    def test_generates_clean_concise_comment(self, get_document, openai_stream) -> None:
        get_document.return_value = {"title": "Attention Test"}
        openai_stream.return_value = iter(["## 批注：", "这段话强调路由只读取块摘要，从而降低选择候选块的计算成本。"])

        result = agent_service.generate_margin_comment(
            "paper-id",
            "The router only reads block summaries.",
        )

        self.assertEqual(
            result,
            "这段话强调路由只读取块摘要，从而降低选择候选块的计算成本。",
        )
        messages = openai_stream.call_args.args[0]
        self.assertIn("Attention Test", messages[-1]["content"])
        self.assertIn("block summaries", messages[-1]["content"])

    def test_rejects_empty_selection(self) -> None:
        with self.assertRaises(ValueError):
            agent_service.generate_margin_comment("paper-id", " ")


if __name__ == "__main__":
    unittest.main()
