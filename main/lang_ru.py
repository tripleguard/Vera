import re


def ru_to_en(s: str) -> str:
    """Транслитерация русских букв в латинские."""
    table = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'i', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
    }
    return "".join(table.get(ch, ch) for ch in s)


TIME_UNITS = {
    "секунд": 1, "секунды": 1, "секунда": 1, "секунду": 1, "сек": 1,
    "минут": 60, "минута": 60, "минуты": 60, "минуту": 60, "мин": 60,
    "час": 3600, "часа": 3600, "часов": 3600,
}

NUM_WORDS = {
    "ноль": 0,
    "один": 1, "одна": 1,
    "два": 2, "две": 2,
    "три": 3,
    "четыре": 4,
    "пять": 5,
    "шесть": 6,
    "семь": 7,
    "восемь": 8,
    "девять": 9,
    "десять": 10,
    "одиннадцать": 11,
    "двенадцать": 12,
    "тринадцать": 13,
    "четырнадцать": 14,
    "пятнадцать": 15,
    "шестнадцать": 16,
    "семнадцать": 17,
    "восемнадцать": 18,
    "девятнадцать": 19,
    "двадцать": 20,
    "тридцать": 30,
    "сорок": 40,
    "пятьдесят": 50,
    "шестьдесят": 60,
    "семьдесят": 70,
    "восемьдесят": 80,
    "девяносто": 90,
    "сто": 100,
    "двести": 200,
    "двухсот": 200,
    "триста": 300,
    "трехсот": 300,
    "четыреста": 400,
    "четырехсот": 400,
    "пятьсот": 500,
    "пятисот": 500,
    "шестьсот": 600,
    "шестисот": 600,
    "семьсот": 700,
    "семисот": 700,
    "восемьсот": 800,
    "восьмисот": 800,
    "девятьсот": 900,
    "девятисот": 900,
    "тысяча": 1000,
    "тысячи": 1000,

}

# Порядковые числительные (первую, вторую и т.д.)
ORDINAL_WORDS = {
    "первую": 1, "первая": 1, "первый": 1,
    "вторую": 2, "вторая": 2, "второй": 2,
    "третью": 3, "третья": 3, "третий": 3,
    "четвертую": 4, "четвёртую": 4, "четвертая": 4, "четвёртая": 4, "четвертый": 4, "четвёртый": 4,
    "пятую": 5, "пятая": 5, "пятый": 5,
    "шестую": 6, "шестая": 6, "шестой": 6,
    "седьмую": 7, "седьмая": 7, "седьмой": 7,
    "восьмую": 8, "восьмая": 8, "восьмой": 8,
    "девятую": 9, "девятая": 9, "девятый": 9,
    "десятую": 10, "десятая": 10, "десятый": 10,
}


def replace_number_words(text: str) -> str:
    """Заменяет словесные числительные на цифры.
    
    Обрабатывает составные числа (например, "двадцать пять" -> "25").
    """
    tokens = text.split()
    result, i = [], 0
    
    while i < len(tokens):
        token = tokens[i]
        if token in NUM_WORDS:
            first_val = NUM_WORDS[token]
            # Проверка составных чисел
            if i + 1 < len(tokens) and tokens[i + 1] in NUM_WORDS:
                second_val = NUM_WORDS[tokens[i + 1]]
                if (first_val >= 20 and first_val % 10 == 0 and second_val < 10) or \
                   (first_val == 0 and 0 <= second_val < 10):
                    result.append(str(first_val + second_val if first_val else second_val))
                    i += 2
                    continue
            result.append(str(first_val))
            i += 1
        else:
            result.append(token)
            i += 1
    
    return " ".join(result)


def _number_to_text(n: int) -> str:
    """Преобразует число от 0 до 99 в текст."""
    ones = ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
    tens = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"]
    teens = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать", 
             "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
    
    if n == 0:
        return "ноль"
    elif n < 10:
        return ones[n]
    elif 10 <= n < 20:
        return teens[n - 10]
    elif n < 100:
        return (tens[n // 10] + (" " + ones[n % 10] if n % 10 != 0 else "")).strip()
    else:
        return str(n)

def _hundreds_to_text(n: int) -> str:
    """Преобразует сотни (100-900) в текст."""
    hundreds = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"]
    return hundreds[n // 100] if 0 <= n // 100 < len(hundreds) else ""

def year_to_text(year: int, case: str = "nominative") -> str:
    """Преобразует год в текстовое представление."""
    if not (1000 <= year <= 2999):
        return str(year)
    
    # Для годов 2000-2099
    if 2000 <= year <= 2099:
        decade = year - 2000
        if case == "prepositional":
            if decade == 0:
                return "двухтысячном году"
            elif decade < 10:
                ordinals = ["", "первом", "втором", "третьем", "четвертом", "пятом", 
                           "шестом", "седьмом", "восьмом", "девятом"]
                return f"две тысячи {ordinals[decade]} году"
            elif decade < 20:
                teens_ord = ["десятом", "одиннадцатом", "двенадцатом", "тринадцатом", "четырнадцатом",
                            "пятнадцатом", "шестнадцатом", "семнадцатом", "восемнадцатом", "девятнадцатом"]
                return f"две тысячи {teens_ord[decade - 10]} году"
            else:
                tens_ord = ["", "", "двадцатом", "тридцатом", "сороковом", "пятидесятом", 
                           "шестидесятом", "семидесятом", "восьмидесятом", "девяностом"]
                ones_ord = ["", "первом", "втором", "третьем", "четвертом", "пятом", 
                           "шестом", "седьмом", "восьмом", "девятом"]
                
                if decade % 10 == 0:
                    return f"две тысячи {tens_ord[decade // 10]} году"
                else:
                    return f"две тысячи {_number_to_text(decade // 10 * 10)} {ones_ord[decade % 10]} году"
        elif case == "genitive":
            # Родительный падеж
            if decade == 0:
                return "двухтысячного года"
            elif decade < 10:
                ordinals_gen = ["", "первого", "второго", "третьего", "четвертого", "пятого", 
                               "шестого", "седьмого", "восьмого", "девятого"]
                return f"две тысячи {ordinals_gen[decade]} года"
            elif decade < 20:
                teens_ord_gen = ["десятого", "одиннадцатого", "двенадцатого", "тринадцатого", "четырнадцатого",
                                "пятнадцатого", "шестнадцатого", "семнадцатого", "восемнадцатого", "девятнадцатого"]
                return f"две тысячи {teens_ord_gen[decade - 10]} года"
            else:
                tens_ord_gen = ["", "", "двадцатого", "тридцатого", "сорокового", "пятидесятого", 
                               "шестидесятого", "семидесятого", "восьмидесятого", "девяностого"]
                ones_ord_gen = ["", "первого", "второго", "третьего", "четвертого", "пятого", 
                               "шестого", "седьмого", "восьмого", "девятого"]
                
                if decade % 10 == 0:
                    return f"две тысячи {tens_ord_gen[decade // 10]} года"
                else:
                    return f"две тысячи {_number_to_text(decade // 10 * 10)} {ones_ord_gen[decade % 10]} года"
        else:
            if decade == 0:
                return "двухтысячный год"
            else:
                return f"две тысячи {_number_to_text(decade)} год"
    
    # Для годов 1900-1999
    elif 1900 <= year <= 1999:
        decade = year - 1900
        if case == "prepositional":
            if decade == 0:
                return "тысяча девятисотом году"
            else:
                hundreds_text = "тысяча девятьсот"
                
                if decade < 10:
                    ordinals = ["", "первом", "втором", "третьем", "четвертом", "пятом", 
                               "шестом", "седьмом", "восьмом", "девятом"]
                    return f"{hundreds_text} {ordinals[decade]} году"
                elif decade < 20:
                    teens_ord = ["десятом", "одиннадцатом", "двенадцатом", "тринадцатом", "четырнадцатом",
                                "пятнадцатом", "шестнадцатом", "семнадцатом", "восемнадцатом", "девятнадцатом"]
                    return f"{hundreds_text} {teens_ord[decade - 10]} году"
                else:
                    tens_ord = ["", "", "двадцатом", "тридцатом", "сороковом", "пятидесятом", 
                               "шестидесятом", "семидесятом", "восьмидесятом", "девяностом"]
                    ones_ord = ["", "первом", "втором", "третьем", "четвертом", "пятом", 
                               "шестом", "седьмом", "восьмом", "девятом"]
                    
                    if decade % 10 == 0:
                        return f"{hundreds_text} {tens_ord[decade // 10]} года"
                    else:
                        return f"{hundreds_text} {_number_to_text(decade // 10 * 10)} {ones_ord[decade % 10]} года"
        elif case == "genitive":
            # Родительный падеж
            hundreds_text = "тысяча девятьсот"
            if decade == 0:
                return "тысяча девятисотого года"
            elif decade < 10:
                ordinals_gen = ["", "первого", "второго", "третьего", "четвертого", "пятого", 
                               "шестого", "седьмого", "восьмого", "девятого"]
                return f"{hundreds_text} {ordinals_gen[decade]} года"
            elif decade < 20:
                teens_ord_gen = ["десятого", "одиннадцатого", "двенадцатого", "тринадцатого", "четырнадцатого",
                                "пятнадцатого", "шестнадцатого", "семнадцатого", "восемнадцатого", "девятнадцатого"]
                return f"{hundreds_text} {teens_ord_gen[decade - 10]} года"
            else:
                tens_ord_gen = ["", "", "двадцатого", "тридцатого", "сорокового", "пятидесятого", 
                               "шестидесятого", "семидесятого", "восьмидесятого", "девяностого"]
                ones_ord_gen = ["", "первого", "второго", "третьего", "четвертого", "пятого", 
                               "шестого", "седьмого", "восьмого", "девятого"]
                
                if decade % 10 == 0:
                    return f"{hundreds_text} {tens_ord_gen[decade // 10]} года"
                else:
                    return f"{hundreds_text} {_number_to_text(decade // 10 * 10)} {ones_ord_gen[decade % 10]} года"
        else:
            hundreds_text = "тысяча девятьсот"
            if decade == 0:
                return f"{hundreds_text} год"
            else:
                return f"{hundreds_text} {_number_to_text(decade)} год"
    
    # Для других годов (1000-1899, 2100-2999)
    else:
        # Упрощенный вариант для других веков
        thousands = year // 1000
        remainder = year % 1000
        hundreds = remainder // 100
        tens = remainder % 100
        
        if case == "prepositional":
            # Для предложного падежа нужна более сложная логика, пока упрощаем
            return f"{year} году"
        else:
            parts = []
            if thousands == 1:
                parts.append("тысяча")
            elif thousands == 2:
                parts.append("две тысячи")
            
            if hundreds > 0:
                parts.append(_hundreds_to_text(hundreds * 100))
            
            if tens > 0:
                parts.append(_number_to_text(tens))
            
            parts.append("год")
            return " ".join(parts)

def convert_years_in_text(text: str) -> str:
    """Преобразует годы в тексте в правильное произношение.
    
    Обрабатывает как контекстные случаи (родился в, вышел в), так и отдельно стоящие годы.
    """
    result = text
    
    def replace_v_year_godu(match):
        year_str = match.group(1)
        try:
            year = int(year_str)
            if 1900 <= year <= 2099:
                year_text = year_to_text(year, "prepositional")
                return f"в {year_text}"
            return match.group(0)
        except ValueError:
            return match.group(0)
    
    result = re.sub(r'\bв\s+((?:19|20)\d{2})\s+году\b', replace_v_year_godu, result, flags=re.IGNORECASE)
    
    context_patterns = [
        r'\b(родил[ас]я|родился|родилась|появил[ас]я|появился|появилась)\s+в\s+((?:19|20)\d{2})\b',
        r'\b(вышел|вышла|вышло|выпущен|выпущена|выпущено|создан|создана|создано|основан|основана|основано)\s+в\s+((?:19|20)\d{2})\b',
        r'\b(умер|умерла|скончал[ас]я|скончался|скончалась)\s+в\s+((?:19|20)\d{2})\b',
    ]
    
    for pattern in context_patterns:
        def replace_context_year(match):
            context_word = match.group(1)
            year_str = match.group(2)
            try:
                year = int(year_str)
                if 1900 <= year <= 2099:
                    year_text = year_to_text(year, "prepositional")
                    return f"{context_word} в {year_text}"
                return match.group(0)
            except ValueError:
                return match.group(0)
        
        result = re.sub(pattern, replace_context_year, result, flags=re.IGNORECASE)
    
    def replace_v_year(match):
        year_str = match.group(1)
        try:
            year = int(year_str)
            if 1900 <= year <= 2099:
                year_text = year_to_text(year, "prepositional")
                return f"в {year_text}"
            return match.group(0)
        except ValueError:
            return match.group(0)
    
    result = re.sub(r'\bв\s+((?:19|20)\d{2})\b(?!\s+году)', replace_v_year, result, flags=re.IGNORECASE)
    
    def replace_year_goda(match):
        year_str = match.group(1)
        try:
            year = int(year_str)
            if 1900 <= year <= 2099:
                # Используем родительный падеж (genitive) для правильного произношения
                year_text = year_to_text(year, "genitive")
                return year_text
            return match.group(0)
        except ValueError:
            return match.group(0)
    
    result = re.sub(r'\b((?:19|20)\d{2})\s+года\b', replace_year_goda, result, flags=re.IGNORECASE)
    
    def replace_year_god(match):
        year_str = match.group(1)
        try:
            year = int(year_str)
            if 1900 <= year <= 2099:
                year_text = year_to_text(year, "nominative")
                # year_text уже содержит слово "год", поэтому просто возвращаем его
                return year_text
            return match.group(0)
        except ValueError:
            return match.group(0)
    
    result = re.sub(r'\b((?:19|20)\d{2})\s+год\b', replace_year_god, result, flags=re.IGNORECASE)
    
    def replace_standalone_year(match):
        year_str = match.group(0)
        try:
            year = int(year_str)
            if 1900 <= year <= 2099:
                # Проверяем, что это похоже на год (не телефон, не другое число)
                return year_to_text(year, "nominative")
            return year_str
        except ValueError:
            return year_str
    
    result = re.sub(r'(?<!в\s)(?<!года\s)(?<!году\s)\b((?:19|20)\d{2})\b(?!\s+году)(?!\s+года)', 
                   replace_standalone_year, result)
    
    return result

def format_date_for_tts(date_str: str) -> str:
    """
    Преобразует дату в формате DD.MM.YYYY HH:MM в читаемый текст для TTS.
    """
    try:
        # Разбираем дату
        match = re.match(r'(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+(\d{1,2}):(\d{2}))?', date_str)
        if not match:
            return date_str
        
        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3))
        
        # Названия месяцев в родительном падеже (какого числа?)
        month_names = [
            "", "января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря"
        ]
        
        if not (1 <= month <= 12):
            return date_str
        
        month_name = month_names[month]
        
        # Формируем читаемую дату
        # Используем year_to_text для правильного произношения года
        year_text = year_to_text(year, "genitive")
        
        return f"{day} {month_name} {year_text}"
        
    except Exception:
        return date_str