"""
Скрипт для автоматической загрузки llama-server.exe с GitHub Releases.

Использование:
    python download_llama_server.py

Скачивает последнюю версию llama-server.exe (Windows x64, Vulkan)
из репозитория ggml-org/llama.cpp и кладёт в корень проекта.
"""

import io
import os
import sys
import zipfile
from pathlib import Path

import requests


GITHUB_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
# Паттерн для поиска нужного архива (Windows x64 Vulkan)
ASSET_KEYWORDS = ("win", "vulkan", "x64")
ASSET_EXTENSION = ".zip"
TARGET_FILE = "llama-server.exe"

PROJECT_ROOT = Path(__file__).resolve().parent


def get_latest_release_info() -> dict:
    """Получает информацию о последнем релизе."""
    print("[DOWNLOAD] Получение информации о последнем релизе...")
    headers = {"Accept": "application/vnd.github.v3+json"}

    # Используем токен если есть (для избежания rate-limit)
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"

    r = requests.get(GITHUB_API, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()


def find_vulkan_asset(release: dict) -> dict | None:
    """Находит архив с Vulkan-сборкой для Windows x64."""
    for asset in release.get("assets", []):
        name = asset["name"].lower()
        if name.endswith(ASSET_EXTENSION) and all(kw in name for kw in ASSET_KEYWORDS):
            return asset
    return None


def download_and_extract(asset: dict) -> Path:
    """Скачивает архив и извлекает llama-server.exe."""
    url = asset["browser_download_url"]
    size_mb = asset["size"] / (1024 * 1024)
    print(f"[DOWNLOAD] Скачивание: {asset['name']} ({size_mb:.1f} МБ)...")

    r = requests.get(url, stream=True, timeout=300)
    r.raise_for_status()

    # Читаем всё в память для распаковки
    data = io.BytesIO()
    downloaded = 0
    total = asset["size"]
    for chunk in r.iter_content(chunk_size=8192):
        data.write(chunk)
        downloaded += len(chunk)
        pct = downloaded * 100 / total
        print(f"\r[DOWNLOAD] {pct:.0f}% ({downloaded / 1024 / 1024:.1f} МБ)", end="", flush=True)
    print()

    data.seek(0)

    # Извлекаем llama-server.exe
    print(f"[DOWNLOAD] Извлечение {TARGET_FILE}...")
    with zipfile.ZipFile(data) as zf:
        # Ищем llama-server.exe внутри архива (может быть в подпапке)
        target_path = None
        for name in zf.namelist():
            if name.lower().endswith(TARGET_FILE.lower()):
                target_path = name
                break

        if not target_path:
            print(f"[ERROR] {TARGET_FILE} не найден в архиве!")
            print(f"  Содержимое: {', '.join(zf.namelist()[:20])}")
            sys.exit(1)

        # Извлекаем файл
        dest = PROJECT_ROOT / TARGET_FILE
        with zf.open(target_path) as src, open(dest, "wb") as dst:
            dst.write(src.read())

        # Также извлекаем vulkan-1.dll и другие DLL если есть
        for name in zf.namelist():
            basename = os.path.basename(name).lower()
            if basename.endswith(".dll"):
                dll_dest = PROJECT_ROOT / os.path.basename(name)
                if not dll_dest.exists():
                    with zf.open(name) as src, open(dll_dest, "wb") as dst:
                        dst.write(src.read())
                    print(f"  Извлечено: {os.path.basename(name)}")

    return dest


def main():
    # Проверяем, не скачан ли уже
    existing = PROJECT_ROOT / TARGET_FILE
    if existing.is_file():
        size_mb = existing.stat().st_size / (1024 * 1024)
        print(f"[INFO] {TARGET_FILE} уже существует ({size_mb:.1f} МБ).")
        answer = input("Перезаписать? (y/n): ").strip().lower()
        if answer not in ("y", "yes", "д", "да"):
            print("Отменено.")
            return

    try:
        release = get_latest_release_info()
        tag = release.get("tag_name", "unknown")
        print(f"[DOWNLOAD] Последний релиз: {tag}")

        asset = find_vulkan_asset(release)
        if not asset:
            print("[ERROR] Не найден подходящий архив (Windows x64 Vulkan).")
            print("  Скачайте вручную: https://github.com/ggml-org/llama.cpp/releases")
            sys.exit(1)

        dest = download_and_extract(asset)
        print(f"\n[OK] {TARGET_FILE} успешно установлен: {dest}")
        print(f"  Версия: {tag}")
        print(f"  Размер: {dest.stat().st_size / 1024 / 1024:.1f} МБ")

    except requests.HTTPError as e:
        print(f"[ERROR] Ошибка HTTP: {e}")
        if "403" in str(e):
            print("  Возможно, превышен лимит запросов GitHub API.")
            print("  Установите GITHUB_TOKEN для увеличения лимита.")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
