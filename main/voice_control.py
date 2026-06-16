"""Pure helpers for voice-mode control phrases."""

from __future__ import annotations

import re


_TRAILING_WAKE_RE = re.compile(r"^[\s,!.?:;\-]+|[\s,!.?:;\-]+$")
_SPACING_RE = re.compile(r"[\s,!.?:;\-]+")

STOP_COMMANDS = frozenset({
    "стоп",
    "хватит",
    "остановись",
    "останови",
    "тихо",
    "замолчи",
    "выключи",
    "отключи",
})


def normalize_voice_text(text: str) -> str:
    cleaned = str(text or "").casefold().replace("ё", "е")
    cleaned = _SPACING_RE.sub(" ", cleaned)
    return cleaned.strip()


def strip_activation_phrase(text: str, activation_word: str = "Вера") -> str:
    raw = str(text or "").strip()
    activation = re.escape(str(activation_word or "Вера").strip())
    if not activation:
        return raw
    pattern = re.compile(rf"^\s*{activation}(?:[\s,!.?:;\-]+|$)", re.IGNORECASE)
    return pattern.sub("", raw, count=1).strip()


def is_bare_activation_command(text: str, activation_word: str = "Вера") -> bool:
    normalized = normalize_voice_text(text)
    return bool(normalized) and normalized == normalize_voice_text(activation_word)


def is_voice_stop_command(text: str, activation_word: str = "Вера") -> bool:
    normalized = normalize_voice_text(text)
    if not normalized:
        return False
    if normalized in STOP_COMMANDS:
        return True
    if is_bare_activation_command(text, activation_word):
        return True
    after_activation = strip_activation_phrase(text, activation_word)
    return normalize_voice_text(after_activation) in STOP_COMMANDS
