"""
Скрипт для автоматической загрузки LLM-модели (GGUF) с HuggingFace.

Использование:
    python download_model.py
    python download_model.py --install-dir "C:\Program Files\Vera"

По умолчанию скачивает Qwen3.5-2B в формате Q4_K_M (без mmproj).
"""

import argparse
import os
import sys
from pathlib import Path

import requests


MODEL_REPO = "unsloth/Qwen3.5-2B-GGUF"
MODEL_FILENAME = "Qwen3.5-2B-Q4_K_M.gguf"
HUGGINGFACE_URL = f"https://huggingface.co/{MODEL_REPO}/resolve/main/{MODEL_FILENAME}"

PROJECT_ROOT = Path(__file__).resolve().parent


def download_file(url: str, dest: Path, chunk_size: int = 8192) -> None:
    """Скачивает файл с отображением прогресса."""
    print(f"[DOWNLOAD] Скачивание: {dest.name}")
    print(f"[DOWNLOAD] URL: {url}")

    r = requests.get(url, stream=True, timeout=30)
    r.raise_for_status()

    total = int(r.headers.get("content-length", 0))
    total_mb = total / (1024 * 1024) if total else 0
    if total_mb:
        print(f"[DOWNLOAD] Размер: {total_mb:.1f} МБ")

    downloaded = 0
    with open(dest, "wb") as f:
        for chunk in r.iter_content(chunk_size=chunk_size):
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = downloaded * 100 / total
                dl_mb = downloaded / (1024 * 1024)
                print(
                    f"\r[DOWNLOAD] {pct:.0f}% ({dl_mb:.1f} / {total_mb:.1f} МБ)",
                    end="",
                    flush=True,
                )
    print()


def main():
    parser = argparse.ArgumentParser(description="Скачивание LLM-модели (GGUF)")
    parser.add_argument(
        "--install-dir",
        type=str,
        default=None,
        help="Папка установки (по умолчанию — корень проекта)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Перезаписать без подтверждения",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=HUGGINGFACE_URL,
        help="URL для скачивания (по умолчанию — Qwen3.5-2B-Q4_K_M)",
    )
    parser.add_argument(
        "--filename",
        type=str,
        default=MODEL_FILENAME,
        help="Имя файла модели",
    )
    args = parser.parse_args()

    dest_dir = Path(args.install_dir).resolve() if args.install_dir else PROJECT_ROOT
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest = dest_dir / args.filename

    # Проверяем, не скачан ли уже
    if dest.is_file() and not args.force:
        size_mb = dest.stat().st_size / (1024 * 1024)
        print(f"[INFO] {args.filename} уже существует ({size_mb:.1f} МБ).")
        answer = input("Перезаписать? (y/n): ").strip().lower()
        if answer not in ("y", "yes", "д", "да"):
            print("Отменено.")
            return

    try:
        download_file(args.url, dest)
        final_mb = dest.stat().st_size / (1024 * 1024)
        print(f"\n[OK] Модель успешно скачана: {dest}")
        print(f"  Размер: {final_mb:.1f} МБ")
    except requests.HTTPError as e:
        print(f"[ERROR] Ошибка HTTP: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
