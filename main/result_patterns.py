import re


# Паттерны неудачных результатов (regex)
FAILURE_PATTERNS = [
    r"\bошибка\b",
    r"\bне\s+(?:удалось|найден[оа]?|могу|работает)\b",
    r"\bпровал\b",
    r"\bневозможно\b",
    r"\bнедоступ\w*\b",
    r"\bтаймаут\b",
    r"\bсбой\b",
    r"\bне поддерживается\b",
    r"\bexception\b",
    r"\berror\b",
]

# Паттерны успешных результатов (regex)
SUCCESS_PATTERNS = [
    r"\bготово\b",
    r"\bуспешно\b",
    r"\bвыполнено\b",
    r"\bсоздан[оа]?\b",
    r"\bоткрыт[оа]?\b",
    r"\bнайден[оа]?\b",
    r"\bсохранён[оа]?\b",
    r"\bзапущен[оа]?\b",
    r"\bотправлено\b",
]


def is_successful_result(result: str) -> bool:
    """
    Эвристическая проверка успешности результата.

    1. Если найден паттерн неудачи — False.
    2. Если найден паттерн успеха — True.
    3. Если содержательный ответ (>= 10 символов) без признаков ошибки — True.
    """
    if not result:
        return False

    result_lower = result.lower()

    # Проверяем наличие проблем
    for pattern in FAILURE_PATTERNS:
        if re.search(pattern, result_lower):
            return False

    # Проверяем индикаторы успеха
    for pattern in SUCCESS_PATTERNS:
        if re.search(pattern, result_lower):
            return True

    # Если есть содержательный ответ без признаков ошибки — считаем успехом
    # Минимум 10 символов реального контента
    clean_result = re.sub(r'\s+', ' ', result).strip()
    return len(clean_result) >= 10
