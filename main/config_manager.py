import copy
import json
import logging
import os
import shutil
import sys
import threading
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

APP_NAME = "Vera"
MIGRATION_MARKER = ".migration_v1_done"

DEFAULT_CONFIG = {
    "model": {
        "ctx_size": 8192,
        "server_port": 29741,
        "temperature": 0.3,
        "top_p": 0.8,
        "top_k": 20,
        "min_p": 0,
        "repeat_penalty": 1.1,
        "max_tokens": 0,
        "seed": 42,
        "chat_format": "chatml",
        "thinking_enabled": True,
        "thinking_budget_tokens": 1024,
        "vision_projector_path": "auto",
        "use_external_server": False,
        "external_api_url": "http://127.0.0.1:1234/v1",
    },
    "sherpa_onnx": {
        "model_dir": "sherpa-onnx-streaming-zipformer-small-ru-vosk-2025-08-16",
        "tokens": "tokens.txt",
        "encoder": "encoder.onnx",
        "decoder": "decoder.onnx",
        "joiner": "joiner.onnx",
        "samplerate": 16000,
        "provider": "cpu",
        "num_threads": 1,
        "decoding_method": "greedy_search",
        "enable_endpoint_detection": True,
        "rule1_min_trailing_silence": 2.4,
        "rule2_min_trailing_silence": 1.2,
        "rule3_min_utterance_length": 300.0,
    },
    "activation_word": "Вера",
    "silence_timeout": 2,
    "tts": {
        "voice_name": "Lily",
        "total_steps": 4,
        "volume": 50,
        "volume_scale": "percent_v2",
        "speed": 1.15,
    },
    "commands": {},
    "sites": {
        "ютуб": "https://www.youtube.com/",
        "хабр": "https://habr.com/ru/",
        "вк": "https://vk.com/",
    },
    "web_search": {
        "max_sources": 3,
        "page_timeout_sec": 2.5,
        "per_page_limit": 1200,
        "llm_max_tokens": 500,
        "oversample_links_factor": 2,
        "oversample_candidates_factor": 2,
        "log_page_errors": False,
        "max_bytes_per_page": 70000,
        "disable_time_limits": True,
        "total_context_limit": 3600,
        "news_max_age_days": 7,
        "cache_ttl_sec": 600,
        "cache_max_entries": 100,
        "early_stop_min_sources": 3,
        "early_stop_timeout": 5.0,
    },
    "ui": {
        "performance_mode": "balanced",
        "animation_adaptive": True,
    },

}

_DEFAULT_DATA_FILES = [
    "CORE.md",
    "IDENTITY.md",
    "SOUL.md",
    "TOOLS.md",
    "USER.md",
    "config.json",
    "heartbeat_tasks.json",
    "reminders.json",
    "memory.json",
]

_MUTABLE_FILES = [
    "config.json",
    "memory.json",
    "heartbeat_tasks.json",
    "reminders.json",
    "app_index.json",
]

_MUTABLE_DIRS = [
    "uploads",
    "interpreter_tmp",
]

_FALLBACK_TEXT = {
    "CORE.md": (
        "# Core\n\n"
        "Ты Вера, локальный персональный помощник. Говори о себе в женском роде.\n\n"
        "Отвечай естественно, кратко и по делу. Используй только предоставленные "
        "инструменты и не выдумывай результаты действий.\n"
    ),
    "IDENTITY.md": "# Identity\n\nYou are Vera voice assistant.\n",
    "SOUL.md": "# Soul\n\nBe concise, helpful, and safe.\n",
    "TOOLS.md": "# Tools\n\nUse available tools when needed.\n",
    "USER.md": "# User\n\nNo user profile yet.\n",
    "memory.json": '{\n  "profile": {},\n  "facts": []\n}\n',
}

_DATA_LAYOUT_READY = False
_DATA_LAYOUT_LOCK = threading.Lock()


def _get_localappdata_root() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data)
    return Path.home() / "AppData" / "Local"


def get_install_root() -> Path:
    """
    Returns the read-only install root where binaries and bundled assets live.
    """
    env_root = os.getenv("VERA_INSTALL_ROOT")
    if env_root:
        try:
            return Path(env_root).expanduser().resolve()
        except Exception:
            return Path(env_root)

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _get_bundled_data_dir() -> Path:
    """
    Returns path to bundled data templates.
    For PyInstaller: inside _MEIPASS/data/
    For dev: install_root/data/
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "data"
    return get_install_root() / "data"


def _get_legacy_data_dir() -> Path:
    """
    Legacy data location near install root (used only for one-time migration).
    """
    return get_install_root() / "data"


def _get_target_data_dir() -> Path:
    return _get_localappdata_root() / APP_NAME / "data"


def _has_existing_user_state(data_dir: Path) -> bool:
    for filename in _MUTABLE_FILES:
        if (data_dir / filename).exists():
            return True

    if list(data_dir.glob("telegram_session.*")):
        return True

    for dirname in _MUTABLE_DIRS:
        p = data_dir / dirname
        if p.exists() and any(p.iterdir()):
            return True
    return False


def _copy_if_missing(src: Path, dst: Path) -> None:
    if not src.exists() or dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_tree_if_missing(src: Path, dst: Path) -> None:
    if not src.exists() or dst.exists():
        return
    shutil.copytree(src, dst)


def _seed_default_files(data_dir: Path, legacy_data_dir: Path) -> None:
    for filename in _DEFAULT_DATA_FILES:
        dst = data_dir / filename
        if dst.exists():
            continue
        src = legacy_data_dir / filename
        if src.exists():
            _copy_if_missing(src, dst)
            continue
        fallback = _FALLBACK_TEXT.get(filename)
        if fallback:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(fallback, encoding="utf-8")


def _migrate_legacy_data_if_needed(data_dir: Path, legacy_data_dir: Path) -> None:
    marker = data_dir / MIGRATION_MARKER
    if marker.exists():
        return

    migrated_any = False
    has_user_state = _has_existing_user_state(data_dir)

    if not has_user_state and legacy_data_dir.exists():
        for filename in _MUTABLE_FILES:
            src = legacy_data_dir / filename
            dst = data_dir / filename
            before = dst.exists()
            _copy_if_missing(src, dst)
            migrated_any = migrated_any or (not before and dst.exists())

        for src in legacy_data_dir.glob("telegram_session.*"):
            dst = data_dir / src.name
            before = dst.exists()
            _copy_if_missing(src, dst)
            migrated_any = migrated_any or (not before and dst.exists())

        for dirname in _MUTABLE_DIRS:
            src = legacy_data_dir / dirname
            dst = data_dir / dirname
            before = dst.exists()
            _copy_tree_if_missing(src, dst)
            migrated_any = migrated_any or (not before and dst.exists())

    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps({"migrated": migrated_any}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if migrated_any:
        logger.info("Legacy data migrated from %s to %s", legacy_data_dir, data_dir)


def ensure_data_layout_and_migrate() -> Path:
    global _DATA_LAYOUT_READY
    with _DATA_LAYOUT_LOCK:
        data_dir = _get_target_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)

        if _DATA_LAYOUT_READY:
            return data_dir

        legacy_data_dir = _get_legacy_data_dir()
        bundled_data_dir = _get_bundled_data_dir()
        _migrate_legacy_data_if_needed(data_dir, legacy_data_dir)
        _seed_default_files(data_dir, bundled_data_dir)

        for dirname in _MUTABLE_DIRS:
            (data_dir / dirname).mkdir(parents=True, exist_ok=True)

        _DATA_LAYOUT_READY = True
        return data_dir


def get_data_dir() -> Path:
    return ensure_data_layout_and_migrate()


class ConfigManager:
    _instance: Optional["ConfigManager"] = None
    _config: Optional[dict] = None
    _raw_config: Optional[dict] = None
    _config_path: Optional[Path] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config_path: Optional[Path] = None):
        if self._config is None:
            if config_path is None:
                config_path = get_data_dir() / "config.json"
            self._config_path = config_path
            self._ensure_config_exists()
            self._load_config()
            self._resolve_paths()

    def _ensure_config_exists(self) -> None:
        if self._config_path.exists():
            return

        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        with self._config_path.open("w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        logger.info("Created default config: %s", self._config_path)


    def _resolve_paths(self) -> None:
        if self._config is None:
            return

        install_root = get_install_root()

        # LLM model resolution (always auto-detect now)
        gguf_path = self._find_gguf_model(install_root)
        if gguf_path:
            # We store it in self._config for runtime use, but it won't be in the saved config.json
            if "model" not in self._config:
                self._config["model"] = {}
            self._config["model"]["path"] = str(gguf_path)
            logger.info("LLM model auto-detected: %s", gguf_path)

        if "sherpa_onnx" not in self._config:
            self._config["sherpa_onnx"] = copy.deepcopy(DEFAULT_CONFIG["sherpa_onnx"])

        if "sherpa_onnx" in self._config:
            stt_cfg = self._config["sherpa_onnx"]
            model_dir = str(stt_cfg.get("model_dir", "") or "")
            if model_dir:
                model_dir_path = Path(model_dir)
                if not model_dir_path.is_absolute():
                    model_dir_path = install_root / model_dir_path
                stt_cfg["model_dir"] = str(model_dir_path)

                for key in ("tokens", "encoder", "decoder", "joiner"):
                    value = stt_cfg.get(key)
                    if value and not os.path.isabs(str(value)):
                        stt_cfg[key] = str(model_dir_path / str(value))

    def _find_gguf_model(self, search_dir: Path) -> Optional[Path]:
        try:
            gguf_files = list(search_dir.glob("*.gguf"))
            gguf_files.extend(search_dir.glob("models/*.gguf"))
            # Also check parent dirs (for Inno Setup layout)
            if not gguf_files:
                for parent in search_dir.parents:
                    gguf_files = list(parent.glob("*.gguf"))
                    if gguf_files:
                        break
                    if parent == search_dir.parent.parent:
                        break
            if gguf_files:
                gguf_files.sort(key=lambda p: p.stat().st_size, reverse=True)
                return gguf_files[0]
        except Exception as e:
            logger.error("Error searching for .gguf files: %s", e)
        return None

    def _load_config(self) -> None:
        if not self._config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self._config_path}")

        with self._config_path.open(encoding="utf-8-sig") as f:
            self._raw_config = json.load(f)
            tts_migrated = self._normalize_tts_config(self._raw_config)
            model_migrated = self._normalize_model_config(self._raw_config)
            migrated = tts_migrated or model_migrated
            self._config = copy.deepcopy(self._raw_config)
            logger.info("Configuration loaded from %s", self._config_path)
        if migrated:
            self.save()

    @staticmethod
    def _normalize_tts_config(config: dict) -> bool:
        tts = config.setdefault("tts", {})
        raw_volume = tts.get("volume", DEFAULT_CONFIG["tts"]["volume"])
        try:
            volume = float(raw_volume)
        except (TypeError, ValueError):
            volume = float(DEFAULT_CONFIG["tts"]["volume"])

        scale = str(tts.get("volume_scale", "") or "")
        if scale != "percent_v2":
            if 0 < volume <= 1:
                volume *= 100
            elif 1 < volume <= 15:
                volume = (volume / 15) * 100

        volume = round(max(0.0, min(100.0, volume)))
        changed = raw_volume != volume or scale != "percent_v2"
        tts["volume"] = volume
        tts["volume_scale"] = "percent_v2"
        return changed

    @staticmethod
    def _normalize_model_config(config: dict) -> bool:
        model = config.setdefault("model", {})
        raw_budget = model.get(
            "thinking_budget_tokens",
            DEFAULT_CONFIG["model"]["thinking_budget_tokens"],
        )
        try:
            budget = int(raw_budget)
        except (TypeError, ValueError):
            budget = int(DEFAULT_CONFIG["model"]["thinking_budget_tokens"])

        budget = max(0, min(32768, budget))
        changed = (
            raw_budget != budget
            or model.get("thinking_budget_tokens") != budget
        )
        model["thinking_budget_tokens"] = budget
        return changed

    def reload(self) -> None:
        self._config = None
        self._load_config()
        self._resolve_paths()

    def get(self, *keys: str, default: Any = None) -> Any:
        if self._config is None:
            return default

        current = self._config
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current

    def get_all(self) -> dict:
        return self._config or {}

    def get_raw(self) -> dict:
        return self._raw_config or self._config or {}

    def set_all(self, new_config: dict) -> None:
        self._raw_config = copy.deepcopy(new_config)
        self._normalize_tts_config(self._raw_config)
        self._normalize_model_config(self._raw_config)
        self._config = copy.deepcopy(new_config)
        self._normalize_tts_config(self._config)
        self._normalize_model_config(self._config)

    def set(self, *keys: str, value: Any) -> None:
        if self._config is None:
            self._config = {}

        current = self._config
        for key in keys[:-1]:
            if key not in current or not isinstance(current[key], dict):
                current[key] = {}
            current = current[key]

        current[keys[-1]] = value

    def save(self) -> None:
        payload = self._raw_config if self._raw_config is not None else self._config
        if payload is None:
            payload = {}
        with self._config_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        logger.info("Configuration saved to %s", self._config_path)


def get_config() -> ConfigManager:
    return ConfigManager()


# Compatibility alias used in some tools.
EXE_DIR = str(get_install_root())
