"""FFmpeg-рекордер: захват видео+аудио в MKV, финализация в MP4, проверка."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from pathlib import Path

from app.capture.audio import AudioSource
from app.capture.video import VideoSource
from app.config import AppConfig

log = logging.getLogger("capture.recorder")


class RecorderError(RuntimeError):
    pass


class Recorder:
    """Управляет одним процессом FFmpeg для одной записи."""

    def __init__(
        self,
        cfg: AppConfig,
        video: VideoSource,
        audio: AudioSource,
        out_dir: Path,
        session_log_path: Path,
    ) -> None:
        self.cfg = cfg
        self.video = video
        self.audio = audio
        self.out_dir = out_dir
        self.session_log_path = session_log_path

        self.mkv_path = out_dir / "recording.mkv"
        self.mp4_path = out_dir / "recording.mp4"

        self._proc: asyncio.subprocess.Process | None = None
        self._log_fh: object | None = None

    # ------------------------------------------------------------------ start
    async def start(self) -> None:
        out_dir = self.out_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        env = self.audio.env()
        env["DISPLAY"] = self.video.display

        width = self.cfg.video.width
        height = self.cfg.video.height
        fps = self.cfg.video.fps
        sr = self.cfg.audio.sample_rate

        # Аудио: parec записывает monitor-источник изолированного sink в raw PCM
        # и передаёт его в stdin ffmpeg. parec из pulseaudio-utils — надёжнее,
        # чем ffmpeg-демультиплексор pulse, который есть не во всех сборках.
        parec = (
            f"parec --device={self.audio.ffmpeg_input} "
            f"--format=s16le --channels=2 --rate={sr}"
        )
        ffmpeg = (
            f"ffmpeg -hide_banner -loglevel warning "
            f"-f x11grab -video_size {width}x{height} -framerate {fps} "
            f"-i {self.video.ffmpeg_input} "
            f"-f s16le -ar {sr} -ac 2 -i pipe:0 "
            f"-map 0:v:0 -map 1:a:0 "
            f"-c:v libx264 -preset veryfast -tune zerolatency -pix_fmt yuv420p "
            f"-g {fps * 2} "
            f"-c:a {self.cfg.audio.codec} -b:a {self.cfg.audio.bitrate} "
            f"-f matroska {self.mkv_path}"
        )
        full_cmd = f"{parec} | {ffmpeg}"

        self._log_fh = open(self.session_log_path, "a", encoding="utf-8")
        log.info("Старт захвата: %s", full_cmd)
        self._proc = await asyncio.create_subprocess_exec(
            "sh", "-c", full_cmd,
            stdout=self._log_fh,
            stderr=self._log_fh,
            env=env,
            start_new_session=True,
        )

        # Даем захвату время подняться; если он сразу упал — запись не стартовала.
        await asyncio.sleep(1.5)
        if self._proc.returncode is not None:
            self._append_log(
                f"Процесс захвата завершился сразу с кодом {self._proc.returncode}.\n"
            )
            raise RecorderError(
                "Не удалось запустить захват. Подробности в session.log."
            )

    def _append_log(self, text: str) -> None:
        if self._log_fh is not None:
            self._log_fh.write(text)
            self._log_fh.flush()

    # -------------------------------------------------------------- monitoring
    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    def current_size(self) -> int:
        for path in (self.mkv_path, self.mp4_path):
            try:
                return path.stat().st_size
            except FileNotFoundError:
                continue
        return 0

    def wait_or_exit(self) -> int | None:
        """Нон-блокирующая проверка кода завершения процесса (если уже завершился)."""
        return self._proc.returncode if self._proc else None

    # -------------------------------------------------------------------- stop
    async def stop(self) -> None:
        if self._proc is None or self._proc.returncode is not None:
            self._close_log()
            return
        # SIGINT всей группе (parec + ffmpeg) — корректное завершение с промывкой.
        self._signal_group(signal.SIGINT)
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=15)
        except asyncio.TimeoutError:
            log.warning("Захват не завершился по SIGINT, отправляю SIGKILL")
            self._signal_group(signal.SIGKILL)
            await self._proc.wait()
        self._close_log()

    def _signal_group(self, sig: int) -> None:
        try:
            os.killpg(os.getpgid(self._proc.pid), sig)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                self._proc.send_signal(sig)
            except ProcessLookupError:
                pass

    def _close_log(self) -> None:
        if self._log_fh is not None:
            try:
                self._log_fh.close()
            finally:
                self._log_fh = None

    # -------------------------------------------------------------- finalize
    async def finalize(self) -> dict:
        """Переупаковывает MKV в MP4 (copy) и проверяет результат."""
        if not self.mkv_path.exists():
            raise RecorderError("Промежуточный файл MKV не найден — запись не удалась.")

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-i", str(self.mkv_path),
            "-c", "copy",
            "-movflags", "+faststart",
            str(self.mp4_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        if proc.returncode != 0 or not self.mp4_path.exists():
            self._append_log(f"Ошибка remux в MP4:\n{out.decode('utf-8', 'replace')}\n")
            raise RecorderError(
                "Не удалось сформировать MP4. Промежуточный MKV сохранён."
            )

        info = await self._probe(self.mp4_path)
        if info.get("error"):
            raise RecorderError(f"Итоговый файл не прошёл проверку: {info['error']}")

        # Успех: убираем промежуточный MKV (только после проверки MP4).
        try:
            self.mkv_path.unlink()
        except FileNotFoundError:
            pass

        return {
            "file_path": str(self.mp4_path),
            "file_size": self.mp4_path.stat().st_size,
            "duration_s": info.get("duration_s"),
        }

    async def _probe(self, path: Path) -> dict:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        try:
            data = json.loads(out.decode("utf-8", "replace") or "{}")
        except json.JSONDecodeError as exc:
            return {"error": f"не удалось разобрать ffprobe: {exc}"}

        types = {s.get("codec_type") for s in data.get("streams", [])}
        if "video" not in types:
            return {"error": "в файле нет видеодорожки"}
        if "audio" not in types:
            return {"error": "в файле нет аудиодорожки"}

        duration = None
        try:
            duration = float(data.get("format", {}).get("duration"))
        except (TypeError, ValueError):
            pass
        return {"duration_s": duration}
