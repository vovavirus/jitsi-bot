"""Управление изолированным аудиовыходом PulseAudio (захват звука)."""
from __future__ import annotations

import asyncio
import logging
import os

log = logging.getLogger("capture.audio")


class AudioSource:
    """Обёртка над виртуальным sink PulseAudio, куда пишется звук браузера."""

    def __init__(self, sink_name: str, pulse_server: str) -> None:
        self.sink_name = sink_name
        self.monitor_source = f"{sink_name}.monitor"
        self._pulse_server = pulse_server

    def _pactl(self, *args: str) -> list[str]:
        return ["pactl", *args]

    def _pulse_env(self) -> dict[str, str]:
        """Окружение для pactl/parec: свой инстанс PulseAudio слота."""
        env = dict(os.environ)
        env["PULSE_SERVER"] = self._pulse_server
        env["PULSE_RUNTIME_PATH"] = os.path.dirname(self._pulse_server)
        return env

    async def _run(self, args: list[str]) -> tuple[int, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=self._pulse_env(),
            )
        except FileNotFoundError:
            return 1, "pactl: не найден (PulseAudio не установлен)"
        out, _ = await proc.communicate()
        return proc.returncode or 0, out.decode("utf-8", "replace").strip()

    async def is_available(self) -> bool:
        """Проверяет, что sink существует."""
        code, out = await self._run(self._pactl("list", "sinks", "short"))
        if code != 0:
            return False
        return self.sink_name in out

    async def ensure(self) -> bool:
        """Добавляет sink при отсутствии и делает его дефолтным."""
        if not await self.is_available():
            code, out = await self._run(
                self._pactl(
                    "load-module",
                    "module-null-sink",
                    f"sink_name={self.sink_name}",
                    f"sink_properties=device.description=BotCaptureSink",
                )
            )
            if code != 0:
                log.error("Не удалось создать sink %s: %s", self.sink_name, out)
                return False
            log.info("Создан аудио-sink %s", self.sink_name)

        await self._run(self._pactl("set-default-sink", self.sink_name))
        return await self.is_available()

    def env(self) -> dict[str, str]:
        """Переменные окружения для Chromium, чтобы звук шёл в наш sink."""
        return self._pulse_env()

    @property
    def ffmpeg_input(self) -> str:
        # ffmpeg: захват monitor-источника sink (только звук, прошедший через него).
        return self.monitor_source
