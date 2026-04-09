import re
import time
import datetime
import threading
import winsound
from typing import Optional, Callable
from dataclasses import dataclass, asdict
from main.lang_ru import TIME_UNITS, replace_number_words
from main.config_manager import get_data_dir, get_install_root
from user.json_storage import load_json, save_json
from .scheduler_base import SchedulerBase, TIME_FORMAT, ts_from_float, ts_to_float, parse_time_str


# Путь к файлу напоминаний
_REMINDERS_FILE = get_data_dir() / "reminders.json"

# Импорт модуля уведомлений
try:
    from user.notifications import show_reminder_notification
    _NOTIFICATIONS_ENABLED = True
except ImportError:
    _NOTIFICATIONS_ENABLED = False


@dataclass
class _Reminder:
    ts: str  # Время в формате "2025-12-02-19-57"
    message: str
    is_timer: bool = False  # True для таймеров, False для напоминаний
    
    @property
    def timestamp(self) -> float:
        """Возвращает unix timestamp для сравнения."""
        try:
            return ts_to_float(self.ts)
        except Exception:
            return 0.0
    
    @staticmethod
    def from_timestamp(ts: float) -> str:
        """Конвертирует unix timestamp в строковый формат."""
        return ts_from_float(ts)


_scheduled: list[_Reminder] = []
_timer_ringing = False


def stop_timer_ring() -> bool:
    """Останавливает звонок таймера."""
    global _timer_ringing
    was_ringing = _timer_ringing
    _timer_ringing = False
    return was_ringing

def is_timer_ringing() -> bool:
    return _timer_ringing


def _start_timer_ring():
    """Запускает звонок таймера (mp3)."""
    global _timer_ringing
    _timer_ringing = True
    
    def ring_thread():
        try:
            import ctypes
            timer_path = str(get_install_root() / "timer.mp3").replace('/', '\\')
            
            mci = ctypes.windll.winmm.mciSendStringW
            mci('close vera_timer_sound', None, 0, None)
            err_open = mci(f'open "{timer_path}" type mpegvideo alias vera_timer_sound', None, 0, None)
            err_play = mci('play vera_timer_sound repeat', None, 0, None)
            
            if err_open != 0 or err_play != 0:
                print(f"[TIMER] Предупреждение: mciSendString вернул ошибку, код open: {err_open}, play: {err_play}")
            
            # Ждём, пока флаг не станет False
            while _timer_ringing:
                time.sleep(0.5)
                
            # Закрываем устройство в ТОМ ЖЕ потоке, в котором оно было открыто
            mci('stop vera_timer_sound', None, 0, None)
            mci('close vera_timer_sound', None, 0, None)
        except Exception as e:
            print(f"[TIMER] Ошибка воспроизведения timer.mp3: {e}")
            
    threading.Thread(target=ring_thread, daemon=True).start()


def _save_reminders() -> None:
    """Сохраняет напоминания в JSON файл."""
    data = [asdict(r) for r in _scheduled]
    save_json(_REMINDERS_FILE, data, "REMINDER")


def _load_reminders() -> None:
    """Загружает напоминания из JSON файла."""
    global _scheduled
    data = load_json(_REMINDERS_FILE, [])
    if not data:
        return
    now = time.time()
    loaded = []
    for r in data:
        ts_val = r.get("ts")
        # Поддержка старого формата (float) и нового (string)
        if isinstance(ts_val, (int, float)):
            # Старый формат - конвертируем
            ts_str = _Reminder.from_timestamp(ts_val)
            ts_float = ts_val
        else:
            ts_str = ts_val
            try:
                ts_float = ts_to_float(ts_str)
            except Exception:
                continue
        
        if ts_float > now:
            loaded.append(_Reminder(ts=ts_str, message=r["message"], is_timer=r.get("is_timer", False)))
    
    _scheduled = loaded
    # Сохраняем обновлённый список (без просроченных, в новом формате)
    if len(_scheduled) != len(data):
        _save_reminders()
    print(f"[REMINDER] Загружено {len(_scheduled)} напоминаний")


class _ReminderScheduler(SchedulerBase):
    """Планировщик напоминаний и таймеров."""

    def __init__(self):
        super().__init__(name="REMINDER", tick_interval=1.0)

    def _on_start(self):
        _load_reminders()

    def _tick(self):
        now = time.time()
        for task in _scheduled[:]:
            if now >= task.timestamp:
                print(f"[{'ТАЙМЕР' if task.is_timer else 'REMINDER'}] {task.message}")
                
                if task.is_timer:
                    _start_timer_ring()
                    self.speak(task.message + ". Скажите стоп чтобы отключить.")
                else:
                    self.speak(task.message)
                    if _NOTIFICATIONS_ENABLED:
                        try:
                            show_reminder_notification("⏰ Напоминание", task.message)
                        except Exception:
                            pass
                
                _scheduled.remove(task)
                _save_reminders()


_reminder_scheduler = _ReminderScheduler()

# Публичные функции-обёртки для обратной совместимости
def set_speak_callback(cb: Callable) -> None:
    _reminder_scheduler.set_speak_callback(cb)

def set_shutdown_event(event: threading.Event) -> None:
    _reminder_scheduler.set_shutdown_event(event)

def start_scheduler() -> None:
    """Запускает планировщик напоминаний."""
    _reminder_scheduler.start()


def execute_time_command(text: str) -> Optional[str]:
    """Сообщает текущее время."""
    lowered = text.lower().strip()

    time_patterns = [
        r"\bсколько\s+времени\s*[?.!]?\s*$",  # "сколько времени" в конце
        r"^\s*сколько\s+времени\s*[?.!]?\s*$",  # только "сколько времени"
        r"\bкакое\s+время\b",
        r"\bкоторый\s+час\b",
    ]
    
    if any(re.search(p, lowered) for p in time_patterns) or lowered == "время":
        return f"Сейчас {datetime.datetime.now().strftime('%H:%M')}."
    return None


def execute_date_command(text: str) -> Optional[str]:
    """Сообщает текущую дату."""
    lowered = text.lower().strip()
    
    # Паттерны для запросов о дате
    patterns = [
        r"\bкакой\s+(?:сейчас\s+)?день\b",
        r"\bкакая\s+(?:сейчас\s+)?дата\b",
        r"\bкакое\s+(?:сейчас\s+)?число\b",
        r"\bсколько\s+(?:сейчас\s+)?число\b",
        r"\bкакой\s+(?:сегодня\s+)?день\b",
        r"\bкакая\s+(?:сегодня\s+)?дата\b",
        r"\bкакое\s+(?:сегодня\s+)?число\b",
    ]
    
    if any(re.search(p, lowered) for p in patterns):
        now = datetime.datetime.now()
        
        # Названия дней недели на русском
        weekdays = [
            "понедельник", "вторник", "среда", "четверг",
            "пятница", "суббота", "воскресенье"
        ]
        
        # Названия месяцев на русском (в родительном падеже)
        months = [
            "января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря"
        ]
        
        weekday = weekdays[now.weekday()]
        day = now.day
        month = months[now.month - 1]
        year = now.year
        
        return f"Сегодня {weekday}, {day} {month} {year} года."
    
    return None


def execute_reminder_command(text: str) -> Optional[str]:
    """Обрабатывает команды напоминаний и таймеров."""
    lowered = text.lower()
    cleaned = replace_number_words(lowered)
    
    # Удаление всех напоминаний
    if re.search(r"(удали|отмени|очисти)\s+все\s+напоминани", cleaned):
        count = len(_scheduled)
        _scheduled.clear()
        _save_reminders()
        return f"Удалено напоминаний: {count}" if count else "Напоминаний не было."
    
    # Удаление напоминания
    if m := re.search(r"(удали|отмени)\s+напоминани[ея]\s+на\s+(\d{1,2})[:.\s](\d{1,2})", cleaned):
        hour = max(0, min(int(m.group(2)), 23))
        minute = max(0, min(int(m.group(3)), 59))
        target_str = f"{hour:02d}:{minute:02d}"
        
        removed = 0
        for task in list(_scheduled):
            try:
                if parse_time_str(task.ts).strftime("%H:%M") == target_str:
                    _scheduled.remove(task)
                    removed += 1
            except Exception:
                pass
        
        if removed:
            _save_reminders()
        return f"Удалено напоминание на {target_str}" if removed else \
               f"Напоминаний на {target_str} не найдено."
    
    # Удаление всех таймеров
    if re.search(r"(удали|отмени|очисти|\u0441брось?)\s+все\s+таймер", cleaned):
        timers = [t for t in _scheduled if t.is_timer]
        for t in timers:
            _scheduled.remove(t)
        _save_reminders()
        return f"Удалено таймеров: {len(timers)}" if timers else "Таймеров не было."
    
    # Удаление таймера по времени: "удали таймер на 5 минут"
    if m := re.search(r"(удали|отмени|сбрось?)\s+таймер(?:\s+на)?\s+(\d+)\s+([\u0430-\u044f]+)", cleaned):
        n, unit = int(m.group(2)), m.group(3)
        if unit in TIME_UNITS:
            # Ищем таймер с таким сообщением
            target_msg = f"Таймер {n} {unit} завершён."
            for task in list(_scheduled):
                if task.is_timer and task.message == target_msg:
                    _scheduled.remove(task)
                    _save_reminders()
                    return f"Таймер на {n} {unit} удалён."
            return f"Таймер на {n} {unit} не найден."
    
    # Удаление таймера без указания времени: "удали таймер", "отмени таймер"
    if re.search(r"(удали|отмени|сбрось?)\s+таймер\b", cleaned):
        timers = [t for t in _scheduled if t.is_timer]
        if not timers:
            return "Активных таймеров нет."
        # Удаляем последний добавленный таймер
        last_timer = timers[-1]
        _scheduled.remove(last_timer)
        _save_reminders()
        return f"Таймер удалён."
    
    # Таймер: "таймер на 5 минут", "включи таймер на 10 минут", "поставь таймер на 15 минут"
    if m := re.search(r"(?:включи|поставь|установи|запусти)?\s*таймер\s+(?:на\s+)?(\d+)\s+([\u0430-\u044f]+)", cleaned):
        n, unit = int(m.group(1)), m.group(2)
        if unit in TIME_UNITS:
            sec = n * TIME_UNITS[unit]
            ts_str = _Reminder.from_timestamp(time.time() + sec)
            _scheduled.append(_Reminder(ts_str, f"Таймер {n} {unit} завершён.", is_timer=True))
            _save_reminders()
            return f"Таймер на {n} {unit} установлен."
    
    # Таймер без числа (по умолчанию 1): "таймер минуту"
    if m := re.search(r"(?:включи|поставь|установи|запусти)?\s*таймер\s+(?:на\s+)?([\u0430-\u044f]+)(?:\s|$)", cleaned):
        unit = m.group(1)
        if unit in TIME_UNITS:
            sec = TIME_UNITS[unit]
            ts_str = _Reminder.from_timestamp(time.time() + sec)
            _scheduled.append(_Reminder(ts_str, f"Таймер 1 {unit} завершён.", is_timer=True))
            _save_reminders()
            return f"Таймер на 1 {unit} установлен."
    
    # "напомни позвонить маме через 5 минут"
    if m := re.search(r"(?:напомн(?:и|ить)|поставь\s+напоминани[ея])\s+(.+?)\s+через\s+(\d+)\s+([а-я]+)$", cleaned):
        message, n, unit = m.group(1).strip(), int(m.group(2)), m.group(3)
        if unit in TIME_UNITS:
            sec = n * TIME_UNITS[unit]
            target_ts = time.time() + sec
            ts_str = _Reminder.from_timestamp(target_ts)
            target_time = datetime.datetime.fromtimestamp(target_ts).strftime('%H:%M')
            _scheduled.append(_Reminder(ts_str, message))
            _save_reminders()
            return f"Напоминание на {target_time} установлено."
    
    # "напомни позвонить маме через минуту"
    if m := re.search(r"(?:напомн(?:и|ить)|поставь\s+напоминани[ея])\s+(.+?)\s+через\s+([а-я]+)$", cleaned):
        message, unit = m.group(1).strip(), m.group(2)
        if unit in TIME_UNITS:
            sec = TIME_UNITS[unit]
            target_ts = time.time() + sec
            ts_str = _Reminder.from_timestamp(target_ts)
            target_time = datetime.datetime.fromtimestamp(target_ts).strftime('%H:%M')
            _scheduled.append(_Reminder(ts_str, message))
            _save_reminders()
            return f"Напоминание на {target_time} установлено."
    
    # "напомни через минуту позвонить маме"
    if m := re.search(r"напомн(?:и|ить)\s+через\s+([а-я]+)\s+(.+)", cleaned):
        unit = m.group(1)
        if unit in TIME_UNITS:
            message = m.group(2).strip()
            sec = TIME_UNITS[unit]
            target_ts = time.time() + sec
            ts_str = _Reminder.from_timestamp(target_ts)
            target_time = datetime.datetime.fromtimestamp(target_ts).strftime('%H:%M')
            _scheduled.append(_Reminder(ts_str, message))
            _save_reminders()
            return f"Напоминание на {target_time} установлено."
    
    # "напомни через 5 минут позвонить маме"
    if m := re.search(r"напомн(?:и|ить)\s+через\s+(\d+)\s+([а-я]+)\s+(.+)", cleaned):
        n, unit, message = int(m.group(1)), m.group(2), m.group(3).strip()
        sec = n * TIME_UNITS.get(unit, 60)
        target_ts = time.time() + sec
        ts_str = _Reminder.from_timestamp(target_ts)
        target_time = datetime.datetime.fromtimestamp(target_ts).strftime('%H:%M')
        _scheduled.append(_Reminder(ts_str, message))
        _save_reminders()
        return f"Напоминание на {target_time} установлено."
    
    # Напоминание на конкретное время "напоминание на 14:30 позвонить"
    if m := re.search(r"напоминани[ея]\s+на\s+(\d{1,2})[:.\s](\d{1,2})(?:\s+(.+))?$", cleaned):
        hour = max(0, min(int(m.group(1)), 23))
        minute = max(0, min(int(m.group(2)), 59))
        message = (m.group(3) or "Напоминание").strip()
        
        now_dt = datetime.datetime.now()
        target = now_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now_dt:
            target += datetime.timedelta(days=1)
        
        ts_str = target.strftime(TIME_FORMAT)
        _scheduled.append(_Reminder(ts_str, message))
        _save_reminders()
        return f"Напоминание на {target.strftime('%H:%M')} установлено."
    
    return None


def execute_list_reminders_command(text: str) -> Optional[str]:
    """Показывает список активных напоминаний."""
    lowered = text.lower().strip()
    
    if not re.search(r"(покажи|список|какие|все)\s+напоминани[яй]?", lowered):
        return None
    
    if not _scheduled:
        return "Активных напоминаний нет."
    
    # Сортируем по времени
    sorted_tasks = sorted(_scheduled, key=lambda r: r.timestamp)
    
    lines = [f"Активных напоминаний: {len(sorted_tasks)}"]
    for i, task in enumerate(sorted_tasks, 1):
        try:
            dt = parse_time_str(task.ts)
        except Exception:
            dt = datetime.datetime.now()
        time_str = dt.strftime('%H:%M')
        # Если не сегодня, добавляем дату
        if dt.date() != datetime.datetime.now().date():
            time_str = dt.strftime('%d.%m %H:%M')
        lines.append(f"{i}. {time_str} — {task.message}")
    
    return "\n".join(lines)
