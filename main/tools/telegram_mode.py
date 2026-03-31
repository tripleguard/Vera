import asyncio
import logging
import re
import threading
from pathlib import Path
from typing import Callable, List, Dict, Optional

from telethon import TelegramClient, events
from main.config_manager import get_data_dir

log = logging.getLogger("telegram_mode")

# ----- Расширения файлов для определения типа отправки -----
_PHOTO_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
_VIDEO_EXT = {'.mp4', '.avi', '.mkv', '.mov', '.webm', '.wmv', '.m4v'}
_AUDIO_EXT = {'.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a', '.wma'}

# ----- Паттерны запроса файлов -----
_FILE_PATTERNS = [
    # «скинь/отправь/пришли/кинь/перешли [файл/документ/...] <название>»
    re.compile(
        r"\b(?:скинь|отправь|пришли|кинь|перешли)\s+"
        r"(?:мне\s+)?(?:файл|документ|фото|фотку|фотографию|видео|видос|ролик|аудио|песню|музыку|архив|презентацию)?\s*"
        r"(.{2,})",
        re.IGNORECASE
    ),
    # «дай файл/документ/фото <название>» — слово-тип ОБЯЗАТЕЛЬНО, иначе «дай информацию» уйдёт в LLM
    re.compile(
        r"\bдай\s+(?:мне\s+)?(?:файл|документ|фото|фотку|видео|аудио|архив|презентацию)\s+"
        r"(.{2,})",
        re.IGNORECASE
    ),
    # «найди/поищи ФАЙЛ <название>» — слово-тип ОБЯЗАТЕЛЬНО, иначе «найди курс доллара» уйдёт в веб-поиск
    re.compile(
        r"\b(?:найди|поищи|ищи)\s+(?:файл|документ|фото|видео|презентацию|архив)\s+"
        r"(.{2,})",
        re.IGNORECASE
    ),
]

# Команды выхода из Telegram-режима (единый набор, импортируется и в agent.py)
TELEGRAM_EXIT_COMMANDS = {
    "вернись", "стоп", "выйди", "выход", "вера вернись",
    "хватит", "отключись", "верни голос", "назад",
    "выйди из телеги", "выйди из телеграма",
}
_EXIT_COMMANDS = TELEGRAM_EXIT_COMMANDS  # alias для обратной совместимости


class TelegramMode:
    """Режим работы Веры через Telegram (Saved Messages)."""

    def __init__(self, route_func: Callable[[str], str],
                 file_search_func: Callable[[str], List[Dict]],
                 on_exit: Optional[Callable] = None):

        self.route_func = route_func
        self.file_search = file_search_func
        self.on_exit = on_exit

        self.client = None
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._handler = None
        self._ready_event = threading.Event()  # Сигнал готовности
        # Для хранения результатов поиска между сообщениями (выбор файла по номеру)
        self._pending_files: List[Dict] = []
        self._my_id: int = 0

    #Запуск / остановка

    def start_in_background(self) -> bool:
        """Запускает Telegram-режим в фоновом потоке. Возвращает True при успехе."""
        if self.running:
            return False
        self._ready_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="TelegramMode")
        self._thread.start()
        # Ждём сигнал готовности (макс 30 сек)
        self._ready_event.wait(timeout=30)
        return self.running

    def stop(self):
        """Останавливает Telegram-режим (из любого потока)."""
        if not self.running:
            return
        self.running = False
        
        # Отключаем клиент
        if self.client:
            try:
                if self._loop and not self._loop.is_closed():
                    # Если вызвано из того же event loop (из обработчика сообщения)
                    if self._loop.is_running():
                        self._loop.create_task(self._async_stop())
                        return  # on_exit будет вызван из _async_stop
                    else:
                        self._loop.run_until_complete(self.client.disconnect())
            except Exception as e:
                log.warning(f"Ошибка отключения клиента: {e}")
            self.client = None
        
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
        
        log.info("Telegram-режим остановлен")
        if self.on_exit:
            try:
                self.on_exit()
            except Exception as e:
                log.error(f"Ошибка on_exit: {e}")
    
    async def _async_stop(self):
        """Асинхронная остановка (когда stop() вызван изнутри event loop)."""
        try:
            if self.client:
                await self.client.disconnect()
                self.client = None
        except Exception as e:
            log.warning(f"Ошибка отключения: {e}")
        log.info("Telegram-режим остановлен (async)")
        if self.on_exit:
            try:
                self.on_exit()
            except Exception as e:
                log.error(f"Ошибка on_exit: {e}")

    def _run_loop(self):
        """Запускает asyncio event loop в отдельном потоке."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._start_listening())
        except Exception as e:
            log.error(f"Telegram-режим упал: {e}")
            self.running = False
            self._ready_event.set()

    async def _start_listening(self):
        """Подключается к Telegram и начинает слушать Saved Messages."""
        from .telegram import API_ID, API_HASH, DATA_DIR, _client_disconnect

        # Отключаем старый клиент из telegram.py, чтобы освободить сессию
        _client_disconnect()

        # Создаём СВОЙ клиент в ТЕКУЩЕМ event loop (не переиспользуем чужой)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.client = TelegramClient(
            str(DATA_DIR / "telegram_session"), API_ID, API_HASH,
            device_model="Windows 10", system_version="10.0",
            app_version="5.9.0", lang_code="ru"
        )
        await self.client.connect()

        if not await self.client.is_user_authorized():
            log.error("Telegram не авторизован! Сначала авторизуйтесь.")
            self.running = False
            self._ready_event.set()
            return

        me = await self.client.get_me()
        self._my_id = me.id
        log.info(f"Telegram-режим запущен от имени: {me.first_name} (ID: {me.id})")

        # Слушаем ТОЛЬКО свои сообщения (Saved Messages)
        @self.client.on(events.NewMessage(
            from_users=me.id,
            incoming=False,       # Наши исходящие в Saved Messages
            outgoing=True
        ))
        async def on_my_message(event):
            # Saved Messages = чат с самим собой
            if event.chat_id != me.id:
                return
            await self._process_message(event)

        # Также ловим входящие от себя (Telegram может роутить по-разному)
        @self.client.on(events.NewMessage(
            from_users=me.id,
            chats=me.id
        ))
        async def on_saved_message(event):
            await self._process_message(event)

        self.running = True
        self._ready_event.set()
        # Отправляем приветствие в Saved Messages
        try:
            await self.client.send_message("me", "👋 Вера в Telegram-режиме!\n\n"
                "📎 Скинь [название] — найду и отправлю файл\n"
                "💬 Любой вопрос — отвечу\n"
                "🔍 Найди/поищи — веб-поиск\n"
                "🚪 «Вернись» — выход из режима")
        except Exception as e:
            log.warning(f"Не удалось отправить приветствие: {e}")

        # Бесконечный цикл прослушивания
        try:
            while self.running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    # Защита от повторной обработки 
    _processed_ids = set()

    async def _process_message(self, event):
        """Обрабатывает входящее сообщение из Saved Messages."""
        # Дедупликация (два обработчика могут поймать одно сообщение)
        msg_id = event.message.id
        if msg_id in self._processed_ids:
            return
        self._processed_ids.add(msg_id)
        # Чистим старые ID чтобы не утекала память
        if len(self._processed_ids) > 200:
            self._processed_ids.clear()

        text = (event.message.text or "").strip()
        if not text:
            return

        log.info(f"[TG] Получено: {text[:100]}")

        try:
            # 1. Команда выхода
            if text.lower().strip() in _EXIT_COMMANDS:
                await self.client.send_message("me", "Возвращаюсь в голосовой режим 👋")
                self.stop()
                return

            # 2. Выбор файла по номеру (если есть pending)
            if self._pending_files and text.isdigit():
                idx = int(text) - 1
                if 0 <= idx < len(self._pending_files):
                    await self._send_file(self._pending_files[idx]["path"])
                    self._pending_files.clear()
                    return
                else:
                    await self.client.send_message("me", f"Нет файла с номером {text}. Доступны: 1-{len(self._pending_files)}")
                    return

            # 3. Запрос файла
            file_query = self._extract_file_query(text)
            if file_query:
                await self._handle_file_request(file_query)
                return

            # 4. Обычная команда → route_command (в отдельном потоке, т.к. синхронная)
            response = await asyncio.get_event_loop().run_in_executor(
                None, self.route_func, text
            )
            if response:
                # Проверяем маркер файла для автоотправки (презентации и т.д.)
                if response.startswith("__FILE__"):
                    parts = response.split("__ENDFILE__", 1)
                    file_path = parts[0].replace("__FILE__", "")
                    text_msg = parts[1].strip() if len(parts) > 1 else ""
                    if text_msg:
                        await self.client.send_message("me", text_msg)
                    await self._send_file(file_path)
                    return

                # Telegram лимит 4096 символов
                if len(response) > 4000:
                    # Отправляем как файл
                    tmp = get_data_dir() / "tg_response.txt"
                    tmp.write_text(response, encoding="utf-8")
                    await self.client.send_file("me", str(tmp), caption="📝 Ответ слишком длинный, отправлен файлом")
                else:
                    await self.client.send_message("me", response)

        except Exception as e:
            log.error(f"Ошибка обработки сообщения: {e}", exc_info=True)
            try:
                await self.client.send_message("me", f"❌ Ошибка: {e}")
            except Exception:
                pass

    # Поиск и отправка файлов

    def _extract_file_query(self, text: str) -> Optional[str]:
        """Извлекает поисковый запрос файла из текста. Возвращает None если это не запрос файла."""
        for pattern in _FILE_PATTERNS:
            m = pattern.search(text)
            if m:
                query = m.group(1).strip()
                # Убираем лишние слова
                query = re.sub(r"^(?:пожалуйста|плиз|плз)\s*", "", query, flags=re.IGNORECASE).strip()
                if len(query) >= 2:
                    return query
        return None

    async def _handle_file_request(self, query: str):
        """Ищет файл и отправляет (или предлагает выбор)."""
        try:
            results = self.file_search(query)
        except Exception as e:
            await self.client.send_message("me", f"❌ Ошибка поиска: {e}")
            return

        # Фильтруем папки
        results = [r for r in results if not r.get("is_dir")]

        if not results:
            await self.client.send_message("me", f"🤷 Не нашла файл «{query}»")
            return

        if len(results) == 1:
            await self._send_file(results[0]["path"])
            return

        # Несколько результатов — предлагаем выбор (макс 10)
        show = results[:10]
        self._pending_files = show
        msg = f"📂 Нашла {len(results)} файлов по «{query}»:\n\n"
        for i, r in enumerate(show, 1):
            name = r["name"]
            path = r["path"]
            # Показываем папку для контекста
            folder = str(Path(path).parent.name) if path else ""
            msg += f"{i}. 📄 {name}"
            if folder:
                msg += f"  ({folder})"
            msg += "\n"
        if len(results) > 10:
            msg += f"\n...и ещё {len(results) - 10} файлов."
        msg += "\n✏️ Напиши номер файла для отправки."
        await self.client.send_message("me", msg)

    async def _send_file(self, file_path: str):
        """Отправляет файл в Saved Messages, определяя тип автоматически."""
        path = Path(file_path)

        if not path.exists():
            await self.client.send_message("me", f"❌ Файл не найден: {path.name}")
            return

        # Проверяем размер (Telethon лимит ~2 ГБ)
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > 2000:
            await self.client.send_message("me", f"❌ Файл слишком большой: {size_mb:.0f} МБ (лимит 2 ГБ)")
            return

        ext = path.suffix.lower()
        is_photo = ext in _PHOTO_EXT
        is_video = ext in _VIDEO_EXT
        is_audio = ext in _AUDIO_EXT

        try:
            # Уведомляем о начале загрузки для больших файлов
            if size_mb > 50:
                await self.client.send_message("me", f"⏳ Загружаю {path.name} ({size_mb:.0f} МБ)...")

            await self.client.send_file(
                "me",
                file=str(path),
                caption=f"📎 {path.name}",
                force_document=not (is_photo or is_video or is_audio),
                voice_note=False,
            )
            log.info(f"[TG] Отправлен файл: {path.name} ({size_mb:.1f} МБ)")
        except Exception as e:
            log.error(f"Ошибка отправки файла {path.name}: {e}")
            await self.client.send_message("me", f"❌ Не удалось отправить {path.name}: {e}")
