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
    prepared: list[dict] = []
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


def _zen_uses_responses(provider: str, base_url: str, model: str) -> bool:
    """OpenCode Zen routes by model: GPT/Grok/Muse Spark use /responses.

    Free models such as mimo-v2.5-free, plus DeepSeek/GLM/Kimi/MiniMax,
    use OpenAI-compatible /chat/completions per official Zen docs.
    """
    zen = provider == "opencode_zen" or str(base_url).rstrip("/").endswith("/zen/v1")
    if not zen:
        return False
    mid = str(model or "").lower()
    return mid.startswith(("gpt-", "grok-", "muse-spark"))


def _openai_stream(messages: list[dict]) -> Generator[str, None, str]:
    settings = settings_store.load()
    api_key = settings.get("api_key", "")
    if not api_key:
        raise RuntimeError("尚未配置 AI API Key")
    base_url = settings.get("base_url", "").rstrip("/")
    model = settings.get("model") or "openrouter/free"
    provider = settings.get("provider")
    is_responses = _zen_uses_responses(str(provider or ""), base_url, str(model or ""))
    api_messages = _prepare_api_messages(messages, is_responses)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "InkRead/1.0",
        "HTTP-Referer": "http://127.0.0.1:3217",
        "X-Title": "InkRead",
    }
    if is_responses:
        url = base_url + "/responses"
        payload = {
            "model": model,
            "input": api_messages,
            "max_output_tokens": 3500,
            "temperature": 0.35,
            "stream": True,
        }
    else:
        url = base_url + "/chat/completions"
        payload = {
            "model": model,
            "messages": api_messages,
            "max_tokens": 3500,
            "temperature": 0.35,
            "stream": True,
        }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
    )
    emitted_text = False
    completed_text = ""
    terminal_error = ""
    with urllib.request.urlopen(request, timeout=180) as response:
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
            text = ""
            if is_responses:
                event_type = event.get("type")
                if event_type in {"response.output_text.delta", "output_text.delta"}:
                    text = event.get("delta", "")
                elif event.get("delta") and isinstance(event["delta"], str):
                    text = event["delta"]
                elif event_type == "response.completed":
                    completed_text = _response_output_text(event.get("response") or {})
                elif event_type in {"response.failed", "response.incomplete"}:
                    failed_response = event.get("response") or {}
                    error = failed_response.get("error") or {}
                    terminal_error = (
                        error.get("message")
                        or (failed_response.get("incomplete_details") or {}).get("reason")
                        or "AI 响应未完成"
                    )
            else:
                choices = event.get("choices") or []
                if choices:
                    text = choices[0].get("delta", {}).get("content") or ""
            if text:
                emitted_text = True
                yield text
    if not emitted_text and completed_text:
        yield completed_text
        emitted_text = True
    if not emitted_text:
        raise RuntimeError(terminal_error or "AI 返回了空响应")
    return model


def generate_margin_comment(document_id: str, selected_text: str) -> str:
    selected = re.sub(r"\s+", " ", str(selected_text or "")).strip()
    if len(selected) < 2:
        raise ValueError("请先扫描需要批注的文字")
    if len(selected) > 8_000:
        selected = selected[:8_000]
    document = get_document(str(document_id or ""))
    title = str(document.get("title") or "当前论文")
    messages = [
        {
            "role": "system",
            "content": (
                "你是砚读 InkRead 的学术旁注助手。请为用户选中的论文原文生成一则精炼中文批注。"
                "批注应优先解释这段话的含义、数学或方法直觉、重要性、限制或复现注意事项；"
                "只选择最有价值的角度，不要面面俱到。"
                "直接输出 60–180 个汉字的批注正文，不要标题、编号、Markdown 标记、来源编号、"
                "客套话，也不要声称你已联网核实。若原文信息不足，应使用谨慎措辞。"
            ),
        },
        {
            "role": "user",
            "content": f"论文《{title}》\n\n选中的原文：\n{selected}",
        },
    ]
    content = "".join(_openai_stream(messages)).strip()
    content = re.sub(r"^\s*(?:#+\s*)?(?:批注|注释)[:：]?\s*", "", content)
    content = content.strip(" \n\t\"'\u201c\u201d")
    if not content:
        raise RuntimeError("AI 未生成批注内容")
    return content[:1200]


def _compact_retry_messages(
    question: str,
    classification: dict,
    titles: list[str],
    paper_sources: list[dict],
    web_sources: list[dict],
    web_insufficient: bool,
    image_data_url: str = "",
) -> list[dict]:
    compact_paper: list[dict] = []
    for source in paper_sources[:3]:
        item = dict(source)
        item["content"] = str(item.get("content") or "")[:1600]
        compact_paper.append(item)
    compact_web: list[dict] = []
    for source in web_sources[:3]:
        item = dict(source)
        item["content"] = str(item.get("content") or "")[:900]
        compact_web.append(item)
    compact_sources = _serialize_sources(compact_paper, compact_web)
    if web_insufficient:
        prompt = f"""你是砚读 InkRead 的 AI 阅读助手。你必须直接回答用户问题，禁止返回空内容。

论文与网络检索没有找到足够依据，用户界面已经显示了资料不足提示，不要重复该提示。

回答要求：
1. 使用你的既有知识给出有帮助的回答，并以“## 基于 AI 既有知识”作为第一个标题。
2. 明确说明模型知识可能过时，不能把“最新”“当前最好”说成已经联网核实的事实。
3. 可以参考下方论文片段，但不得编造来源、论文、年份、指标或链接。
4. 区分可靠判断、不确定信息和建议核验方向。
5. 使用清晰的中文 Markdown；即使没有任何来源，也必须给出正文。

当前论文：{'；'.join(titles) if titles else '未选择论文'}

<可用论文片段>
{compact_sources or '没有可用论文片段。'}
</可用论文片段>
"""
    else:
        prompt = _system_prompt(
            classification,
            compact_sources,
            titles,
            web_insufficient=False,
        )
        prompt += "\n这是精简上下文重试。请直接输出最终回答，不要描述重试过程。"
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": question},
    ]
    if image_data_url:
        messages[-1]["image_data_url"] = image_data_url
    return messages


def _local_answer(
    question: str,
    sources: list[dict],
    *,
    configured: bool = False,
    web_insufficient: bool = False,
) -> str:
    if not sources:
        prefix = "**未找到足够的新资料。**\n\n" if web_insufficient else ""
        if configured:
            return prefix + "AI 接口未能生成正文，请稍后重试或更换模型。"
        return prefix + "未找到足够依据。请先导入并选择论文，或在设置中配置 AI 服务。"
    top = sources[:3]
    lines: list[str] = []
    if web_insufficient:
        lines.extend([
            "**未找到足够的新资料。**",
            "",
            "> AI 接口未能完成知识兜底，下面先展示论文中可核验的相关原文。",
            "",
        ])
    elif configured:
        lines.extend(["AI 接口未能生成正文，下面先展示最相关的论文原文：", ""])
    else:
        lines.extend(["当前尚未配置 AI 模型，先为你展示检索 Agent 找到的最相关原文：", ""])
    for index, source in enumerate(top, 1):
        excerpt = re.sub(r"\s+", " ", source.get("content", "")).strip()[:420]
        lines.append(
            f"- **{source.get('section', '原文')}**：{excerpt}… [P{index}]"
        )
    if not configured:
        lines.extend([
            "",
            "> 在“设置”中填写 OpenRouter 或 OpenAI 兼容接口后，可获得完整的综合分析与事实校验。",
        ])
    return "\n".join(lines)


def _verify(answer: str, paper_sources: list[dict], web_sources: list[dict]) -> dict:
    cited_paper = {int(value) for value in re.findall(r"\[P(\d+)\]", answer)}
    cited_web = {int(value) for value in re.findall(r"\[W(\d+)\]", answer)}
    valid_paper = {value for value in cited_paper if 1 <= value <= len(paper_sources)}
    valid_web = {value for value in cited_web if 1 <= value <= len(web_sources)}
    invalid = (cited_paper - valid_paper) | (cited_web - valid_web)
    sentences = [part for part in re.split(r"[。！？\n]+", answer) if len(part.strip()) > 12]
    cited_sentences = [part for part in sentences if re.search(r"\[[PW]\d+\]", part)]
    coverage = len(cited_sentences) / max(1, len(sentences))

    source_tokens = set()
    for source in [*paper_sources, *web_sources]:
        source_tokens.update(tokenize(source.get("content", "")))
    answer_tokens = tokenize(answer)
    overlap = sum(1 for token in answer_tokens if token in source_tokens) / max(1, len(answer_tokens))
    uses_model_knowledge = "基于 AI 既有知识" in answer
    confidence = min(0.99, 0.42 + coverage * 0.35 + overlap * 0.35)
    if uses_model_knowledge:
        confidence = min(confidence, 0.58)
    passed = (
        not uses_model_knowledge
        and not invalid
        and bool(valid_paper or valid_web)
        and coverage >= 0.22
    )
    if uses_model_knowledge:
        message = "回答包含 AI 既有知识兜底，相关内容未由当前来源核实，请复核"
    elif passed:
        message = "来源编号有效，回答已通过可追溯性检查"
    else:
        message = "部分结论缺少就近来源，请将其视为低置信度分析"
    return {
        "passed": passed,
        "confidence": round(confidence, 2),
        "citationCoverage": round(coverage, 2),
        "invalidCitations": sorted(invalid),
        "message": message,
    }


def run_agent(body: dict) -> Generator[dict, None, None]:
    question = str(body.get("message") or "").strip()
    document_ids = [str(value) for value in body.get("document_ids") or []]
    selected_text = str(body.get("selected_text") or "").strip()
    history = body.get("history") or []
    image_data_url = ""
    image_ocr_text = ""
    screenshot_mode = ""
    if body.get("image_data_url"):
        image_data_url = clean_image_data_url(body.get("image_data_url"))
        model = str(settings_store.load().get("model") or "")
        screenshot_mode = image_mode(model)
        if screenshot_mode == "ocr":
            image_ocr_text = windows_ocr(
                image_data_url,
                str(body.get("image_ocr_text") or ""),
            )
            if image_ocr_text:
                selected_text = "\n\n".join(
                    value for value in (selected_text, image_ocr_text) if value
                )
            image_data_url = ""
    if not question and (image_data_url or image_ocr_text):
        question = "请解读这张论文截图，说明其中的文字、图表或公式表达了什么。"
    if not question:
        yield {"type": "error", "message": "问题不能为空"}
        return

    classification = _classify(question, document_ids)
    detail = f"识别为 {classification['intent']}"
    if screenshot_mode == "vision":
        detail += " · 多模态模型直接识图"
    elif screenshot_mode == "ocr":
        detail += (
            f" · 文本模型使用本地 OCR（{len(image_ocr_text)} 字）"
            if image_ocr_text
            else " · 文本模型未识别到截图文字"
        )
    yield _status("orchestrator", "running", detail)

    titles: list[str] = []
    for document_id in document_ids:
        try:
            titles.append(get_document(document_id)["title"])
        except FileNotFoundError:
            continue

    retrieval_query = f"{question}\n{selected_text}" if selected_text else question
    yield _status("long_context", "running", "在独立论文命名空间中检索章节")
    paper_sources = retrieve(document_ids, retrieval_query, limit=10)
    paper_evidence_insufficient = _paper_evidence_insufficient(question, paper_sources)
    if selected_text:
        paper_sources.insert(0, {
            "source_type": "paper_internal",
            "document_id": document_ids[0] if document_ids else "",
            "document_title": titles[0] if titles else "当前选区",
            "section": "截图 OCR 文字" if image_ocr_text else "用户选中的原文",
            "page": None,
            "content": selected_text[:6000],
            "relevance_score": 1.0,
        })
    context_detail = f"命中 {len(paper_sources)} 个原文片段"
    if paper_evidence_insufficient:
        context_detail += "，但未找到足以解释问题的论文证据"
    yield _status("long_context", "done", context_detail)

    requested_current_information = classification["needs_web"]
    needs_web = (
        bool(body.get("web_search"))
        or requested_current_information
        or paper_evidence_insufficient
    )
    classification["needs_web"] = needs_web
    classification["paper_evidence_insufficient"] = paper_evidence_insufficient
    web_sources: list[dict] = []
    search_enabled = bool(settings_store.load().get("web_search"))
    if needs_web and search_enabled:
        yield _status("web_search", "running", "检索学术网络来源并与论文原文隔离")
        search_query = f"{question} {selected_text} {' '.join(titles)}".strip()
        web_sources, errors = academic_search(search_query)
        detail = f"获得 {len(web_sources)} 条学术来源"
        if not web_sources and errors:
            detail = "未找到足够的外部资料，将启用 AI 既有知识兜底"
        elif len(web_sources) < 2:
            detail = "外部资料不足，将启用 AI 既有知识兜底"
        yield _status("web_search", "done", detail)
    elif needs_web:
        yield _status("web_search", "skipped", "联网检索未启用，将使用 AI 既有知识兜底")
    else:
        yield _status("web_search", "skipped", "当前问题无需联网")

    web_insufficient = needs_web and len(web_sources) < 2
    yield {
        "type": "sources",
        "paper": paper_sources,
        "web": web_sources,
        "classification": classification,
    }
    yield _status("orchestrator", "done", "已完成上下文编排，开始生成回答")

    source_text = _serialize_sources(paper_sources, web_sources)
    messages = [{
        "role": "system",
        "content": _system_prompt(
            classification,
            source_text,
            titles,
            web_insufficient=web_insufficient,
        ),
    }]
    if screenshot_mode == "vision":
        messages[0]["content"] += (
            "\n\n用户随问题附带了一张论文截图。请直接观察截图中的文字、公式、图表、"
            "结构和视觉关系；基于截图得出的结论标注为“截图观察”，不要伪造 [P#]/[W#] 引用。"
        )
    for item in history[-8:]:
        role = item.get("role")
        content = str(item.get("content") or "")
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:8000]})
    user_message = {"role": "user", "content": question}
    if image_data_url:
        user_message["image_data_url"] = image_data_url
    messages.append(user_message)

    answer_parts: list[str] = []
    if web_insufficient:
        if requested_current_information:
            notice = (
                "**未找到足够的新资料。**\n\n"
                "> 以下回答会结合论文原文与 AI 的既有知识；AI 既有知识可能不是最新信息，请谨慎核验。\n\n"
            )
        else:
            notice = (
                "**现有论文与网络资料中未找到足够依据。**\n\n"
                "> 以下回答将使用 AI 的既有知识进行解释；相关内容未由当前来源核实，请谨慎判断。\n\n"
            )
        answer_parts.append(notice)
        yield {"type": "content", "text": notice}
    configured = bool(settings_store.load().get("api_key"))
    try:
        if configured:
            generated_chars = 0
            try:
                for chunk in _openai_stream(messages):
                    generated_chars += len(chunk)
                    answer_parts.append(chunk)
                    yield {"type": "content", "text": chunk}
            except (RuntimeError, urllib.error.URLError, urllib.error.HTTPError):
                if generated_chars:
                    raise
                yield _status("orchestrator", "running", "首次生成无正文，正在精简上下文重试")
                retry_messages = _compact_retry_messages(
                    question,
                    classification,
                    titles,
                    paper_sources,
                    web_sources,
                    web_insufficient,
                    image_data_url,
                )
                for chunk in _openai_stream(retry_messages):
                    generated_chars += len(chunk)
                    answer_parts.append(chunk)
                    yield {"type": "content", "text": chunk}
                yield _status("orchestrator", "done", "精简上下文重试成功")
        else:
            local = _local_answer(
                question,
                paper_sources,
                configured=False,
                web_insufficient=False,
            )
            answer_parts.append(local)
            yield {"type": "content", "text": local}
    except (RuntimeError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        fallback = _local_answer(
            question,
            paper_sources,
            configured=configured,
            web_insufficient=False,
        )
        answer_parts.append(fallback)
        yield {"type": "warning", "message": f"AI 接口不可用：{str(exc)[:220]}"}
        yield {"type": "content", "text": fallback}

    answer = "".join(answer_parts)
    yield _status("fact_check", "running", "核验来源编号、引用覆盖与语义重合")
    verification = _verify(answer, paper_sources, web_sources)
    yield {"type": "verification", **verification}
    yield _status("fact_check", "done", verification["message"])
    yield {"type": "done"}
