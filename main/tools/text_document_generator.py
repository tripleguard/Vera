"""Deterministic pipeline for reports and other text documents."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Optional


_FORMAT_TOKENS = re.compile(
    r"\b(?:текстов(?:ый|ого)\s+документ|доклад|отч[её]т|реферат|статью|статья|"
    r"заметку|заметка|документ|файл|формат(?:е)?|txt|docx|word|markdown|md)\b",
    re.IGNORECASE,
)
_COMMAND_PREFIX = re.compile(
    r"^\s*(?:пожалуйста[,\s]+)?(?:создай|сделай|подготовь|сгенерируй|напиши|сохрани)\s+",
    re.IGNORECASE,
)

MAX_RESEARCH_CONTEXT = 6500


def is_text_document_request(text: str) -> bool:
    from main.tool_router import route_intent

    return route_intent(text).skill == "documents"


def extract_document_topic(text: str) -> str:
    topic = _COMMAND_PREFIX.sub("", text or "")
    topic = re.sub(r"\b(?:по\s+теме|на\s+тему|про|о|об)\b", " ", topic, flags=re.IGNORECASE)
    topic = _FORMAT_TOKENS.sub(" ", topic)
    topic = re.sub(r"\s+", " ", topic).strip(" .,:;-")
    return topic or "запрошенная тема"


def infer_document_format(text: str) -> str:
    lowered = (text or "").lower()
    if re.search(r"\b(?:docx|word)\b", lowered):
        return "docx"
    if re.search(r"\b(?:markdown|md)\b", lowered):
        return "md"
    if re.search(r"\btxt\b|текстов(?:ый|ого)\s+документ", lowered):
        return "txt"
    return "docx"


def _extract_search_result(value: Any) -> tuple[str, list[str]]:
    if isinstance(value, dict):
        text = str(value.get("text") or value.get("answer") or "")
        sources = value.get("sources") or []
        return text, [str(source) for source in sources if source]
    return str(value or ""), []


def collect_document_research(
    topic: str,
    web_search_func: Optional[Callable[[str], Any]],
) -> tuple[str, list[str], bool]:
    if not web_search_func:
        return "", [], False

    queries = (
        f"{topic}: основные факты, определения и контекст",
        f"{topic}: актуальные данные, примеры, преимущества и ограничения",
    )
    sections: list[str] = []
    sources: list[str] = []
    for query in queries:
        try:
            text, result_sources = _extract_search_result(web_search_func(query))
        except Exception:
            continue
        if len(text.strip()) < 80:
            continue
        sections.append(f"Запрос: {query}\n{text.strip()}")
        for source in result_sources:
            if source not in sources:
                sources.append(source)

    context = "\n\n".join(sections)[:MAX_RESEARCH_CONTEXT]
    return context, sources[:10], bool(context)


def generate_document_content(
    topic: str,
    llm: Any,
    *,
    research_context: str = "",
    skill_instructions: str = "",
) -> str:
    context_block = (
        f"\n\nПроверенные материалы для использования:\n{research_context}"
        if research_context
        else "\n\nИнтернет-материалы недоступны. Используй устойчивые локальные знания."
    )
    messages = [
        {
            "role": "system",
            "content": (
                "Ты редактор русскоязычных докладов и отчетов. "
                "Верни только готовый текст документа без служебных комментариев, "
                "без JSON и без описания процесса."
                + (f"\n\nПроцедура работы:\n{skill_instructions}" if skill_instructions else "")
            ),
        },
        {
            "role": "user",
            "content": (
                f"Подготовь полноценный документ на тему «{topic}». "
                "Используй ясный заголовок, введение, содержательные разделы и вывод. "
                "Текст должен быть связным, подробным и пригодным для сохранения без редактирования."
                f"{context_block}"
            ),
        },
    ]
    result = llm.create_chat_completion(
        messages=messages,
        max_tokens=3200,
        temperature=0.35,
        top_p=0.85,
        chat_template_kwargs={"enable_thinking": False},
        reasoning_budget=0,
    )
    message = result.get("choices", [{}])[0].get("message", {})
    content = message.get("content") or ""
    if isinstance(content, list):
        content = "".join(
            str(part.get("text") or "") if isinstance(part, dict) else str(part)
            for part in content
        )
    content = re.sub(r"<think>.*?</think>", "", str(content), flags=re.DOTALL).strip()
    content = re.sub(r"^```(?:markdown|text)?\s*|\s*```$", "", content, flags=re.IGNORECASE).strip()
    if len(content) < 120:
        raise RuntimeError("Модель не сформировала достаточный текст документа.")
    return content


def _extract_created_path(result: str) -> Optional[str]:
    match = re.search(r"(?:создан|создана):\s*(.+?\.(?:txt|md|docx))\b", result, re.IGNORECASE)
    return match.group(1).strip() if match else None


def execute_text_document_creation(
    text: str,
    llm: Any,
    *,
    web_search_func: Optional[Callable[[str], Any]] = None,
    create_txt_func: Optional[Callable[[str, str], str]] = None,
    create_md_func: Optional[Callable[[str, str, Optional[str]], str]] = None,
    create_docx_func: Optional[Callable[[str, str, Optional[str]], str]] = None,
) -> tuple[str, Optional[str]]:
    topic = extract_document_topic(text)
    document_format = infer_document_format(text)
    research_context, sources, online_used = collect_document_research(topic, web_search_func)

    try:
        from main.skills import load_builtin_skill
        skill_instructions = load_builtin_skill("documents") or ""
    except Exception:
        skill_instructions = ""

    content = generate_document_content(
        topic,
        llm,
        research_context=research_context,
        skill_instructions=skill_instructions,
    )
    filename = re.sub(r"[^\w\s-]", "", topic, flags=re.UNICODE)
    filename = re.sub(r"\s+", "_", filename).strip("_")[:60] or "document"
    title = topic[:1].upper() + topic[1:]

    if document_format == "txt" and create_txt_func:
        result = create_txt_func(filename, content)
    elif document_format == "md" and create_md_func:
        result = create_md_func(filename, content, title)
    elif create_docx_func:
        result = create_docx_func(filename, content, title)
    else:
        raise RuntimeError(f"Создание формата {document_format} недоступно.")

    if str(result).lower().startswith("ошибка"):
        raise RuntimeError(result)
    file_path = _extract_created_path(str(result))
    if file_path and not Path(file_path).exists():
        raise RuntimeError("Генератор сообщил путь, но файл не найден после сохранения.")

    source_note = (
        f" Использовано интернет-источников: {len(sources)}."
        if online_used
        else " Интернет-данные получить не удалось, использованы локальные знания."
    )
    result_text = f"Документ сохранён: {file_path}" if file_path else str(result)
    return f"{result_text}.{source_note}", file_path
