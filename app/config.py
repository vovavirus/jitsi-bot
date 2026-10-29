"""Загрузка конфигурации из YAML с переопределением через переменные окружения."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class VideoConfig:
    width: int = 1920
    height: int = 1080
    fps: int = 25


@dataclass
class AudioConfig:
    codec: str = "aac"
    bitrate: str = "128k"
    sample_rate: int = 48000


@dataclass
class AppConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    storage_dir: str = "/app/recordings"
    min_free_space_gb: float = 2.0
    connect_timeout_s: int = 120
    default_max_duration_min: int = 180
    default_bot_name: str = "Владимир Русин AI"
    display: str = ":99"
    pulse_sink: str = "botsink"
    pulse_socket: str = "/run/pulse/native"
    log_level: str = "INFO"
    # Сколько встреч можно записывать одновременно.
    # Каждый слот — свой X-дисплей, свой PulseAudio и свой sink.
    max_concurrent_recordings: int = 3
    video: VideoConfig = field(default_factory=VideoConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)

    # ------------------------------------------------------- слоты ресурсов
    def _base_display_num(self) -> int:
        return int(self.display.lstrip(":").split(".")[0] or 99)

    def display_for_slot(self, slot: int) -> str:
        """X-дисплей слота: :99, :100, :101..."""
        return f":{self._base_display_num() + slot}"

    def pulse_socket_for_slot(self, slot: int) -> str:
        """Сокет PulseAudio-инстанса слота.

        Слот 0: /run/pulse/native; слот i: /run/pulse{i}/native.
        Поддерживается базовый сокет вида <prefix>/pulse/native
        (как в docker-compose).
        """
        if slot == 0:
            return self.pulse_socket
        suffix = "/pulse/native"
        if self.pulse_socket.endswith(suffix):
            return self.pulse_socket[: -len(suffix)] + f"/pulse{slot}/native"
        # Нестандартный сокет: кладём инстанс рядом с базовым.
        parent, _, name = self.pulse_socket.rpartition("/")
        return f"{parent}/pulse{slot}/{name}"

    def sink_for_slot(self, slot: int) -> str:
        """Имя null-sink слота: botsink, botsink1, botsink2..."""
        return self.pulse_sink if slot == 0 else f"{self.pulse_sink}{slot}"

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> "AppConfig":
        """Создаёт конфигурацию: значения по умолчанию -> YAML -> env."""
        data: dict[str, Any] = {}
        candidates = [
            Path(path) if path else None,
            Path("/app/config.yaml"),
            Path("config.yaml"),
        ]
        for candidate in candidates:
            if candidate and candidate.is_file():
                with open(candidate, "r", encoding="utf-8") as fh:
                    loaded = yaml.safe_load(fh) or {}
                if isinstance(loaded, dict):
                    data = loaded
                break

        video = VideoConfig(**{**data.get("video", {})})
        audio = AudioConfig(**{**data.get("audio", {})})

        cfg = cls(
            host=_env_str("HOST", data.get("host", cls.host)),
            port=_env_int("PORT", data.get("port", cls.port)),
            storage_dir=_env_str("STORAGE_DIR", data.get("storage_dir", cls.storage_dir)),
            min_free_space_gb=_env_float(
                "MIN_FREE_SPACE_GB", data.get("min_free_space_gb", cls.min_free_space_gb)
            ),
            connect_timeout_s=_env_int(
                "CONNECT_TIMEOUT_S", data.get("connect_timeout_s", cls.connect_timeout_s)
            ),
            default_max_duration_min=_env_int(
                "DEFAULT_MAX_DURATION_MIN",
                data.get("default_max_duration_min", cls.default_max_duration_min),
            ),
            default_bot_name=_env_str(
                "DEFAULT_BOT_NAME", data.get("default_bot_name", cls.default_bot_name)
            ),
            display=_env_str("DISPLAY", data.get("display", cls.display)),
            pulse_sink=_env_str("PULSE_SINK", data.get("pulse_sink", cls.pulse_sink)),
            pulse_socket=_env_str("PULSE_SOCKET", data.get("pulse_socket", cls.pulse_socket)),
            log_level=_env_str("LOG_LEVEL", data.get("log_level", cls.log_level)).upper(),
            max_concurrent_recordings=_env_int(
                "MAX_CONCURRENT_RECORDINGS",
                data.get("max_concurrent_recordings", cls.max_concurrent_recordings),
            ),
            video=video,
            audio=audio,
        )
        Path(cfg.storage_dir).mkdir(parents=True, exist_ok=True)
        return cfg


def _env_str(name: str, default: Any) -> str:
    value = os.environ.get(name)
    return str(value) if value not in (None, "") else str(default)


def _env_int(name: str, default: Any) -> int:
    value = os.environ.get(name)
    return int(value) if value not in (None, "") else int(default)


def _env_float(name: str, default: Any) -> float:
    value = os.environ.get(name)
    return float(value) if value not in (None, "") else float(default)
