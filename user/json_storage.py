import json
from pathlib import Path
from typing import Any


def load_json(file_path: Path, default: Any = None) -> Any:
    """Load data from a JSON file. Returns default on error."""
    try:
        if file_path.exists():
            # Support files both with and without UTF-8 BOM.
            return json.loads(file_path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        print(f"[JSON] Failed to load {file_path.name}: {e}")
    return default if default is not None else {}


def save_json(file_path: Path, data: Any, log_name: str = "JSON") -> bool:
    """Save data to a JSON file atomically. Returns True on success."""
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = file_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # Atomic rename (overwrites target on Windows NTFS)
        import os
        os.replace(str(tmp_path), str(file_path))
        return True
    except Exception as e:
        print(f"[{log_name}] Failed to save: {e}")
        return False

