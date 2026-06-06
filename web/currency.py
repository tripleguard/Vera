import re
import json
from typing import Optional
from datetime import datetime

from web.http_client import http as requests
from web.web_utils import get_default_headers

# Импортируем функцию для форматирования дат для TTS
try:
    from main.lang_ru import format_date_for_tts
except ImportError:
    # Fallback если импорт не удался
    def format_date_for_tts(date_str: str) -> str:
        return date_str


def _extract_currency_from_text(t: str) -> Optional[tuple[str, str]]:
    """
    Извлекает валюты из текста запроса.
    Возвращает (валюта_из, валюта_в) или None если не найдено.
    """
    try:
        s = (t or "").lower().strip()
        s = re.sub(r"[?!.]+$", "", s)
        
        # Словарь валют и их синонимов
        currency_map = {
            "usd": ["доллар", "бакс", "usd", "dollar"],
            "eur": ["евро", "eur", "euro"],
            "cny": ["юан", "cny", "yuan"],
            "gbp": ["фунт", "gbp", "pound"],
            "jpy": ["иен", "jpy", "yen"],
            "chf": ["франк", "chf"],
            "try": ["лир", "try"],
            "inr": ["руп", "inr"],
            "cad": ["канадск", "cad"],
            "aud": ["австралийск", "aud"],
            "brl": ["реал", "brl"],
            "krw": ["вон", "krw"],
            "aed": ["дирхам", "aed"],
            "hkd": ["гонконг", "hkd"],
            "kzt": ["тенге", "kzt"],
            "byn": ["белорус", "byn"],
            "azn": ["манат", "azn"],
            "amd": ["драм", "amd"],
            "gel": ["лари", "gel"],
            "kgs": ["сом", "kgs"],
            "uzs": ["сум", "uzs"],
            "tjs": ["сомон", "tjs"],
        }
        
        # Ищем упоминания валют
        found_currencies = []
        for code, keywords in currency_map.items():
            for keyword in keywords:
                if keyword in s:
                    found_currencies.append(code.upper())
                    break
        
        # Паттерны для извлечения валют
        patterns = [
            r"курс\s+(\w+)\s+(?:к|в|на)\s+(\w+)",  # курс USD к RUB
            r"(\w+)\s+(?:к|в)\s+(\w+)",  # USD к рублю
            r"сколько\s+(\w+)\s+(?:в|на)\s+(\w+)",  # сколько долларов в рублях
        ]
        
        for pattern in patterns:
            m = re.search(pattern, s)
            if m and len(found_currencies) >= 1:
                # Если нашли паттерн и хотя бы одну валюту
                if len(found_currencies) >= 2:
                    return (found_currencies[0], found_currencies[1])
                else:
                    # По умолчанию вторая валюта - рубль
                    return (found_currencies[0], "RUB")
        
        # Если нашли валюты без явного паттерна
        if len(found_currencies) >= 1:
            # Первая упомянутая валюта к рублю
            return (found_currencies[0], "RUB")
        
        # Если есть общие запросы о курсе
        if any(kw in s for kw in ["курс", "валют", "exchange", "rate"]):
            # Проверяем самые популярные валюты
            for keyword, code in [("доллар", "USD"), ("евро", "EUR"), ("юан", "CNY")]:
                if keyword in s:
                    return (code, "RUB")
    except Exception:
        pass
    return None


def _fetch_currency_data() -> Optional[dict]:
    """Получает данные о курсах валют от ЦБ РФ через API cbr-xml-daily.ru."""
    try:
        url = "https://www.cbr-xml-daily.ru/daily_json.js"
        headers = get_default_headers()
        
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"[CURRENCY] Ошибка при получении данных: {e}")
    return None


def _format_currency_name(char_code: str) -> str:
    """Возвращает русское название валюты по коду."""
    names = {
        "USD": "доллар США",
        "EUR": "евро",
        "CNY": "китайский юань",
        "GBP": "фунт стерлингов",
        "JPY": "японская иена",
        "CHF": "швейцарский франк",
        "TRY": "турецкая лира",
        "INR": "индийская рупия",
        "CAD": "канадский доллар",
        "AUD": "австралийский доллар",
        "BRL": "бразильский реал",
        "KRW": "южнокорейская вона",
        "AED": "дирхам ОАЭ",
        "HKD": "гонконгский доллар",
        "KZT": "казахстанский тенге",
        "BYN": "белорусский рубль",
        "AZN": "азербайджанский манат",
        "AMD": "армянский драм",
        "GEL": "грузинский лари",
        "KGS": "киргизский сом",
        "UZS": "узбекский сум",
        "TJS": "таджикский сомони",
    }
    return names.get(char_code, char_code)


def _calculate_exchange_rate(data: dict, from_currency: str, to_currency: str) -> Optional[tuple[float, str, str, int]]:
    """
    Рассчитывает курс обмена между двумя валютами.
    Возвращает (rate, from_name, to_name, nominal) или None.
    """
    try:
        valute = data.get("Valute", {})
        
        # Если конвертируем в рубли
        if to_currency == "RUB":
            if from_currency in valute:
                currency_info = valute[from_currency]
                rate = currency_info.get("Value", 0)
                nominal = currency_info.get("Nominal", 1)
                name = currency_info.get("Name", _format_currency_name(from_currency))
                
                return (rate, name, "российский рубль", nominal)
        
        # Если конвертируем из рублей
        elif from_currency == "RUB" and to_currency in valute:
            currency_info = valute[to_currency]
            rate = currency_info.get("Value", 0)
            nominal = currency_info.get("Nominal", 1)
            name = currency_info.get("Name", _format_currency_name(to_currency))
            
            if rate > 0:
                inverse_rate = nominal / rate
                return (inverse_rate, "российский рубль", name, 1)
        
        # Конвертация между двумя иностранными валютами через рубль
        elif from_currency in valute and to_currency in valute:
            from_info = valute[from_currency]
            to_info = valute[to_currency]
            
            from_rate = from_info.get("Value", 0)
            from_nominal = from_info.get("Nominal", 1)
            to_rate = to_info.get("Value", 0)
            to_nominal = to_info.get("Nominal", 1)
            
            if from_rate > 0 and to_rate > 0:
                # Курс = (from в рублях) / (to в рублях)
                rate = (from_rate / from_nominal) / (to_rate / to_nominal)
                from_name = from_info.get("Name", _format_currency_name(from_currency))
                to_name = to_info.get("Name", _format_currency_name(to_currency))
                
                return (rate, from_name, to_name, 1)
    except Exception as e:
        print(f"[CURRENCY] Ошибка при расчете курса: {e}")
    return None


def execute_currency_command(text: str) -> Optional[str]:
    """
    Обрабатывает запросы о курсах валют.
    Возвращает ответ строкой или None, если запрос не о валютах.
    """
    try:
        lowered = (text or '').lower().strip()
        
        # Проверяем, что запрос о валютах
        if not any(kw in lowered for kw in ['курс', 'валют', 'доллар', 'евро', 'юан', 'фунт', 'usd', 'eur', 'cny', 'exchange']):
            return None
        
        # Извлекаем валюты из запроса
        currencies = _extract_currency_from_text(lowered)
        if not currencies:
            return "Уточните валюты, например: 'курс доллара' или 'курс евро к рублю'."
        
        from_currency, to_currency = currencies
        
        # Получаем данные от ЦБ
        data = _fetch_currency_data()
        if not data:
            return "Не удалось получить данные о курсах валют."
        
        # Извлекаем дату обновления
        date_str = data.get("Date", "")
        formatted_date = ""
        formatted_date_tts = ""
        try:
            if date_str:
                date_obj = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                # Формат для отображения в тексте
                formatted_date = date_obj.strftime("%d.%m.%Y %H:%M")
                # Формат для голосового вывода (TTS)
                formatted_date_tts = format_date_for_tts(formatted_date)
        except Exception:
            formatted_date = ""
            formatted_date_tts = ""
        
        # Рассчитываем курс
        result = _calculate_exchange_rate(data, from_currency, to_currency)
        if not result:
            return f"К сожалению, не нашла курс {from_currency} к {to_currency}."
        
        rate, from_name, to_name, nominal = result
        
        # Форматируем ответ
        if nominal == 1:
            response = f"Курс: 1 {from_name} = {rate:.2f} {to_name}"
        else:
            response = f"Курс: {nominal} {from_name} = {rate:.2f} {to_name}"
        
        if formatted_date_tts:
            response += f" (на {formatted_date_tts})"
        
        # Добавляем информацию об изменении, если доступна
        if from_currency != "RUB" and to_currency == "RUB":
            valute = data.get("Valute", {})
            if from_currency in valute:
                previous = valute[from_currency].get("Previous", 0)
                current = valute[from_currency].get("Value", 0)
                if previous > 0 and current > 0:
                    change = current - previous
                    change_percent = (change / previous) * 100
                    
                    if abs(change) >= 0.01:  # Показываем изменение только если оно заметное
                        direction = "вырос" if change > 0 else "упал"
                        response += f". Курс {direction} на {abs(change):.2f} руб. ({change_percent:+.2f}%)"
        
        return response
        
    except Exception as e:
        print(f"[CURRENCY] error: {e}")
        return "Не удалось получить курс валют сейчас."
