from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Generator

import settings_store
from document_store import get_document
from ocr_service import clean_image_data_url, image_mode, windows_ocr
from retrieval import retrieve, tokenize
from search_agent import academic_search


def _classify(question: str, document_ids: list[str]) -> dict:
    lowered = question.lower()
    summary_words = ("总结", "概括", "摘要", "summary", "贡献")
    compare_words = ("比较", "对比", "不同", "区别", "compare", "vs")
    extract_words = ("提取", "列出", "数据", "参数", "表格", "extract")
    current_words = (
        "现在", "目前", "最近", "近期", "近年", "最新", "新方法", "新模型",
        "进展", "前沿", "排行榜", "榜单", "sota", "后来", "后续", "引用",
        "优于", "超过", "超越", "替代", "联网", "网上", "搜索", "查一下",
        "today", "latest", "recent", "current", "state of the art",
    )
    if len(document_ids) > 1 or any(word in lowered for word in compare_words):
        intent = "multi_paper_compare"
    elif any(word in lowered for word in summary_words):
        intent = "whole_paper_summary"
    elif any(word in lowered for word in extract_words):
        intent = "information_extraction"
    else:
        intent = "targeted_qa"
    return {
        "intent": intent,
        "needs_web": (
            any(word in lowered for word in current_words)
            or bool(re.search(r"\b20\d{2}\b", lowered))
        ),
        "document_count": len(document_ids),
    }


def _definition_term(question: str) -> str:
    cleaned = question.strip().strip("？?")
    chinese = re.match(
        r"^[\u201c\"']?(.{2,80}?)[\u201d\"']?\s*(?:是什么|是什么意思|什么意思|指什么|的含义(?:是什么)?)$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if chinese:
        return chinese.group(1).strip()
    english = re.match(r"^what\s+is\s+(.{2,80})$", cleaned, flags=re.IGNORECASE)
    return english.group(1).strip() if english else ""


def _paper_evidence_insufficient(question: str, paper_sources: list[dict]) -> bool:
    if not paper_sources:
        return True
    top_score = float(paper_sources[0].get("relevance_score") or 0)
    if top_score <= 0:
        return True
    term = _definition_term(question)
    if not term:
        return False
    term_key = re.sub(r"[\W_]+", "", term.lower())
    if len(term_key) < 2:
        return False
    for source in paper_sources[:6]:
        content = str(source.get("content") or "")
        content_key = re.sub(r"[\W_]+", "", content.lower())
        if term_key in content_key and len(content.strip()) >= max(160, len(term) * 4):
            return False
    return True


def _status(agent: str, state: str, detail: str) -> dict:
    return {"type": "agent_status", "agent": agent, "state": state, "detail": detail}


def _serialize_sources(paper_sources: list[dict], web_sources: list[dict]) -> str:
    blocks: list[str] = []
    for index, item in enumerate(paper_sources, 1):
        location = item.get("section") or "全文"
        if item.get("page"):
            location += f" · 第 {item['page']} 页"
        blocks.append(
            f"[P{index}] 论文原文｜{item['document_title']}｜{location}\n"
            f"{item['content'][:5000]}"
        )
    for index, item in enumerate(web_sources, 1):
        blocks.append(
            f"[W{index}] 网络检索｜{item['provider']}｜{item['title']}\n"
            f"URL: {item['url']}\n{item['content'][:1800]}"
        )
    return "\n\n---\n\n".join(blocks)


def _system_prompt(
    classification: dict,
    sources: str,
    titles: list[str],
    web_insufficient: bool = False,
) -> str:
    source_rule = (
        "1. 优先依据下方 SOURCES 作答；SOURCES 无法覆盖的问题，可以使用明确标注的 AI 既有知识补充。来源中的可核验事实仍须标注 [P1] 或 [W1]。"
        if web_insufficient
        else "1. 优先依据下方 SOURCES 作答。来源中的可核验事实必须标注 [P1] 或 [W1]；如果 SOURCES 不能回答，允许使用明确标注的 AI 既有知识继续回答。"
    )
    knowledge_policy = """
7. 当前论文与网络检索没有找到足够依据，界面已经向用户显示资料不足提示。
8. 此时允许使用你的既有知识补充回答，但必须单列“基于 AI 既有知识”小节，明确说明这些信息可能过时，不能把它们伪装成论文原文或网络检索结果，也不要为它们编造 [P#]/[W#] 引用。
9. 即使资料不足也必须给出有帮助的正文：先回答你能够可靠判断的内容，再列出不确定点和建议核验方向，禁止返回空答案。
""" if web_insufficient else """
7. 如果论文原文或网络来源不足以回答，必须继续使用你的既有知识回答，并单列“基于 AI 既有知识”小节；不得把模型记忆冒充为论文或已检索的新资料，也不得编造引用。
8. 无论资料是否充分，都必须给出有帮助的正文；不确定内容要明确标注，禁止仅以“未找到足够依据”结束回答。
"""
    return f"""你是“砚读 InkRead”的编排调度 Agent，正在协调长上下文、网络检索与事实校验三个专职 Agent。

当前任务类型：{classification['intent']}
当前论文：{'；'.join(titles) if titles else '未选择论文'}

必须遵守：
{source_rule}
2. 论文原文与网络信息必须分区。涉及“论文说了什么”只能引用 P 来源；涉及后续、最新进展才引用 W 来源。
3. 资料不支持时明确写“未找到足够依据”，绝不补写似是而非的细节。
4. 对论文作批判性判断时，把“原文事实”和“你的分析”分开表述。
5. 使用清晰、精炼的中文 Markdown。多篇比较优先用表格；公式用 LaTeX。
6. 末尾给出“依据”小节，逐条列出实际使用的来源。网络来源必须给出可点击 URL。
{knowledge_policy}

<SOURCES>
{sources or '没有可用来源。'}
</SOURCES>
"""


def _response_output_text(response: dict) -> str:
    parts: list[str] = []
    for item in response.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
    return "".join(parts)


def _prepare_api_messages(messages: list[dict], is_responses: bool) -> list[dict]:
    prepared: list[str] = []
    for message in messages:
        item = {"role": message.get("role"), "content": message.get("content", "")}
        image_data_url = str(message.get("image_data_url") or "")
        if image_data_url and item["role"] == "user":
            text = str(item["content"] or "请解读这张论文截图")
            if is_responses:
                item["content"] = [
                    {"type": "input_text", "text": text},
                    {"type": "input_image", "image_url": image_data_url},
                ]
            else:
                item["content"] = [
                    {"type": "text", "text": text},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ]
        prepared.append(item)
    return prepared
