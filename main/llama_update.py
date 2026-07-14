"""Update checks for the bundled llama.cpp runtime."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

import requests

from main.config_manager import get_install_root


GITHUB_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
TARGET_FILE = "llama-server.exe"
_CACHE_TTL_SECONDS = 6 * 60 * 60
_CACHE: dict[str, Any] = {"checked_at": 0.0, "payload": None}
_INSTALL_LOCK = None
_EXCLUDED_DLLS = {"vulkan-1.dll", "vk_swiftshader.dll"}


def parse_llama_build(value: str | None) -> int | None:
    text = str(value or "")
    patterns = (
        r"\bb(\d{3,})\b",
        r"\bversion:\s*(\d{3,})\b",
        r"\bbuild\s*(\d{3,})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
    return None


def _find_best_asset(release: dict[str, Any]) -> dict[str, Any] | None:
    assets = release.get("assets") or []
    for keywords in (("win", "vulkan", "x64"), ("win", "cpu", "x64")):
        for asset in assets:
            name = str(asset.get("name") or "").lower()
            if name.endswith(".zip") and all(keyword in name for keyword in keywords):
                return asset
    return None


def _get_install_lock():
    global _INSTALL_LOCK
    if _INSTALL_LOCK is None:
        import threading

        _INSTALL_LOCK = threading.Lock()
    return _INSTALL_LOCK


def _runtime_files_from_zip(zip_path: Path, extract_dir: Path) -> list[Path]:
    files: list[Path] = []
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.namelist():
            basename = os.path.basename(member)
            lower = basename.lower()
            if not basename or member.endswith("/"):
                continue
            if lower == TARGET_FILE.lower() or (lower.endswith(".dll") and lower not in _EXCLUDED_DLLS):
                destination = extract_dir / basename
                with archive.open(member) as src, destination.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                files.append(destination)
    if not any(path.name.lower() == TARGET_FILE.lower() for path in files):
        raise RuntimeError(f"{TARGET_FILE} не найден в архиве обновления.")
    return files


def _download_asset(asset: dict[str, Any], destination: Path) -> None:
    url = str(asset.get("download_url") or asset.get("browser_download_url") or "")
    if not url:
        raise RuntimeError("У релиза нет ссылки на скачивание runtime-архива.")
    name = str(asset.get("name") or "runtime archive")

    headers = {"User-Agent": "VeraLlamaUpdater"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    with requests.get(url, headers=headers, stream=True, timeout=300) as response:
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            status = response.status_code
            raise RuntimeError(f"GitHub вернул HTTP {status} для {name}: {url}") from exc
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    handle.write(chunk)


def _stop_running_llama_server() -> None:
    try:
        from main import agent

        server = getattr(agent, "_llm_server", None)
        if server is not None:
            server.stop()
    except Exception:
        pass
    if sys.platform.startswith("win"):
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", TARGET_FILE],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=8,
            )
        except Exception:
            pass


def _replace_file_with_retry(source: Path, destination: Path) -> None:
    temp_destination = destination.with_name(destination.name + ".new")
    shutil.copy2(source, temp_destination)
    last_error: Exception | None = None
    for _attempt in range(6):
        try:
            os.replace(temp_destination, destination)
            return
        except PermissionError as exc:
            last_error = exc
            _stop_running_llama_server()
            time.sleep(0.4)
    if temp_destination.exists():
        temp_destination.unlink(missing_ok=True)
    if last_error:
        raise last_error


def _find_local_llama_executable() -> Path:
    install_root = get_install_root()
    for directory in (install_root, *install_root.parents):
        candidate = directory / TARGET_FILE
        if candidate.is_file():
            return candidate
        if directory == install_root.parent.parent:
            break
    return install_root / TARGET_FILE


def install_latest_llama_update() -> dict[str, Any]:
    lock = _get_install_lock()
    if not lock.acquire(blocking=False):
        return {
            "status": "busy",
            "update_available": False,
            "restart_required": False,
            "error": "Обновление llama.cpp уже выполняется.",
        }

    try:
        update = check_llama_update(force_refresh=True)
        if update.get("status") != "ok":
            return {**update, "restart_required": False}
        if not update.get("update_available"):
            return {**update, "restart_required": False, "installed": False}

        asset = update.get("asset") or {}
        install_root = _find_local_llama_executable().parent
        install_root.mkdir(parents=True, exist_ok=True)
        backup_root = install_root / "runtime_backups"
        backup_dir = backup_root / f"llama-{int(time.time())}"
        backup_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="vera-llama-update-") as tmp:
            tmp_dir = Path(tmp)
            archive_path = tmp_dir / "llama-runtime.zip"
            extract_dir = tmp_dir / "runtime"
            extract_dir.mkdir()

            _download_asset(asset, archive_path)
            extracted_files = _runtime_files_from_zip(archive_path, extract_dir)

            _stop_running_llama_server()

            installed: list[str] = []
            for source in extracted_files:
                destination = install_root / source.name
                if destination.exists():
                    shutil.copy2(destination, backup_dir / destination.name)
                _replace_file_with_retry(source, destination)
                installed.append(destination.name)

        _CACHE.update({"checked_at": 0.0, "payload": None})
        post_update = check_llama_update(force_refresh=True)
        return {
            **post_update,
            "status": "installed",
            "installed": True,
            "installed_files": installed,
            "backup_dir": str(backup_dir),
            "restart_required": True,
        }
    except Exception as exc:
        return {
            "status": "error",
            "update_available": True,
            "restart_required": False,
            "error": str(exc),
        }
    finally:
        lock.release()


def get_local_llama_version(exe_path: Path | None = None) -> dict[str, Any]:
    exe = exe_path or _find_local_llama_executable()
    payload: dict[str, Any] = {
        "path": str(exe),
        "raw": "",
        "build": None,
        "available": exe.is_file(),
    }
    if not exe.is_file():
        return payload

    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
    try:
        result = subprocess.run(
            [str(exe), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=creationflags,
        )
    except Exception as exc:
        payload["error"] = str(exc)
        return payload

    raw = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    payload["raw"] = raw
    payload["build"] = parse_llama_build(raw)
    if result.returncode != 0:
        payload["error"] = f"llama-server --version exited with {result.returncode}"
    return payload


def check_llama_update(*, force_refresh: bool = False) -> dict[str, Any]:
    now = time.time()
    cached = _CACHE.get("payload")
    if (
        not force_refresh
        and cached is not None
        and now - float(_CACHE.get("checked_at") or 0.0) < _CACHE_TTL_SECONDS
    ):
        return dict(cached)

    local = get_local_llama_version()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "VeraLlamaUpdateChecker",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.get(GITHUB_API, headers=headers, timeout=15)
        response.raise_for_status()
        release = response.json()
    except Exception as exc:
        payload = {
            "status": "error",
            "checked_at": now,
            "current": local,
            "latest": None,
            "update_available": False,
            "error": str(exc),
        }
        _CACHE.update({"checked_at": now, "payload": payload})
        return payload

    latest_tag = str(release.get("tag_name") or "")
    latest_build = parse_llama_build(latest_tag) or parse_llama_build(release.get("name"))
    asset = _find_best_asset(release)
    current_build = local.get("build")
    update_available = (
        isinstance(current_build, int)
        and isinstance(latest_build, int)
        and latest_build > current_build
    )

    payload = {
        "status": "ok",
        "checked_at": now,
        "current": local,
        "latest": {
            "tag": latest_tag,
            "name": release.get("name"),
            "build": latest_build,
            "published_at": release.get("published_at"),
        },
        "asset": None if asset is None else {
            "name": asset.get("name"),
            "size": asset.get("size"),
            "download_url": asset.get("browser_download_url"),
        },
        "update_available": update_available,
    }
    _CACHE.update({"checked_at": now, "payload": payload})
    return payload
