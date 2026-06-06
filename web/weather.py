import re
from typing import Optional

from web.http_client import http as requests
from web.web_utils import get_default_headers, fetch_url, search_brave


def _extract_city_from_text(t: str) -> Optional[str]:
    try:
        s = (t or "").lower().strip()
        s = re.sub(r"[?!.]+$", "", s)
        
        # Паттерны с группой захвата города
        patterns = [
            r"(?:какая|какой)?\s*погод\w*\s+(?:в|во|на)\s+([а-яёa-z][а-яёa-z\-\s]+)",
            r"(?:в|во|на)\s+([а-яёa-z][а-яёa-z\-\s]+)\s+(?:какая|какой)?\s*погод\w*",
            r"погод\w*\s+([а-яёa-z][а-яёa-z\-\s]+)",
        ]
        
        for pattern in patterns:
            m = re.search(pattern, s)
            if m:
                city = m.group(1).strip()
                # Убираем временные маркеры
                city = re.sub(r"\b(сегодня|завтра|послезавтра|на\s+неделю|недел[юь]).*$", "", city).strip()
                if len(city) >= 2:
                    return city
    except Exception:
        pass
    return None


def _parse_weather_text(text: str) -> tuple[Optional[str], Optional[int], Optional[int]]:
    """Универсальный парсер погоды из любого текста."""
    try:
        t = (text or "").replace("\u2212", "-")
        
        # Температура (первое вхождение)
        temp_match = re.search(r"([+\-]?\d{1,2})°", t)
        temp = int(temp_match.group(1)) if temp_match else None
        
        # Ощущается как
        feels_match = re.search(r"ощуща[её]тс[яь]\s+как\s+([+\-]?\d{1,2})°", t.lower())
        feels = int(feels_match.group(1)) if feels_match else None
        
        # Погодные условия (от сложных к простым)
        conditions = [
            "облачно с прояснениями", "переменная облачность", "небольшой дождь",
            "небольшой снег", "ясно", "пасмурно", "облачно", "малооблачно",
            "дождь", "ливень", "снег", "снегопад", "гроза", "туман", "морось", "град"
        ]
        
        text_lower = t.lower()
        found_condition = None
        min_pos = len(text_lower)
        
        for cond in conditions:
            pos = text_lower.find(cond)
            if pos != -1 and pos < min_pos:
                min_pos = pos
                found_condition = cond
        
        return found_condition, temp, feels
    except Exception:
        return None, None, None


def _get_weather_advice(temp: Optional[int], feels: Optional[int], condition: Optional[str]) -> str:
    """Генерирует совет на основе погодных условий."""
    import random
    
    # Используем ощущаемую температуру, если есть, иначе реальную
    t = feels if feels is not None else temp
    cond = (condition or "").lower()
    
    # Советы по температуре
    if t is not None:
        if t < 0:
            temp_advice = random.choice([
                "Одевайтесь теплее, на улице мороз.",
                "Советую надеть тёплую куртку.",
                "Не забудьте шапку и перчатки."
            ])
        elif t < 10:
            temp_advice = random.choice([
                "Советую одеться потеплее.",
                "Возьмите тёплую куртку.",
                "На улице прохладно, одевайтесь теплее."
            ])
        elif t < 15:
            temp_advice = random.choice([
                "Рекомендую лёгкую куртку.",
                "Возьмите кофту или ветровку.",
                "Прохладно, возьмите что-то тёплое."
            ])
        elif t > 25:
            temp_advice = random.choice([
                "На улице жарко, одевайтесь легче.",
                "Не забудьте взять воду.",
                "Жаркая погода, оденьтесь полегче."
            ])
        else:
            temp_advice = ""
    else:
        temp_advice = ""
    
    # Советы по осадкам
    if any(x in cond for x in ["дождь", "ливень", "морось"]):
        rain_advice = random.choice([
            "Возьмите зонт.",
            "Не забудьте зонтик.",
            "Захватите зонт с собой."
        ])
    elif "снег" in cond or "снегопад" in cond:
        rain_advice = random.choice([
            "Идёт снег, будьте осторожны.",
            "Снегопад, одевайтесь теплее.",
            "На улице снег."
        ])
    elif "гроза" in cond:
        rain_advice = "Гроза, лучше остаться дома."
    else:
        rain_advice = ""
    
    # Объединяем советы
    advice_parts = [a for a in [temp_advice, rain_advice] if a]
    return " " + advice_parts[0] if advice_parts else ""


def execute_weather_command(text: str) -> Optional[str]:
    """Получает погоду через общий веб-поиск без привязки к конкретному сайту."""
    try:
        lowered = (text or '').lower().strip()
        if 'погод' not in lowered:
            return None
        
        # Проверка на запросы о будущей погоде
        if re.search(r"\b(завтра|послезавтра|на\s+неделю|через|будет|прогноз)\b", lowered):
            return "Извините, пока я могу сообщить только текущую погоду."
        
        city_hint = _extract_city_from_text(lowered)
        if not city_hint:
            return "Уточните город: например, 'погода в Москве'."
        
        # Ищем через fallback search
        search_query = f"погода {city_hint}"
        print(f"[WEATHER] Searching: {search_query}")
        links = search_brave(search_query, max_results=5)
        
        if not links:
            return f"Не нашла информацию о погоде в городе {city_hint.title()}."
        
        # Пробуем парсить погоду из первых результатов
        headers = get_default_headers()
        web_cfg = {
            "page_timeout_sec": 3,
            "per_page_limit": 2500,
            "disable_time_limits": True,
            "connect_timeout_sec": 3,
            "read_timeout_sec": 3,
            "max_bytes_per_page": 120000,
        }
        
        for url in links[:3]:  # Проверяем первые 3 результата
            try:
                print(f"[WEATHER] Trying: {url}")
                item = fetch_url(url, headers, web_cfg, log_page_errors=False)
                if not item:
                    continue
                
                _, text_page = item
                cond, temp, feels = _parse_weather_text(text_page)
                
                # Если нашли температуру - считаем успехом
                if temp is not None:
                    city_name = city_hint.strip().title()
                    
                    parts = [f"Погода в {city_name}:"]
                    if temp is not None:
                        parts.append(f"{temp}°")
                    if cond:
                        parts.append(cond)
                    if feels is not None and temp != feels:
                        parts.append(f"Ощущается как {feels}°")
                    
                    # Добавляем совет
                    advice = _get_weather_advice(temp, feels, cond)
                    
                    base_response = " ".join(parts)
                    return base_response + advice
            except Exception as e:
                print(f"[WEATHER] Parse error for {url}: {e}")
                continue
        
        # Если ни один из источников не дал результата
        return f"Не удалось определить погоду в городе {city_hint.title()}."
        
    except Exception as e:
        print(f"[WEATHER] error: {e}")
        return "Не удалось получить погоду сейчас."
