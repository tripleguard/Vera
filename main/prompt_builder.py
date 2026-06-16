"""Compact system prompt builder with a small runtime layer."""

from datetime import datetime
from pathlib import Path
import threading


CORE_FILE = "CORE.md"
LEGACY_PROMPT_FILES = ("IDENTITY.md", "SOUL.md")

_lock = threading.Lock()
_cached_core: str = ""
_cache_mtimes: dict[str, float] = {}
_cached_data_dir: str = ""


def _read_md_body(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except Exception as exc:
        print(f"[PROMPT] Ошибка чтения {path.name}: {exc}")
        return ""

    return "\n".join(
        line for line in text.splitlines()
        if not (line.startswith("# ") or line == "#")
    ).strip()


def _source_files(data_dir: Path) -> tuple[str, ...]:
    if (data_dir / CORE_FILE).exists():
        return (CORE_FILE,)
    return LEGACY_PROMPT_FILES


def _files_changed(data_dir: Path) -> bool:
    if _cached_data_dir != str(data_dir.resolve()):
        return True
    source_files = _source_files(data_dir)
    if set(_cache_mtimes) != set(source_files):
        return True
    for filename in source_files:
        path = data_dir / filename
        try:
            mtime = path.stat().st_mtime if path.exists() else 0
        except Exception:
            return True
        if _cache_mtimes.get(filename) != mtime:
            return True
    return False


def _load_core(data_dir: Path, force_reload: bool = False) -> str:
    global _cached_core, _cache_mtimes, _cached_data_dir

    with _lock:
        if not force_reload and _cached_core and not _files_changed(data_dir):
            return _cached_core

        source_files = _source_files(data_dir)
        parts = []
        mtimes: dict[str, float] = {}
        for filename in source_files:
            path = data_dir / filename
            body = _read_md_body(path)
            if body:
                parts.append(body)
            try:
                mtimes[filename] = path.stat().st_mtime if path.exists() else 0
            except Exception:
                mtimes[filename] = 0

        _cached_core = "\n\n".join(parts)
        _cache_mtimes = mtimes
        _cached_data_dir = str(data_dir.resolve())
        return _cached_core


def build_runtime_context(now: datetime | None = None) -> str:
    current = now or datetime.now().astimezone()
    timezone_name = current.tzname() or "local"
    return (
        f"Текущая дата: {current:%Y-%m-%d}. "
        f"Локальный часовой пояс: {timezone_name}. "
        "Город пользователя из памяти используй только для погоды, маршрутов, локальных мест "
        "и других явно геозависимых запросов; не подставляй его в ответы о людях, организациях "
        "и общих фактах, если пользователь прямо не связал тему с этим городом."
    )


def build_system_prompt(
    data_dir: Path,
    force_reload: bool = False,
    *,
    runtime_context: str | None = None,
    active_skill: str | None = None,
) -> str:
    parts = [_load_core(data_dir, force_reload=force_reload)]
    runtime = runtime_context if runtime_context is not None else build_runtime_context()
    if runtime:
        parts.append(runtime.strip())
    if active_skill:
        parts.append(f"<active_skill>\n{active_skill.strip()}\n</active_skill>")
    return "\n\n".join(part for part in parts if part)


def reload_prompt(data_dir: Path) -> str:
    return build_system_prompt(data_dir, force_reload=True)


def get_prompt_status(data_dir: Path) -> str:
    source_files = _source_files(data_dir)
    lines = ["Файлы системного промпта:"]
    for filename in source_files:
        path = data_dir / filename
        if path.exists():
            lines.append(f"  [OK] {filename} ({path.stat().st_size} байт)")
        else:
            lines.append(f"  [!!] {filename} — не найден")
    lines.append("  [DYNAMIC] дата и часовой пояс")
    lines.append(f"Кеш ядра: {'актуален' if _cached_core else 'пустой'}")
    return "\n".join(lines)
