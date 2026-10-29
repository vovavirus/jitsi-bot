"""Управление виртуальным экраном Xvfb (захват видео)."""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("capture.video")


class VideoSource:
    """Обёртка над Xvfb-дисплеем, на котором рисуется окно браузера."""

    def __init__(self, display: str) -> None:
        self.display = display

    async def is_available(self) -> bool:
        """Проверяет, что X-дисплей отвечает (xset q)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "xset", "-display", self.display, "q",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            return proc.returncode == 0
        except FileNotFoundError:
            log.warning("xset не найден; пропускаю проверку дисплея")
            return True

    @property
    def ffmpeg_input(self) -> str:
        # ffmpeg x11grab принимает дисплей в виде ":99.0".
        return f"{self.display}.0"
