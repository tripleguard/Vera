"""
Сборщик системного промпта из модульных файлов.

Структура файлов в data/:
  IDENTITY.md  — персона, стиль, год (кто ты)
  SOUL.md      — правила поведения (как ты ведёшь себя)
  TOOLS.md     — инструменты, форматы, примеры
  USER.md      — предпочтения пользователя

Порядок сборки: IDENTITY → SOUL → TOOLS → USER
Каждый файл заголовок (# ...) игнорируется — только содержимое.
"""

from pathlib import Path
import threading

# Порядок и имена файлов для сборки промпта
PROMPT_FILES = ["IDENTITY.md", "SOUL.md", "TOOLS.md", "USER.md"]

_lock = threading.Lock()
_cached_prompt: str = ""
_cache_mtimes: dict = {}


def _read_md_body(path: Path) -> str:
    """Читает файл и убирает markdown-заголовки первого уровня (#)."""
    try:
        text = path.read_text(encoding="utf-8").strip()
        # Убираем строки вида "# Заголовок" в начале файла
        lines = text.splitlines()
        result = []
        for line in lines:
            if line.startswith("# ") or line == "#":
                continue  # пропускаем h1 заголовки
            result.append(line)
        return "\n".join(result).strip()
    except FileNotFoundError:
        return ""
    except Exception as e:
        print(f"[PROMPT] Ошибка чтения {path.name}: {e}")
        return ""


def _files_changed(data_dir: Path) -> bool:
    """Проверяет, изменились ли файлы промпта с момента последнего кеширования."""
    for fname in PROMPT_FILES:
        path = data_dir / fname
        try:
            mtime = path.stat().st_mtime if path.exists() else 0
            if _cache_mtimes.get(fname) != mtime:
                return True
        except Exception:
            return True
    return False


def build_system_prompt(data_dir: Path, force_reload: bool = False) -> str:
    """
    Собирает системный промпт из отдельных файлов.

    Args:
        data_dir: Директория с файлами IDENTITY.md, SOUL.md и т.д.
        force_reload: Принудительно перечитать файлы (игнорировать кеш).

    Returns:
        Собранный системный промпт.
    """
    global _cached_prompt, _cache_mtimes

    with _lock:
        if not force_reload and _cached_prompt and not _files_changed(data_dir):
            return _cached_prompt

        parts = []
        new_mtimes = {}

        for fname in PROMPT_FILES:
            path = data_dir / fname
            body = _read_md_body(path)
            if body:
                parts.append(body)
            # Обновляем время модификации (0 если файл не существует)
            try:
                new_mtimes[fname] = path.stat().st_mtime if path.exists() else 0
            except Exception:
                new_mtimes[fname] = 0

        prompt = "\n\n".join(parts)

        _cached_prompt = prompt
        _cache_mtimes = new_mtimes

        return prompt


def reload_prompt(data_dir: Path) -> str:
    """Сбрасывает кеш и перечитывает все файлы промпта."""
    return build_system_prompt(data_dir, force_reload=True)


def get_prompt_status(data_dir: Path) -> str:
    """Возвращает статус загруженных файлов промпта (для диагностики)."""
    lines = ["Файлы системного промпта:"]
    for fname in PROMPT_FILES:
        path = data_dir / fname
        if path.exists():
            size = path.stat().st_size
            lines.append(f"  [OK] {fname} ({size} байт)")
        else:
            lines.append(f"  [!!] {fname} — не найден")
    lines.append(f"Кеш: {'актуален' if _cached_prompt else 'пустой'}")
    return "\n".join(lines)

