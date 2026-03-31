
import asyncio
import logging
import re
import threading
from datetime import timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from telethon import TelegramClient
from telethon.errors import (
    ApiIdInvalidError,
    AuthRestartError,
    FloodWaitError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberFloodError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from telethon.tl.types import User
from main.config_manager import get_data_dir

log = logging.getLogger("telegram")

API_ID, API_HASH = 2040, "b18441a1ff607e10a989891a5462e627"
DATA_DIR = get_data_dir()

_client: Optional[TelegramClient] = None
_auth = {"phone": None, "hash": None, "code": False, "2fa": False}
_runtime_loop: Optional[asyncio.AbstractEventLoop] = None
_runtime_thread: Optional[threading.Thread] = None
_runtime_ready = threading.Event()
_runtime_lock = threading.Lock()

_CONTACT_TELEGRAM_TAIL_RE = re.compile(
    r"\s+(?:РІ|С‡РµСЂРµР·)\s+(?:С‚РµР»РµРіСЂР°Рј(?:РјРµ|РјР°|Рµ|Сѓ)?|С‚РµР»РµРіРµ|С‚РµР»РµРіСѓ|С‚РµР»РµРіР°|С‚Рі)\b.*$",
    re.IGNORECASE,
)
_CONTACT_CASE_SUFFIXES = (
    ("РѕРј", ""),
    ("РµРј", ""),
    ("РѕСЋ", "Р°"),
    ("РµСЋ", "СЏ"),
    ("Сѓ", ""),
    ("СЋ", "СЏ"),
    ("Рµ", "Р°"),
    ("Рё", "СЏ"),
    ("С‹", "Р°"),
)
def _ensure_runtime_loop() -> asyncio.AbstractEventLoop:
    global _runtime_loop, _runtime_thread
    with _runtime_lock:
        if (
            _runtime_loop
            and not _runtime_loop.is_closed()
            and _runtime_thread
            and _runtime_thread.is_alive()
        ):
            return _runtime_loop

        _runtime_ready.clear()

        def _loop_runner() -> None:
            global _runtime_loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            with _runtime_lock:
                _runtime_loop = loop
            _runtime_ready.set()
            loop.run_forever()
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
            with _runtime_lock:
                if _runtime_loop is loop:
                    _runtime_loop = None

        _runtime_thread = threading.Thread(target=_loop_runner, daemon=True, name="TelegramRuntime")
        _runtime_thread.start()

    if not _runtime_ready.wait(timeout=5.0):
        raise RuntimeError("РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РїСѓСЃС‚РёС‚СЊ Telegram event loop.")
    with _runtime_lock:
        if not _runtime_loop:
            raise RuntimeError("Telegram event loop РЅРµРґРѕСЃС‚СѓРїРµРЅ.")
        return _runtime_loop


def _run(coro):
    loop = _ensure_runtime_loop()
    if _runtime_thread and threading.current_thread() is _runtime_thread:
        raise RuntimeError("_run РЅРµР»СЊР·СЏ РІС‹Р·С‹РІР°С‚СЊ РІРЅСѓС‚СЂРё TelegramRuntime РїРѕС‚РѕРєР°.")
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()


def _client_disconnect():
    """Disconnects global Telegram client."""
    global _client
    if _client is None:
        return

    async def _disconnect() -> None:
        global _client
        if not _client:
            return
        try:
            if _client.is_connected():
                await _client.disconnect()
        except Exception as exc:
            log.warning(f"РћС€РёР±РєР° РѕС‚РєР»СЋС‡РµРЅРёСЏ РєР»РёРµРЅС‚Р°: {exc}")
        finally:
            _client = None

    try:
        _run(_disconnect())
    except Exception as exc:
        log.warning(f"РћС€РёР±РєР° Р·Р°РІРµСЂС€РµРЅРёСЏ Telegram РєР»РёРµРЅС‚Р°: {exc}")


def _normalize_search_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower().replace("С‘", "Рµ")


def _clean_contact_name(name: str) -> str:
    value = re.sub(r"\s+", " ", str(name or "")).strip(" '\"В«В».,!?")
    if not value:
        return ""
    value = _CONTACT_TELEGRAM_TAIL_RE.sub("", value).strip(" '\"В«В».,!?")
    return re.sub(r"\s+", " ", value)


def _norm_name(name: str) -> str:
    """Human-readable normalized contact value for messages/logs."""
    return _clean_contact_name(name)


def _name_variants(name: str) -> List[str]:
    cleaned = _normalize_search_text(_clean_contact_name(name))
    if not cleaned:
        return []

    variants: Set[str] = {cleaned}
    tokens = cleaned.split()
    if len(tokens) > 1:
        variants.add(tokens[0])

    for base in list(variants):
        for suffix, repl in _CONTACT_CASE_SUFFIXES:
            if not base.endswith(suffix):
                continue
            if len(base) - len(suffix) < 3:
                continue
            variants.add(base[: -len(suffix)] + repl)

    return sorted((v for v in variants if v), key=len, reverse=True)


async def _client_get() -> TelegramClient:
    global _client
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not _client:
        _client = TelegramClient(
            str(DATA_DIR / "telegram_session"),
            API_ID,
            API_HASH,
            device_model="Desktop PC",
            system_version="Windows 10",
            app_version="4.14.9",
            lang_code="ru",
            system_lang_code="ru-RU",
        )
    if not _client.is_connected():
        await _client.connect()
    return _client


async def _authorized_client() -> Optional[TelegramClient]:
    client = await _client_get()
    if not await client.is_user_authorized():
        return None
    return client


def _format_message_time(value: Any) -> str:
    if not value:
        return ""
    try:
        return (
            value.replace(tzinfo=timezone.utc)
            .astimezone(timezone(timedelta(hours=3)))
            .strftime("%H:%M")
        )
    except Exception:
        return ""


async def _auth_start(phone: str) -> str:
    client = await _client_get()
    phone = re.sub(r"[\s\-\(\)]", "", str(phone or ""))
    if not phone.startswith("+"):
        phone = "+" + phone
    try:
        result = await client.send_code_request(phone)
        _auth.update({"phone": phone, "hash": result.phone_code_hash, "code": True, "2fa": False})
        type_name = type(result.type).__name__
        if "App" in type_name:
            return f"РљРѕРґ РѕС‚РїСЂР°РІР»РµРЅ РІ РїСЂРёР»РѕР¶РµРЅРёРµ Telegram РЅР° {phone}. РћС‚РєСЂРѕР№С‚Рµ Telegram Рё СЃРєР°Р¶РёС‚Рµ РєРѕРґ."
        return f"РљРѕРґ РѕС‚РїСЂР°РІР»РµРЅ РЅР° {phone}. РЎРєР°Р¶РёС‚Рµ РєРѕРґ."
    except FloodWaitError as exc:
        return f"РЎР»РёС€РєРѕРј РјРЅРѕРіРѕ РїРѕРїС‹С‚РѕРє. РџРѕРґРѕР¶РґРёС‚Рµ {exc.seconds} СЃРµРєСѓРЅРґ."
    except PhoneNumberFloodError:
        return "РЎР»РёС€РєРѕРј РјРЅРѕРіРѕ РїРѕРїС‹С‚РѕРє Р°РІС‚РѕСЂРёР·Р°С†РёРё. РџРѕРїСЂРѕР±СѓР№С‚Рµ РїРѕР·Р¶Рµ."
    except PhoneNumberBannedError:
        return f"РќРѕРјРµСЂ {phone} Р·Р°Р±Р»РѕРєРёСЂРѕРІР°РЅ РІ Telegram."
    except PhoneNumberInvalidError:
        return f"РќРµРІРµСЂРЅС‹Р№ РЅРѕРјРµСЂ: {phone}. Р¤РѕСЂРјР°С‚: +7XXXXXXXXXX"
    except ApiIdInvalidError:
        return "РћС€РёР±РєР° API РєР»СЋС‡РµР№ Telegram. РџСЂРѕРІРµСЂСЊС‚Рµ API_ID Рё API_HASH."
    except AuthRestartError:
        return "РћС€РёР±РєР° Р°РІС‚РѕСЂРёР·Р°С†РёРё. РЈРґР°Р»РёС‚Рµ С„Р°Р№Р» СЃРµСЃСЃРёРё Рё РїРѕРїСЂРѕР±СѓР№С‚Рµ СЃРЅРѕРІР°."
    except Exception as exc:
        if type(exc).__name__ == "SendCodeUnavailableError":
            return (
                "Telegram РёСЃС‡РµСЂРїР°Р» Р»РёРјРёС‚С‹ РѕС‚РїСЂР°РІРєРё SMS/Р·РІРѕРЅРєРѕРІ РґР»СЏ СЌС‚РѕРіРѕ РЅРѕРјРµСЂР°. "
                "РџРѕРїСЂРѕР±СѓР№С‚Рµ РїРѕР»СѓС‡РёС‚СЊ РєРѕРґ РІ РїСЂРёР»РѕР¶РµРЅРёРё."
            )
        log.error(f"РћС€РёР±РєР° Р°РІС‚РѕСЂРёР·Р°С†РёРё: {type(exc).__name__}: {exc}", exc_info=True)
        return f"РћС€РёР±РєР° ({type(exc).__name__}): {exc}"


async def _auth_code(code: str) -> str:
    if not _auth["code"]:
        return "РЎРЅР°С‡Р°Р»Р° СѓРєР°Р¶РёС‚Рµ РЅРѕРјРµСЂ С‚РµР»РµС„РѕРЅР°."
    client = await _client_get()
    try:
        await client.sign_in(phone=_auth["phone"], code=code, phone_code_hash=_auth["hash"])
        _auth.update({"code": False, "2fa": False})
        return "Telegram РїРѕРґРєР»СЋС‡РµРЅ!"
    except SessionPasswordNeededError:
        _auth.update({"code": False, "2fa": True})
        return "РќСѓР¶РµРЅ 2FA РїР°СЂРѕР»СЊ."
    except PhoneCodeInvalidError:
        return "РќРµРІРµСЂРЅС‹Р№ РєРѕРґ."
    except Exception as exc:
        return f"РћС€РёР±РєР°: {exc}"


async def _auth_2fa(password: str) -> str:
    if not _auth["2fa"]:
        return "2FA РЅРµ С‚СЂРµР±СѓРµС‚СЃСЏ."
    try:
        await (await _client_get()).sign_in(password=password)
        _auth.update({"code": False, "2fa": False})
        return "Telegram РїРѕРґРєР»СЋС‡РµРЅ!"
    except Exception as exc:
        return f"РћС€РёР±РєР°: {exc}"


async def _logout() -> str:
    global _client
    if not _client:
        return "Telegram РЅРµ Р±С‹Р» РїРѕРґРєР»СЋС‡РµРЅ."
    try:
        await _client.log_out()
        _client = None
        return "Р’С‹С€Р»Р° РёР· Telegram."
    except Exception as exc:
        return f"РћС€РёР±РєР°: {exc}"


async def _find(name: str) -> Optional[Dict[str, Any]]:
    client = await _client_get()
    needles = _name_variants(name)
    if not needles:
        return None

    best = None
    score = 0.0
    async for dialog in client.iter_dialogs(limit=150):
        title = _normalize_search_text(dialog.name or "")
        first = (
            _normalize_search_text(dialog.entity.first_name or "")
            if isinstance(dialog.entity, User)
            else ""
        )
        username = (
            _normalize_search_text(dialog.entity.username or "")
            if isinstance(dialog.entity, User)
            else ""
        )

        candidates = [title, first, username]
        for needle in needles:
            if needle in candidates:
                return {"id": dialog.id, "name": dialog.name, "entity": dialog.entity}

            for candidate in candidates:
                if not candidate:
                    continue
                if needle not in candidate and candidate not in needle:
                    continue
                overlap = min(len(needle), len(candidate))
                local_score = overlap / max(1, len(candidate))
                if local_score > score:
                    score = local_score
                    best = {"id": dialog.id, "name": dialog.name, "entity": dialog.entity}
    return best


async def _send(contact: str, message: str) -> str:
    client = await _authorized_client()
    if not client:
        return "Telegram РЅРµ РїРѕРґРєР»СЋС‡РµРЅ."
    dialog = await _find(contact)
    if not dialog:
        return f"РќРµ РЅР°С€Р»Р° '{_norm_name(contact)}'."
    try:
        await client.send_message(dialog["id"], str(message))
        return f'РќР°РїРёСЃР°Р»Р° {dialog["name"]}: "{message}"'
    except Exception as exc:
        return f"РћС€РёР±РєР°: {exc}"


async def _send_batch(recipients: List[Dict]) -> str:
    results = [
        await _send(item.get("contact"), item.get("message"))
        for item in (recipients or [])
        if item.get("contact") and item.get("message")
    ]
    return " ".join(results) if results else "РќРµС‚ РїРѕР»СѓС‡Р°С‚РµР»РµР№ РґР»СЏ РѕС‚РїСЂР°РІРєРё."


async def _read(contact: str) -> str:
    client = await _authorized_client()
    if not client:
        return "Telegram РЅРµ РїРѕРґРєР»СЋС‡РµРЅ."
    dialog = await _find(contact)
    if not dialog:
        return f"РќРµ РЅР°С€Р»Р° С‡Р°С‚ СЃ '{_norm_name(contact)}'."

    me = await client.get_me()
    messages: List[Dict[str, Any]] = []
    async for message in client.iter_messages(dialog["id"], limit=5):
        if not message.text:
            continue
        is_me = message.sender_id == me.id
        stamp = _format_message_time(message.date)
        messages.append({"text": message.text[:300], "time": stamp, "is_me": is_me})

    if not messages:
        return f"РќРµС‚ СЃРѕРѕР±С‰РµРЅРёР№ СЃ {dialog['name']}."
    if messages[0]["is_me"]:
        return f'{dialog["name"]} РїРѕРєР° РЅРµ РѕС‚РІРµС‚РёР»(Р°). РўРІРѕРµ ({messages[0]["time"]}): "{messages[0]["text"]}"'

    incoming = [m for m in messages if not m["is_me"]]
    incoming = incoming[: next((i for i, m in enumerate(messages) if m["is_me"]), len(messages))]
    if len(incoming) == 1:
        return f'{dialog["name"]} ({incoming[0]["time"]}): "{incoming[0]["text"]}"'
    return (
        f'{dialog["name"]} РЅР°РїРёСЃР°Р»(Р°) {len(incoming)} СЃРѕРѕР±С‰РµРЅРёР№:\n'
        + "\n".join(f'[{m["time"]}] {m["text"]}' for m in reversed(incoming))
    )


async def _who_wrote(contact: Optional[str] = None) -> str:
    if contact:
        return await _read(contact)

    client = await _authorized_client()
    if not client:
        return "Telegram РЅРµ РїРѕРґРєР»СЋС‡РµРЅ."

    me = await client.get_me()
    lines: List[str] = []
    async for dialog in client.iter_dialogs(limit=30):
        if not isinstance(dialog.entity, User):
            continue
        async for message in client.iter_messages(dialog.id, limit=1):
            if message.sender_id != me.id and message.text:
                stamp = _format_message_time(message.date)
                text = message.text[:80] + ("..." if len(message.text) > 80 else "")
                lines.append(f"вЂў {dialog.name} ({stamp}): {text}")
            break
        if len(lines) >= 10:
            break
    return "РќРёРєС‚Рѕ РЅРµ РїРёСЃР°Р»." if not lines else "Р’ Р»РёС‡РєРµ РїРёСЃР°Р»Рё:\n" + "\n".join(lines)


def execute_telegram_tool(args: dict) -> str:
    action = str(args.get("action", "send_message")).strip()
    get = args.get
    required = {
        "start_auth": ("phone",),
        "enter_code": ("code",),
        "enter_password": ("password",),
        "send_message": ("contact", "message"),
        "send_batch": ("recipients",),
        "read_chat": ("contact",),
    }

    for key in required.get(action, ()):
        if not get(key):
            return f"РЈРєР°Р¶Рё {key}."

    try:
        if action == "check_auth":
            async def _check() -> bool:
                return bool(await _authorized_client())

            return "РџРѕРґРєР»СЋС‡РµРЅ." if _run(_check()) else "РќРµ РїРѕРґРєР»СЋС‡РµРЅ."

        action_map = {
            "start_auth": lambda: _auth_start(get("phone")),
            "enter_code": lambda: _auth_code(get("code")),
            "enter_password": lambda: _auth_2fa(get("password")),
            "send_message": lambda: _send(get("contact"), get("message")),
            "send_batch": lambda: _send_batch(get("recipients")),
            "read_chat": lambda: _read(get("contact")),
            "check_who_wrote": lambda: _who_wrote(get("contact")),
            "logout": _logout,
        }
        handler = action_map.get(action)
        if handler:
            return _run(handler())
        return f"РќРµРёР·РІРµСЃС‚РЅРѕРµ РґРµР№СЃС‚РІРёРµ: {action}"
    except Exception as exc:
        return f"РћС€РёР±РєР°: {exc}"

