"""
Базовая инфраструктура для фоновых планировщиков.

Обеспечивает общие элементы, используемые time_commands и heartbeat_commands:
- Формат даты/времени для JSON хранения
- Управление callback-ами (speak, shutdown event)
- Запуск фонового потока-планировщика
"""

import threading
import datetime
from typing import Optional, Callable


# Единый формат времени для хранения (актуальный - с секундами)
TIME_FORMAT = "%Y-%m-%d-%H-%M-%S"
LEGACY_TIME_FORMAT = "%Y-%m-%d-%H-%M"

def parse_time_str(ts_str: str) -> datetime.datetime:
    """Парсит строку времени, поддерживая старый и новый форматы."""
    try:
        return datetime.datetime.strptime(ts_str, TIME_FORMAT)
    except ValueError:
        try:
            return datetime.datetime.strptime(ts_str, LEGACY_TIME_FORMAT)
        except ValueError:
            return datetime.datetime.now()



def ts_from_float(ts: float) -> str:
    """Конвертирует unix timestamp в строковый формат."""
    return datetime.datetime.fromtimestamp(ts).strftime(TIME_FORMAT)


def ts_to_float(ts_str: str) -> float:
    """Конвертирует строковый формат в unix timestamp."""
    return parse_time_str(ts_str).timestamp()


def now_str() -> str:
    """Возвращает текущее время в стандартном строковом формате."""
    return datetime.datetime.now().strftime(TIME_FORMAT)


class SchedulerBase:
    """
    Базовый класс для фоновых планировщиков.

    Подклассы должны реализовать метод _tick(), который вызывается
    на каждой итерации цикла планировщика.
    """

    def __init__(self, name: str, tick_interval: float = 1.0):
        self._name = name
        self._tick_interval = tick_interval
        self._speak_cb: Optional[Callable] = None
        self._shutdown_event: Optional[threading.Event] = None
        self._started = False

    # ---- callback-ы ----

    def set_speak_callback(self, cb: Callable) -> None:
        self._speak_cb = cb

    def set_shutdown_event(self, event: threading.Event) -> None:
        self._shutdown_event = event

    def speak(self, text: str) -> None:
        """Вызвать callback озвучки, если он установлен."""
        if self._speak_cb:
            self._speak_cb(text)

    # ---- жизненный цикл ----

    def start(self) -> None:
        """Запускает планировщик в фоновом потоке (идемпотентно)."""
        if self._started:
            return
        self._on_start()
        threading.Thread(target=self._loop, daemon=True).start()
        self._started = True

    def _on_start(self) -> None:
        """Хук: вызывается перед запуском цикла (загрузка данных и т.п.)."""

    def _loop(self) -> None:
        while not (self._shutdown_event and self._shutdown_event.is_set()):
            self._tick()
            if self._shutdown_event:
                self._shutdown_event.wait(timeout=self._tick_interval)
            else:
                import time as _t
                _t.sleep(self._tick_interval)
        print(f"[{self._name}] Scheduler остановлен")

    def _tick(self) -> None:
        """Одна итерация планировщика. Должна быть реализована в подклассе."""
        raise NotImplementedError
