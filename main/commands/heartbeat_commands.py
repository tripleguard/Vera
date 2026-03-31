import re
import datetime
import threading
from typing import Optional, Callable
from dataclasses import dataclass, asdict
from user.json_storage import load_json, save_json
from main.lang_ru import replace_number_words
from main.config_manager import get_data_dir
from .scheduler_base import SchedulerBase, TIME_FORMAT, now_str
import os

_HEARTBEAT_FILE = get_data_dir() / "heartbeat_tasks.json"

@dataclass
class HeartbeatTask:
    task_text: str
    time: str              # "HH:MM"
    recurring: str         # "once", "daily", "weekdays", "weekends", "interval"
    created_at: str        # Дата создания YYYY-MM-DD-HH-MM
    last_run: Optional[str] = None
    enabled: bool = True
    target_date: Optional[str] = None
    interval_minutes: int = 0

_heartbeat_tasks: list[HeartbeatTask] = []
_ROUTE_CMD_CB: Optional[Callable[[str], str]] = None

def set_heartbeat_route_callback(cb: Callable[[str], str]) -> None:
    """Устанавливает функцию выполнения команды (route_command)."""
    global _ROUTE_CMD_CB
    _ROUTE_CMD_CB = cb

def _save_heartbeat_tasks() -> None:
    data = [asdict(t) for t in _heartbeat_tasks]
    save_json(_HEARTBEAT_FILE, data, "HEARTBEAT")
    if _heartbeat_scheduler:
        _heartbeat_scheduler.update_mtime()

def _load_heartbeat_tasks() -> None:
    global _heartbeat_tasks
    data = load_json(_HEARTBEAT_FILE, [])
    if not data:
        return
    
    loaded = []
    for item in data:
        try:
            loaded.append(HeartbeatTask(
                task_text=item["task_text"],
                time=item["time"],
                recurring=item.get("recurring", "daily"),
                created_at=item.get("created_at", now_str()),
                last_run=item.get("last_run"),
                enabled=item.get("enabled", True),
                target_date=item.get("target_date"),
                interval_minutes=item.get("interval_minutes", 0)
            ))
        except Exception as e:
            print(f"[HEARTBEAT] Ошибка загрузки задачи: {e}")
            
    _heartbeat_tasks = loaded
    print(f"[HEARTBEAT] Загружено {len(_heartbeat_tasks)} периодических задач")

def _should_run_today(task: HeartbeatTask) -> bool:
    if not task.enabled:
        return False
    
    today = datetime.datetime.now()
    weekday = today.weekday()
    today_str = today.strftime("%Y-%m-%d")
    
    if task.recurring == "once":
        if task.last_run:
            return False
        if task.target_date:
            return task.target_date == today_str
        return True
    elif task.recurring == "daily":
        return True
    elif task.recurring == "weekdays":
        return weekday < 5
    elif task.recurring == "weekends":
        return weekday >= 5
    return False

def _was_run_today(task: HeartbeatTask) -> bool:
    if not task.last_run:
        return False
    try:
        last = datetime.datetime.strptime(task.last_run, TIME_FORMAT)
        return last.date() == datetime.datetime.now().date()
    except Exception:
        return False

class _HeartbeatScheduler(SchedulerBase):
    def __init__(self):
        super().__init__(name="HEARTBEAT", tick_interval=30.0)
        self._last_mtime = 0.0
        
    def update_mtime(self):
        if _HEARTBEAT_FILE.exists():
            self._last_mtime = os.path.getmtime(_HEARTBEAT_FILE)
            
    def _on_start(self):
        _load_heartbeat_tasks()
        self.update_mtime()
        
    def _tick(self):
        # Hot reload
        if _HEARTBEAT_FILE.exists():
            current_mtime = os.path.getmtime(_HEARTBEAT_FILE)
            if current_mtime > self._last_mtime:
                print(f"[HEARTBEAT] Файл обновлен извне, перезагружаю задачи...")
                _load_heartbeat_tasks()
                self._last_mtime = current_mtime
                
        now = datetime.datetime.now()
        current_time = now.strftime("%H:%M")
        
        for task in _heartbeat_tasks:
            if not task.enabled:
                continue
            
            should_run_now = False

            if task.recurring == "interval":
                # Интервальные задачи: проверяем сколько минут прошло с last_run или created_at
                last_time_str = task.last_run if task.last_run else task.created_at
                try:
                    last_time = datetime.datetime.strptime(last_time_str, TIME_FORMAT)
                except Exception:
                    last_time = now
                
                # Если прошло достаточно минут (и интервал задан корректно > 0)
                if task.interval_minutes > 0 and (now - last_time).total_seconds() >= task.interval_minutes * 60:
                    should_run_now = True
            else:
                # Обычные задачи: сверяем точное время и день
                if task.time == current_time and not _was_run_today(task) and _should_run_today(task):
                    should_run_now = True

            if not should_run_now:
                continue
                
            print(f"[HEARTBEAT] Исполняю задачу: {task.task_text}")
            
            try:
                if _ROUTE_CMD_CB:
                    # Выполняем задачу: прокидываем в парсер команд
                    result = _ROUTE_CMD_CB(task.task_text)
                    if result:
                        print(f"[HEARTBEAT] Результат: {result}")
                        self.speak(f"Напоминание по задаче: {result}")
            except Exception as e:
                print(f"[HEARTBEAT] Ошибка выполнения задачи '{task.task_text}': {e}")
                
            task.last_run = now_str()
            if task.recurring == "once":
                task.enabled = False
            _save_heartbeat_tasks()

_heartbeat_scheduler = _HeartbeatScheduler()

def start_heartbeat_scheduler() -> None:
    _heartbeat_scheduler.start()

def set_heartbeat_speak_callback(cb: Callable) -> None:
    _heartbeat_scheduler.set_speak_callback(cb)
    
def set_heartbeat_shutdown_event(event: threading.Event) -> None:
    _heartbeat_scheduler.set_shutdown_event(event)

def add_heartbeat_task(task_text: str, time_str: str, recurring: str="daily", target_date: Optional[str]=None, interval_minutes: int=0) -> HeartbeatTask:
    # Важно: перезагрузим задачи перед добавлением, чтобы избежать перезаписи чужих правок
    if _heartbeat_scheduler and _HEARTBEAT_FILE.exists():
        current_mtime = os.path.getmtime(_HEARTBEAT_FILE)
        if current_mtime > _heartbeat_scheduler._last_mtime:
            _load_heartbeat_tasks()
            
    task = HeartbeatTask(
        task_text=task_text,
        time=time_str,
        recurring=recurring,
        created_at=now_str(),
        target_date=target_date,
        interval_minutes=interval_minutes
    )
    _heartbeat_tasks.append(task)
    _save_heartbeat_tasks()
    return task

def remove_heartbeat_task_by_text(partial_text: str) -> tuple[bool, int]:
    if _heartbeat_scheduler and _HEARTBEAT_FILE.exists():
        current_mtime = os.path.getmtime(_HEARTBEAT_FILE)
        if current_mtime > _heartbeat_scheduler._last_mtime:
            _load_heartbeat_tasks()
            
    removed = 0
    for task in _heartbeat_tasks[:]:
        if partial_text.lower() in task.task_text.lower():
            _heartbeat_tasks.remove(task)
            removed += 1
            
    if removed > 0:
        _save_heartbeat_tasks()
    return (removed > 0, removed)


_RECURRING_MAP = {
    "каждый день": "daily",
    "ежедневно": "daily",
    "каждое утро": "daily",
    "каждый вечер": "daily",
    "постоянно": "daily",
    "всегда": "daily",
    "регулярно": "daily",
    "систематически": "daily",
    "по будням": "weekdays",
    "по рабочим": "weekdays",
    "в будни": "weekdays",
    "в рабочие дни": "weekdays",
    "в рабочее время": "weekdays",
    "когда работаю": "weekdays",
    "по выходным": "weekends",
    "в выходные": "weekends",
    "на выходных": "weekends",
    "один раз": "once",
    "однократно": "once",
}

_RECURRING_NAMES = {
    "daily": "ежедневно",
    "weekdays": "по будням",
    "weekends": "по выходным",
    "once": "один раз",
    "interval": "интервал",
}

def execute_heartbeat_command(text: str) -> Optional[str]:
    lowered = text.lower().strip()
    cleaned = replace_number_words(lowered)
    
    # Покажи / Удали
    if re.search(r"(покажи|список|какие)\s+(периодически|фоновы|сервисны|запланированны.*задач|расписани)", cleaned):
        if not _heartbeat_tasks:
            return "Нет активных периодических задач."
        lines = [f"Периодических задач: {len(_heartbeat_tasks)}"]
        for i, t in enumerate(_heartbeat_tasks, 1):
            st = "[+]" if t.enabled else "[-]"
            r = _RECURRING_NAMES.get(t.recurring, t.recurring)
            if t.recurring == "interval":
                lines.append(f"{i}. {st} [Интервал {t.interval_minutes} мин] {t.task_text}")
            else:
                lines.append(f"{i}. {st} [{t.time}] {t.task_text} ({r})")
        return "\n".join(lines)
        
    if m := re.search(r"(удали|отмени|убери)\s+(?:задачу|запуск|запланированн\w+\s+запуск\s+)?(.+)", cleaned):
        # Если команда звучит как удаление задачи из heartbeat или приложений
        if "задач" in cleaned or "напоминани" in cleaned or "запуск" in cleaned or "расписани" in cleaned:
            task_name = m.group(2).strip()
            success, count = remove_heartbeat_task_by_text(task_name)
            if success:
                return f"Удалено периодических задач: {count}."
            return None # Пропускаем дальше, возможно это удаление из ToDo листа
            
    # Добавление: "читай новости каждое утро в 9 30"
    patterns = [
        # <task> <recurring> в <time>
        r"(.+?)\s+(каждый день|ежедневно|каждое утро|каждый вечер|постоянно|регулярно|по будням|по выходным)\s+в\s+(\d{1,2})[:.\s]?(\d{0,2})(?:\s+утра|\s+вечера)?(?:$|\s)",
        # <recurring> в <time> <task>
        r"(каждый день|ежедневно|каждое утро|каждый вечер|постоянно|регулярно|по будням|по выходным)\s+в\s+(\d{1,2})[:.\s]?(\d{0,2})\s+(.+)",
        # <task> в <time> <recurring>
        r"(.+?)\s+в\s+(\d{1,2})[:.\s]?(\d{0,2})\s+(каждый день|ежедневно|каждое утро|каждый вечер|постоянно|регулярно|по будням|по выходным)",
        # <recurring> <task> в <time>
        r"(каждый день|ежедневно|каждое утро|каждый вечер|постоянно|регулярно|по будням|по выходным)\s+(.+?)\s+в\s+(\d{1,2})[:.\s]?(\d{0,2})(?:\s+утра|\s+вечера)?(?:$|\s)",
    ]
    
    for i, pat in enumerate(patterns):
        if m := re.search(pat, cleaned):
            groups = m.groups()
            if i == 0:
                task_text, rec_text, hour, minute = groups
            elif i == 1:
                rec_text, hour, minute, task_text = groups
            elif i == 2:
                task_text, hour, minute, rec_text = groups
            elif i == 3:
                rec_text, task_text, hour, minute = groups
                
            task_text = task_text.strip()
            
            hour = int(hour)
            minute = int(minute) if minute else 0
            
            # Корректировка времени если "каждое утро" и т.д.
            if "вечер" in rec_text and hour < 12:
                hour += 12
                
            if hour > 23 or minute > 59:
                return "Неверное время."
                
            time_str = f"{hour:02d}:{minute:02d}"
            rec = _RECURRING_MAP.get(rec_text.strip(), "daily")
            
            # Если это запрос вроде "напомни/запомни/Вера", немного почистим начало
            task_text = re.sub(r"^(вера|напомни|запомни)\s+", "", task_text).strip()
            
            add_heartbeat_task(task_text, time_str, rec)
            rname = _RECURRING_NAMES.get(rec, rec)
            return f"Периодическая задача добавлена: '{task_text}' в {time_str} ({rname})."
            
    # Добавление на "через N минут/часов"
    if m := re.search(r"(?:через|через\s+время)\s+(\d+)\s+(минут[уыа]?|час[оав]?)\s+(.+)", cleaned):
        amount = int(m.group(1))
        unit = m.group(2)
        task_text = m.group(3).strip()
        
        now = datetime.datetime.now()
        if "час" in unit:
            target = now + datetime.timedelta(hours=amount)
        else:
            target = now + datetime.timedelta(minutes=amount)
            
        time_str = target.strftime("%H:%M")
        target_date = target.strftime("%Y-%m-%d")
        
        task_text = re.sub(r"^(вера|напомни|запомни)\s+", "", task_text).strip()
        add_heartbeat_task(task_text, time_str, "once", target_date)
        return f"Задача запланирована на {time_str} ('{task_text}')."
            
    # Добавление на интервалы "каждые N минут/часов", "каждые полчаса", "каждые пол часа"
    if m := re.search(r"каждые\s+(полчаса|пол\s+часа)", cleaned):
        task_text = re.sub(r".*каждые\s+(полчаса|пол\s+часа)\s*", "", cleaned).strip()
        if not task_text:
            task_text = "полчаса прошло"
            
        task_text = re.sub(r"^(вера|напомни|запомни)\s+", "", task_text).strip()
        add_heartbeat_task(task_text, now_str()[-5:], recurring="interval", interval_minutes=30)
        return f"Периодическая задача добавлена: '{task_text}' (интервал 30 мин)."
        
    if m := re.search(r"каждые\s+(\d+)\s+(минут[уыа]?|час[оав]?)", cleaned):
        amount = int(m.group(1))
        unit = m.group(2)
        
        interval_minutes = amount if "мин" in unit else amount * 60
        
        # Убираем "каждые N минут" из текста задачи
        task_text = re.sub(r"каждые\s+\d+\s+(минут[уыа]?|час[оав]?)", "", cleaned).strip()
        if not task_text:
            task_text = f"прошло {amount} {unit}"
            
        task_text = re.sub(r"^(вера|напомни|запомни)\s+", "", task_text).strip()
        
        time_str = datetime.datetime.now().strftime("%H:%M")
        add_heartbeat_task(task_text, time_str, recurring="interval", interval_minutes=interval_minutes)
        return f"Периодическая задача добавлена: '{task_text}' (интервал {interval_minutes} мин)."
        
    # Напоминание/запуск с указанием дня: "запусти телегу завтра в 22:00" или "напомни купить хлеб сегодня в 12:00"
    patterns_once_day = [
        r"(.+?)\s+(сегодня|завтра)\s+в\s+(\d{1,2})[:.\s]?(\d{0,2})(?:\s+утра|\s+вечера)?(?:$|\s)",
        r"(сегодня|завтра)\s+в\s+(\d{1,2})[:.\s]?(\d{0,2})\s+(.+)",
    ]
    for i, pat in enumerate(patterns_once_day):
        if m := re.search(pat, cleaned):
            if i == 0:
                task_text, day, hour, minute = m.group(1), m.group(2), m.group(3), m.group(4)
            else:
                day, hour, minute, task_text = m.group(1), m.group(2), m.group(3), m.group(4)
                
            hour = int(hour)
            minute = int(minute) if minute else 0
            
            if hour <= 23 and minute <= 59:
                today = datetime.datetime.now()
                if day == "завтра":
                    target = today + datetime.timedelta(days=1)
                else:
                    target = today
                
                target_date = target.strftime("%Y-%m-%d")
                time_str = f"{hour:02d}:{minute:02d}"
                
                task_text = re.sub(r"^(вера|напомни|запомни)\s+", "", task_text).strip()
                add_heartbeat_task(task_text, time_str, "once", target_date)
                day_name = "сегодня" if day == "сегодня" else "завтра"
                return f"Задача запланирована на {day_name} в {time_str} ('{task_text}')."

    # Простой вариант (умное определение даты): "напомни выключить суп в 20 00"
    if not any(k in cleaned for k in ["каждый", "каждую", "ежедневно", "постоянно", "регулярно", "будням", "выходным", "всегда"]):
        if m := re.search(r"(.+?)\s+в\s+(\d{1,2})[:.\s]?(\d{0,2})(?:\s+(утра|вечера|ночи|дня))?(?:$|\s)", cleaned):
            if "завтра" not in cleaned and "сегодня" not in cleaned:
                task_text = m.group(1).strip()
                hour = int(m.group(2))
                minute = int(m.group(3)) if m.group(3) else 0
                period = m.group(4) if len(m.groups()) >= 4 else None
                
                if period == "вечера" and hour < 12:
                    hour += 12
                elif period == "ночи" and hour < 12:
                    hour = hour
                elif period == "дня" and hour < 12:
                    hour += 12
                    
                if hour <= 23 and minute <= 59:
                    now = datetime.datetime.now()
                    target_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    
                    if target_time <= now:
                        target = now + datetime.timedelta(days=1)
                        day_name = "завтра"
                    else:
                        target = now
                        day_name = "сегодня"
                    
                    target_date = target.strftime("%Y-%m-%d")
                    time_str = f"{hour:02d}:{minute:02d}"
                    
                    task_text = re.sub(r"^(вера|напомни|запомни)\s+", "", task_text).strip()
                    add_heartbeat_task(task_text, time_str, "once", target_date)
                    return f"Задача запланирована на {day_name} в {time_str} ('{task_text}')."

    return None

