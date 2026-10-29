"""Модели задания: состояние, данные, сериализация."""
from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field


class TaskStatus(str, enum.Enum):
    CREATED = "created"
    SCHEDULED = "scheduled"
    CONNECTING = "connecting"
    RECORDING = "recording"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


#: Состояния, в которых задание занято (нельзя стартовать новое).
ACTIVE_STATUSES = {
    TaskStatus.CREATED,
    TaskStatus.SCHEDULED,
    TaskStatus.CONNECTING,
    TaskStatus.RECORDING,
    TaskStatus.FINALIZING,
}


#: Конечные состояния.
TERMINAL_STATUSES = {
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
    TaskStatus.INTERRUPTED,
}


@dataclass
class Task:
    url: str
    name: str
    bot_name: str
    max_duration_min: int
    # Момент начала (epoch). None — подключаться сразу.
    start_at: float | None = None

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: TaskStatus = TaskStatus.CREATED
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None      # фактическое начало записи (reconnecting)
    ended_at: float | None = None
    room: str | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

    # Результаты финализации.
    file_path: str | None = None
    file_size: int | None = None
    duration_s: float | None = None

    # Ссылки на вспомогательные файлы (относительно корня хранения).
    folder: str | None = None
    session_log_path: str | None = None
    metadata_path: str | None = None

    # Внутренние ссылки (не сериализуются в JSON).
    _stop_requested: bool = field(default=False, repr=False)
    _cancel_requested: bool = field(default=False, repr=False)
    _live_size: int = field(default=0, repr=False)
    # Слот ресурсов (свой X-дисплей + PulseAudio). None — не выделен.
    _slot: int | None = field(default=None, repr=False)

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def recording_seconds(self) -> float:
        """Текущая длительность записи (если идёт)."""
        if self.started_at is None:
            return 0.0
        end = self.ended_at if self.ended_at is not None else time.time()
        return max(0.0, end - self.started_at)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "name": self.name,
            "bot_name": self.bot_name,
            "max_duration_min": self.max_duration_min,
            "start_at": self.start_at,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "room": self.room,
            "error": self.error,
            "warnings": list(self.warnings),
            "file_path": self.file_path,
            "file_size": self.file_size,
            "duration_s": self.duration_s,
            "folder": self.folder,
            "session_log_path": self.session_log_path,
            "metadata_path": self.metadata_path,
            "live_duration_s": self.recording_seconds if self.is_active else None,
            "live_size": self._live_size if self.is_active else None,
        }

    @classmethod
    def from_row(cls, row: dict) -> "Task":
        return cls(
            url=row["url"],
            name=row["name"],
            bot_name=row["bot_name"],
            max_duration_min=row["max_duration_min"],
            start_at=row["start_at"],
            id=row["id"],
            status=TaskStatus(row["status"]),
            created_at=row["created_at"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            room=row["room"],
            error=row["error"],
            warnings=[],
            file_path=row["file_path"],
            file_size=row["file_size"],
            duration_s=row["duration_s"],
            folder=row["folder"],
            session_log_path=row["session_log_path"],
            metadata_path=row["metadata_path"],
        )
