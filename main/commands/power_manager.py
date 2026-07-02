import re
import subprocess
from typing import Optional
from main.lang_ru import TIME_UNITS, replace_number_words


# Глобальная переменная для отслеживания запланированных действий
_scheduled_shutdown = None  # Тип: None | 'shutdown' | 'restart'


def _run_power_command(argv: list[str]) -> None:
    subprocess.Popen(argv)


def execute_power_command(text: str) -> Optional[str]:
    """Обрабатывает команды управления питанием."""

    lowered = text.lower()
    
    # Отмена запланированного выключения/перезагрузки
    if re.search(r"\b(отмени|отменить)\s+(выключение|перезагрузку|выключени[ея]|перезагрузк[уи])\b", lowered):
        return _cancel_shutdown()
    
    # Спящий режим
    if "спящий режим" in lowered or "режим сна" in lowered:
        subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        return "Перевожу компьютер в спящий режим."
    
    # Выключение через время
    if re.search(r"\b(выключ[иь]|выключить)\s+(компьютер\s+)?через\b", lowered):
        return _schedule_shutdown(lowered, action="shutdown")
    
    # Перезагрузка через время
    if re.search(r"\b(перезагруз[иь]|перезагрузить)\s+(компьютер\s+)?через\b", lowered):
        return _schedule_shutdown(lowered, action="restart")
    
    # Немедленное выключение
    if re.search(r"\b(выключ[иь]|выключить)\s+компьютер\b", lowered):
        _run_power_command(["shutdown", "/s", "/t", "0"])
        return "Выключаю компьютер."
    
    # Немедленная перезагрузка
    if re.search(r"\b(перезагруз[иь]|перезагрузить)\s+компьютер\b", lowered):
        _run_power_command(["shutdown", "/r", "/t", "0"])
        return "Перезагружаю компьютер."
    
    return None


def _schedule_shutdown(text: str, action: str) -> str:
    """Планирует выключение или перезагрузку через указанное время."""

    global _scheduled_shutdown
    
    cleaned = replace_number_words(text)
    
    # Парсинг времени: "через N минут/часов/секунд"
    # Паттерн 1: через N единиц
    if m := re.search(r"через\s+(\d+)\s+([а-я]+)", cleaned):
        n = int(m.group(1))
        unit = m.group(2)
        
        # Определяем секунды
        seconds = n * TIME_UNITS.get(unit, 60)  # По умолчанию минуты
    
    # Паттерн 2: через единицу (подразумевается 1)
    elif m := re.search(r"через\s+([а-я]+)", cleaned):
        unit = m.group(1)
        seconds = TIME_UNITS.get(unit, 60)
        n = 1
    
    else:
        return "Не удалось распознать время. Скажите, например: 'выключи компьютер через 10 минут'."
    
    # Ограничение: не более 24 часов
    if seconds > 86400:
        return "Максимальное время отложенного выключения - 24 часа."
    
    try:
        if action == "shutdown":
            cmd = ["shutdown", "/s", "/t", str(seconds)]
            action_name = "Выключение"
        else:  # restart
            cmd = ["shutdown", "/r", "/t", str(seconds)]
            action_name = "Перезагрузка"
        
        _run_power_command(cmd)
        _scheduled_shutdown = action
        
        # Форматирование времени для ответа
        if seconds >= 3600:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            time_str = f"{hours} ч" + (f" {minutes} мин" if minutes else "")
        elif seconds >= 60:
            minutes = seconds // 60
            time_str = f"{minutes} мин"
        else:
            time_str = f"{seconds} сек"
        
        return f"{action_name} запланировано через {time_str}."
    
    except Exception as e:
        print(f"[POWER] Ошибка планирования: {e}")
        return f"Не удалось запланировать {action_name.lower()}."


def _cancel_shutdown() -> str:
    """Отменяет запланированное выключение или перезагрузку."""
    global _scheduled_shutdown
    
    try:
        # Отменяем через команду shutdown -a
        result = subprocess.run(["shutdown", "/a"], capture_output=True, text=True)
        
        if result.returncode == 0:
            action_name = "выключение" if _scheduled_shutdown == "shutdown" else "перезагрузка"
            _scheduled_shutdown = None
            return f"Запланированное {action_name} отменено."
        else:
            # Проверяем, нет ли активного выключения
            if "не удается" in result.stderr.lower() or "unable" in result.stderr.lower():
                return "Нет запланированного выключения или перезагрузки."
            return "Не удалось отменить."
    
    except Exception as e:
        print(f"[POWER] Ошибка отмены: {e}")
        return "Ошибка при отмене."
