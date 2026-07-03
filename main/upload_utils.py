"""Upload filename helpers for the FastAPI layer."""

from __future__ import annotations

import re
import uuid
from pathlib import Path


_INVALID_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_MAX_SAFE_NAME_LENGTH = 120


def safe_upload_name(filename: str | None) -> str:
    """Return a local-only, unique filename derived from a user supplied name."""
    raw = str(filename or "upload").replace("\\", "/")
    name = Path(raw).name
    name = _INVALID_FILENAME_CHARS_RE.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = "upload"

    path = Path(name)
    suffix = path.suffix[:16].lower()
    stem = path.stem.strip(" ._") or "upload"
    max_stem = max(1, _MAX_SAFE_NAME_LENGTH - len(suffix) - 9)
    stem = stem[:max_stem].rstrip(" ._") or "upload"
    return f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"
