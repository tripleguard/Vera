"""Thread-safe runtime readiness state shared with the UI."""

from copy import deepcopy
from threading import Lock
from typing import Dict, Optional


COMPONENT_NAMES = ("llm", "tts", "stt", "audio")
VOICE_COMPONENTS = ("tts", "stt", "audio")
VALID_STATUSES = {"starting", "ready", "degraded", "error", "disabled"}


class RuntimeStatus:
    """Tracks text readiness separately from optional voice components."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._text_ready = False
        self._components: Dict[str, Dict[str, Optional[str]]] = {
            name: {"status": "starting", "error": None}
            for name in COMPONENT_NAMES
        }

    def set_text_ready(self, ready: bool = True) -> None:
        with self._lock:
            self._text_ready = bool(ready)

    def update(self, name: str, status: str, error: Optional[object] = None) -> None:
        if name not in COMPONENT_NAMES:
            raise ValueError(f"Unknown runtime component: {name}")
        if status not in VALID_STATUSES:
            raise ValueError(f"Unknown runtime status: {status}")
        error_text = None if error is None else str(error).strip() or None
        with self._lock:
            self._components[name] = {"status": status, "error": error_text}

    def is_ready(self, name: str) -> bool:
        if name not in COMPONENT_NAMES:
            raise ValueError(f"Unknown runtime component: {name}")
        with self._lock:
            return self._components[name]["status"] == "ready"

    def snapshot(self) -> dict:
        with self._lock:
            text_ready = self._text_ready
            components = deepcopy(self._components)

        voice_ready = all(
            components[name]["status"] == "ready"
            for name in VOICE_COMPONENTS
        )
        if not text_ready:
            mode = "starting"
        elif voice_ready:
            mode = "full"
        else:
            mode = "text_only"

        return {
            # Backward-compatible field: ready now means that text requests work.
            "ready": text_ready,
            "mode": mode,
            "components": components,
            "llm_ready": components["llm"]["status"] == "ready",
            "tts_ready": components["tts"]["status"] == "ready",
            "stt_ready": components["stt"]["status"] == "ready",
            "audio_ready": components["audio"]["status"] == "ready",
        }
