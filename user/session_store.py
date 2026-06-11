from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


MAX_CONTEXT_MESSAGES = 5


class SessionStore:
    """Persistent, session-scoped chat history backed by SQLite."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=10.0,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    preview TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'chat',
                    active_task_id TEXT,
                    last_error TEXT
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'text',
                    metadata_json TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS session_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_updated
                    ON sessions(archived, pinned DESC, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON messages(session_id, id);
                """
            )

    @staticmethod
    def _clean_title(text: str, fallback: str = "Новая сессия") -> str:
        cleaned = " ".join(str(text or "").split()).strip()
        if not cleaned:
            return fallback
        if len(cleaned) <= 60:
            return cleaned
        shortened = cleaned[:60].rsplit(" ", 1)[0].strip()
        return (shortened or cleaned[:60]).rstrip(".,:;!?") + "..."

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "preview": row["preview"],
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "archived": bool(row["archived"]),
            "pinned": bool(row["pinned"]),
            "source": row["source"],
            "active_task_id": row["active_task_id"],
            "last_error": row["last_error"],
        }

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {}
        raw_metadata = row["metadata_json"]
        if raw_metadata:
            try:
                parsed = json.loads(raw_metadata)
                if isinstance(parsed, dict):
                    metadata = parsed
            except (TypeError, ValueError):
                metadata = {}
        return {
            "id": int(row["id"]),
            "session_id": row["session_id"],
            "role": row["role"],
            "content": row["content"],
            "created_at": float(row["created_at"]),
            "kind": row["kind"],
            "metadata": metadata,
        }

    def create_session(
        self,
        title: str = "Новая сессия",
        *,
        source: str = "chat",
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        session_id = session_id or str(uuid.uuid4())
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO sessions (
                    id, title, preview, created_at, updated_at, source
                ) VALUES (?, ?, '', ?, ?, ?)
                """,
                (session_id, self._clean_title(title), now, now, source or "chat"),
            )
        return self.get_session(session_id) or {}

    def ensure_session(
        self,
        session_id: Optional[str],
        *,
        title: str = "Новая сессия",
        source: str = "chat",
    ) -> Dict[str, Any]:
        if session_id:
            existing = self.get_session(session_id)
            if existing:
                return existing
            return self.create_session(title, source=source, session_id=session_id)
        return self.create_session(title, source=source)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        if not session_id:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        return self._row_to_session(row) if row else None

    def list_sessions(
        self,
        *,
        archived: bool = False,
        limit: int = 100,
        search: str = "",
    ) -> List[Dict[str, Any]]:
        clauses = ["archived = ?"]
        params: List[Any] = [1 if archived else 0]
        query = str(search or "").strip()
        if query:
            clauses.append("(LOWER(title) LIKE ? OR LOWER(preview) LIKE ?)")
            pattern = f"%{query.lower()}%"
            params.extend([pattern, pattern])
        params.append(max(1, min(int(limit), 500)))
        sql = (
            "SELECT * FROM sessions WHERE "
            + " AND ".join(clauses)
            + " ORDER BY pinned DESC, updated_at DESC LIMIT ?"
        )
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_session(row) for row in rows]

    def update_session(
        self,
        session_id: str,
        *,
        title: Optional[str] = None,
        archived: Optional[bool] = None,
        pinned: Optional[bool] = None,
        active_task_id: Optional[str] = None,
        clear_active_task: bool = False,
        last_error: Optional[str] = None,
        clear_error: bool = False,
    ) -> Optional[Dict[str, Any]]:
        fields: List[str] = []
        params: List[Any] = []
        if title is not None:
            fields.append("title = ?")
            params.append(self._clean_title(title))
        if archived is not None:
            fields.append("archived = ?")
            params.append(1 if archived else 0)
        if pinned is not None:
            fields.append("pinned = ?")
            params.append(1 if pinned else 0)
        if active_task_id is not None:
            fields.append("active_task_id = ?")
            params.append(active_task_id)
        elif clear_active_task:
            fields.append("active_task_id = NULL")
        if last_error is not None:
            fields.append("last_error = ?")
            params.append(str(last_error)[:500])
        elif clear_error:
            fields.append("last_error = NULL")
        if not fields:
            return self.get_session(session_id)
        fields.append("updated_at = ?")
        params.append(time.time())
        params.append(session_id)
        with self._lock, self._conn:
            cursor = self._conn.execute(
                f"UPDATE sessions SET {', '.join(fields)} WHERE id = ?",
                params,
            )
        return self.get_session(session_id) if cursor.rowcount else None

    def delete_session(self, session_id: str) -> bool:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "DELETE FROM sessions WHERE id = ?",
                (session_id,),
            )
        return cursor.rowcount > 0

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        kind: str = "text",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        text = str(content or "").strip()
        if not session_id or not text:
            return None
        if role not in {"user", "assistant", "system"}:
            role = "system"
        session = self.ensure_session(session_id)
        now = time.time()
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False) if metadata else None
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO messages (
                    session_id, role, content, created_at, kind, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, role, text, now, kind or "text", metadata_json),
            )
            updates = ["updated_at = ?", "last_error = NULL"]
            params: List[Any] = [now]
            if role == "user":
                preview = self._clean_title(text, fallback="")
                updates.append("preview = ?")
                params.append(preview)
                if session["title"] == "Новая сессия":
                    updates.append("title = ?")
                    params.append(preview or "Новая сессия")
            params.append(session_id)
            self._conn.execute(
                f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            row = self._conn.execute(
                "SELECT * FROM messages WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return self._row_to_message(row) if row else None

    def get_messages(
        self,
        session_id: str,
        *,
        limit: Optional[int] = None,
        roles: Optional[Iterable[str]] = None,
    ) -> List[Dict[str, Any]]:
        clauses = ["session_id = ?"]
        params: List[Any] = [session_id]
        role_list = [role for role in (roles or []) if role]
        if role_list:
            placeholders = ",".join("?" for _ in role_list)
            clauses.append(f"role IN ({placeholders})")
            params.extend(role_list)
        if limit is None:
            sql = (
                "SELECT * FROM messages WHERE "
                + " AND ".join(clauses)
                + " ORDER BY id ASC"
            )
        else:
            params.append(max(1, int(limit)))
            sql = (
                "SELECT * FROM (SELECT * FROM messages WHERE "
                + " AND ".join(clauses)
                + " ORDER BY id DESC LIMIT ?) ORDER BY id ASC"
            )
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_message(row) for row in rows]

    def get_context_messages(
        self,
        session_id: str,
        limit: int = MAX_CONTEXT_MESSAGES,
    ) -> List[Dict[str, str]]:
        messages = self.get_messages(
            session_id,
            limit=limit,
            roles=("user", "assistant"),
        )
        return [
            {"role": message["role"], "content": message["content"]}
            for message in messages
        ]

    def import_legacy_dialog(self, messages: Iterable[Dict[str, Any]]) -> Optional[str]:
        with self._lock:
            done = self._conn.execute(
                "SELECT value FROM session_meta WHERE key = 'legacy_dialog_imported'"
            ).fetchone()
        if done:
            return None
        normalized = [
            {
                "role": str(item.get("role") or "user"),
                "content": str(item.get("content") or "").strip(),
            }
            for item in messages
            if isinstance(item, dict) and str(item.get("content") or "").strip()
        ]
        imported_id: Optional[str] = None
        if normalized:
            imported = self.create_session("Импортированный диалог", source="migration")
            imported_id = imported["id"]
            for item in normalized:
                self.add_message(imported_id, item["role"], item["content"])
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO session_meta (key, value)
                VALUES ('legacy_dialog_imported', ?)
                """,
                (imported_id or "empty",),
            )
        return imported_id

    def close(self) -> None:
        with self._lock:
            self._conn.close()
