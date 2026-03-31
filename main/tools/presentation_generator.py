"""
Умный генератор презентаций для агента Вера.

Позволяет LLM самостоятельно:
- Структурировать презентацию по теме
- Искать информацию через web_search
- Создавать слайды с контентом

Оптимизировано для маленьких моделей (1.7B):
- Генерация по частям (слайд за слайдом)
- Ограниченный контекст
- Простые промпты
"""

import re
import json
from typing import List, Dict, Optional, Any, Callable, Tuple


# Лимиты для оптимизации на слабых устройствах
MAX_SLIDES = 6  # Максимум слайдов
MAX_CONTENT_PER_SLIDE = 300  # Символов на слайд
MAX_CONTEXT_FOR_GENERATION = 3500  # Контекст для генерации (увеличено для более осмысленного текста)


def extract_presentation_topic(text: str) -> Optional[str]:
    """Извлекает тему презентации из запроса."""
    patterns = [
        r"(?:создай|сделай|подготовь)\s+презентацию\s+(?:про|о|об|на тему)\s+(.+)",
        r"презентаци[яию]\s+(?:про|о|об|на тему)\s+(.+)",
        r"(?:создай|сделай)\s+презентацию\s+(.+)",
    ]
    
    text_lower = text.lower().strip()
    
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            topic = match.group(1).strip()
            # Убираем лишние слова в конце
            topic = re.sub(r"\s+(?:пожалуйста|плиз|срочно|быстро)$", "", topic)
            return topic
    
    return None


def is_presentation_request(text: str) -> bool:
    """Проверяет, является ли запрос созданием презентации."""
    keywords = [
        "презентацию", "презентация", "презентации",
        "слайды", "слайд", "pptx", "powerpoint"
    ]
    text_lower = text.lower()
    
    create_words = ["создай", "сделай", "подготовь", "сгенерируй"]
    has_create = any(w in text_lower for w in create_words)
    has_pres = any(k in text_lower for k in keywords)
    
    return has_create and has_pres


def generate_presentation_structure(
    topic: str,
    llm,
    context: str = "",
    num_slides: int = 4
) -> List[Dict[str, str]]:
    """
    Генерирует структуру презентации с помощью LLM.
    
    Args:
        topic: Тема презентации
        llm: Экземпляр Llama
        context: Дополнительный контекст (результаты поиска)
        num_slides: Желаемое количество слайдов
    
    Returns:
        Список слайдов [{"title": "...", "content": "..."}, ...]
    """
    num_slides = min(num_slides, MAX_SLIDES)
    
    # Обрезаем контекст для экономии токенов
    if context and len(context) > MAX_CONTEXT_FOR_GENERATION:
        context = context[:MAX_CONTEXT_FOR_GENERATION] + "..."
    
    # Качественный промпт, чтобы модель сама писала полный контент
    prompt = f"""Создай подробную структуру презентации на тему: {topic}

Количество слайдов: {num_slides}

{f"Опирайся на эту информацию при создании текста слайдов:{chr(10)}{context}" if context else "Используй свои знания для написания качественного контента."}

Для каждого слайда напиши содержательный текст (2-4 предложения), который раскрывает суть заголовка. Текст не должен обрываться.
Не делай слайды слишком короткими.

ВАЖНО: Ты ДОЛЖЕН создать РОВНО {num_slides} слайдов! Не меньше и не больше. Ни один слайд не должен быть пропущен.

Ответь ТОЛЬКО в формате JSON (без пояснений):
{{
  "slides": [
    {{"title": "Введение", "content": "Подробный связный текст из нескольких предложений..."}},
    {{"title": "Основная часть", "content": "Подробный связный текст из нескольких предложений..."}}
  ]
}}"""

    messages = [
        {"role": "system", "content": "Ты эксперт по созданию презентаций. Твоя задача — писать качественный, связный и информативный текст для слайдов. Отвечай ТОЛЬКО JSON без пояснений."},
        {"role": "user", "content": prompt}
    ]
    
    try:
        # Увеличенный max_tokens для презентаций, так как текста будет больше
        result = llm.create_chat_completion(
            messages=messages,
            max_tokens=1500,
            temperature=0.7,
            stop=["```", "\n\n\n"]
        )
        response = result["choices"][0]["message"]["content"].strip()
        
        # Убираем теги мышления если есть
        response = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()
        
        # Парсим JSON
        slides = _parse_slides_json(response)
        if slides:
            print(f"[PRES_GEN] Создано {len(slides)} слайдов")
            return slides[:MAX_SLIDES]
            
    except Exception as e:
        print(f"[PRES_GEN] Ошибка генерации структуры: {e}")
    
    # Fallback: простая структура
    return _create_fallback_structure(topic)


def _parse_slides_json(response: str) -> List[Dict[str, str]]:
    """Парсит JSON со слайдами из ответа модели."""
    # Пробуем найти JSON в ответе
    json_patterns = [
        r'\{[\s\S]*"slides"[\s\S]*\}',
        r'\[[\s\S]*\{[\s\S]*"title"[\s\S]*\}[\s\S]*\]',
    ]
    
    for pattern in json_patterns:
        match = re.search(pattern, response)
        if match:
            try:
                data = json.loads(match.group())
                if isinstance(data, dict) and "slides" in data:
                    return data["slides"]
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                continue
    
    # Пробуем парсить построчно
    slides = []
    current_slide = {}
    
    for line in response.split("\n"):
        line = line.strip()
        
        # Ищем заголовок
        title_match = re.search(r'"title"\s*:\s*"([^"]+)"', line)
        if title_match:
            if current_slide:
                slides.append(current_slide)
                current_slide = {}
            current_slide["title"] = title_match.group(1)
        
        # Ищем контент
        content_match = re.search(r'"content"\s*:\s*"([^"]*)"', line)
        if content_match:
            current_slide["content"] = content_match.group(1)
    
    if current_slide and "title" in current_slide:
        slides.append(current_slide)
    
    return slides


def _create_fallback_structure(topic: str) -> List[Dict[str, str]]:
    """Создаёт простую структуру презентации без LLM."""
    return [
        {"title": topic.capitalize(), "content": f"Презентация на тему: {topic}"},
        {"title": "Введение", "content": f"Основные понятия темы '{topic}'"},
        {"title": "Основная часть", "content": "Ключевые аспекты и факты"},
        {"title": "Заключение", "content": "Выводы и итоги"},
    ]


def create_smart_presentation(
    topic: str,
    llm,
    web_search_func: Callable[[str], str] = None,
    num_slides: int = 4
) -> Dict[str, Any]:
    """
    Создаёт умную презентацию с автопоиском информации.
    
    Args:
        topic: Тема презентации
        llm: Экземпляр LLM
        web_search_func: Функция веб-поиска (опционально)
        num_slides: Количество слайдов
    
    Returns:
        {"slides": [...], "context_used": str, "search_performed": bool, "sources": [...]}
    """
    context = ""
    search_performed = False
    sources = []
    
    # Если есть функция поиска — ищем информацию
    if web_search_func:
        try:
            print(f"[PRES_GEN] Поиск информации по теме: {topic}")
            search_result = web_search_func(topic)
            
            if search_result and len(search_result) > 50:
                # Извлекаем полезную информацию и ссылки
                context, sources = _extract_useful_content(search_result)
                search_performed = True
                print(f"[PRES_GEN] Найдено {len(context)} символов контекста и {len(sources)} источников")
        except Exception as e:
            print(f"[PRES_GEN] Ошибка поиска: {e}")
    
    # Генерируем структуру
    slides = generate_presentation_structure(topic, llm, context, num_slides)
    
    # Мы больше не обогащаем слайды механической копипастой,
    # модель сама пишет осмысленный текст на основе контекста.
    
    return {
        "slides": slides,
        "context_used": context[:500] if context else "",
        "search_performed": search_performed,
        "sources": sources
    }


def _extract_useful_content(search_result: str) -> Tuple[str, List[str]]:
    """Извлекает полезный контент и URL-ы из результатов поиска."""
    if not search_result:
        return "", []
    
    # Извлекаем URL-ы
    urls = re.findall(r'https?://[^\s\)]+', search_result)
    
    # Убираем URL-ы и источники из текста для контента
    text = re.sub(r"https?://\S+", "", search_result)
    text = re.sub(r"\(источники?:.*?\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"Источники?:.*$", "", text, flags=re.IGNORECASE | re.MULTILINE)
    
    # Убираем лишние пробелы
    text = re.sub(r"\s+", " ", text).strip()
    
    # Ограничиваем размер
    if len(text) > MAX_CONTEXT_FOR_GENERATION:
        text = text[:MAX_CONTEXT_FOR_GENERATION]
        # Обрезаем по последнему полному предложению
        last_dot = text.rfind(".")
        if last_dot > 100:
            text = text[:last_dot + 1]
    
    return text, list(set(urls))  # Уникальные ссылки


def execute_presentation_creation(
    text: str,
    llm,
    web_search_func: Callable[[str], str] = None,
    create_pptx_func: Callable = None
) -> tuple:
    """
    Главная функция создания презентации.
    
    Вызывается из agent.py когда обнаружен запрос на презентацию.
    
    Args:
        text: Исходный запрос пользователя
        llm: Экземпляр LLM
        web_search_func: Функция веб-поиска
        create_pptx_func: Функция создания PPTX файла
    
    Returns:
        Tuple (сообщение, путь_к_файлу | None)
    """
    # Извлекаем тему
    topic = extract_presentation_topic(text)
    if not topic:
        return "Укажите тему презентации. Например: 'Создай презентацию про искусственный интеллект'", None
    
    print(f"[PRES_GEN] Создание презентации на тему: {topic}")
    
    # Получаем количество слайдов из настроек, по умолчанию 6
    try:
        from main.config_manager import get_config
        _config = get_config()
        slides_count = _config.get("tools", default={}).get("presentation_slides", 6)
    except:
        slides_count = 6
        
    # Создаём умную презентацию
    result = create_smart_presentation(
        topic=topic,
        llm=llm,
        web_search_func=web_search_func,
        num_slides=slides_count
    )
    
    slides = result["slides"]
    sources = result.get("sources", [])
    
    # Добавляем слайд с источниками если они есть
    if sources:
        # Берём топ-5 источников
        top_sources = sources[:5]
        sources_text = "\n".join(top_sources)
        slides.append({
            "title": "Использованные материалы",
            "content": f"Информация взята из открытых источников:\n\n{sources_text}"
        })
    
    if not slides:
        return "Не удалось создать структуру презентации.", None
    
    # Создаём файл если есть функция
    if create_pptx_func:
        try:
            # Выбираем тему фона
            theme = "light_blue"  # По умолчанию приятный голубой
            if "исотерик" in topic.lower() or "космос" in topic.lower():
                theme = "white" # или другой если бы были тёмные темы
            
            file_result = create_pptx_func(
                filename=topic.replace(" ", "_")[:30],
                slides=slides,
                title=topic.capitalize(),
                theme=theme
            )
            
            # Извлекаем путь к файлу из результата (формат: "Презентация создана: <path> ...")
            file_path = None
            if "создана:" in file_result:
                path_part = file_result.split("создана:", 1)[1].strip()
                # Путь идёт до " (" или до конца строки
                path_part = path_part.split(" (")[0].strip()
                if path_part:
                    file_path = path_part
            
            search_note = ""
            if result["search_performed"]:
                search_note = f" Использовано {len(sources)} источников."
            
            return f"{file_result} Создано {len(slides)} слайдов.{search_note}", file_path
            
        except Exception as e:
            print(f"[PRES_GEN] Ошибка создания файла: {e}")
            # Fallback на старую сигнатуру если create_pptx_func не поддерживает theme (на всякий случай)
            try:
                file_result = create_pptx_func(
                    filename=topic.replace(" ", "_")[:30],
                    slides=slides,
                    title=topic.capitalize()
                )
                return f"{file_result} (без темы). Создано {len(slides)} слайдов.", None
            except:
                return f"Структура создана ({len(slides)} слайдов), но не удалось сохранить файл: {e}", None
    
    # Если нет функции создания файла — возвращаем структуру
    slides_desc = ", ".join([s.get("title", "?") for s in slides[:4]])
    return f"Подготовлена презентация из {len(slides)} слайдов: {slides_desc}", None
