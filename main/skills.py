from functools import lru_cache
from pathlib import Path
import sys
from typing import Any, Optional

from .config_manager import get_data_dir, get_install_root


def _strip_frontmatter(text: str) -> str:
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return stripped
    parts = stripped.split("---", 2)
    if len(parts) < 3:
        return stripped
    return parts[2].strip()


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return {}, stripped

    parts = stripped.split("---", 2)
    if len(parts) < 3:
        return {}, stripped

    metadata: dict[str, Any] = {}
    nested_key: Optional[str] = None
    for raw_line in parts[1].splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip())
        line = raw_line.strip()
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))

        if indent and nested_key:
            nested = metadata.setdefault(nested_key, {})
            if isinstance(nested, dict):
                nested[key] = value.strip("'\"")
            continue

        nested_key = key if not value else None
        metadata[key] = {} if not value else value.strip("'\"")

    return metadata, parts[2].strip()


def _bundled_skills_root() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) / "skills" if meipass else get_install_root() / "skills"


def _user_skills_root() -> Path:
    return get_data_dir().parent / "skills"


def _skill_title(name: str, body: str) -> str:
    for line in body.splitlines():
        candidate = line.strip()
        if candidate.startswith("# "):
            return candidate[2:].strip()
    return name.replace("-", " ").replace("_", " ").title()


def _read_skill(skill_path: Path, source: str) -> Optional[dict[str, Any]]:
    try:
        metadata, body = _split_frontmatter(skill_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError):
        return None

    directory_name = skill_path.parent.name
    name = str(metadata.get("name") or directory_name).strip()
    if not name:
        return None

    raw_allowed_tools = metadata.get("allowed-tools", "")
    if isinstance(raw_allowed_tools, str):
        allowed_tools = [
            item
            for item in raw_allowed_tools.replace(",", " ").split()
            if item
        ]
    else:
        allowed_tools = []

    vera_metadata = metadata.get("metadata", {})
    if not isinstance(vera_metadata, dict):
        vera_metadata = {}

    return {
        "name": name,
        "title": _skill_title(name, body),
        "description": str(metadata.get("description") or "").strip(),
        "allowed_tools": allowed_tools,
        "source": source,
        "activation": str(vera_metadata.get("vera.activation") or "").strip(),
        "model_profile": str(vera_metadata.get("vera.model-profile") or "").strip(),
    }


def list_installed_skills(
    bundled_root: Optional[Path] = None,
    user_root: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Return bundled and user-installed skills without exposing prompt bodies."""
    roots = (
        ("builtin", bundled_root or _bundled_skills_root()),
        ("user", user_root or _user_skills_root()),
    )
    skills: dict[str, dict[str, Any]] = {}

    for source, root in roots:
        try:
            skill_paths = sorted(root.glob("*/SKILL.md"))
        except OSError:
            continue
        for skill_path in skill_paths:
            skill = _read_skill(skill_path, source)
            if skill:
                skills[skill["name"].lower()] = skill

    return sorted(skills.values(), key=lambda skill: skill["title"].casefold())


@lru_cache(maxsize=16)
def load_builtin_skill(name: str) -> Optional[str]:
    """Load a bundled, read-only skill body by its safe directory name."""
    safe_name = (name or "").strip().lower()
    if not safe_name or not safe_name.replace("-", "").replace("_", "").isalnum():
        return None

    skill_path = _bundled_skills_root() / safe_name / "SKILL.md"
    try:
        body = _strip_frontmatter(skill_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError):
        return None
    return body or None
