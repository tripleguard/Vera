import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class AuditLogger:
    """Append-only JSONL audit logger for assistant actions."""

    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write_event(self, event: str, payload: Dict[str, Any]) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "payload": payload,
        }
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")


_audit_logger: AuditLogger | None = None
_audit_lock = threading.Lock()


def get_audit_logger(log_path: Path) -> AuditLogger:
    global _audit_logger
    with _audit_lock:
        if _audit_logger is None:
            _audit_logger = AuditLogger(log_path)
        return _audit_logger
