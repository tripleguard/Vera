import re
from typing import List
from main.lang_ru import NUM_WORDS

# Паттерны для определения сложных задач
_COMPLEX_PATTERNS = [
    # Несколько действий
    r"\bи\s+(?:потом|затем|после)\b",
    r"\bсначала\b.*\bзатем\b",
    r"\bпотом\b",
    r"\bзатем\b",
    r"\bпосле\s+(?:этого|чего)\b",
    
    # Исследовательские запросы
    r"\bнайди\s+(?:информацию|данные)\b.*\b(?:и|затем)\b",
    r"\bузнай\b.*\b(?:и|затем)\b",
    r"\bисследуй\b",
    r"\bпроанализируй\b",
    
    # Составные действия
    r"\bсоздай\b.*\b(?:на основе|из|по)\b",
    r"\bсделай\b.*\b(?:и|потом)\b",
    r"\bнапиши\s+(?:документ|отчёт|презентацию)\b.*\b(?:про|о|об)\b",
    
    # Многошаговые запросы
    r"\bсравни\b",
    r"\bобъедини\b",
    r"\bсобери\b.*\bинформацию\b",
]

# Паттерны для простых задач (приоритетнее)
_SIMPLE_PATTERNS = [
    r"^(?:открой|запусти|закрой|выключи|включи)\s+\w+$",
    r"^(?:который\s+)?час$",
    r"^(?:какая\s+)?(?:сегодня\s+)?дата$",
    r"^(?:какая\s+)?погода",
    r"^(?:сколько|какой)\s+(?:времени|час)",
    r"^напомни\s+",
    r"^таймер\s+",
    r"^(?:громкость|звук)\s+",
    r"^яркость\s+",
]

# Ключевые слова, указывающие на сложность
_COMPLEX_KEYWORDS = {
    "исследуй", "проанализируй", "сравни", "объедини", "собери",
    "на основе", "используя", "с учётом", "по результатам"
}

# Максимальное количество шагов в плане
MAX_PLAN_STEPS = 5
MIN_PLAN_STEPS = 2


def _is_math_expression(text: str) -> bool:
    """Проверяет, является ли текст математическим выражением."""
    # Паттерн для чисел (цифры или словесные числительные)
    num_words_pattern = "|".join(re.escape(w) for w in NUM_WORDS.keys())
    number_pattern = rf"(?:\d+|(?:{num_words_pattern})(?:\s+(?:{num_words_pattern}))?)"
    
    # Математические операторы
    operators = r"(?:плюс|минус|умножить(?:\s+на)?|разделить(?:\s+на)?|делить(?:\s+на)?|на)"
    
    # Полный паттерн: число оператор число
    math_pattern = rf"{number_pattern}\s+{operators}\s+{number_pattern}"
    
    return bool(re.search(math_pattern, text.lower()))


def _expand_implicit_commands(commands: List[str]) -> List[str]:
    """Раскрывает неявные команды (открой X и Y -> открой X, открой Y)."""
    expanded = []
    last_action = None
    
    for cmd in commands:
        cmd = cmd.strip()
        
        # Проверяем есть ли в команде глагол действия
        has_action = re.search(
            r"\b(открой|запусти|закрой|выключи|включи|установи|поставь|"
            r"создай|удали|найди|покажи|скажи|расскажи|проверь|измерь|"
            r"сделай|сверни|разверни|переключись|перезагрузи|громкость|"
            r"яркость|таймер|напомни)\b",
            cmd,
            re.IGNORECASE
        )
        
        if has_action:
            # Запоминаем действие
            action_match = has_action.group(1)
            last_action = action_match
            expanded.append(cmd)
        else:
            # Если нет действия - добавляем последнее использованное
            if last_action and last_action.lower() in ["открой", "запусти", "закрой", "выключи"]:
                expanded.append(f"{last_action} {cmd}")
            else:
                # Если не можем определить - оставляем как есть
                expanded.append(cmd)
    
    return expanded


def is_complex_task(text: str) -> bool:

    if not text:
        return False
    
    text_lower = text.lower().strip()
    
    # Проверяем простые паттерны (приоритет)
    for pattern in _SIMPLE_PATTERNS:
        if re.search(pattern, text_lower):
            return False
    
    # Проверяем сложные паттерны
    for pattern in _COMPLEX_PATTERNS:
        if re.search(pattern, text_lower):
            return True
    
    # Проверяем ключевые слова
    for keyword in _COMPLEX_KEYWORDS:
        if keyword in text_lower:
            return True

    # Подсчитываем явные глаголы действий
    verbs = re.findall(
        r"\b(?:найди|создай|напиши|сделай|открой|запусти|"
        r"закрой|проверь|узнай|расскажи|покажи)\b",
        text_lower,
    )

    # Если это один запрос на написание/объяснение кода с относительным придаточным
    # ("напиши программу, которая ... и ..."), это НЕ сложная многозадачность.
    if len(verbs) <= 1 and re.search(r"\b(?:программ|код|скрипт|функц|алгоритм|пример)\b", text_lower):
        return False

    # Длинные запросы с несколькими глаголами — скорее всего сложные
    if len(verbs) >= 2:
        return True
    
    # "и"/"плюс" считаем признаком сложности только если есть минимум два действия
    # и это не обычное относительное предложение ("которая ... и ...").
    has_conjunction = bool(re.search(r"\s+и\s+", text_lower) or re.search(r"\s+плюс\s+", text_lower))
    if has_conjunction and not _is_math_expression(text_lower):
        if re.search(r"\bкотор(?:ый|ая|ое|ые|ую)\b", text_lower):
            return False
        if len(verbs) >= 2:
            return True

    return False


def create_plan_heuristic(text: str) -> List[str]:

    text_lower = text.lower().strip()
    
    # Удаляем обращение
    text_clean = re.sub(r"^\s*Вера[,\s]+", "", text_lower, flags=re.IGNORECASE)
    
    # Если это математика - не разбиваем
    is_math = _is_math_expression(text_clean)
    
    # Собираем разделители
    separators = [
        r"\s+и\s+(?:потом|затем)\s+",
        r"\s+(?:потом|затем)\s+",
        r"\s+после\s+(?:этого|чего)\s+",
        r",\s*(?:потом|затем)\s+",
        r"\s+а\s+также\s+",
        r"\s+ещё\s+",
    ]
    
    # "и" и "плюс" добавляем только если не математика
    if not is_math:
        separators.append(r"\s+плюс\s+")
        # "и" как обычный разделитель, но с низким приоритетом (в конце списка проверок) нет, лучше сразу
        separators.append(r"\s+и\s+")
    
    # Создаем единый паттерн разделителей
    separator_pattern = "|".join(f"(?:{p})" for p in separators)
    
    # Разбиваем
    parts = re.split(separator_pattern, text_clean)
    steps = [p.strip() for p in parts if p and p.strip() not in ["и", "а также", "плюс", "ещё", "потом"]]
    
    # Раскрываем неявные команды (открой X и Y)
    if len(steps) > 1:
        steps = _expand_implicit_commands(steps)
    
    # Если не удалось разбить — пробуем по "и" + глагол
    if len(steps) == 1:
        # "найди X и создай Y" → ["найди X", "создай Y"]
        match = re.match(
            r"(.+?)\s+и\s+((?:создай|напиши|сделай|открой|запусти|сохрани).+)",
            text_lower
        )
        if match:
            steps = [match.group(1).strip(), match.group(2).strip()]
    
    # Фильтруем пустые и слишком короткие
    steps = [s for s in steps if len(s) > 3]
    
    # Ограничиваем количество шагов
    if len(steps) > MAX_PLAN_STEPS:
        steps = steps[:MAX_PLAN_STEPS]
    
    return steps if len(steps) >= MIN_PLAN_STEPS else [text]


def create_plan_with_llm(text: str, llm, system_prompt: str = "") -> List[str]:

    planning_prompt = f"""Разбей задачу на 2-5 простых шагов. Каждый шаг должен быть конкретным действием.

Задача: {text}

Формат ответа:
1. [первый шаг]
2. [второй шаг]
...

Шаги:"""

    messages = [
        {"role": "system", "content": system_prompt or "Ты помощник для планирования задач. Отвечай кратко."},
        {"role": "user", "content": planning_prompt}
    ]
    
    try:
        result = llm.create_chat_completion(
            messages=messages,
            max_tokens=256,
            temperature=0.3,
            stop=["\n\n", "Задача:", "---"]
        )
        response = result["choices"][0]["message"]["content"].strip()
        
        # Парсим шаги из ответа
        steps = []
        for line in response.split("\n"):
            line = line.strip()
            # Убираем нумерацию
            match = re.match(r"^\d+[\.\)]\s*(.+)", line)
            if match:
                step = match.group(1).strip()
                if step and len(step) > 3:
                    steps.append(step)
        
        # Валидация результата
        if MIN_PLAN_STEPS <= len(steps) <= MAX_PLAN_STEPS:
            return steps
        
    except Exception as e:
        print(f"[PLANNER] Ошибка LLM планирования: {e}")
    
    # Fallback на эвристику
    return create_plan_heuristic(text)


def create_plan(text: str, llm=None, use_llm: bool = True) -> List[str]:

    # Сначала пробуем эвристику
    heuristic_plan = create_plan_heuristic(text)
    
    if len(heuristic_plan) >= MIN_PLAN_STEPS:
        print(f"[PLANNER] План (эвристика): {heuristic_plan}")
        return heuristic_plan
    
    # Если эвристика не сработала и есть LLM — используем его
    if use_llm and llm is not None:
        llm_plan = create_plan_with_llm(text, llm)
        if len(llm_plan) >= MIN_PLAN_STEPS:
            print(f"[PLANNER] План (LLM): {llm_plan}")
            return llm_plan
    
    # Возвращаем исходный запрос как единственный шаг
    return [text]


def format_plan_for_display(steps: List[str]) -> str:
    #Форматирует план для отображения пользователю.
    if not steps:
        return ""
    
    lines = ["План выполнения:"]
    for i, step in enumerate(steps, 1):
        lines.append(f"  {i}. {step}")
    
    return "\n".join(lines)


