from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import agent_service


class FakeResponse:
    def __init__(self, events: list[dict]):
        self.lines = [
            f"data: {json.dumps(event, ensure_ascii=False)}\n".encode("utf-8")
            for event in events
        ]

    def __enter__(self):
        return iter(self.lines)

    def __exit__(self, exc_type, exc, traceback):
        return False


class AgentServiceTests(unittest.TestCase):
    def test_recent_comparison_triggers_web_search(self):
        result = agent_service._classify("最近还有什么方法优于 DETR？", ["paper"])

        self.assertTrue(result["needs_web"])
        self.assertEqual(result["intent"], "targeted_qa")

    def test_unknown_definition_is_insufficient_paper_evidence(self):
        sources = [{
            "content": "Segment Anything Model 的论文正文，介绍 promptable segmentation。",
            "relevance_score": 0.8,
        }]

        self.assertEqual(agent_service._definition_term("Text-to-Mas是什么"), "Text-to-Mas")
        self.assertTrue(
            agent_service._paper_evidence_insufficient("Text-to-Mas是什么", sources)
        )

    def test_completed_response_text_is_used_when_deltas_are_missing(self):
        events = [{
            "type": "response.completed",
            "response": {
                "output": [{
                    "type": "message",
                    "content": [{"type": "output_text", "text": "兜底正文"}],
                }],
            },
        }]
        settings = {
            "api_key": "test-key",
            "base_url": "https://opencode.ai/zen/v1",
            "model": "test-model",
            "provider": "opencode_zen",
        }

        with (
            patch("agent_service.settings_store.load", return_value=settings),
            patch("agent_service.urllib.request.urlopen", return_value=FakeResponse(events)),
        ):
            chunks = list(agent_service._openai_stream([{"role": "user", "content": "测试"}]))

        self.assertEqual(chunks, ["兜底正文"])

    def test_empty_completed_response_raises_clear_error(self):
        events = [{
            "type": "response.completed",
            "response": {"output": [{"type": "reasoning", "content": []}]},
        }]
        settings = {
            "api_key": "test-key",
            "base_url": "https://opencode.ai/zen/v1",
            "model": "test-model",
            "provider": "opencode_zen",
        }

        with (
            patch("agent_service.settings_store.load", return_value=settings),
            patch("agent_service.urllib.request.urlopen", return_value=FakeResponse(events)),
        ):
            with self.assertRaisesRegex(RuntimeError, "空响应"):
                list(agent_service._openai_stream([{"role": "user", "content": "测试"}]))

    def test_insufficient_web_prompt_allows_labeled_model_knowledge(self):
        prompt = agent_service._system_prompt(
            {"intent": "targeted_qa"},
            "没有可用来源。",
            ["测试论文"],
            web_insufficient=True,
        )

        self.assertIn("允许使用你的既有知识", prompt)
        self.assertIn("禁止返回空答案", prompt)
        self.assertIn("没有找到足够依据", prompt)

    def test_agent_retries_empty_answer_and_keeps_knowledge_notice(self):
        source = {
            "source_type": "paper_internal",
            "document_id": "paper",
            "document_title": "DETR 测试论文",
            "section": "实验",
            "page": 1,
            "content": "论文原文片段",
            "relevance_score": 0.9,
        }
        settings = {
            "api_key": "test-key",
            "web_search": True,
            "fact_check": True,
        }
        attempts = 0

        def fake_stream(messages):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("AI 返回了空响应")
            yield "## 基于 AI 既有知识\n\n这里是精简上下文生成的兜底回答。"

        with (
            patch("agent_service.settings_store.load", return_value=settings),
            patch("agent_service.get_document", return_value={"title": "DETR 测试论文"}),
            patch("agent_service.retrieve", return_value=[source]),
            patch("agent_service.academic_search", return_value=([], [])),
            patch("agent_service._openai_stream", side_effect=fake_stream),
        ):
            events = list(agent_service.run_agent({
                "message": "最近还有什么方法优于 DETR？",
                "document_ids": ["paper"],
                "history": [],
            }))

        answer = "".join(
            event["text"] for event in events if event["type"] == "content"
        )
        self.assertEqual(attempts, 2)
        self.assertTrue(answer.startswith("**未找到足够的新资料。**"))
        self.assertIn("基于 AI 既有知识", answer)
        self.assertTrue(any(
            event.get("detail") == "首次生成无正文，正在精简上下文重试"
            for event in events
        ))
        self.assertEqual(events[-1]["type"], "done")

    def test_unknown_term_uses_model_knowledge_when_search_has_no_result(self):
        source = {
            "source_type": "paper_internal",
            "document_id": "sam",
            "document_title": "Segment Anything",
            "section": "第 1 页",
            "page": 1,
            "content": "Segment Anything Model supports promptable segmentation.",
            "relevance_score": 0.7,
        }
        settings = {
            "api_key": "test-key",
            "web_search": True,
            "fact_check": True,
        }

        with (
            patch("agent_service.settings_store.load", return_value=settings),
            patch("agent_service.get_document", return_value={"title": "Segment Anything"}),
            patch("agent_service.retrieve", return_value=[source]),
            patch("agent_service.academic_search", return_value=([], ["no result"])),
            patch(
                "agent_service._openai_stream",
                return_value=iter([
                    "## 基于 AI 既有知识\n\n"
                    "Text-to-Mas 很可能是 Text-to-Mask 的截断或拼写遗漏。"
                ]),
            ),
        ):
            events = list(agent_service.run_agent({
                "message": "Text-to-Mas是什么",
                "document_ids": ["sam"],
                "selected_text": "Text-to-Mas",
                "history": [],
            }))

        answer = "".join(
            event["text"] for event in events if event["type"] == "content"
        )
        source_event = next(event for event in events if event["type"] == "sources")
        verification = next(
            event for event in events if event["type"] == "verification"
        )
        self.assertTrue(source_event["classification"]["needs_web"])
        self.assertTrue(source_event["classification"]["paper_evidence_insufficient"])
        self.assertTrue(answer.startswith("**现有论文与网络资料中未找到足够依据。**"))
        self.assertIn("基于 AI 既有知识", answer)
        self.assertFalse(verification["passed"])
        self.assertIn("未由当前来源核实", verification["message"])


if __name__ == "__main__":
    unittest.main()
