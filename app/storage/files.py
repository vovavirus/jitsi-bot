"""Файловая часть хранения: имена, санитизация, свободное место, путь к файлам."""
from __future__ import annotations

import re
import shutil
import time
import unicodedata
from pathlib import Path

from app.core.models import Task

# Разрешённые символы в пользовательском названии (кроме разделителей).
_ALLOWED = re.compile(r"[^0-9A-Za-zА-Яа-яЁё_\-]+")


def sanitize_name(name: str, max_len: int = 60) -> str:
    """Приводит пользовательское название к безопасному фрагменту имени файла.

    Убирает недопустимые символы, разделители каталогов и переходы по путям.
    """
    name = unicodedata.normalize("NFKC", name).strip()
    # Заменяем любые недопустимые последовательности символов на дефис.
    name = _ALLOWED.sub("-", name)
    # Схлопываем повторяющиеся дефисы/подчёркивания.
    name = re.sub(r"[-_]{2,}", "-", name).strip("-_")
    name = name[:max_len].strip("-_")
    return name or "recording"


def build_folder_name(task: Task, at: float | None = None) -> str:
    """Формирует уникальное имя папки записи: YYYY-MM-DD_HHMMSS_<slug>_<id>."""
    at = at if at is not None else time.time()
    stamp = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(at))
    slug = sanitize_name(task.name)
    return f"{stamp}_{slug}_{task.id}"


def free_space_bytes(path: Path) -> int:
    try:
        return shutil.disk_usage(path).free
    except FileNotFoundError:
        return 0


def gb(free_gb: float) -> int:
    return int(free_gb * 1024 * 1024 * 1024)


def has_enough_space(storage_dir: Path, min_free_gb: float) -> bool:
    return free_space_bytes(storage_dir) >= gb(min_free_gb)
