from __future__ import annotations

import base64
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import unquote, urlparse

from services.config import BASE_DIR
from services.image_storage_service import image_storage_service

DEFAULT_IMAGE_CONVERSATIONS_DB = BASE_DIR / "state" / "image_conversations.db"
IMAGE_FILE_RETENTION_DAYS = 7


class ImageConversationAccessError(RuntimeError):
    pass


class ImageConversationNotFound(RuntimeError):
    pass


def _db_path() -> Path:
    raw = os.getenv("IMAGE_CONVERSATIONS_DB_PATH", "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_IMAGE_CONVERSATIONS_DB


def _clean(value: object, default: str = "") -> str:
    return str(value or default).strip()


def _owner_id(identity: dict[str, object]) -> str:
    return _clean(identity.get("id")) or "anonymous"


def _is_admin(identity: dict[str, object]) -> bool:
    return identity.get("role") == "admin"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _timestamp(value: object) -> float:
    raw = _clean(value)
    if not raw:
        return 0.0
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw[:26], fmt).timestamp()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _plus_days_iso(value: object, days: int = IMAGE_FILE_RETENTION_DAYS) -> datetime:
    base_ts = _timestamp(value) or time.time()
    return datetime.fromtimestamp(base_ts).replace(microsecond=0) + timedelta(days=days)


def _format_iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _bool(value: object) -> int:
    return 1 if value is True or value == 1 else 0


def _frontend_bool(value: object) -> bool:
    return value is True or value == 1


def _extract_rel_from_url(url: object) -> str:
    raw = _clean(url)
    if not raw:
        return ""
    try:
        path = unquote(urlparse(raw).path)
    except Exception:
        path = raw
    marker = "/images/"
    if marker not in path:
        return ""
    return path.split(marker, 1)[1].strip("/")


def _decode_data_url(data_url: str) -> bytes | None:
    match = re.match(r"^data:[^;]+;base64,(.+)$", data_url, flags=re.DOTALL)
    if not match:
        return None
    try:
        return base64.b64decode(match.group(1), validate=False)
    except Exception:
        return None


def _data_url_mime_type(data_url: str) -> str:
    match = re.match(r"^data:([^;]+);base64,", data_url)
    return match.group(1) if match else "image/png"


def _public_url(rel: str, base_url: str) -> str:
    if not rel:
        return ""
    return image_storage_service._public_url(rel, base_url)  # reuse storage settings/public base URL


class ImageConversationService:
    def __init__(self, path: Path | None = None):
        self.path = path or _db_path()
        self._lock = RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _db(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock, self._db() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS image_conversations (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_image_conversations_owner_updated
                    ON image_conversations(owner_id, deleted_at, updated_at);

                CREATE TABLE IF NOT EXISTS image_conversation_turns (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    order_index INTEGER NOT NULL,
                    prompt TEXT NOT NULL,
                    model TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    count INTEGER NOT NULL,
                    size TEXT NOT NULL,
                    ratio TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    quality TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    prompt_deleted INTEGER NOT NULL DEFAULT 0,
                    results_deleted INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_image_turns_conversation
                    ON image_conversation_turns(conversation_id, order_index);

                CREATE TABLE IF NOT EXISTS image_conversation_images (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    order_index INTEGER NOT NULL,
                    task_id TEXT,
                    status TEXT NOT NULL,
                    task_status TEXT,
                    progress TEXT,
                    rel TEXT,
                    url TEXT,
                    revised_prompt TEXT,
                    error TEXT,
                    start_time REAL,
                    elapsed_secs REAL,
                    elapsed_updated_at REAL,
                    duration_ms INTEGER,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    expired_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_image_conversation_images_conversation
                    ON image_conversation_images(conversation_id, turn_id, order_index);
                CREATE INDEX IF NOT EXISTS idx_image_conversation_images_task
                    ON image_conversation_images(owner_id, task_id);
                CREATE INDEX IF NOT EXISTS idx_image_conversation_images_expiry
                    ON image_conversation_images(expired_at, expires_at);

                CREATE TABLE IF NOT EXISTS image_conversation_references (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    order_index INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    rel TEXT,
                    url TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    expired_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_image_conversation_refs_conversation
                    ON image_conversation_references(conversation_id, turn_id, order_index);
                CREATE INDEX IF NOT EXISTS idx_image_conversation_refs_expiry
                    ON image_conversation_references(expired_at, expires_at);
                """
            )

    def list_conversations(self, identity: dict[str, object], *, include_all: bool = False, base_url: str = "") -> dict[str, object]:
        with self._lock:
            self.expire_old_images()
            owner = _owner_id(identity)
            with self._db() as conn:
                if include_all and _is_admin(identity):
                    rows = conn.execute(
                        "SELECT * FROM image_conversations WHERE deleted_at IS NULL ORDER BY updated_at DESC"
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT * FROM image_conversations
                        WHERE owner_id = ? AND deleted_at IS NULL
                        ORDER BY updated_at DESC
                        """,
                        (owner,),
                    ).fetchall()
                return {"items": [self._serialize_conversation(conn, row, base_url) for row in rows]}

    def upsert_conversation(
        self,
        identity: dict[str, object],
        conversation_id: str,
        conversation: dict[str, Any],
        *,
        base_url: str = "",
    ) -> dict[str, object]:
        source = conversation.get("conversation") if isinstance(conversation.get("conversation"), dict) else conversation
        if not isinstance(source, dict):
            raise ValueError("conversation is required")
        conv_id = _clean(source.get("id")) or _clean(conversation_id)
        if not conv_id or conv_id != _clean(conversation_id):
            raise ValueError("conversation id mismatch")

        now = _now_iso()
        owner = _owner_id(identity)
        with self._lock, self._db() as conn:
            existing = conn.execute("SELECT * FROM image_conversations WHERE id = ?", (conv_id,)).fetchone()
            if existing is not None:
                owner = str(existing["owner_id"])
                if owner != _owner_id(identity) and not _is_admin(identity):
                    raise ImageConversationAccessError("no permission to update conversation")

            created_at = _clean(source.get("createdAt"), now)
            updated_at = _clean(source.get("updatedAt"), now)
            title = _clean(source.get("title")) or self._derive_title(source)

            conn.execute(
                """
                INSERT INTO image_conversations(id, owner_id, title, created_at, updated_at, deleted_at)
                VALUES (?, ?, ?, ?, ?, NULL)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    updated_at = excluded.updated_at,
                    deleted_at = NULL
                """,
                (conv_id, owner, title, created_at, updated_at),
            )
            conn.execute("DELETE FROM image_conversation_turns WHERE conversation_id = ?", (conv_id,))
            conn.execute("DELETE FROM image_conversation_images WHERE conversation_id = ?", (conv_id,))
            conn.execute("DELETE FROM image_conversation_references WHERE conversation_id = ?", (conv_id,))

            turns = source.get("turns") if isinstance(source.get("turns"), list) else []
            for turn_index, raw_turn in enumerate(turns):
                if not isinstance(raw_turn, dict):
                    continue
                turn = self._normalize_turn(raw_turn, turn_index, conv_id, owner, now)
                conn.execute(
                    """
                    INSERT INTO image_conversation_turns(
                        id, conversation_id, owner_id, order_index, prompt, model, mode,
                        count, size, ratio, tier, quality, created_at, status, error,
                        prompt_deleted, results_deleted
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        turn["id"],
                        conv_id,
                        owner,
                        turn_index,
                        turn["prompt"],
                        turn["model"],
                        turn["mode"],
                        turn["count"],
                        turn["size"],
                        turn["ratio"],
                        turn["tier"],
                        turn["quality"],
                        turn["created_at"],
                        turn["status"],
                        turn["error"],
                        turn["prompt_deleted"],
                        turn["results_deleted"],
                    ),
                )
                for image_index, raw_image in enumerate(raw_turn.get("images") if isinstance(raw_turn.get("images"), list) else []):
                    if not isinstance(raw_image, dict):
                        continue
                    image = self._normalize_image(raw_image, image_index, conv_id, turn["id"], owner, turn["created_at"], base_url)
                    conn.execute(
                        """
                        INSERT INTO image_conversation_images(
                            id, conversation_id, turn_id, owner_id, order_index, task_id,
                            status, task_status, progress, rel, url, revised_prompt, error,
                            start_time, elapsed_secs, elapsed_updated_at, duration_ms,
                            created_at, expires_at, expired_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            image["id"],
                            conv_id,
                            turn["id"],
                            owner,
                            image_index,
                            image["task_id"],
                            image["status"],
                            image["task_status"],
                            image["progress"],
                            image["rel"],
                            image["url"],
                            image["revised_prompt"],
                            image["error"],
                            image["start_time"],
                            image["elapsed_secs"],
                            image["elapsed_updated_at"],
                            image["duration_ms"],
                            image["created_at"],
                            image["expires_at"],
                            image["expired_at"],
                        ),
                    )
                for ref_index, raw_ref in enumerate(raw_turn.get("referenceImages") if isinstance(raw_turn.get("referenceImages"), list) else []):
                    if not isinstance(raw_ref, dict):
                        continue
                    ref = self._normalize_reference(raw_ref, ref_index, conv_id, turn["id"], owner, turn["created_at"], base_url)
                    if ref is None:
                        continue
                    conn.execute(
                        """
                        INSERT INTO image_conversation_references(
                            id, conversation_id, turn_id, owner_id, order_index,
                            name, type, rel, url, created_at, expires_at, expired_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            ref["id"],
                            conv_id,
                            turn["id"],
                            owner,
                            ref_index,
                            ref["name"],
                            ref["type"],
                            ref["rel"],
                            ref["url"],
                            ref["created_at"],
                            ref["expires_at"],
                            ref["expired_at"],
                        ),
                    )

            row = conn.execute("SELECT * FROM image_conversations WHERE id = ?", (conv_id,)).fetchone()
            return {"item": self._serialize_conversation(conn, row, base_url)}

    def rename_conversation(self, identity: dict[str, object], conversation_id: str, title: str, *, base_url: str = "") -> dict[str, object]:
        clean_title = _clean(title)
        if not clean_title:
            raise ValueError("title is required")
        with self._lock, self._db() as conn:
            row = self._require_conversation(conn, identity, conversation_id)
            conn.execute(
                "UPDATE image_conversations SET title = ?, updated_at = ? WHERE id = ?",
                (clean_title, _now_iso(), row["id"]),
            )
            next_row = conn.execute("SELECT * FROM image_conversations WHERE id = ?", (row["id"],)).fetchone()
            return {"item": self._serialize_conversation(conn, next_row, base_url)}

    def delete_conversation(self, identity: dict[str, object], conversation_id: str) -> dict[str, object]:
        with self._lock, self._db() as conn:
            row = self._require_conversation(conn, identity, conversation_id)
            conn.execute("UPDATE image_conversations SET deleted_at = ?, updated_at = ? WHERE id = ?", (_now_iso(), _now_iso(), row["id"]))
            return {"ok": True}

    def clear_conversations(self, identity: dict[str, object]) -> dict[str, object]:
        owner = _owner_id(identity)
        with self._lock, self._db() as conn:
            now = _now_iso()
            cursor = conn.execute(
                "UPDATE image_conversations SET deleted_at = ?, updated_at = ? WHERE owner_id = ? AND deleted_at IS NULL",
                (now, now, owner),
            )
            return {"ok": True, "removed": cursor.rowcount}

    def download_paths(self, identity: dict[str, object], conversation_id: str, image_ids: list[str] | None = None) -> list[str]:
        requested = {item for item in (_clean(value) for value in (image_ids or [])) if item}
        self.expire_old_images()
        with self._lock, self._db() as conn:
            row = self._require_conversation(conn, identity, conversation_id)
            params: list[object] = [row["id"]]
            sql = """
                SELECT id, rel FROM image_conversation_images
                WHERE conversation_id = ?
                  AND status = 'success'
                  AND rel IS NOT NULL
                  AND rel != ''
                  AND expired_at IS NULL
            """
            if requested:
                sql += f" AND id IN ({','.join('?' for _ in requested)})"
                params.extend(sorted(requested))
            rows = conn.execute(sql, params).fetchall()
            paths = []
            for item in rows:
                rel = _clean(item["rel"])
                if rel and image_storage_service.exists(rel):
                    paths.append(rel)
            return paths

    def record_task_result(
        self,
        identity: dict[str, object],
        task: dict[str, Any],
        data: list[Any],
        *,
        error: str = "",
        base_url: str = "",
    ) -> None:
        conversation_id = _clean(task.get("conversation_id"))
        turn_id = _clean(task.get("turn_id"))
        image_id = _clean(task.get("image_id"))
        task_id = _clean(task.get("id"))
        if not conversation_id or not turn_id or not image_id:
            return
        owner = _owner_id(identity)
        with self._lock, self._db() as conn:
            row = conn.execute("SELECT * FROM image_conversations WHERE id = ?", (conversation_id,)).fetchone()
            if row is None or (row["owner_id"] != owner and not _is_admin(identity)):
                return

            first = data[0] if data and isinstance(data[0], dict) else {}
            rel, url, created_at = self._resolve_generated_image(owner, task_id, first, base_url)
            expires_at = _format_iso(_plus_days_iso(created_at or task.get("updated_at") or _now_iso()))
            status = "error" if error else "success"
            conn.execute(
                """
                UPDATE image_conversation_images
                SET task_id = ?, status = ?, task_status = NULL, progress = NULL,
                    rel = COALESCE(NULLIF(?, ''), rel),
                    url = COALESCE(NULLIF(?, ''), url),
                    revised_prompt = COALESCE(NULLIF(?, ''), revised_prompt),
                    error = ?, duration_ms = ?, expires_at = COALESCE(expires_at, ?),
                    expired_at = expired_at
                WHERE conversation_id = ? AND turn_id = ? AND id = ?
                """,
                (
                    task_id,
                    status,
                    rel,
                    url or _clean(first.get("url")),
                    _clean(first.get("revised_prompt")),
                    error,
                    task.get("duration_ms") if isinstance(task.get("duration_ms"), int) else None,
                    expires_at,
                    conversation_id,
                    turn_id,
                    image_id,
                ),
            )
            self._refresh_turn_status(conn, conversation_id, turn_id)
            self._touch_conversation(conn, conversation_id)

    def expire_old_images(self) -> dict[str, int]:
        now = time.time()
        expired_images = 0
        expired_refs = 0
        with self._lock, self._db() as conn:
            image_rows = conn.execute(
                """
                SELECT id, rel, expires_at FROM image_conversation_images
                WHERE expired_at IS NULL AND rel IS NOT NULL AND rel != ''
                """
            ).fetchall()
            for row in image_rows:
                rel = _clean(row["rel"])
                due = _timestamp(row["expires_at"]) > 0 and _timestamp(row["expires_at"]) <= now
                missing = bool(rel and not image_storage_service.exists(rel))
                if not due and not missing:
                    continue
                if due:
                    try:
                        image_storage_service.delete(rel)
                    except Exception:
                        pass
                conn.execute("UPDATE image_conversation_images SET expired_at = ? WHERE id = ?", (_now_iso(), row["id"]))
                expired_images += 1

            ref_rows = conn.execute(
                """
                SELECT id, rel, expires_at FROM image_conversation_references
                WHERE expired_at IS NULL AND rel IS NOT NULL AND rel != ''
                """
            ).fetchall()
            for row in ref_rows:
                rel = _clean(row["rel"])
                due = _timestamp(row["expires_at"]) > 0 and _timestamp(row["expires_at"]) <= now
                missing = bool(rel and not image_storage_service.exists(rel))
                if not due and not missing:
                    continue
                if due:
                    try:
                        image_storage_service.delete(rel)
                    except Exception:
                        pass
                conn.execute("UPDATE image_conversation_references SET expired_at = ? WHERE id = ?", (_now_iso(), row["id"]))
                expired_refs += 1
        return {"images": expired_images, "references": expired_refs}

    def _derive_title(self, conversation: dict[str, Any]) -> str:
        turns = conversation.get("turns") if isinstance(conversation.get("turns"), list) else []
        for turn in turns:
            if isinstance(turn, dict):
                prompt = _clean(turn.get("prompt"))
                if prompt:
                    return prompt[:12] + ("..." if len(prompt) > 12 else "")
        return "未命名对话"

    def _normalize_turn(self, turn: dict[str, Any], index: int, conversation_id: str, owner: str, now: str) -> dict[str, object]:
        return {
            "id": _clean(turn.get("id"), f"{conversation_id}-turn-{index}"),
            "prompt": _clean(turn.get("prompt")),
            "model": _clean(turn.get("model"), "gpt-image-2"),
            "mode": "edit" if turn.get("mode") == "edit" else "generate",
            "count": max(1, int(turn.get("count") or 1)),
            "size": _clean(turn.get("size")),
            "ratio": _clean(turn.get("ratio"), "1:1"),
            "tier": _clean(turn.get("tier"), "1k"),
            "quality": _clean(turn.get("quality"), "auto"),
            "created_at": _clean(turn.get("createdAt"), now),
            "status": _clean(turn.get("status"), "success"),
            "error": _clean(turn.get("error")) or None,
            "prompt_deleted": _bool(turn.get("promptDeleted")),
            "results_deleted": _bool(turn.get("resultsDeleted")),
        }

    def _normalize_image(
        self,
        image: dict[str, Any],
        index: int,
        conversation_id: str,
        turn_id: str,
        owner: str,
        turn_created_at: str,
        base_url: str,
    ) -> dict[str, object]:
        image_id = _clean(image.get("id"), f"{turn_id}-{index}")
        task_id = _clean(image.get("taskId"))
        rel, url, image_created_at = self._resolve_generated_image(owner, task_id, image, base_url)
        created_at = _clean(image.get("createdAt"), image_created_at or turn_created_at)
        expires_at = _clean(image.get("expiresAt")) or _format_iso(_plus_days_iso(created_at))
        expired_at = _clean(image.get("expiredAt"))
        expired = _frontend_bool(image.get("expired")) or bool(expired_at)
        if rel and not image_storage_service.exists(rel):
            expired = True
        return {
            "id": image_id,
            "task_id": task_id or None,
            "status": _clean(image.get("status"), "success" if url or rel else "loading"),
            "task_status": _clean(image.get("taskStatus")) or None,
            "progress": _clean(image.get("progress")) or None,
            "rel": rel or None,
            "url": url or _clean(image.get("url")) or None,
            "revised_prompt": _clean(image.get("revised_prompt")) or None,
            "error": _clean(image.get("error")) or None,
            "start_time": image.get("startTime") if isinstance(image.get("startTime"), (int, float)) else None,
            "elapsed_secs": image.get("elapsedSecs") if isinstance(image.get("elapsedSecs"), (int, float)) else None,
            "elapsed_updated_at": image.get("elapsedUpdatedAt") if isinstance(image.get("elapsedUpdatedAt"), (int, float)) else None,
            "duration_ms": image.get("durationMs") if isinstance(image.get("durationMs"), int) else None,
            "created_at": created_at,
            "expires_at": expires_at,
            "expired_at": expired_at or (_now_iso() if expired else None),
        }

    def _normalize_reference(
        self,
        ref: dict[str, Any],
        index: int,
        conversation_id: str,
        turn_id: str,
        owner: str,
        turn_created_at: str,
        base_url: str,
    ) -> dict[str, object] | None:
        rel = _clean(ref.get("rel")) or _extract_rel_from_url(ref.get("url"))
        url = _clean(ref.get("url"))
        created_at = _clean(ref.get("createdAt"), turn_created_at)
        if not rel:
            data_url = _clean(ref.get("dataUrl"))
            payload = _decode_data_url(data_url) if data_url else None
            if payload:
                stored = image_storage_service.save(
                    payload,
                    base_url,
                    metadata={
                        "owner_id": owner,
                        "conversation_id": conversation_id,
                        "turn_id": turn_id,
                        "kind": "reference",
                    },
                )
                rel = stored.rel
                url = stored.url
                created_at = _now_iso()
        if not rel and not url:
            return None
        expires_at = _clean(ref.get("expiresAt")) or _format_iso(_plus_days_iso(created_at))
        expired_at = _clean(ref.get("expiredAt"))
        expired = _frontend_bool(ref.get("expired")) or bool(expired_at)
        if rel and not image_storage_service.exists(rel):
            expired = True
        return {
            "id": f"{turn_id}-ref-{index}",
            "name": _clean(ref.get("name"), f"reference-{index + 1}.png"),
            "type": _clean(ref.get("type"), _data_url_mime_type(_clean(ref.get("dataUrl")))),
            "rel": rel or None,
            "url": url or (_public_url(rel, base_url) if rel else None),
            "created_at": created_at,
            "expires_at": expires_at,
            "expired_at": expired_at or (_now_iso() if expired else None),
        }

    def _resolve_generated_image(self, owner: str, task_id: str, image: dict[str, Any], base_url: str) -> tuple[str, str, str]:
        rel = _clean(image.get("rel")) or _clean(image.get("path")) or _extract_rel_from_url(image.get("url"))
        url = _clean(image.get("url"))
        created_at = _clean(image.get("createdAt"))
        if task_id:
            try:
                items = image_storage_service.list_task_items(owner, task_id, base_url)
            except Exception:
                items = []
            if items:
                item = items[0]
                rel = rel or _clean(item.get("rel")) or _clean(item.get("path"))
                url = url or _clean(item.get("url"))
                created_at = created_at or _clean(item.get("created_at"))
        if rel and not url:
            url = _public_url(rel, base_url)
        return rel, url, created_at

    def _serialize_conversation(self, conn: sqlite3.Connection, row: sqlite3.Row | None, base_url: str) -> dict[str, object]:
        if row is None:
            raise ImageConversationNotFound("conversation not found")
        turns = conn.execute(
            "SELECT * FROM image_conversation_turns WHERE conversation_id = ? ORDER BY order_index ASC",
            (row["id"],),
        ).fetchall()
        return {
            "id": row["id"],
            "ownerId": row["owner_id"],
            "title": row["title"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "turns": [self._serialize_turn(conn, turn, base_url) for turn in turns],
        }

    def _serialize_turn(self, conn: sqlite3.Connection, turn: sqlite3.Row, base_url: str) -> dict[str, object]:
        images = conn.execute(
            "SELECT * FROM image_conversation_images WHERE turn_id = ? ORDER BY order_index ASC",
            (turn["id"],),
        ).fetchall()
        refs = conn.execute(
            "SELECT * FROM image_conversation_references WHERE turn_id = ? ORDER BY order_index ASC",
            (turn["id"],),
        ).fetchall()
        return {
            "id": turn["id"],
            "prompt": turn["prompt"],
            "model": turn["model"],
            "mode": turn["mode"],
            "referenceImages": [self._serialize_reference(ref, base_url) for ref in refs],
            "count": turn["count"],
            "size": turn["size"],
            "ratio": turn["ratio"],
            "tier": turn["tier"],
            "quality": turn["quality"],
            "images": [self._serialize_image(image, base_url) for image in images],
            "createdAt": turn["created_at"],
            "status": turn["status"],
            **({"error": turn["error"]} if turn["error"] else {}),
            **({"promptDeleted": True} if turn["prompt_deleted"] else {}),
            **({"resultsDeleted": True} if turn["results_deleted"] else {}),
        }

    def _serialize_image(self, row: sqlite3.Row, base_url: str) -> dict[str, object]:
        expired = bool(row["expired_at"])
        rel = _clean(row["rel"])
        url = "" if expired else (_clean(row["url"]) or (_public_url(rel, base_url) if rel else ""))
        item: dict[str, object] = {
            "id": row["id"],
            "status": row["status"],
            "expired": expired,
            "expiresAt": row["expires_at"],
        }
        optional = {
            "taskId": row["task_id"],
            "taskStatus": row["task_status"],
            "progress": row["progress"],
            "rel": rel or None,
            "url": url or None,
            "revised_prompt": row["revised_prompt"],
            "error": "图片已过期" if expired else row["error"],
            "startTime": row["start_time"],
            "elapsedSecs": row["elapsed_secs"],
            "elapsedUpdatedAt": row["elapsed_updated_at"],
            "durationMs": row["duration_ms"],
        }
        item.update({key: value for key, value in optional.items() if value not in {None, ""}})
        return item

    def _serialize_reference(self, row: sqlite3.Row, base_url: str) -> dict[str, object]:
        expired = bool(row["expired_at"])
        rel = _clean(row["rel"])
        url = "" if expired else (_clean(row["url"]) or (_public_url(rel, base_url) if rel else ""))
        return {
            "name": row["name"],
            "type": row["type"],
            "expired": expired,
            "expiresAt": row["expires_at"],
            **({"rel": rel} if rel else {}),
            **({"url": url} if url else {}),
        }

    def _require_conversation(self, conn: sqlite3.Connection, identity: dict[str, object], conversation_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM image_conversations WHERE id = ? AND deleted_at IS NULL",
            (_clean(conversation_id),),
        ).fetchone()
        if row is None:
            raise ImageConversationNotFound("conversation not found")
        if row["owner_id"] != _owner_id(identity) and not _is_admin(identity):
            raise ImageConversationAccessError("no permission to access conversation")
        return row

    def _refresh_turn_status(self, conn: sqlite3.Connection, conversation_id: str, turn_id: str) -> None:
        rows = conn.execute(
            "SELECT status FROM image_conversation_images WHERE conversation_id = ? AND turn_id = ?",
            (conversation_id, turn_id),
        ).fetchall()
        statuses = [str(row["status"]) for row in rows]
        if not statuses:
            status = "success"
            error = None
        elif any(status == "loading" for status in statuses):
            status = "generating"
            error = None
        elif any(status == "error" for status in statuses):
            failed = sum(1 for item in statuses if item == "error")
            status = "error"
            error = f"其中 {failed} 张未成功生成"
        else:
            status = "success"
            error = None
        conn.execute(
            "UPDATE image_conversation_turns SET status = ?, error = ? WHERE conversation_id = ? AND id = ?",
            (status, error, conversation_id, turn_id),
        )

    def _touch_conversation(self, conn: sqlite3.Connection, conversation_id: str) -> None:
        conn.execute("UPDATE image_conversations SET updated_at = ? WHERE id = ?", (_now_iso(), conversation_id))


image_conversation_service = ImageConversationService()
