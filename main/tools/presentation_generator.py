"""Local presentation planner for Vera.

The LLM plans the story and concise slide content. Rendering is deterministic
and fully offline in document_generator.py, so visual quality does not depend
on the model producing layout instructions or on an external design API.
"""

import json
import re
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, List, Optional, Tuple


MIN_SLIDES = 4
MAX_SLIDES = 10
MAX_CONTEXT_FOR_GENERATION = 7000
MIN_ONLINE_CONTEXT = 240
ALLOWED_VISUALS = {
    "overview",
    "process",
    "comparison",
    "numbers",
    "timeline",
    "quote",
    "summary",
}


def extract_presentation_topic(text: str) -> Optional[str]:
    patterns = [
        r"(?:создай|сделай|подготовь|сгенерируй)\s+презентацию\s+(?:про|о|об|на тему)\s+(.+)",
        r"презентаци[яию]\s+(?:про|о|об|на тему)\s+(.+)",
        r"(?:создай|сделай|подготовь|сгенерируй)\s+презентацию\s+(.+)",
    ]
    cleaned = text.strip()
    for pattern in patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            topic = match.group(1).strip(" .")
            topic = re.sub(
                r"\s+(?:пожалуйста|плиз|срочно|быстро)$",
                "",
                topic,
                flags=re.IGNORECASE,
            )
            topic = re.sub(
                r"\s+(?:на|из)\s+\d+\s+слайд(?:а|ов)?\b.*$",
                "",
                topic,
                flags=re.IGNORECASE,
            ).strip()
            return topic or None
    return None


def extract_slide_count(text: str, default: int = 6) -> int:
    match = re.search(r"\b(\d{1,2})\s+слайд(?:а|ов)?\b", text, flags=re.IGNORECASE)
    if not match:
        return max(MIN_SLIDES, min(MAX_SLIDES, default))
    return max(MIN_SLIDES, min(MAX_SLIDES, int(match.group(1))))


def is_presentation_request(text: str) -> bool:
    from main.tool_router import route_intent

    return route_intent(text).skill == "presentations"


def _trim(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    shortened = text[: limit + 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return shortened + "…"


def _normalize_slide(raw: Any, index: int) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    title = _trim(raw.get("title"), 64)
    if not title:
        return None

    bullets = raw.get("bullets", [])
    if isinstance(bullets, str):
        bullets = re.split(r"\n+|(?<=[.!?])\s+", bullets)
    bullets = [_trim(item, 110) for item in bullets if _trim(item, 110)][:4]

    stats = []
    for item in raw.get("stats", []) if isinstance(raw.get("stats"), list) else []:
        if not isinstance(item, dict):
            continue
        value = _trim(item.get("value"), 18)
        label = _trim(item.get("label"), 45)
        if value and label:
            stats.append({"value": value, "label": label})
    stats = stats[:3]

    visual = str(raw.get("visual") or "").strip().lower()
    if visual not in ALLOWED_VISUALS:
        visual = ("numbers" if stats else ("process" if index in (1, 2) else "overview"))

    return {
        "title": title,
        "kicker": _trim(raw.get("kicker"), 28),
        "key_message": _trim(raw.get("key_message") or raw.get("content"), 170),
        "bullets": bullets,
        "visual": visual,
        "stats": stats,
        "quote": _trim(raw.get("quote"), 180),
    }


def _extract_json(response: str) -> Dict[str, Any]:
    cleaned = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()
    cleaned = cleaned.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {"slides": parsed}
    except json.JSONDecodeError:
        match = re.search(r'\{[\s\S]*"slides"[\s\S]*\}', cleaned)
        if not match:
            return {}
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return {}


def _fallback_slides(topic: str, content_count: int) -> List[Dict[str, Any]]:
    templates = [
        ("Почему тема важна", "overview", ["Контекст и актуальность", "Главный вопрос", "Что изменилось"]),
        ("Ключевая идея", "comparison", ["Основной принцип", "Практическое значение", "Ограничения"]),
        ("Как это устроено", "process", ["От исходной точки", "Через ключевой механизм", "К результату"]),
        ("Факты и ориентиры", "numbers", ["Что можно измерить", "На что обратить внимание", "Как читать данные"]),
        ("Что делать дальше", "timeline", ["Первый шаг", "Развитие подхода", "Ожидаемый эффект"]),
        ("Главный вывод", "summary", ["Суть темы", "Практический вывод", "Следующий вопрос"]),
    ]
    slides = []
    for index in range(content_count):
        title, visual, bullets = templates[min(index, len(templates) - 1)]
        slides.append({
            "title": title,
            "kicker": topic,
            "key_message": f"{topic.capitalize()}: короткое объяснение ключевой мысли этого раздела.",
            "bullets": bullets,
            "visual": visual,
            "stats": [],
            "quote": "",
        })
    return slides


def _looks_like_title_slide(slide: Dict[str, Any], topic: str) -> bool:
    if "титуль" in str(slide.get("kicker") or "").lower():
        return True
    title = re.sub(r"\W+", " ", str(slide.get("title") or "").lower()).strip()
    normalized_topic = re.sub(r"\W+", " ", topic.lower()).strip()
    return SequenceMatcher(None, title, normalized_topic).ratio() >= 0.72


def _apply_visual_rhythm(slides: List[Dict[str, Any]]) -> None:
    count = len(slides)
    if count <= 4:
        rhythm = ["overview", "comparison", "process", "summary"]
    elif count == 5:
        rhythm = ["overview", "comparison", "process", "timeline", "summary"]
    else:
        rhythm = ["overview", "comparison", "process", "numbers", "timeline", "summary"]
    for index, slide in enumerate(slides):
        if slide.get("stats"):
            slide["visual"] = "numbers"
        else:
            slide["visual"] = rhythm[min(index, len(rhythm) - 1)]


def _deduplicate_content(slides: List[Dict[str, Any]]) -> None:
    seen = set()
    for slide in slides:
        unique = []
        for bullet in slide.get("bullets", []):
            key = re.sub(r"\W+", " ", bullet.lower()).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(bullet)
        slide["bullets"] = unique[:4]
        if slide.get("visual") != "quote":
            slide["quote"] = ""


def _filter_unverified_stats(slides: List[Dict[str, Any]], context: str) -> None:
    compact_context = re.sub(r"\s+", " ", context).lower()
    for slide in slides:
        verified = []
        for stat in slide.get("stats", []):
            value = str(stat.get("value") or "").strip()
            if value and len(value) >= 2 and value.lower() in compact_context:
                verified.append(stat)
        slide["stats"] = verified


def _summary_slide(topic: str, slides: List[Dict[str, Any]]) -> Dict[str, Any]:
    bullets = [slide.get("title", "") for slide in slides[-3:] if slide.get("title")]
    return {
        "title": "Главный вывод",
        "kicker": "Итог",
        "key_message": f"{topic.capitalize()} — это не отдельная технология, а изменение способа решать задачи.",
        "bullets": bullets[:3],
        "visual": "summary",
        "stats": [],
        "quote": "",
    }


def _plan_needs_refinement(slides: List[Dict[str, Any]], content_count: int) -> bool:
    if len(slides) != content_count:
        return True
    bullets = [
        re.sub(r"\W+", " ", bullet.lower()).strip()
        for slide in slides
        for bullet in slide.get("bullets", [])
    ]
    repeated = len(bullets) - len(set(bullets))
    messages = [
        re.sub(r"\W+", " ", str(slide.get("key_message") or "").lower()).strip()
        for slide in slides
    ]
    return repeated >= 2 or len(set(messages)) < len(messages)


def _refine_plan(
    topic: str,
    llm: Any,
    draft_slides: List[Dict[str, Any]],
    content_count: int,
) -> List[Dict[str, Any]]:
    rhythm = (
        ["overview", "comparison", "process", "summary"]
        if content_count <= 4
        else ["overview", "comparison", "process", "timeline", "summary"]
    )
    if content_count >= 6:
        rhythm = ["overview", "comparison", "process", "numbers", "timeline", "summary"]
    rhythm = rhythm[:content_count]
    prompt = f"""Отредактируй план презентации на тему «{topic}».

Верни ровно {content_count} содержательных слайдов. Титульный слайд НЕ создавай.
Исправь повторы: одна мысль или bullet не должны встречаться дважды.
Построй развитие истории: контекст → различия → механизм → последствия → вывод.
Используй visual строго в таком порядке: {json.dumps(rhythm, ensure_ascii=False)}.
Заголовки должны быть выводами. key_message — одно короткое предложение.
На каждом слайде 2-4 конкретных bullet. Не выдумывай точные числа.

Черновик:
{json.dumps(draft_slides, ensure_ascii=False)}

Ответь только JSON:
{{"slides":[{{"title":"","kicker":"","key_message":"","bullets":[],"visual":"","stats":[],"quote":""}}]}}"""
    try:
        result = llm.create_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": "Ты строгий редактор презентаций. Удаляй повторы и возвращай только JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=1900,
            temperature=0.3,
            top_p=0.8,
            stop=["```"],
            chat_template_kwargs={"enable_thinking": False},
            thinking_budget_tokens=0,
        )
        parsed = _extract_json(result["choices"][0]["message"]["content"])
        refined = []
        for index, raw in enumerate(parsed.get("slides", [])):
            slide = _normalize_slide(raw, index)
            if slide and not _looks_like_title_slide(slide, topic):
                refined.append(slide)
        if len(refined) >= content_count - 1:
            refined = refined[:content_count]
            if len(refined) < content_count:
                refined.append(_summary_slide(topic, refined))
            _apply_visual_rhythm(refined)
            return refined
    except Exception as exc:
        print(f"[PRES_GEN] Ошибка редакторского прохода: {exc}")
    return draft_slides


def generate_presentation_plan(
    topic: str,
    llm: Any,
    context: str = "",
    total_slides: int = 6,
    skill_instructions: str = "",
) -> Dict[str, Any]:
    total_slides = max(MIN_SLIDES, min(MAX_SLIDES, total_slides))
    content_count = total_slides - 1
    context = context[:MAX_CONTEXT_FOR_GENERATION]

    prompt = f"""Спроектируй презентацию на русском языке.

ТЕМА: {topic}
ВСЕГО СЛАЙДОВ: {total_slides}, включая титульный. Верни {content_count} содержательных слайдов.

Задача: построить ясную историю, а не конспект. Один слайд = одна мысль.
Заголовок каждого слайда должен выражать вывод, а не просто называть раздел.
Текст будет показан крупно, поэтому:
- key_message: одно предложение, до 140 символов;
- bullets: 2-4 коротких пункта, каждый до 90 символов;
- не повторяй одну мысль разными словами;
- не используй канцелярит, вводные фразы и общие слова;
- числа добавляй только если они есть в контексте или общеизвестны;
- каждый слайд должен отличаться по роли и ритму.

visual выбери из:
overview — карта ключевых идей;
process — последовательность шагов;
comparison — сравнение двух сторон;
numbers — 1-3 крупных показателя;
timeline — этапы или развитие;
quote — сильная цитата/формулировка;
summary — финальные выводы.

Контекст источников:
{context if context else "Интернет недоступен или не требуется. Используй знания локальной модели и не выдумывай точные статистические данные."}

Ответь только валидным JSON:
{{
  "subtitle": "короткий подзаголовок до 90 символов",
  "slides": [
    {{
      "title": "заголовок-вывод",
      "kicker": "короткая метка раздела",
      "key_message": "главная мысль",
      "bullets": ["пункт", "пункт"],
      "visual": "overview",
      "stats": [{{"value": "42%", "label": "что означает показатель"}}],
      "quote": ""
    }}
  ]
}}"""
    messages = [
        {
            "role": "system",
            "content": (
                "Ты редактор и информационный дизайнер презентаций. "
                "Сначала выстраивай аргумент, затем сокращай текст. "
                "Никогда не отвечай вне JSON."
                + (
                    f"\n\nПроцедура работы:\n{skill_instructions}"
                    if skill_instructions
                    else ""
                )
            ),
        },
        {"role": "user", "content": prompt},
    ]

    try:
        result = llm.create_chat_completion(
            messages=messages,
            max_tokens=2200,
            temperature=0.45,
            top_p=0.85,
            stop=["```"],
            chat_template_kwargs={"enable_thinking": False},
            thinking_budget_tokens=0,
        )
        parsed = _extract_json(result["choices"][0]["message"]["content"])
        slides: List[Dict[str, Any]] = []
        for index, raw in enumerate(parsed.get("slides", [])):
            normalized = _normalize_slide(raw, index)
            if normalized and not _looks_like_title_slide(normalized, topic):
                slides.append(normalized)
        if slides:
            if _plan_needs_refinement(slides, content_count):
                slides = _refine_plan(topic, llm, slides, content_count)
            slides = [
                slide for slide in slides
                if not _looks_like_title_slide(slide, topic)
            ]
            while len(slides) < content_count:
                if len(slides) == content_count - 1:
                    slides.append(_summary_slide(topic, slides))
                else:
                    fallback = _fallback_slides(topic, content_count)
                    slides.append(fallback[len(slides)])
            slides = slides[:content_count]
            _deduplicate_content(slides)
            _filter_unverified_stats(slides, context)
            _apply_visual_rhythm(slides)
            return {
                "subtitle": _trim(parsed.get("subtitle"), 90),
                "slides": slides,
            }
    except Exception as exc:
        print(f"[PRES_GEN] Ошибка планирования: {exc}")

    return {
        "subtitle": "Ключевые идеи, факты и практические выводы",
        "slides": _fallback_slides(topic, content_count),
    }


def _extract_useful_content(search_result: Any) -> Tuple[str, List[str]]:
    if not search_result:
        return "", []
    supplied_urls: List[str] = []
    if isinstance(search_result, dict):
        supplied_urls = [
            str(url).strip().rstrip(".,;:]}>'\"")
            for url in search_result.get("sources", [])
            if str(url).strip()
        ]
        search_result = str(search_result.get("text") or "")
    else:
        search_result = str(search_result)
    parsed_urls = [
        url.rstrip(".,;:]}>'\"")
        for url in re.findall(r"https?://[^\s)]+", search_result)
    ]
    urls = list(dict.fromkeys(supplied_urls + parsed_urls))
    text = re.sub(r"https?://\S+", "", search_result)
    text = re.sub(r"\(источники?:.*?\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"Источники?:.*$", "", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_CONTEXT_FOR_GENERATION], urls[:6]


def _research_queries(topic: str) -> List[str]:
    return [
        f"{topic}: ключевые факты, определения, причины и контекст",
        f"{topic}: актуальные данные, цифры, тенденции и реальные примеры",
        f"{topic}: практическое применение, преимущества, ограничения и риски",
    ]


def _collect_online_research(
    topic: str,
    web_search_func: Optional[Callable[[str], Any]],
) -> Tuple[str, List[str], bool]:
    if not web_search_func:
        return "", [], False

    sections: List[str] = []
    sources: List[str] = []
    for query in _research_queries(topic):
        try:
            print(f"[PRES_GEN] Поиск информации: {query}")
            text, result_sources = _extract_useful_content(web_search_func(query))
        except Exception as exc:
            print(f"[PRES_GEN] Запрос не выполнен: {exc}")
            continue
        if len(text) < 80:
            continue
        sections.append(f"Исследовательский запрос: {query}\n{text}")
        for source in result_sources:
            if source not in sources:
                sources.append(source)

    context = "\n\n".join(sections)[:MAX_CONTEXT_FOR_GENERATION]
    online_ok = len(context) >= MIN_ONLINE_CONTEXT
    if not online_ok:
        print("[PRES_GEN] Онлайн-данных недостаточно, включён локальный fallback.")
        return "", [], False
    return context, sources[:12], True


def execute_presentation_creation(
    text: str,
    llm: Any,
    web_search_func: Optional[Callable[[str], Any]] = None,
    create_pptx_func: Optional[Callable[..., str]] = None,
) -> tuple:
    topic = extract_presentation_topic(text)
    if not topic:
        return "Укажите тему презентации. Например: «Создай презентацию про искусственный интеллект»", None

    try:
        from main.config_manager import get_config
        configured = int(get_config().get("tools", "presentation_slides", default=6))
    except Exception:
        configured = 6
    total_slides = extract_slide_count(text, configured)

    context, sources, online_used = _collect_online_research(topic, web_search_func)

    try:
        from main.skills import load_builtin_skill
        skill_instructions = load_builtin_skill("presentations") or ""
    except Exception:
        skill_instructions = ""

    plan = generate_presentation_plan(
        topic,
        llm,
        context,
        total_slides,
        skill_instructions=skill_instructions,
    )
    if not create_pptx_func:
        return f"Подготовлен план презентации из {total_slides} слайдов.", None

    try:
        file_result = create_pptx_func(
            filename=topic.replace(" ", "_")[:50],
            slides=plan["slides"],
            title=topic.capitalize(),
            subtitle=plan.get("subtitle", ""),
            theme="auto",
            sources=sources,
        )
    except TypeError:
        file_result = create_pptx_func(
            filename=topic.replace(" ", "_")[:50],
            slides=plan["slides"],
            title=topic.capitalize(),
            theme="light_blue",
        )

    file_path = None
    match = re.search(r"Презентация создана:\s*(.*?\.pptx)", file_result, flags=re.IGNORECASE)
    if match:
        file_path = match.group(1).strip()
    source_note = (
        f" Использовано интернет-источников: {len(sources)}."
        if online_used
        else " Интернет-данные получить не удалось, использован локальный режим."
    )
    return f"{file_result} Всего слайдов: {total_slides}.{source_note}", file_path
