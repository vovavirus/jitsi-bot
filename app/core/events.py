"""Простая pub/sub-шина для live-обновлений статусов (WebSocket)."""
from __future__ import annotations

import asyncio
from typing import Any


class EventBus:
    """Очередь событий, к которой подключаются WebSocket-клиенты."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def publish(self, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Медленный клиент — не роняем остальных.
                pass
