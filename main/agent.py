import json
import os
import re
import queue
import threading
import sys
import time
from contextvars import ContextVar
from array import array
from typing import Any, Callable, Dict, Optional
import difflib
import sounddevice as sd
import sherpa_onnx
from supertonic import TTS
from main.audio_utils import apply_tts_volume
from main.llm_server import LlamaServer, LlamaClient
import msvcrt
from functools import partial
from web.web_search import web_search_answer, execute_wikipedia_command
from web.weather import execute_weather_command
from web.currency import execute_currency_command
from .lang_ru import convert_years_in_text
from .commands import HANDLERS, set_speak_callback, set_last_search_urls_ref, stop_timer_ring, is_timer_ringing, set_timer_ws_callback
from .commands import set_reminder_shutdown_event
from .commands import start_heartbeat_scheduler, set_heartbeat_speak_callback, set_heartbeat_route_callback, set_heartbeat_shutdown_event
from .commands.time_commands import start_scheduler
from user.memory import MemoryManager
from user.memory_extractor import extract_facts, should_extract_facts, extract_from_remember_command
from user.session_store import SessionStore

from .tools import TOOLS
from .tool_definitions import TOOL_DEFINITIONS_BY_NAME, get_tool_definitions
from .tool_router import route_intent
from .tools.presentation_generator import execute_presentation_creation
from .tools.text_document_generator import execute_text_document_creation
from .tools.document_generator import create_docx, create_md, create_pptx, create_txt
from .prompt_builder import build_system_prompt, reload_prompt, get_prompt_status
from .audit import get_audit_logger


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_ws_out_queue: "queue.Queue[dict]" = queue.Queue()
_current_session_id: ContextVar[Optional[str]] = ContextVar("vera_session_id", default=None)
_current_task_id: ContextVar[Optional[str]] = ContextVar("vera_task_id", default=None)

def _send_ws(msg: dict):
    """Send an event tagged with the active session/task when available."""
    payload = dict(msg)
    session_id = _current_session_id.get()
    task_id = _current_task_id.get()
    if session_id and "session_id" not in payload:
        payload["session_id"] = session_id
    if task_id and "task_id" not in payload:
        payload["task_id"] = task_id
    _ws_out_queue.put(payload)

_mic_muted = False
_mic_muted_lock = threading.Lock()  # Lock для thread-safe доступа к _mic_muted
_shutdown_event = threading.Event()  # Event для graceful shutdown
_tts_ready_event = threading.Event()
_agent_ready_event = threading.Event()


def get_agent_readiness() -> dict:
    return {
        "ready": _agent_ready_event.is_set(),
        "tts_ready": _tts_ready_event.is_set(),
    }

_task_seq_lock = threading.Lock()
_task_seq = 0
_MAX_TOOL_LOOP_DEPTH = 4
_PER_TOOL_TIMEOUT_SEC = 20.0


def _next_task_id() -> str:
    global _task_seq
    with _task_seq_lock:
        _task_seq += 1
        return f"task-{_task_seq}"


def _emit_task_status(
    task_id: str,
    state: str,
    extra: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
):
    payload: Dict[str, Any] = {"type": "task_status", "task_id": task_id, "state": state}
    if session_id:
        payload["session_id"] = session_id
    if extra:
        payload.update(extra)
    _send_ws(payload)

# ── Telegram-режим ──
_telegram_mode = None  # Экземпляр TelegramMode (или None)
_TELEGRAM_TRIGGERS = (
    "уйди в телегу", "уйди в телеграм", "перейди в телеграм",
    "запусти телегу", "работай в телеграме", "иди в телегу",
    "переходи в телегу", "переходи в телеграм",
)
_TELEGRAM_EXIT = None  # Lazily loaded from telegram_mode
_WHO_ARE_YOU_RE = re.compile(
    r"(?:^|\W)("
    r"кто\s+ты"
    r"|ты\s+кто"
    r"|кто\s+такая"
    r"|кто\s+такой"
    r"|как\s+тебя\s+зовут"
    r"|представься"
    r"|что\s+ты\s+за\s+агент"
    r")(?:\W|$)",
    re.IGNORECASE,
)

_WAKE_WORD_RE = re.compile("^\\s*\\u0432\\u0435\\u0440\\u0430[\\s,!.?:;\\-]*", re.IGNORECASE)
_GREETING_RE = re.compile(
    "^(?:\\u043f\\u0440\\u0438\\u0432\\u0435\\u0442|\\u0437\\u0434\\u0440\\u0430\\u0432\\u0441\\u0442\\u0432\\u0443\\u0439(?:\\u0442\\u0435)?|\\u0434\\u043e\\u0431\\u0440\\u043e\\u0435\\s+\\u0443\\u0442\\u0440\\u043e|\\u0434\\u043e\\u0431\\u0440\\u044b\\u0439\\s+\\u0434\\u0435\\u043d\\u044c|\\u0434\\u043e\\u0431\\u0440\\u044b\\u0439\\s+\\u0432\\u0435\\u0447\\u0435\\u0440|\\u0445\\u0430\\u0439|\\u043a\\u0443)\\W*$",
    re.IGNORECASE,
)


def _strip_wake_word(text: str) -> str:
    return _WAKE_WORD_RE.sub("", text or "", count=1).strip()


def _is_simple_greeting(text: str) -> bool:
    cleaned = _strip_wake_word(text).strip()
    if not cleaned:
        return True
    return bool(_GREETING_RE.fullmatch(cleaned))

def _is_small_talk(text: str) -> bool:
    """Определяет, является ли запрос простой болтовней/руганью, для которой НЕ нужны инструменты."""
    cleaned = text.lower().strip()
    # Оставляем только буквы и цифры
    cleaned = re.sub(r'[^\w\s]', '', cleaned)
    words = set(cleaned.split())
    
    # 1. Если текст пустой или 1-2 слова без командных глаголов:
    command_keywords = {
        "найди", "погугли", "поищи", "узнай", "открой", "запусти", "закрой",
        "напиши", "отправь", "прочитай", "посчитай", "сколько", "создай", "сделай", 
        "переведи", "скачай", "курс", "погода", "телеграм", "телега", "файл", 
        "документ", "презентация", "запомни", "сохрани", "удали", "включи", "выключи",
        "пароль", "сгенерируй", "кто", "что", "когда"
    }
    
    if len(words) <= 3 and not words.intersection(command_keywords):
        return True
        
    # 2. Прямые паттерны болтовни / ругани
    chat_patterns = [
        r"^как (твой |твои )?дела",
        r"^ч[её] (ты )?делаешь",
        r"^что (ты )?делаешь",
        r"^(как |какое )(тво[её] )?настроение",
        r"^расскажи (о себе|сказку|анекдот|историю)",
        r"^(бля|блять|сука|пздц|еба|хз|заебись|хуй|пиздец)",
        r"^ты (дура|умная|кто|тупая|классная|супер)",
        r"^(очень )?круто",
        r"^(я )?понял",
        r"^(огромное )?(спасибо|спс|благодарю)",
        r"^пожалуйста",
        r"^не за что",
        r"^(да|нет|ок|окей|хорошо|ладно|ясно|понятно)$",
        r"^спокойной ночи",
        r"^доброе утро",
        r"^привет",
    ]
    for p in chat_patterns:
        if re.search(p, cleaned):
            return True
            
    return False

def _get_telegram_exit_commands():
    """Lazily loads Telegram exit commands from telegram_mode module."""
    global _TELEGRAM_EXIT
    if _TELEGRAM_EXIT is None:
        try:
            from main.tools.telegram_mode import TELEGRAM_EXIT_COMMANDS
            _TELEGRAM_EXIT = TELEGRAM_EXIT_COMMANDS
        except ImportError:
            _TELEGRAM_EXIT = {"вернись", "вера вернись", "выйди из телеги", "выйди из телеграма"}
    return _TELEGRAM_EXIT

def _start_telegram_mode() -> str:
    """Запускает Telegram-режим и отключает микрофон."""
    global _telegram_mode, _mic_muted
    if _telegram_mode and _telegram_mode.running:
        return "Я уже в Telegram-режиме. Пиши в збранное."
    # Отключаем старый клиент telegram.py ДО запуска нового потока,
    # чтобы освободить блокировку SQLite-сессии
    try:
        from main.tools.telegram import _client_disconnect
        _client_disconnect()
    except Exception:
        pass
    from main.tools.telegram_mode import TelegramMode
    from main.file_indexer import smart_search
    _telegram_mode = TelegramMode(
        route_func=_telegram_route_command,
        file_search_func=smart_search,
        on_exit=_exit_telegram_mode_callback
    )
    ok = _telegram_mode.start_in_background()
    if ok:
        with _mic_muted_lock:
            _mic_muted = True
        print("[TG_MODE] Telegram-режим запущен, микрофон отключён.")
        return "Ушла в Telegram! Пиши в збранное (Saved Messages) 💬\nДля возврата напиши 'вернись' в Telegram или в консоль."
    else:
        _telegram_mode = None
        return "Не удалось запустить Telegram-режим. Проверь авторизацию."

def _stop_telegram_mode() -> str:
    """Останавливает Telegram-режим и включает микрофон."""
    global _telegram_mode, _mic_muted
    if not _telegram_mode or not _telegram_mode.running:
        return "Я не в Telegram-режиме."
    _telegram_mode.stop()
    _telegram_mode = None
    with _mic_muted_lock:
        _mic_muted = False
    print("[TG_MODE] Вернулась из Telegram, микрофон включён.")
    return "Вернулась из Telegram! Голосовой режим восстановлен."

def _exit_telegram_mode_callback():
    """Колбэк от TelegramMode при выходе изнутри (по команде 'вернись' в Telegram)."""
    global _telegram_mode, _mic_muted
    _telegram_mode = None
    with _mic_muted_lock:
        _mic_muted = False
    print("[TG_MODE] Вернулась из Telegram (по команде), микрофон включён.")

def _telegram_route_command(text: str) -> str:
    """Маршрутизация команд в Telegram-режиме (без управления ПК)."""
    # В Telegram-режиме выполняем ТОЛЬКО:
    #   - создание презентаций (с отправкой файла)
    #   - обработчики задач, памяти, истории
    #   - валюты, погоду, википедию
    #   - веб-поиск и LLM
    # НЕ выполняем HANDLERS (там управление ПК: окна, приложения, щелчки и т.д.)
    lowered = (text or "").lower().strip()

    if _WHO_ARE_YOU_RE.search(lowered):
        return "Я Вера, твой агент-помощник. Могу отвечать на вопросы и помогать с задачами."

    intent = route_intent(text)
    if intent.skill:
        msg, file_path, _tool_name = _execute_skill_request(intent.skill, text)
        if file_path:
            return f"__FILE__{file_path}__ENDFILE__{msg}"
        return msg

    handled = _run_deterministic_handlers(text, include_system=False, log_prefix="TG_ROUTE")
    if handled is not None:
        return handled
    # В Telegram-режиме обычный диалог ведём без tool-calling, чтобы LLM не запускала
    # create_document/read_document на простых сообщениях.
    return ask_llm(text, source="telegram", allow_tools=False)

def _print_banner_and_tips(activation_word: str):
    banner = (
        "\n"
        " __     _______ ____      _    \n"
        " \\ \\   / / ____|  _ \\    / \\   \n"
        "  \\ \\ / /|  _| | |_) |  / _ \\  \n"
        "   \\ V / | |___|  _ <  / ___ \\ \n"
        "    \\_/  |_____|_| \\_\\/_/   \\_\\\n"
        "\n"
        "Голосовой персональный ассистент\n"
    )
    print(banner)
    print(f"1. Для запуска агента скажите активационное слово \"{activation_word}\".")

def _safe_shutdown():
    """Безопасное завершение работы агента с сохранением данных."""
    print("Завершение работы агента...")
    
    # Устанавливаем event завершения для остановки всех циклов
    _shutdown_event.set()
    
    # Очищаем очередь TTS и останавливаем поток
    try:
        while True:
            _tts_queue.get_nowait()
    except queue.Empty:
        pass
    _tts_queue.put({'cmd': 'quit'})
    
    # Даем время на завершение потока TTS
    time.sleep(0.5)
    
    # Останавливаем LLM-сервер
    try:
        _llm_server.stop()
    except Exception as e:
        print(f"[SAVE] Ошибка остановки LLM-сервера: {e}")


    
    # Сохраняем все данные пользователя (безопасный доступ через globals)
    print("Сохранение данных...")
    g = globals()
    
    if 'memory_manager' in g:
        try:
            # Сохраняем краткое содержание сессии перед выходом
            summary = memory_manager.get_context_for_prompt()
            if summary:
                memory_manager.update_session_summary(summary)
            g['memory_manager'].save()
            print("[SAVE] Память сохранена")
        except Exception as e:
            print(f"[SAVE] Ошибка сохранения памяти: {e}")
    

    
    print("Данные сохранены. До свидания!")
    # Не вызываем sys.exit() сразу - даем главному циклу завершиться
    # sys.exit(0) будет вызван из главного цикла


def queue_command(
    text: str,
    source: str,
    file_name: Optional[str] = None,
    file_context: Optional[str] = None,
    image_data_url: Optional[str] = None,
    image_preview_data_url: Optional[str] = None,
    file_size: Optional[int] = None,
    bypass_confirmation: bool = False,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
):
    task_id = task_id or _next_task_id()
    payload = {
        "task_id": task_id,
        "text": text,
        "source": source,
        "file_name": file_name,
        "file_context": file_context,
        "image_data_url": image_data_url,
        "image_preview_data_url": image_preview_data_url,
        "file_size": file_size,
        "bypass_confirmation": bool(bypass_confirmation),
        "session_id": session_id,
    }
    _command_queue.put(payload)
    _emit_task_status(task_id, "queued", {"source": source}, session_id=session_id)
    audit_logger.write_event(
        "task.queued",
        {
            "task_id": task_id,
            "session_id": session_id,
            "source": source,
            "text": text,
            "bypass_confirmation": bool(bypass_confirmation),
        },
    )
    return task_id




def execute_slash_command(text: str) -> str:
    """Единый обработчик слеш-команд для консоли и GUI."""
    global _mic_muted
    if text == "/mute":
        with _mic_muted_lock:
            _mic_muted = True
        return ""
    if text == "/unmute":
        with _mic_muted_lock:
            _mic_muted = False
        return ""
    if text == "/exit":
        _safe_shutdown()
        return "Завершаю работу..."
    if text == "/tg":
        return _start_telegram_mode()
    return "Неизвестная команда."

def _stdin_listener():
    global _mic_muted
    retry_count = 0
    max_retries = 3
    
    while retry_count < max_retries and not _shutdown_event.is_set():
        try:
            line = sys.stdin.readline()
            if line is None or not line:
                if _shutdown_event.is_set():
                    return
                time.sleep(0.1)
                continue
            line = line.strip()
            if line.startswith("/"):
                response = execute_slash_command(line)
                if response:
                    print(f"[Вера] {response}")
                continue
            # Проверка команды выхода из Telegram-режима через консоль
            if _telegram_mode and _telegram_mode.running:
                if line.lower().strip() in _get_telegram_exit_commands():
                    response = _stop_telegram_mode()
                    print(f"[Вера] {response}")
                    continue
                else:
                    print("[TG_MODE] Сейчас в Telegram-режиме. Напиши 'вернись' для выхода или /tg для статуса.")
                    continue
            # Текстовый режим: любая строка без префикса '/' — это команда/запрос
            response = _handle_user_command(line)
            print(f"[Вера] {response}")
        except Exception as e:
            retry_count += 1
            print(f"[STDIN] Ошибка чтения команд (попытка {retry_count}/{max_retries}): {e}")
            if retry_count >= max_retries:
                print("[STDIN] КРТЧНО: stdin поток остановлен после множественных сбоев")
                break
            time.sleep(1)

def _flush_stdin_buffer():
    try:
        # Считываем и игнорируем все нажатые ранее клавиши, чтобы они не попали в обработку
        while msvcrt.kbhit():
            try:
                msvcrt.getwch()
            except Exception:
                # На всякий случай пробуем байтовое чтение
                try:
                    msvcrt.getch()
                except Exception:
                    break
    except Exception:
        pass

# спользование ConfigManager для централизованного доступа к конфигурации
from main.config_manager import get_config, get_data_dir

try:
    config = get_config()
    cfg = config.get_all()  # Получаем весь конфиг для обратной совместимости
except Exception as e:
    print(f"[ERROR] Не удалось загрузить конфигурацию: {e}")
    sys.exit(1)

# Функция проверки активационного слова с учётом возможных искажений
def _is_activation(fragment: str) -> bool:
    target = cfg["activation_word"].lower()
    for word in fragment.split():
        if difflib.SequenceMatcher(None, word, target).ratio() >= 0.8:
            return True
    return False

def _remove_activation_words(text: str) -> str:
    target = cfg["activation_word"].lower()
    tokens = text.split()
    kept = []
    for t in tokens:
        if difflib.SequenceMatcher(None, t, target).ratio() >= 0.8:
            continue
        kept.append(t)
    return " ".join(kept).strip()

_model_cfg = cfg.get("model", {})
_use_external = _model_cfg.get("use_external_server", False)
_external_url = _model_cfg.get("external_api_url", "http://127.0.0.1:1234/v1")

_thinking_lock = threading.Lock()
_thinking_enabled = bool(_model_cfg.get("thinking_enabled", True))
_reasoning_budget = _model_cfg.get("reasoning_budget", 1024)
_max_thought_chars = _model_cfg.get("max_thought_chars", 4000)


def _coerce_reasoning_budget(value, default: int) -> int:
    try:
        budget = int(value)
    except Exception:
        return default
    if budget < -1:
        return -1
    return budget


def _coerce_max_thought_chars(value, default: int) -> int:
    try:
        limit = int(value)
    except Exception:
        return default
    if limit <= 0:
        return default
    return limit


_reasoning_budget = _coerce_reasoning_budget(_reasoning_budget, 1024)
_max_thought_chars = _coerce_max_thought_chars(_max_thought_chars, 4000)


def get_thinking_mode() -> dict:
    with _thinking_lock:
        return {
            "enabled": _thinking_enabled,
            "reasoning_budget": _reasoning_budget,
            "max_thought_chars": _max_thought_chars,
        }


def set_thinking_mode(enabled: bool, reasoning_budget: Optional[int] = None) -> dict:
    global _thinking_enabled, _reasoning_budget
    with _thinking_lock:
        _thinking_enabled = bool(enabled)
        if reasoning_budget is not None:
            _reasoning_budget = _coerce_reasoning_budget(reasoning_budget, _reasoning_budget)
        state = {
            "enabled": _thinking_enabled,
            "reasoning_budget": _reasoning_budget,
            "max_thought_chars": _max_thought_chars,
        }
    _send_ws({"type": "thinking_mode", **state})
    return state

_llm_server = None
try:
    _llm_server = LlamaServer(
        ctx_size=_model_cfg.get("ctx_size", 16384),
        port=_model_cfg.get("server_port", 29741),
    )
except Exception as e:
    print(f"[LLM_SERVER] Не удалось инициализировать локальный LLM: {e}")

if _llm_server and not _use_external:
    try:
        _llm_server.start()
        llm = LlamaClient(port=_llm_server.port)
    except Exception as e:
        print(f"[LLM_CLIENT] Локальный LLM недоступен: {e}")
        try:
            config.set("model", "use_external_server", value=True)
            config.save()
        except Exception:
            pass
        _send_ws({
            "type": "chat",
            "role": "system",
            "text": (
                "Локальный LLM не найден или не запустился. "
                f"Переключаюсь на внешний сервер: {_external_url}"
            ),
        })
        llm = LlamaClient(base_url=_external_url)
else:
    if not _use_external and not _llm_server:
        print(f"[LLM_CLIENT] Модель не найдена, используется внешний сервер: {_external_url}")
    else:
        print(f"[LLM_CLIENT] Использование внешнего сервера: {_external_url}")
    llm = LlamaClient(base_url=_external_url)


_print_banner_and_tips(cfg["activation_word"])

_tts_queue: "queue.Queue[dict]" = queue.Queue()
_tts_thread: Optional[threading.Thread] = None

def _tts_worker():
    retry_count = 0
    max_retries = 3
    
    while retry_count < max_retries:
        try:
            print("[TTS] Инициализация Supertonic TTS...")
            tts = TTS(auto_download=True)
            print("[TTS] Supertonic TTS успешно инициализирован.")
            _tts_ready_event.set()
            
            retry_count = 0
            
            while True:
                cmd = _tts_queue.get()
                if cmd is not None:
                    action = cmd.get('cmd')
                    if action == 'say':
                        text = cmd.get('text', '')
                        if text:
                            # 1. Показываем анимацию размышления (загрузка синтеза)
                            _send_ws({"type": "state", "value": "thinking"})
                            try:
                                # Динамически читаем настройки TTS при каждом запросе
                                voice_name = config.get("tts", "voice_name", default="Lily")
                                total_steps = int(config.get("tts", "total_steps", default=4))
                                volume = max(0.0, min(100.0, float(
                                    config.get("tts", "volume", default=50.0)
                                )))
                                speed = float(config.get("tts", "speed", default=1.15))

                                voice_map = {
                                    "lily": "F2"
                                }
                                mapped_voice_name = voice_map.get(voice_name.lower(), voice_name)
                                try:
                                    voice_style = tts.get_voice_style(mapped_voice_name)
                                except Exception as e:
                                    print(f"[TTS] Ошибка получения стиля голоса {voice_name}: {e}. Используем F2 (Lily).")
                                    voice_style = tts.get_voice_style("F2")

                                print(f"[TTS] Синтез: {text[:50]}...")
                                wav, duration = tts.synthesize(
                                    text=text,
                                    voice_style=voice_style,
                                    lang="ru",
                                    total_steps=total_steps,
                                    speed=speed
                                )
                                duration = float(duration[0]) if hasattr(duration, "__len__") else float(duration)
                                
                                wav = apply_tts_volume(wav, volume)
                                
                                # 2. Переключаем анимацию в speaking строго перед воспроизведением
                                _send_ws({"type": "state", "value": "speaking"})

                                # Воспроизводим аудио
                                sd.play(wav.T, samplerate=tts.sample_rate)
                                
                                # Ожидание конца воспроизведения с поддержкой прерывания
                                start_time = time.time()
                                interrupted = False
                                while time.time() - start_time < duration:
                                    if not _tts_queue.empty():
                                        try:
                                            next_cmd = _tts_queue.get_nowait()
                                            next_action = next_cmd.get('cmd')
                                            if next_action == 'stop':
                                                sd.stop()
                                                interrupted = True
                                                break
                                            elif next_action == 'quit':
                                                sd.stop()
                                                return
                                            else:
                                                _tts_queue.put(next_cmd)
                                        except queue.Empty:
                                            pass
                                    time.sleep(0.02)

                                if not interrupted:
                                    sd.wait()
                            except Exception as e:
                                print(f"[TTS] Ошибка генерации/воспроизведения: {e}")
                            finally:
                                _send_ws({"type": "state", "value": "listening"})
                                
                    elif action == 'stop':
                        try:
                            sd.stop()
                        except Exception:
                            pass
                    elif action == 'quit':
                        try:
                            sd.stop()
                        except Exception:
                            pass
                        return
        except Exception as e:
            retry_count += 1
            print(f"[TTS] Критическая ошибка TTS потока (попытка {retry_count}/{max_retries}): {e}")
            if retry_count >= max_retries:
                print("[TTS] ФАТАЛЬНО: TTS поток остановлен после множественных сбоев")
                print("[TTS] Агент продолжит работу, но озвучивание недоступно")
                break
            time.sleep(2)

# Запускаем фоновый поток TTS один раз
_tts_thread = threading.Thread(target=_tts_worker, daemon=True)
_tts_thread.start()

_EMOJI_RE = re.compile(
    "[" 
    "\U0001F1E6-\U0001F1FF"  # flags
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F680-\U0001F6FF"  # transport & map symbols
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\u2600-\u26FF"          # misc symbols
    "\u2700-\u27BF"          # dingbats
    "]+",
    flags=re.UNICODE,
)


def _strip_markdown_for_tts(text: str) -> str:
    s = text or ""
    # Блоки кода для озвучивания обычно бесполезны
    s = re.sub(r"```[\s\S]*?```", " ", s)
    # markdown-ссылки: оставляем только текст ссылки
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", s)
    # inline-код
    s = re.sub(r"`([^`]+)`", r"\1", s)
    # Заголовки/цитаты/маркеры списков
    s = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", s)
    s = re.sub(r"(?m)^\s{0,3}>\s*", "", s)
    s = re.sub(r"(?m)^\s*[-*+]\s+", "", s)
    s = re.sub(r"(?m)^\s*\d+\.\s+", "", s)
    # Частые inline-маркеры форматирования
    s = s.replace("**", "").replace("__", "").replace("~~", "")
    return s


def _strip_emoji_for_tts(text: str) -> str:
    s = text or ""
    s = _EMOJI_RE.sub("", s)
    # Zero-width joiner + variation selector (часто часть emoji)
    s = s.replace("\u200d", "").replace("\ufe0f", "").replace("\ufe0e", "")
    # Текстовые смайлики
    s = re.sub(r"(?<!\w)([:;=8][\-^]?[)(DPpOo/\\|])(?!\w)", "", s)
    return s


def _clean_for_tts(text: str) -> str:
    """Удаляет из ответа источники и ссылки, чтобы TTS их не зачитывал. Преобразует годы в правильное произношение."""
    try:
        s = _strip_markdown_for_tts(text)
        s = _strip_emoji_for_tts(s)
        # Удаляем блок вида "(источники: ... )" в конце
        s = re.sub(r"\s*\(источники?:.*?\)\s*$", "", s, flags=re.IGNORECASE | re.DOTALL)
        # Удаляем строки, начинающиеся с "источники:"
        s = re.sub(r"\bисточники?:.*$", "", s, flags=re.IGNORECASE)
        # Удаляем URL
        s = re.sub(r"https?://\S+", "", s)
        # Сжимаем пробелы
        s = re.sub(r"\s{2,}", " ", s).strip()
        # Преобразуем годы в правильное произношение
        s = convert_years_in_text(s)
        return s
    except Exception:
        return text

def speak(text: str):
    try:
        while True:
            _tts_queue.get_nowait()
    except queue.Empty:
        pass

    _tts_queue.put({'cmd': 'stop'})
    safe_text = _clean_for_tts(text)
    _tts_queue.put({'cmd': 'say', 'text': safe_text})
    return _tts_thread

def interrupt_speech():
    _tts_queue.put({'cmd': 'stop'})

print("Загрузка модели Sherpa-ONNX...")
stt_model_dir = "sherpa-onnx-streaming-zipformer-small-ru-vosk-2025-08-16"
try:
    stt_cfg = cfg.get("sherpa_onnx", {})
    stt_model_dir = stt_cfg.get("model_dir", stt_model_dir)
    samplerate = int(stt_cfg.get("samplerate", 16000))

    tokens_path = stt_cfg.get("tokens") or os.path.join(stt_model_dir, "tokens.txt")
    encoder_path = stt_cfg.get("encoder") or os.path.join(stt_model_dir, "encoder.onnx")
    decoder_path = stt_cfg.get("decoder") or os.path.join(stt_model_dir, "decoder.onnx")
    joiner_path = stt_cfg.get("joiner") or os.path.join(stt_model_dir, "joiner.onnx")

    print(f"[SHERPA] Загрузка модели из: {stt_model_dir}")
    stt_recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=tokens_path,
        encoder=encoder_path,
        decoder=decoder_path,
        joiner=joiner_path,
        num_threads=int(stt_cfg.get("num_threads", 1)),
        sample_rate=samplerate,
        feature_dim=int(stt_cfg.get("feature_dim", 80)),
        decoding_method=stt_cfg.get("decoding_method", "greedy_search"),
        provider=stt_cfg.get("provider", "cpu"),
        enable_endpoint_detection=bool(stt_cfg.get("enable_endpoint_detection", True)),
        rule1_min_trailing_silence=float(stt_cfg.get("rule1_min_trailing_silence", 2.4)),
        rule2_min_trailing_silence=float(stt_cfg.get("rule2_min_trailing_silence", 1.2)),
        rule3_min_utterance_length=float(stt_cfg.get("rule3_min_utterance_length", 300.0)),
    )
    stt_stream = stt_recognizer.create_stream()
    print("[SHERPA] Модель успешно загружена")
except Exception as e:
    print(f"[ERROR] Ошибка загрузки модели Sherpa-ONNX из '{stt_model_dir}': {e}")
    print("[ERROR] Проверьте раздел sherpa_onnx в config.json и наличие файлов tokens/encoder/decoder/joiner.")
    sys.exit(1)

q = queue.Queue()

def audio_callback(indata, frames, time_, status):
    if status:
        print(status, file=sys.stderr)
    with _mic_muted_lock:
        if _mic_muted:
            return
    q.put(bytes(indata))

# Настройки веб-поиска
_WEB_CFG = cfg["web_search"]
LAST_SEARCH_URLS: list[str] = []

def autonomous_speak(text: str):
    """Озвучивает текст и одновременно отправляет его в UI."""
    _send_ws({"type": "chat", "role": "system", "text": f"\u041d\u0430\u043f\u043e\u043c\u0438\u043d\u0430\u043d\u0438\u0435: {text}"})
    speak(text)

set_speak_callback(autonomous_speak)
set_timer_ws_callback(_send_ws)
set_last_search_urls_ref(LAST_SEARCH_URLS)
set_reminder_shutdown_event(_shutdown_event)  # Передаём event для graceful shutdown
start_scheduler()

# нициализация новых модулей
DATA_DIR = get_data_dir()
DATA_DIR.mkdir(exist_ok=True)

audit_logger = get_audit_logger(DATA_DIR / "audit" / "actions.jsonl")


memory_manager = MemoryManager(DATA_DIR / "MEMORY.md")
session_store = SessionStore(DATA_DIR / "vera.db")
try:
    session_store.import_legacy_dialog(memory_manager.get_last_dialog())
except Exception as e:
    print(f"[SESSIONS] Ошибка импорта старого диалога: {e}")

print(f"[INFO] Модули задач и памяти инициализированы.")
print(f"[MEMORY] История диалога: {memory_manager.memory_path}")

# Обработчик команд памяти (замена execute_profile_command)
def execute_memory_command(text: str) -> Optional[str]:
    """Обрабатывает команды памяти: запомни, забудь, что знаешь обо мне."""
    lowered = text.lower().strip()
    
    # Команда "запомни"
    if lowered.startswith("запомни"):
        profile_key, value, category = extract_from_remember_command(text)
        if value:
            if profile_key:
                memory_manager.set_profile(profile_key, value)
                return f"Запомнила: {profile_key} — {value}."
            else:
                memory_manager.add_fact(value, category=category)
                return f"Запомнила: {value}."
        return "Что запомнить? Уточните."
    
    # Команда "что знаешь обо мне"
    if re.search(r"(?:что\s+(?:ты\s+)?знаешь|расскажи)\s+(?:обо?\s+)?мне", lowered):
        return memory_manager.get_all_info()
    
    # Сброс всей памяти ("забудь всё" / "забудь всё обо мне")
    if re.search(r"забудь\s+(?:вс[её]|абсолютно\s+вс[её])(?:.*обо?\s+мне)?", lowered):
        memory_manager.clear_all()
        return "Забыла всё о вас. Память очищена."
        
    # Команда "забудь" про конкретный факт
    if m := re.search(r"забудь\s+(?:про\s+)?(.+)", lowered):
        fragment = m.group(1).strip()
        if memory_manager.delete_fact(fragment):
            return f"Забыла про {fragment}."
        # Попробуем удалить из профиля
        key = fragment.replace(' ', '_').lower()
        if key in memory_manager.profile:
            del memory_manager.profile[key]
            memory_manager.save()
            return f"Забыла про {fragment}."
        return f"Не нашла информацию про {fragment}."
    
    # Запрос имени пользователя
    name_patterns = [
        r"\bмо[её]\s+им[яь]\b",
        r"\bкак\s+мен[яь]\s+зовут\b",
        r"\bты\s+знаешь\s+как\s+мен[яь]\s+зовут\b",
        r"\bкак\s+мо[её]\s+им[яь]\b",
        r"\bназови\s+мо[её]\s+им[яь]\b",
    ]
    if any(re.search(p, lowered) for p in name_patterns):
        name = memory_manager.get_name()
        if name:
            return f"Вас зовут {name}."
        return "Я не знаю вашего имени. Скажите 'запомни меня зовут' и ваше имя."
    
    # Команда обновления промпта (hot-reload)
    reload_patterns = [
        r"\b(?:обнови|обновить|перезагрузи|перечитай|reload)\s+(?:промпт|prompt|инструкции|настройки)\b",
        r"\b(?:промпт|prompt)\s+(?:обнови|reload|перезагрузи)\b",
    ]
    if any(re.search(p, lowered) for p in reload_patterns):
        try:
            new_prompt = reload_prompt(DATA_DIR)
            status = get_prompt_status(DATA_DIR)
            return f"Промпт обновлён ({len(new_prompt)} символов).\n{status}"
        except Exception as e:
            return f"Ошибка обновления промпта: {e}"

    # Запрос статуса промпта
    if re.search(r"\b(?:статус|status)\s+промпт|\bпромпт\s+(?:статус|status)\b", lowered):
        return get_prompt_status(DATA_DIR)

    return None

# Предрасчитанные обработчики для маршрутизации команд
HANDLERS_WITH_MANAGERS = (
    execute_memory_command,
)


def _run_deterministic_handlers(
    text: str,
    *,
    include_system: bool,
    log_prefix: str,
) -> Optional[str]:
    groups = [
        HANDLERS_WITH_MANAGERS,
        (execute_currency_command, execute_weather_command, execute_wikipedia_command),
    ]
    if include_system:
        groups.append(HANDLERS)

    for handlers in groups:
        for handler in handlers:
            try:
                result = handler(text)
            except Exception as exc:
                print(f"[{log_prefix}] {handler.__name__}: {exc}")
                continue
            if result is not None:
                return result
    return None


def _handle_user_command(
    text: str,
    file_name: str = None,
    file_context: str = None,
    image_data_url: str = None,
    image_preview_data_url: str = None,
    file_size: Optional[int] = None,
    source: str = 'chat',
    task_id: Optional[str] = None,
    bypass_confirmation: bool = False,
    session_id: Optional[str] = None,
) -> str:
    """Обрабатывает команду, логирует в память, извлекает факты, возвращает ответ."""
    # Формируем полный текст для LLM (но в историю пойдёт чистый text + file_name)
    full_prompt = text
    if file_name and file_context:
        full_prompt = f'Пользователь прикрепил файл "{file_name}". Содержимое файла уже извлечено ниже, НЕ вызывай read_document — файл уже прочитан.\n\nСодержимое файла:\n{file_context}'
        if text:
            full_prompt += f'\n---\nВопрос пользователя: {text}'

    try:
        response = route_command(
            full_prompt,
            source=source,
            task_id=task_id,
            file_name=file_name,
            file_context=file_context,
            image_data_url=image_data_url,
            bypass_confirmation=bypass_confirmation,
        )
    except Exception as e:
        response = f"Ошибка обработки запроса: {e}"
    
    # Логирование в память (чистый текст!)
    try:
        display_text = text
        if file_name:
            display_text = f"📎 Прикреплённый файл: {file_name}\n{text}" if text else f"📎 Прикреплённый файл: {file_name}"

        active_session_id = session_id or _current_session_id.get()
        if active_session_id:
            metadata = {}
            if file_name:
                metadata["file_name"] = file_name
            if file_size is not None:
                metadata["file_size"] = int(file_size)
            if image_preview_data_url:
                metadata["image_preview_data_url"] = image_preview_data_url
                metadata["is_image"] = True
            metadata["has_user_text"] = bool(text.strip())
            session_store.add_message(
                active_session_id,
                "user",
                text or file_name or "Вложение",
                kind="image" if image_preview_data_url else ("file" if file_name else "text"),
                metadata=metadata or None,
            )
        # Отправляем сообщение пользователя в UI только если это голос, так как текстовый чат делает оптимистичный апдейт
        if source == 'voice':
            _send_ws({"type": "chat", "role": "user", "text": display_text})
        
        if response:
            if active_session_id:
                session_store.add_message(active_session_id, "assistant", response)
            _send_ws({"type": "chat", "role": "assistant", "text": response})
    except Exception as e:
        print(f"[MEMORY] Ошибка логирования: {e}")
    
    # Автоматическое извлечение фактов из сообщения пользователя
    if should_extract_facts(text):
        try:
            facts = extract_facts(text)
            for profile_key, value, category in facts:
                if profile_key:
                    memory_manager.set_profile(profile_key, value)
                    print(f"[MEMORY] Запомнила: {profile_key} = {value}")
                else:
                    memory_manager.add_fact(value, category=category)
                    print(f"[MEMORY] Новый факт: {value} (категория: {category or 'auto'})")
        except Exception as e:
            print(f"[MEMORY] Ошибка извлечения фактов: {e}")
    
    return response


# Очередь для асинхронной обработки команд (голосовых и текстовых из чата)
# Новый формат элемента: dict с полями text/source/task_id/file_name/file_context/bypass_confirmation
_command_queue: "queue.Queue[dict]" = queue.Queue()

def _command_worker():
    """Поток обработки команд (голос и чат), чтобы LLM не блокировал аудиоцикл."""
    while not _shutdown_event.is_set():
        try:
            item = _command_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        task_id = _next_task_id()
        bypass_confirmation = False
        session_id = None

        # Поддержка разных форматов для обратной совместимости
        if isinstance(item, dict):
            cmd = str(item.get("text") or "")
            source = str(item.get("source") or "voice")
            file_name = item.get("file_name")
            file_context = item.get("file_context")
            image_data_url = item.get("image_data_url")
            image_preview_data_url = item.get("image_preview_data_url")
            file_size = item.get("file_size")
            task_id = str(item.get("task_id") or task_id)
            bypass_confirmation = bool(item.get("bypass_confirmation", False))
            session_id = str(item.get("session_id") or "").strip() or None
        elif isinstance(item, tuple):
            image_data_url = None
            image_preview_data_url = None
            file_size = None
            if len(item) == 4:
                cmd, source, file_name, file_context = item
            elif len(item) == 2:
                cmd, source = item
                file_name, file_context = None, None
            else:
                cmd, source = item[0], item[1]
                file_name, file_context = None, None
        else:
            cmd, source = item, 'voice'
            file_name, file_context = None, None
            image_data_url = None
            image_preview_data_url = None
            file_size = None

        if source == "chat":
            session = session_store.ensure_session(session_id, source=source)
            session_id = session["id"]
        session_token = _current_session_id.set(session_id)
        task_token = _current_task_id.set(task_id)
        if session_id:
            session_store.update_session(
                session_id,
                active_task_id=task_id,
                clear_error=True,
            )

        _emit_task_status(task_id, "running", {"source": source}, session_id=session_id)
        _send_ws({"type": "state", "value": "thinking"})

        if is_timer_ringing():
            target_cmd = cmd.strip().lower()
            if _is_activation(target_cmd) or target_cmd in ("стоп", "хватит", "отключи", "выключи", "удали таймер", "выключи таймер", "отключи таймер"):
                stop_timer_ring()
                _send_ws({"type": "timer_done"})
                _send_ws({"type": "text", "value": "Таймер отключён."})
                _emit_task_status(task_id, "completed", session_id=session_id)
                _send_ws({"type": "state", "value": "idle"})
                if session_id:
                    session_store.update_session(session_id, clear_active_task=True)
                _current_task_id.reset(task_token)
                _current_session_id.reset(session_token)
                continue

        try:
            response = _handle_user_command(
                cmd,
                file_name,
                file_context,
                image_data_url,
                image_preview_data_url,
                file_size,
                source=source,
                task_id=task_id,
                bypass_confirmation=bypass_confirmation,
                session_id=session_id,
            )
            try:
                print(f"[Вера] {response}")
            except UnicodeEncodeError:
                try:
                    print(f"[Вера] {response.encode('cp1251', errors='replace').decode('cp1251')}")
                except Exception:
                    print("[Вера] (Нечитаемый ответ из-за кодировки консоли)")

            _emit_task_status(task_id, "completed", {}, session_id=session_id)
            if session_id:
                session_store.update_session(session_id, clear_active_task=True)
            audit_logger.write_event(
                "task.completed",
                {"task_id": task_id, "source": source, "response": str(response)[:300]},
            )

            # Озвучиваем только голосовые команды
            if source == 'voice':
                speak(response)
            else:
                _send_ws({"type": "state", "value": "listening"})
        except Exception as e:
            _emit_task_status(task_id, "failed", {"reason": str(e)}, session_id=session_id)
            if session_id:
                session_store.update_session(
                    session_id,
                    clear_active_task=True,
                    last_error=str(e),
                )
            audit_logger.write_event("task.failed", {"task_id": task_id, "source": source, "error": str(e)})
            _send_ws({"type": "chat", "role": "system", "text": f"Ошибка выполнения задачи: {e}"})
        finally:
            _current_task_id.reset(task_token)
            _current_session_id.reset(session_token)


# Маршрутизация команд (атомарная, без планирования)





def route_command_simple(
    text: str,
    source: str = 'chat',
    task_id: Optional[str] = None,
    file_name: Optional[str] = None,
    file_context: Optional[str] = None,
    image_data_url: Optional[str] = None,
    bypass_confirmation: bool = False,
    is_background: bool = False,
    _intent=None,
) -> str:
    """Р’С‹РїРѕР»РЅСЏРµС‚ РѕРґРЅСѓ Р°С‚РѕРР°СЂРЅСѓСЋ РєРѕРР°РЅРґСѓ Р±РµР· РїР»Р°РЅРёСЂРѕРІР°РЅРёСЏ."""
    if image_data_url:
        return ask_llm(
            text,
            source=source,
            allow_tools=False,
            task_id=task_id,
            bypass_confirmation=bypass_confirmation,
            is_background=is_background,
            file_name=file_name,
            image_data_url=image_data_url,
        )

    intent = _intent or route_intent(text, allow_skills=False)
    if intent.telegram_action:
        return _execute_telegram_action(intent.telegram_action)
            
    handled = _run_deterministic_handlers(text, include_system=True, log_prefix="ROUTE")
    if handled is not None:
        return handled
    
    return ask_llm(text, source=source, task_id=task_id, bypass_confirmation=bypass_confirmation, is_background=is_background, file_name=file_name)


def _web_search_for_skill(query: str) -> dict:
    """Обёртка веб-поиска для локальных skill-конвейеров."""
    try:
        answer = web_search_answer(query, _WEB_CFG, get_system_prompt(), llm, LAST_SEARCH_URLS)
        return {"text": answer, "sources": list(LAST_SEARCH_URLS)}
    except Exception as e:
        print(f"[SKILL_SEARCH] Ошибка поиска: {e}")
        return {"text": "", "sources": []}


def _execute_telegram_action(args: dict[str, str], *, emit_event: bool = True) -> str:
    if emit_event:
        _send_ws({"type": "tool_call", "name": "telegram", "args": args})
    from main.tools.telegram import execute_telegram_tool
    return execute_telegram_tool(args)


def _execute_skill_request(
    skill_name: str,
    text: str,
) -> tuple[str, Optional[str], str]:
    if skill_name == "presentations":
        msg, file_path = execute_presentation_creation(
            text=text,
            llm=llm,
            web_search_func=_web_search_for_skill,
            create_pptx_func=create_pptx,
        )
        return msg, file_path, "create_presentation"
    if skill_name == "documents":
        msg, file_path = execute_text_document_creation(
            text=text,
            llm=llm,
            web_search_func=_web_search_for_skill,
            create_txt_func=create_txt,
            create_md_func=create_md,
            create_docx_func=create_docx,
        )
        return msg, file_path, "create_document"
    raise ValueError(f"Неизвестный skill: {skill_name}")


# Маршрутизация команд (главная функция)



def route_command(
    text: str,
    source: str = 'chat',
    task_id: Optional[str] = None,
    file_name: Optional[str] = None,
    file_context: Optional[str] = None,
    image_data_url: Optional[str] = None,
    bypass_confirmation: bool = False,
) -> str:
    """\u0413\u043b\u0430\u0432\u043d\u0430\u044f \u043c\u0430\u0440\u0448\u0440\u0443\u0442\u0438\u0437\u0430\u0446\u0438\u044f \u043a\u043e\u043c\u0430\u043d\u0434 \u0431\u0435\u0437 \u043f\u043b\u0430\u043d\u0438\u0440\u043e\u0432\u0449\u0438\u043a\u0430."""
    lowered = text.lower().strip()
    if any(t in lowered for t in _TELEGRAM_TRIGGERS):
        return _start_telegram_mode()
    if any(t in lowered for t in _get_telegram_exit_commands()) and _telegram_mode and _telegram_mode.running:
        return _stop_telegram_mode()

    intent = route_intent(text)
    if intent.skill:
        tool_name = "create_presentation" if intent.skill == "presentations" else "create_document"
        _send_ws({"type": "tool_call", "name": tool_name, "args": {"request": text}})
        try:
            msg, file_path, tool_name = _execute_skill_request(intent.skill, text)
            _send_ws({
                "type": "tool_result",
                "name": tool_name,
                "status": "ok",
                "result": str(file_path or msg)[:1000],
            })
            return msg
        except Exception as e:
            _send_ws({
                "type": "tool_result",
                "name": tool_name,
                "status": "error",
                "result": str(e)[:1000],
            })
            return f"Не удалось выполнить skill {intent.skill}: {e}"

    return route_command_simple(
        text,
        source=source,
        task_id=task_id,
        file_name=file_name,
        file_context=file_context,
        image_data_url=image_data_url,
        bypass_confirmation=bypass_confirmation,
        _intent=intent,
    )

def route_heartbeat_task(text: str) -> str:
    """Специальный маршрутизатор для фоновых задач, который НЕ вызывает LLM для простых напоминаний."""
    background_task_id = _next_task_id()


    intent = route_intent(text, allow_skills=False)
    if intent.telegram_action:
        return _execute_telegram_action(intent.telegram_action, emit_event=False)

    handled = _run_deterministic_handlers(text, include_system=True, log_prefix="HEARTBEAT")
    if handled is not None:
        return handled

    # Проверяем, не является ли это поисковым запросом ("прочитай новости", "какая погода", "кто такой")
    # Если да, перенаправляем в LLM, где он сможет использовать инструменты
    if intent.direct_web:
        return ask_llm(text, source="heartbeat", task_id=background_task_id, is_background=True)

    # Если ни один системный инструмент не отреагировал, считаем это простым текстовым напоминанием.
    # LLM не вызываем, просто возвращаем сам текст (Heartbeat скажет "Напоминание по задаче: {text}").
    return text


# ---- Компактный системный промпт ----
# Файл: data/CORE.md + динамические дата и часовой пояс.
# Для перезагрузки скажи "обнови промпт" или введи команду

def get_system_prompt() -> str:
    """Возвращает текущий системный промпт (с кешированием по mtime файлов)."""
    return build_system_prompt(DATA_DIR)



# Запускаем валидацию промпта при старте (чтобы сразу говорило об ошибке если файлы не те)
try:
    _startup_prompt = build_system_prompt(DATA_DIR)
    if _startup_prompt:
        print(f"[PROMPT] Компактный системный промпт загружен ({len(_startup_prompt)} символов) | CORE + RUNTIME")
    else:
        print("[WARN] Промпт пустой — проверьте файл CORE.md в data/")
except Exception as e:
    print(f"[ERROR] Не удалось загрузить промпт: {e}")




def ask_llm(
    user_text: str,
    source: str = 'chat',
    allow_tools: bool = True,
    task_id: Optional[str] = None,
    bypass_confirmation: bool = False,
    is_background: bool = False,
    _tool_loop_depth: int = 0,
    file_name: Optional[str] = None,
    image_data_url: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    if _is_simple_greeting(user_text):
        return "\u042f \u043d\u0430 \u0441\u0432\u044f\u0437\u0438. \u0427\u0435\u043c \u043f\u043e\u043c\u043e\u0447\u044c?"
        
    # Агрессивно отключаем инструменты для "пустой" болтовни и ругани,
    # чтобы модель случайно не запустила web_search или telegram.
    if allow_tools and _is_small_talk(user_text):
        allow_tools = False

    intent = (
        route_intent(
            user_text,
            file_name=file_name,
            allow_web=not file_name and _tool_loop_depth == 0,
            allow_skills=False,
            available_names=TOOL_DEFINITIONS_BY_NAME,
            max_tools=2,
        )
        if allow_tools
        else None
    )
    routed_tool_names = list(intent.tools) if intent else []

    if (
        _tool_loop_depth == 0
        and not file_name
        and intent
        and intent.direct_web
    ):
        try:
            _send_ws({"type": "tool_call", "name": "web_search", "args": {"query": user_text}})
            result = web_search_answer(user_text, _WEB_CFG, get_system_prompt(), llm, LAST_SEARCH_URLS)
            _send_ws({
                "type": "tool_result",
                "name": "web_search",
                "status": "ok",
                "result": str(result)[:1000],
            })
            return result
        except Exception as e:
            _send_ws({
                "type": "tool_result",
                "name": "web_search",
                "status": "error",
                "result": str(e)[:1000],
            })
            print(f"[WEB_SEARCH] \u041e\u0448\u0438\u0431\u043a\u0430 \u0431\u044b\u0441\u0442\u0440\u043e\u0433\u043e \u043f\u043e\u0438\u0441\u043a\u0430: {e}")

    system_content = get_system_prompt()
    try:
        memory_context = memory_manager.get_context_for_prompt(user_text)
        if memory_context:
            system_content += "\n\n" + memory_context
    except Exception as e:
        print(f"[LLM] \u041e\u0448\u0438\u0431\u043a\u0430 \u0434\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u0438\u044f \u043a\u043e\u043d\u0442\u0435\u043a\u0441\u0442\u0430 \u043f\u0430\u043c\u044f\u0442\u0438: {e}")

    messages = [{"role": "system", "content": system_content}]
    try:
        active_session_id = session_id or _current_session_id.get()
        for m in session_store.get_context_messages(active_session_id) if active_session_id else []:
            messages.append(m)
    except Exception:
        pass
    if image_data_url:
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": user_text or "Опиши изображение."},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        })
    else:
        messages.append({"role": "user", "content": user_text})

    allowed = {
        "temperature", "top_p", "top_k", "min_p", "repeat_penalty",
        "presence_penalty", "frequency_penalty", "max_tokens", "seed", "stop"
    }
    mcfg = cfg["model"]
    gen_args = {k: mcfg[k] for k in allowed if k in mcfg}
    if "max_tokens" in gen_args:
        try:
            if int(gen_args["max_tokens"]) <= 0:
                del gen_args["max_tokens"]
        except Exception:
            pass

    with _thinking_lock:
        thinking_enabled = _thinking_enabled
        reasoning_budget = _reasoning_budget
    gen_args["chat_template_kwargs"] = {"enable_thinking": bool(thinking_enabled)}
    gen_args["reasoning_budget"] = reasoning_budget if thinking_enabled else 0

    effective_allow_tools = allow_tools and not image_data_url and not (intent and intent.plain_code)
    if effective_allow_tools:
        selected_tools = get_tool_definitions(routed_tool_names)
        if selected_tools:
            gen_args["tools"] = selected_tools
            gen_args["tool_choice"] = "auto"

    use_stream = (source == 'chat')
    if use_stream:
        gen_args["stream"] = True

    try:
        result = llm.create_chat_completion(messages=messages, **gen_args)
    except Exception as e:
        print(f"[LLM] \u041e\u0448\u0438\u0431\u043a\u0430 \u0433\u0435\u043d\u0435\u0440\u0430\u0446\u0438\u0438: {e}")
        if image_data_url:
            error_text = str(e).lower()
            if "image input is not supported" in error_text or "mmproj" in error_text:
                return (
                    "Эта локальная модель не поддерживает изображения или для неё "
                    "не найден совместимый mmproj-проектор. Добавьте проектор от "
                    "этой же модели либо задайте model.vision_projector_path в config.json."
                )
        return "\u0421\u0435\u0439\u0447\u0430\u0441 \u043d\u0435 \u043c\u043e\u0433\u0443 \u043e\u0442\u0432\u0435\u0442\u0438\u0442\u044c. \u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435, \u0447\u0442\u043e LLM-\u0441\u0435\u0440\u0432\u0435\u0440 \u0437\u0430\u043f\u0443\u0449\u0435\u043d."

    if use_stream:
        full_response = ""
        full_thoughts = ""
        in_think = False
        streamed_tool_calls: dict[int, dict] = {}

        def _append_chat(chunk_text: str):
            nonlocal full_response
            if not chunk_text:
                return
            full_response += chunk_text
            _send_ws({"type": "chat_chunk", "text": chunk_text})

        def _append_thought(chunk_text: str):
            nonlocal full_thoughts
            if not chunk_text:
                return
            if not thinking_enabled:
                return
            remaining = _max_thought_chars - len(full_thoughts)
            if remaining <= 0:
                return
            safe_chunk = chunk_text[:remaining]
            full_thoughts += safe_chunk
            _send_ws({"type": "thought_chunk", "text": safe_chunk})

        def _process_content_chunk(chunk_text: str):
            nonlocal in_think
            if not chunk_text:
                return
            while chunk_text:
                if in_think:
                    end_idx = chunk_text.find("</think>")
                    if end_idx == -1:
                        _append_thought(chunk_text)
                        break
                    _append_thought(chunk_text[:end_idx])
                    chunk_text = chunk_text[end_idx + len("</think>"):]
                    in_think = False
                else:
                    start_idx = chunk_text.find("<think>")
                    if start_idx == -1:
                        _append_chat(chunk_text)
                        break
                    _append_chat(chunk_text[:start_idx])
                    chunk_text = chunk_text[start_idx + len("<think>"):]
                    in_think = True

        def _merge_tool_call_delta(delta_tool_calls):
            if not isinstance(delta_tool_calls, list):
                return
            for tc in delta_tool_calls:
                if not isinstance(tc, dict):
                    continue
                idx = tc.get("index", 0)
                try:
                    idx = int(idx)
                except Exception:
                    idx = 0
                item = streamed_tool_calls.setdefault(
                    idx,
                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                )
                tc_id = tc.get("id")
                if tc_id:
                    item["id"] = tc_id
                tc_type = tc.get("type")
                if tc_type:
                    item["type"] = tc_type
                fn_delta = tc.get("function") or {}
                if not isinstance(fn_delta, dict):
                    fn_delta = {}
                fn_name = fn_delta.get("name")
                if fn_name:
                    item["function"]["name"] += fn_name
                fn_args = fn_delta.get("arguments")
                if fn_args:
                    item["function"]["arguments"] += fn_args

        for chunk in result:
            delta = chunk.get("choices", [{}])[0].get("delta", {})
            if not isinstance(delta, dict):
                continue
            if delta.get("tool_calls"):
                _merge_tool_call_delta(delta.get("tool_calls"))
            reasoning_content = delta.get("reasoning_content") or ""
            content = delta.get("content") or ""
            if reasoning_content:
                _append_thought(str(reasoning_content))
            if content:
                _process_content_chunk(str(content))

        if streamed_tool_calls:
            ordered_tool_calls = [
                streamed_tool_calls[i]
                for i in sorted(streamed_tool_calls.keys())
                if (streamed_tool_calls[i].get("function", {}) or {}).get("name")
            ]
            if ordered_tool_calls:
                return _handle_tool_calls(
                    ordered_tool_calls,
                    user_text=user_text,
                    source=source,
                    task_id=task_id,
                    bypass_confirmation=bypass_confirmation,
                    is_background=is_background,
                    tool_loop_depth=_tool_loop_depth,
                    file_name=file_name,
                )

        final_reply = full_response.strip()
        if final_reply:
            return final_reply
        if full_thoughts:
            return "\u041d\u0435 \u043f\u043e\u043b\u0443\u0447\u0438\u043b\u0430 \u0444\u0438\u043d\u0430\u043b\u044c\u043d\u044b\u0439 \u0442\u0435\u043a\u0441\u0442 \u043e\u0442 \u043c\u043e\u0434\u0435\u043b\u0438 \u043f\u043e\u0441\u043b\u0435 \u0440\u0430\u0441\u0441\u0443\u0436\u0434\u0435\u043d\u0438\u0439."
        return "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u043e\u043b\u0443\u0447\u0438\u0442\u044c \u0442\u0435\u043a\u0441\u0442\u043e\u0432\u044b\u0439 \u043e\u0442\u0432\u0435\u0442 \u043e\u0442 \u043c\u043e\u0434\u0435\u043b\u0438."

    message = result.get("choices", [{}])[0].get("message", {})
    tool_calls = message.get("tool_calls")
    if tool_calls:
        return _handle_tool_calls(
            tool_calls,
            user_text=user_text,
            source=source,
            task_id=task_id,
            bypass_confirmation=bypass_confirmation,
            is_background=is_background,
            tool_loop_depth=_tool_loop_depth,
            file_name=file_name,
        )

    reasoning_reply = (message.get("reasoning_content") or "").strip()
    if thinking_enabled and reasoning_reply:
        _send_ws({"type": "thought_chunk", "text": reasoning_reply[:_max_thought_chars]})

    assistant_content = message.get("content") or ""
    if isinstance(assistant_content, list):
        parts = []
        for part in assistant_content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or ""))
            else:
                parts.append(str(part))
        assistant_content = "".join(parts)
    assistant_content = str(assistant_content)

    if thinking_enabled:
        for think_part in re.findall(r"<think>(.*?)</think>", assistant_content, flags=re.DOTALL):
            clean_think = think_part.strip()
            if clean_think:
                _send_ws({"type": "thought_chunk", "text": clean_think[:_max_thought_chars]})

    assistant_reply = re.sub(r"<think>.*?</think>", "", assistant_content, flags=re.DOTALL).strip()
    if assistant_reply:
        return assistant_reply

    if reasoning_reply:
        return "\u041d\u0435 \u043f\u043e\u043b\u0443\u0447\u0438\u043b\u0430 \u0444\u0438\u043d\u0430\u043b\u044c\u043d\u044b\u0439 \u0442\u0435\u043a\u0441\u0442 \u043e\u0442 \u043c\u043e\u0434\u0435\u043b\u0438 \u043f\u043e\u0441\u043b\u0435 \u0440\u0430\u0441\u0441\u0443\u0436\u0434\u0435\u043d\u0438\u0439."
    return "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u043e\u043b\u0443\u0447\u0438\u0442\u044c \u0442\u0435\u043a\u0441\u0442\u043e\u0432\u044b\u0439 \u043e\u0442\u0432\u0435\u0442 \u043e\u0442 \u043c\u043e\u0434\u0435\u043b\u0438."


def _run_callable_with_timeout(fn: Callable[[], Any], timeout_sec: float) -> tuple[bool, Any, str]:
    holder: dict[str, Any] = {}
    done = threading.Event()

    def _runner():
        try:
            holder["result"] = fn()
            holder["ok"] = True
        except Exception as e:
            holder["ok"] = False
            holder["error"] = str(e)
        finally:
            done.set()

    worker = threading.Thread(target=_runner, daemon=True)
    worker.start()
    finished = done.wait(timeout=max(0.5, timeout_sec))
    if not finished:
        return False, None, f"timeout after {timeout_sec:.1f}s"
    if not holder.get("ok", False):
        return False, None, str(holder.get("error") or "unknown_error")
    return True, holder.get("result"), ""


def _handle_tool_calls(
    tool_calls: list,
    user_text: str,
    source: str,
    task_id: Optional[str],
    bypass_confirmation: bool,
    is_background: bool,
    tool_loop_depth: int,
    file_name: Optional[str] = None,
) -> str:
    """Обрабатывает один или несколько tool calls с bounded loop и policy gating."""
    if not tool_calls:
        return "Не удалось выполнить инструмент: список вызовов пуст."

    if tool_loop_depth >= _MAX_TOOL_LOOP_DEPTH:
        return "Достигнут лимит глубины инструментальных вызовов. Сформулируйте запрос точнее."

    tool_outputs: list[str] = []
    tool_errors: list[str] = []
    had_successful_tool = False
    terminal_tool_output: Optional[str] = None
    request_intent = route_intent(user_text, allow_skills=False)

    for tc in tool_calls:
        fn = tc.get("function", {}) if isinstance(tc, dict) else {}
        tool_name = str(fn.get("name", "")).strip()
        if not tool_name:
            continue

        try:
            raw_args = fn.get("arguments", {})
            if isinstance(raw_args, str):
                args = json.loads(raw_args or "{}")
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                args = {}
            if not isinstance(args, dict):
                args = {}
        except Exception:
            args = {}





        if (
            tool_name in {"create_document", "code_interpreter"}
            and request_intent.plain_code
        ):
            return ask_llm(
                user_text,
                source=source,
                allow_tools=False,
                task_id=task_id,
                bypass_confirmation=True,
                is_background=is_background,
                _tool_loop_depth=tool_loop_depth + 1,
                file_name=file_name,
            )

        if tool_name == "web_search":
            if file_name:
                tool_outputs.append("web_search: инструмент отключен, так как прикреплен файл.")
                continue
            try:
                _send_ws({"type": "tool_call", "name": "web_search", "args": args})
                query = ""
                if isinstance(args, dict):
                    query = str(args.get("query") or "").strip()
                if not query and tool_loop_depth == 0:
                    query = user_text.strip()
                
                if not query:
                    tool_outputs.append("web_search: пустой поисковый запрос")
                else:
                    output = web_search_answer(
                        query,
                        _WEB_CFG,
                        get_system_prompt(),
                        llm,
                        LAST_SEARCH_URLS,
                    )
                    tool_outputs.append(f"web_search: {output}")
                    _send_ws({
                        "type": "tool_result",
                        "name": "web_search",
                        "status": "ok",
                        "result": str(output)[:1000],
                    })
            except Exception as e:
                print(f"[WEB_SEARCH] Ошибка: {e}")
                tool_outputs.append(f"web_search: error {e}")
                _send_ws({
                    "type": "tool_result",
                    "name": "web_search",
                    "status": "error",
                    "result": str(e)[:1000],
                })
            continue

        if tool_name in TOOLS:
            try:
                print(f"[TOOL_CALL] {tool_name}: {args}")
                _send_ws({"type": "tool_call", "name": tool_name, "args": args})
                ok, output, err = _run_callable_with_timeout(
                    lambda: TOOLS[tool_name](args),
                    _PER_TOOL_TIMEOUT_SEC,
                )
                if not ok:
                    raise RuntimeError(err)
                if tool_name == "create_document" and re.match(
                    r"^\s*(?:Ошибка|Укажите|Неизвестное действие)\b",
                    str(output),
                    flags=re.IGNORECASE,
                ):
                    raise RuntimeError(str(output))
                tool_outputs.append(f"{tool_name}: {output}")
                had_successful_tool = True
                if tool_name == "create_document":
                    terminal_tool_output = str(output)
                _send_ws({
                    "type": "tool_result",
                    "name": tool_name,
                    "status": "ok",
                    "result": str(output)[:1000],
                })
                audit_logger.write_event(
                    "tool.executed",
                    {"task_id": task_id, "tool_name": tool_name, "status": "ok"},
                )
            except Exception as e:
                print(f"[TOOL] Ошибка выполнения {tool_name}: {e}")
                error_line = f"{tool_name}: error {e}"
                tool_outputs.append(error_line)
                tool_errors.append(error_line)
                _send_ws({
                    "type": "tool_result",
                    "name": tool_name,
                    "status": "error",
                    "result": str(e)[:1000],
                })
                audit_logger.write_event(
                    "tool.executed",
                    {"task_id": task_id, "tool_name": tool_name, "status": "error", "error": str(e)},
                )
            continue



        error_line = f"{tool_name}: unknown tool"
        tool_outputs.append(error_line)
        tool_errors.append(error_line)

    if not tool_outputs:
        return "Модель запросила инструменты, но не указала корректные вызовы."
    if tool_errors and not had_successful_tool:
        return "Не удалось выполнить инструмент(ы):\n" + "\n".join(f"- {line}" for line in tool_errors[:5])
    if terminal_tool_output:
        return terminal_tool_output

    tool_context = "\n".join(f"- {line}" for line in tool_outputs)
    followup_prompt = (
        f"{user_text}\n\n"
        f"Результаты инструментов:\n{tool_context}\n\n"
        "Сформируй итоговый ответ пользователю на русском и при необходимости продолжи с инструментами."
    )
    return ask_llm(
        followup_prompt,
        source=source,
        allow_tools=True,
        task_id=task_id,
        bypass_confirmation=bypass_confirmation,
        is_background=is_background,
        _tool_loop_depth=tool_loop_depth + 1,
    )


def run_main_loop():
    """Главный цикл прослушивания и обработки команд."""
    print("[INFO] Завершение инициализации голосового контура...")
    # Запускаем поток обработки голосовых команд (LLM не блокирует аудиоцикл)
    _cmd_thread = threading.Thread(target=_command_worker, daemon=True)
    _cmd_thread.start()
    # Теперь можно принимать команды из консоли — запускаем поток чтения stdin
    _flush_stdin_buffer()
    _stdin_thread = threading.Thread(target=_stdin_listener, daemon=True)
    _stdin_thread.start()

    # нициализация планировщика периодических задач (Heartbeat)
    set_heartbeat_speak_callback(autonomous_speak)
    set_heartbeat_route_callback(route_heartbeat_task)
    set_heartbeat_shutdown_event(_shutdown_event)
    start_heartbeat_scheduler()

    # Запускаем Heartbeat (фоновые периодические задачи)
    # Настройки теперь контролируются самим планировщиком `heartbeat_commands.py`
    # и хранятся в `heartbeat_tasks.json`.

    silence_timeout = cfg["silence_timeout"]

    with sd.RawInputStream(samplerate=samplerate, blocksize=8000, dtype='int16', channels=1, callback=audio_callback):
        while not _tts_ready_event.wait(timeout=0.1):
            if _shutdown_event.is_set():
                return
        _agent_ready_event.set()
        print("[INFO] Система готова. Скажите ключевое слово.")
        _send_ws({"type": "agent_status", **get_agent_readiness()})
        last_audio_time = time.time()
        listening_for_command = False
        while not _shutdown_event.is_set():
            data = q.get()
            pcm16 = array('h')
            pcm16.frombytes(data)
            samples = array('f', (x / 32768.0 for x in pcm16))
            stt_stream.accept_waveform(samplerate, samples)

            partial = ""
            while stt_recognizer.is_ready(stt_stream):
                stt_recognizer.decode_stream(stt_stream)
                partial = stt_recognizer.get_result(stt_stream).lower().strip()

            if partial and listening_for_command:
                last_audio_time = time.time()

            if not stt_recognizer.is_endpoint(stt_stream):
                if listening_for_command and (time.time() - last_audio_time > silence_timeout):
                    listening_for_command = False
                continue

            text = stt_recognizer.get_result(stt_stream).lower().strip()
            stt_recognizer.reset(stt_stream)

            if text:
                print(f"[VOICE] {text}")
            if not text:
                continue

            if _is_activation(text):
                interrupt_speech()

            if is_timer_ringing():
                if _is_activation(text) or text.strip().lower() in ("стоп", "хватит", "отключи", "выключи"):
                    stop_timer_ring()
                    speak("Таймер отключён.")
                    continue

            if not listening_for_command:
                if _is_activation(text):
                    command_text = _remove_activation_words(text)
                    if command_text:
                        user_command = command_text
                    else:
                        speak("Я слушаю. Какую команду выполнить?")
                        listening_for_command = True
                        last_audio_time = time.time()
                        continue
                else:
                    continue
            else:
                user_command = text
                listening_for_command = False

            queue_command(user_command, source='voice')
    
    # Главный цикл завершен
    sys.exit(0)


if __name__ == "__main__":
    run_main_loop()



