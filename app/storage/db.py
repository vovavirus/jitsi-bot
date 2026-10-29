"""История и состояния заданий в SQLite."""
from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

from app.core.models import Task

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id                 TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    url                TEXT NOT NULL,
    bot_name           TEXT NOT NULL,
    max_duration_min   INTEGER NOT NULL,
    start_at           REAL,
    status             TEXT NOT NULL,
    created_at         REAL NOT NULL,
    started_at         REAL,
    ended_at           REAL,
    room               TEXT,
    error              TEXT,
    warnings_json      TEXT,
    file_path          TEXT,
    file_size          INTEGER,
    duration_s         REAL,
    folder             TEXT,
    session_log_path   TEXT,
    metadata_path      TEXT
);
"""


class TaskRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def _connect(self) -> aiosqlite.Connection:
        # Возвращаем awaitable-соединение; использовать как
        # `async with self._connect() as conn:`.
        return aiosqlite.connect(self._db_path)

    async def init(self) -> None:
        async with self._connect() as conn:
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_SCHEMA)
            await conn.commit()
            # Простая миграция для старых баз без колонки start_at.
            cursor = await conn.execute("PRAGMA table_info(tasks)")
            cols = {row[1] for row in await cursor.fetchall()}
            if "start_at" not in cols:
                await conn.execute("ALTER TABLE tasks ADD COLUMN start_at REAL")
                await conn.commit()

    async def save(self, task: Task) -> None:
        async with self._connect() as conn:
            await conn.execute(
                """
                INSERT INTO tasks (
                    id, name, url, bot_name, max_duration_min, start_at, status,
                    created_at, started_at, ended_at, room, error, warnings_json,
                    file_path, file_size, duration_s, folder, session_log_path,
                    metadata_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    url=excluded.url,
                    bot_name=excluded.bot_name,
                    max_duration_min=excluded.max_duration_min,
                    start_at=excluded.start_at,
                    status=excluded.status,
                    created_at=excluded.created_at,
                    started_at=excluded.started_at,
                    ended_at=excluded.ended_at,
                    room=excluded.room,
                    error=excluded.error,
                    warnings_json=excluded.warnings_json,
                    file_path=excluded.file_path,
                    file_size=excluded.file_size,
                    duration_s=excluded.duration_s,
                    folder=excluded.folder,
                    session_log_path=excluded.session_log_path,
                    metadata_path=excluded.metadata_path
                """,
                (
                    task.id,
                    task.name,
                    task.url,
                    task.bot_name,
                    task.max_duration_min,
                    task.start_at,
                    task.status.value,
                    task.created_at,
                    task.started_at,
                    task.ended_at,
                    task.room,
                    task.error,
                    json.dumps(task.warnings, ensure_ascii=False),
                    task.file_path,
                    task.file_size,
                    task.duration_s,
                    task.folder,
                    task.session_log_path,
                    task.metadata_path,
                ),
            )
            await conn.commit()

    async def list(self, limit: int = 100) -> list[dict]:
        async with self._connect() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
            )
            rows = await cursor.fetchall()
        return [self._row_to_dict(r) for r in rows]

    async def get(self, task_id: str) -> dict | None:
        async with self._connect() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    async def mark_interrupted(self) -> int:
        """При старте приложения: пометить незавершённые задания как прерванные."""
        async with self._connect() as conn:
            cursor = await conn.execute(
                """
                UPDATE tasks SET status = ?
                WHERE status IN ('created', 'scheduled', 'connecting', 'recording', 'finalizing')
                """,
                ("interrupted",),
            )
            await conn.commit()
            return cursor.rowcount or 0

    @staticmethod
    def _row_to_dict(row: aiosqlite.Row) -> dict:
        d = dict(row)
        try:
            d["warnings"] = json.loads(d.pop("warnings_json") or "[]")
        except (ValueError, KeyError):
            d["warnings"] = []
            d.pop("warnings_json", None)
        return d
