"""
Автоматическое извлечение фактов из диалогов пользователя.

Извлекает личную информацию без явной команды "запомни":
- Имя, город, работа, возраст
- Предпочтения (любимый..., не любит...)
- Факты о семье, питомцах и т.д.

С v2 возвращает категорию факта через `infer_category()` из `user.memory`,
чтобы новые факты сразу попадали в правильную категорию
(identity / contact / preference / project / fact).
"""
import re
from typing import Optional, Tuple, List

from user.memory import infer_category


# Паттерны для автоматического извлечения
# Формат: (regex_pattern, profile_key или None для факта, функция извлечения значения)
EXTRACTION_PATTERNS = [
    # === Профиль ===

    # Имя (осторожно, много ложных срабатываний)
    (r"(?:^|\s)меня зовут (\w+)", "имя", lambda m: m.group(1).capitalize()),
    (r"(?:^|\s)моё? имя (\w+)", "имя", lambda m: m.group(1).capitalize()),

    # Работа/профессия
    (r"я работаю (\w+(?:\s+\w+)?)", "работа", lambda m: m.group(1)),
    (r"я (\w+) по профессии", "работа", lambda m: m.group(1)),
    (r"моя профессия[:\s]+(\w+)", "работа", lambda m: m.group(1)),
    (r"я по профессии (\w+)", "работа", lambda m: m.group(1)),

    # Город
    (r"я живу в ([а-яё]+(?:-[а-яё]+)?)", "город", lambda m: m.group(1).capitalize()),
    (r"я из ([а-яё]+(?:-[а-яё]+)?)", "город", lambda m: m.group(1).capitalize()),
    (r"мой город[:\s]+([а-яё]+)", "город", lambda m: m.group(1).capitalize()),

    # Возраст
    (r"мне (\d+) (?:лет|год|года)", "возраст", lambda m: f"{m.group(1)} лет"),

    # === Факты (не профиль) ===

    # Предпочтения
    (r"(?:мой|моя|моё) любим(?:ый|ая|ое) (\w+)[:\s]+(\w+)", None,
     lambda m: f"Любимый {m.group(1)}: {m.group(2)}"),
    (r"я люблю (\w+(?:\s+\w+)?)", None, lambda m: f"Любит {m.group(1)}"),
    (r"я не люблю (\w+(?:\s+\w+)?)", None, lambda m: f"Не любит {m.group(1)}"),
    (r"я предпочитаю (\w+(?:\s+\w+)?)", None, lambda m: f"Предпочитает {m.group(1)}"),

    # Семья и питомцы
    (r"у меня есть (\w+) по имени (\w+)", None,
     lambda m: f"Есть {m.group(1)} по имени {m.group(2)}"),
    (r"у меня есть (\w+)", None, lambda m: f"Есть {m.group(1)}"),
    (r"моего? (\w+) зовут (\w+)", None,
     lambda m: f"{m.group(1).capitalize()} зовут {m.group(2)}"),
]


# Ключевые слова, указывающие на личную информацию
PERSONAL_KEYWORDS = [
    "меня зовут", "моё имя", "мое имя",
    "я работаю", "моя профессия", "по профессии",
    "я живу", "я из", "мой город",
    "мне лет", "мне год",
    "мой любим", "моя любим", "моё любим",
    "я люблю", "я не люблю", "я предпочитаю",
    "у меня есть", "моего зовут", "мою зовут"
]


def should_extract_facts(user_text: str) -> bool:
    """
    Быстрая проверка: стоит ли пытаться извлечь факты.
    Экономит время, если текст не содержит личной информации.
    """
    if not user_text:
        return False
    t = user_text.lower()
    return any(k in t for k in PERSONAL_KEYWORDS)


def extract_facts(user_text: str) -> List[Tuple[Optional[str], str, Optional[str]]]:
    """
    Извлекает факты из текста пользователя.

    Args:
        user_text: Текст сообщения пользователя

    Returns:
        Список кортежей (ключ_профиля или None, значение, категория).
        Если ключ None — это факт, иначе это поле профиля (категория для профиля всегда None).
        Категория для факта определяется через `infer_category()`.

    Примеры:
        "меня зовут Тимур"  → [("имя", "Тимур", None)]
        "я люблю кофе"      → [(None, "Любит кофе", "preference")]
        "у меня есть кот"   → [(None, "Есть кот", "fact")]
    """
    if not user_text:
        return []

    results = []
    text = user_text.lower().strip()

    for pattern, profile_key, extractor in EXTRACTION_PATTERNS:
        try:
            m = re.search(pattern, text)
            if m:
                value = extractor(m)
                # Валидация извлечённого значения
                if value and len(value) >= 2 and len(value) <= 100:
                    # Избегаем дубликатов
                    if not any(v == value for _, v, _ in results):
                        cat = None if profile_key else infer_category(value)
                        results.append((profile_key, value, cat))
        except Exception:
            continue

    return results


def extract_from_remember_command(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Извлекает информацию из явной команды "запомни".

    Поддерживает форматы:
    - "запомни что меня зовут Тимур"
    - "запомни мой город Москва"
    - "запомни что я работаю программистом"
    - "запомни что у меня есть кот"

    Returns:
        Кортеж (profile_key, value, category).
        - Для профиля: (key, value, None)
        - Для факта: (None, fact_text, infer_category(fact_text))
        - Если нечего запоминать: (None, None, None)

    Примеры:
        "запомни меня зовут Тимур"  → ("имя", "Тимур", None)
        "запомни что я люблю кофе"  → (None, "что я люблю кофе", "preference")
    """
    if not text:
        return None, None, None

    lowered = text.lower().strip()

    # Удаляем "запомни что" / "запомни"
    cleaned = re.sub(r"^запомни\s+(?:что\s+)?", "", lowered)

    if not cleaned:
        return None, None, None

    # Проверяем паттерны профиля
    profile_patterns = [
        (r"^мен[яь] зовут (\w+)", "имя"),
        (r"^моё? имя (\w+)", "имя"),
        (r"^(?:мой|моя|моё) (\w+)[:\s]+(.+)", None),  # обрабатывается отдельно
        (r"^я работаю (.+)", "работа"),
        (r"^я живу в (.+)", "город"),
        (r"^я из (.+)", "город"),
        (r"^мне (\d+) (?:лет|год|года)", "возраст"),
    ]

    for pattern, key in profile_patterns:
        m = re.match(pattern, cleaned)
        if m:
            if key is None:  # "мой X это Y"
                value = m.group(2).strip()
                return m.group(1), value, None
            value = m.group(1).strip().capitalize() if key == "имя" else m.group(1).strip()
            return key, value, None

    # Если не нашли паттерн профиля — это факт
    return None, cleaned, infer_category(cleaned)
