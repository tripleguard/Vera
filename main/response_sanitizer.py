"""Small text cleanup helpers shared by voice output paths."""

from __future__ import annotations

import re

from .lang_ru import convert_years_in_text


_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\u2600-\u26FF"
    "\u2700-\u27BF"
    "]+",
    flags=re.UNICODE,
)
_REASONING_BUDGET_RE = re.compile(
    r"(?:^|\n|\r)\s*"
    r"(?:бюджет\s+)?размышлени[яй]\s+исчерпан[а-я]*[.!?]?\s*"
    r"перехожу\s+к\s+финальн(?:ому|ый)\s+ответ[ау]?[.!?]?\s*",
    flags=re.IGNORECASE,
)
_EN_REASONING_BUDGET_RE = re.compile(
    r"(?:^|\n|\r)\s*"
    r"(?:reasoning|thinking)\s+budget\s+(?:is\s+)?(?:exhausted|exceeded)[.!?]?\s*"
    r"(?:moving|switching|proceeding)\s+to\s+(?:the\s+)?final\s+answer[.!?]?\s*",
    flags=re.IGNORECASE,
)
_REASONING_BUDGET_PREFIXES = (
    "бюджет размышления исчерпан. перехожу к финальному ответу.",
    "размышления исчерпан. перехожу к финальному ответу.",
    "reasoning budget exhausted. moving to final answer.",
    "thinking budget exhausted. moving to final answer.",
    "reasoning budget exceeded. moving to final answer.",
    "thinking budget exceeded. moving to final answer.",
)


def strip_thinking_markup(text: str) -> str:
    """Remove model/server reasoning markers from text visible to users."""
    clean = str(text or "").replace("\ufffd", "")
    clean = re.sub(r"<think>.*?</think>", "", clean, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r"^.*?</think>", "", clean, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r"<think>.*$", "", clean, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r"</?think>", "", clean, flags=re.IGNORECASE)
    clean = _REASONING_BUDGET_RE.sub("", clean)
    clean = _EN_REASONING_BUDGET_RE.sub("", clean)
    return clean


def might_be_thinking_markup_prefix(text: str) -> bool:
    """Return True while a streaming prefix may still become reasoning markup."""
    clean = str(text or "").replace("\ufffd", "").lstrip().lower()
    clean = re.sub(r"\s+", " ", clean)
    if not clean:
        return True
    if "<think".startswith(clean) or clean.startswith("<think"):
        return True
    return any(prefix.startswith(clean) for prefix in _REASONING_BUDGET_PREFIXES)


def strip_markdown_for_tts(text: str) -> str:
    s = text or ""
    s = re.sub(r"```[\s\S]*?```", " ", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", s)
    s = re.sub(r"(?m)^\s{0,3}>\s*", "", s)
    s = re.sub(r"(?m)^\s*[-*+]\s+", "", s)
    s = re.sub(r"(?m)^\s*\d+\.\s+", "", s)
    return s.replace("**", "").replace("__", "").replace("~~", "")


def strip_emoji_for_tts(text: str) -> str:
    s = text or ""
    s = _EMOJI_RE.sub("", s)
    s = s.replace("\u200d", "").replace("\ufe0f", "").replace("\ufe0e", "")
    return re.sub(r"(?<!\w)([:;=8][\-^]?[)(DPpOo/\\|])(?!\w)", "", s)


def clean_for_tts(text: str) -> str:
    """Remove markup, source noise and links before sending text to TTS."""
    try:
        s = strip_thinking_markup(text)
        s = strip_markdown_for_tts(s)
        s = strip_emoji_for_tts(s)
        s = re.sub(r"\s*\(источники?:.*?\)\s*$", "", s, flags=re.IGNORECASE | re.DOTALL)
        s = re.sub(r"\bисточники?:.*$", "", s, flags=re.IGNORECASE)
        s = re.sub(r"https?://\S+", "", s)
        s = re.sub(r"\s{2,}", " ", s).strip()
        return convert_years_in_text(s)
    except Exception:
        return text
