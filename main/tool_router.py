"""Central intent routing for skills and LLM tools.

System commands such as timers, power management and window control remain in
their deterministic handlers. This module only decides which skill or bounded
set of model tools may handle a conversational request.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


_TELEGRAM_PATTERN = re.compile(
    r"\b(?:телеграм|telegram|сообщени|кто\s+писал|"
    r"что\s+(?:написал|написала|ответил|ответила)|подключи|авторизуй)\b",
    re.IGNORECASE,
)
_TELEGRAM_SEND_PATTERN = re.compile(
    r"\b(?:напиши|отправь)\s+(?!"
    r"(?:текст|код|скрипт|стих|эссе|рассказ|сказк|доклад|реферат|стать|отч[её]т|"
    r"документ|файл|заметк|таблиц|презентац)\b)\S+\s+.+",
    re.IGNORECASE,
)
_TELEGRAM_PHONE_PATTERN = re.compile(
    r"(?:авторизуй|подключи)\s+(?:телеграм|телогу|телеге)"
    r"\s+(?:по\s+номеру\s+)?([\+\d\s\-\(\)]+)",
    re.IGNORECASE,
)
_TELEGRAM_CODE_PATTERN = re.compile(
    r"(?:мой\s+)?(?:код|пароль)\s*"
    r"(?:в\s*телеге|в\s*телегу|в\s*телеграме|для\s*телеграма|для\s*телеги)?"
    r"\s*[:\-]?\s*(\d{5})",
    re.IGNORECASE,
)
_PRESENTATION_SKILL_PATTERN = re.compile(
    r"\b(?:создай|сделай|подготовь|сгенерируй)\b.*"
    r"\b(?:презентац\w*|слайд\w*|pptx|powerpoint)\b",
    re.IGNORECASE,
)
_DOCUMENT_SKILL_PATTERN = re.compile(
    r"\b(?:создай|сделай|подготовь|сгенерируй|напиши|сохрани)\b.*"
    r"\b(?:текстов(?:ый|ого)\s+документ|доклад|отч[её]т|реферат|статью|заметку|"
    r"документ|txt|docx|word|markdown|md)\b",
    re.IGNORECASE,
)
_NON_TEXT_DOCUMENT_PATTERN = re.compile(
    r"\b(?:презентац|слайд|pptx|таблиц|xlsx|excel)\w*\b",
    re.IGNORECASE,
)
_DOCUMENT_CREATE_PATTERN = re.compile(
    r"\b(?:создай|сделай|подготовь|сгенерируй|напиши|сохрани)\b.*"
    r"\b(?:файл|документ|доклад|реферат|стать|отч[её]т|заметк|таблиц|презентац|"
    r"xlsx|docx|pptx|markdown|md|txt)\b",
    re.IGNORECASE,
)
_DOCUMENT_READ_PATTERN = re.compile(
    r"\b(?:прочитай|проанализируй|изучи|перескажи|суммируй|"
    r"что\s+(?:написано|содержится)|о\s+ч[её]м)\b.*"
    r"\b(?:файл|документ|pdf|docx|txt|md)\b",
    re.IGNORECASE,
)
_CODE_EXECUTION_PATTERN = re.compile(
    r"\b(?:посчитай|вычисли|рассчитай|реши\s+уравнение|статистик|"
    r"проанализируй\s+данные|сколько\s+будет|конвертируй|сгенерируй\s+пароль|"
    r"выполни\s+(?:python|код)|запусти\s+(?:python|код))\b",
    re.IGNORECASE,
)
_PLAIN_CODE_PATTERN = re.compile(
    r"\b(?:напиши|покажи|дай|сгенерируй|создай)\b.*"
    r"\b(?:код|скрипт|python|питон)\b",
    re.IGNORECASE,
)
_CODE_RUN_PATTERN = re.compile(
    r"\b(?:запусти|выполни|прогони|проверь\s+код|используй\s+интерпретатор)\b",
    re.IGNORECASE,
)
_FILE_OUTPUT_PATTERN = re.compile(
    r"\b(?:файл|сохрани|документ|txt|md|docx|pptx|xlsx|запиши\s+в\s+файл)\b",
    re.IGNORECASE,
)
_WEB_PATTERN = re.compile(
    r"\b(?:найди|найти|поищи|поискать|погугли|узнай|узнать|кто\s+такой|что\s+такое|"
    r"что\s+за|что\s+означает|как\s+расшифровывается|компания|"
    r"проверь(?:\s+в\s+интернете)?|"
    r"новост|сегодня|завтра|сейчас|онлайн|актуальн|последн(?:ий|яя|ее|ие)|"
    r"расписани|курс|валют|usd|eur|рубл|btc|биткоин|акци|индекс|цена|погода|"
    r"дата\s+(?:выпуска|выхода)|когда\s+(?:выш|выпущен|появил|создан|основан)|"
    r"рейтинг|в\s+топе|какое\s+место|лучш|топ|список|"
    r"iphone|rtx|gtx|playstation|xbox|nvidia|amd)\b",
    re.IGNORECASE,
)
_EXPLICIT_WEB_CONTEXT_PATTERN = re.compile(
    r"\b(?:интернет|онлайн|новост|актуальн|последн(?:ий|яя|ее|ие)|"
    r"сегодня|сейчас|сайт|источник)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RouteIntent:
    skill: str | None = None
    tools: tuple[str, ...] = ()
    plain_code: bool = False
    direct_web: bool = False
    telegram_action: dict[str, str] | None = None


def _parse_telegram_action(text: str) -> dict[str, str] | None:
    phone_match = _TELEGRAM_PHONE_PATTERN.search(text)
    if phone_match:
        phone = phone_match.group(1).strip()
        if len(re.sub(r"\D", "", phone)) >= 5:
            return {"action": "start_auth", "phone": phone}

    code_match = _TELEGRAM_CODE_PATTERN.search(text)
    if not code_match and re.fullmatch(r"\d{5}", text.strip()):
        code_match = re.match(r"(\d{5})", text.strip())
    if code_match:
        return {"action": "enter_code", "code": code_match.group(1)}
    return None


def _detect_skill(text: str) -> str | None:
    if _PRESENTATION_SKILL_PATTERN.search(text):
        return "presentations"
    if _DOCUMENT_SKILL_PATTERN.search(text) and not _NON_TEXT_DOCUMENT_PATTERN.search(text):
        return "documents"
    return None


def _is_plain_code(text: str) -> bool:
    return bool(
        _PLAIN_CODE_PATTERN.search(text)
        and not _FILE_OUTPUT_PATTERN.search(text)
        and not _CODE_RUN_PATTERN.search(text)
    )


def route_intent(
    user_text: str,
    *,
    file_name: str | None = None,
    allow_web: bool = True,
    allow_skills: bool = True,
    available_names: Iterable[str] | None = None,
    max_tools: int = 2,
) -> RouteIntent:
    text = (user_text or "").strip()
    if not text:
        return RouteIntent()

    selected: list[str] = []

    def add(name: str) -> None:
        if name not in selected:
            selected.append(name)

    telegram_action = _parse_telegram_action(text)
    telegram_intent = bool(
        telegram_action
        or _TELEGRAM_PATTERN.search(text)
        or _TELEGRAM_SEND_PATTERN.search(text)
    )
    if telegram_intent:
        add("telegram")

    skill = _detect_skill(text) if allow_skills else None
    if _DOCUMENT_CREATE_PATTERN.search(text):
        add("create_document")

    if not file_name and _DOCUMENT_READ_PATTERN.search(text):
        add("read_document")

    if (
        allow_web
        and _WEB_PATTERN.search(text)
        and (not telegram_intent or _EXPLICIT_WEB_CONTEXT_PATTERN.search(text))
    ):
        add("web_search")

    plain_code = _is_plain_code(text)
    if _CODE_EXECUTION_PATTERN.search(text) and not plain_code:
        add("code_interpreter")

    if available_names is not None:
        available = set(available_names)
        selected = [name for name in selected if name in available]
    tools = tuple(selected[: max(0, max_tools)])

    return RouteIntent(
        skill=skill,
        tools=tools,
        plain_code=plain_code,
        direct_web=tools == ("web_search",),
        telegram_action=telegram_action,
    )


def select_tool_names(
    user_text: str,
    *,
    file_name: str | None = None,
    allow_web: bool = True,
    available_names: Iterable[str] | None = None,
    max_tools: int = 2,
) -> list[str]:
    """Backward-compatible tool-only view of the central route decision."""
    return list(
        route_intent(
            user_text,
            file_name=file_name,
            allow_web=allow_web,
            allow_skills=False,
            available_names=available_names,
            max_tools=max_tools,
        ).tools
    )
