"""Оркестрация жизненного цикла заданий: подключение, запись, финализация.

Поддерживает несколько одновременных записей (до max_concurrent_recordings):
каждому заданию выделяется собственный слот ресурсов — X-дисплей,
PulseAudio-инстанс и аудио-sink. Обеспечивает лимиты, проверку места,
переходы состояний (§6), обработку ошибок (§7) и graceful shutdown (§9).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

from app.capture.audio import AudioSource
from app.capture.recorder import Recorder, RecorderError
from app.capture.video import VideoSource
from app.config import AppConfig
from app.core.events import EventBus
from app.core.models import Task, TaskStatus
from app.jitsi.browser import JitsiBrowser
from app.jitsi.join import (
    JoinError,
    detect_meeting_ended,
    join_meeting,
    room_from_url,
    safe_url,
)
from app.storage.db import TaskRepository
from app.storage.files import build_folder_name, has_enough_space

log = logging.getLogger("core.orchestrator")


class StartRejectionError(RuntimeError):
    """Запуск отклонён (некорректная ссылка, другая запись активна, нет места)."""


class Orchestrator:
    def __init__(
        self,
        cfg: AppConfig,
        repo: TaskRepository,
        bus: EventBus,
    ) -> None:
        self.cfg = cfg
        self.repo = repo
        self.bus = bus
        self.storage_dir = Path(cfg.storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self._tasks: dict[str, Task] = {}
        self._pipelines: dict[str, asyncio.Task] = {}
        # Свободные слоты ресурсов (X-дисплей + PulseAudio + sink).
        self._free_slots: deque[int] = deque(range(cfg.max_concurrent_recordings))
        self._start_lock = asyncio.Lock()
        self._log_handler: logging.Handler | None = None

    # ------------------------------------------------------------------ API
    async def start(
        self,
        url: str,
        name: str,
        bot_name: str,
        max_duration_min: int,
        start_at: float | None = None,
    ) -> Task:
        async with self._start_lock:
            url = self._validate_url(url)

            if not self._free_slots:
                raise StartRejectionError(
                    f"Достигнуто максимальное число одновременных записей "
                    f"({self.cfg.max_concurrent_recordings}). Дождитесь окончания "
                    f"одной из записей."
                )
            slot = self._free_slots.popleft()
            try:
                if not has_enough_space(self.storage_dir, self.cfg.min_free_space_gb):
                    raise StartRejectionError(
                        f"Недостаточно места на диске (нужно не менее "
                        f"{self.cfg.min_free_space_gb:g} ГБ)."
                    )

                if not name or not name.strip():
                    room = room_from_url(url)
                    date = time.strftime("%Y-%m-%d", time.localtime())
                    name = f"{room}_{date}"

                task = Task(
                    url=url,
                    name=name.strip(),
                    bot_name=self._normalize_bot_name(
                        bot_name.strip() or self.cfg.default_bot_name
                    ),
                    max_duration_min=max_duration_min,
                    start_at=start_at,
                )
                task._slot = slot
                self._tasks[task.id] = task
                await self._persist_publish(task)
            except Exception:
                # Не успели создать задание — возвращаем слот.
                self._free_slots.appendleft(slot)
                raise

            log.info(
                "Задание %s: выделен слот %d (display=%s, sink=%s)",
                task.id, slot,
                self.cfg.display_for_slot(slot), self.cfg.sink_for_slot(slot),
            )
            self._pipelines[task.id] = asyncio.create_task(
                self._run(task), name=f"task-{task.id}"
            )
        return task

    def stop(self, task_id: str) -> Task:
        task = self._require(task_id)
        if task.status not in (TaskStatus.CONNECTING, TaskStatus.RECORDING):
            raise StartRejectionError("Эту запись нельзя остановить в текущем состоянии.")
        task._stop_requested = True
        log.info("Запрошена остановка задания %s", task.id)
        self._publish(task)
        return task

    def cancel(self, task_id: str) -> Task:
        task = self._require(task_id)
        if task.status not in (TaskStatus.SCHEDULED, TaskStatus.CONNECTING):
            raise StartRejectionError(
                "Отменить можно только запланированную встречу или подключение "
                "до начала записи."
            )
        task._cancel_requested = True
        log.info("Запрошена отмена подключения задания %s", task.id)
        self._publish(task)
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def history(self) -> list[Task]:
        return sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)

    def active_tasks(self) -> list[Task]:
        return [t for t in self._tasks.values() if t.is_active]

    @property
    def free_slots_count(self) -> int:
        return len(self._free_slots)

    # -------------------------------------------------------------- internals
    def _require(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise StartRejectionError("Задание не найдено.")
        return task

    @staticmethod
    def _normalize_bot_name(name: str) -> str:
        """Имя обязательно; в конце всегда присутствует « AI»."""
        name = (name or "").strip()
        if not name:
            raise StartRejectionError("Укажите имя бота.")
        if name.split()[-1].lower() != "ai":
            name = f"{name} AI"
        return name

    @staticmethod
    def _validate_url(url: str) -> str:
        url = (url or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise StartRejectionError(
                "Некорректная ссылка. Допустимы только протоколы http и https."
            )
        if not parsed.netloc:
            raise StartRejectionError("Некорректная ссылка: отсутствует хост.")
        return url

    # ------------------------------------------------------------- pipeline
    async def _run(self, task: Task) -> None:
        recorder: Recorder | None = None
        browser: JitsiBrowser | None = None
        page = None
        try:
            if task.start_at is not None and task.start_at > time.time():
                if not await self._wait_until(task):
                    return

            task.status = TaskStatus.CONNECTING
            await self._persist_publish(task)

            assert task._slot is not None, "слот не выделен"
            display = self.cfg.display_for_slot(task._slot)
            sink = self.cfg.sink_for_slot(task._slot)
            pulse_socket = self.cfg.pulse_socket_for_slot(task._slot)
            video = VideoSource(display)
            audio = AudioSource(sink, pulse_socket)

            if not await video.is_available():
                raise RecorderError("Виртуальный экран недоступен. Запись невозможна.")
            if not await audio.ensure():
                raise RecorderError("Не удалось подготовить аудиосистему (PulseAudio).")

            folder = self.storage_dir / build_folder_name(task, task.created_at)
            folder.mkdir(parents=True, exist_ok=True)
            task.folder = folder.name
            session_log = folder / "session.log"
            metadata = folder / "metadata.json"
            task.session_log_path = str(session_log)
            task.metadata_path = str(metadata)
            self._attach_log(session_log)
            self._write_metadata(task)

            env = audio.env()
            env["DISPLAY"] = display
            browser = JitsiBrowser(self.cfg, env)
            page = await browser.start()

            room = await join_meeting(page, task.url, task.bot_name, self.cfg.connect_timeout_s)
            task.room = room
            self._publish(task)

            if task._cancel_requested or task._stop_requested:
                await self._conclude(task, None, TaskStatus.CANCELLED,
                                      "Подключение отменено пользователем.")
                return

            recorder = Recorder(self.cfg, video, audio, folder, session_log)
            await recorder.start()  # может бросить RecorderError
            task.status = TaskStatus.RECORDING
            task.started_at = time.time()
            await self._persist_publish(task)
            log.info("Запись пошла: %s", task.id)

            intended = await self._record_loop(task, recorder, page)

            if intended == "crash" or intended == "disk":
                error = {
                    "crash": "Процесс браузера или записи завершился неожиданно. "
                              "Доступный материал сохранён.",
                    "disk": "Недостаточно места на диске. Запись остановлена. "
                             "Доступный материал сохранён.",
                }[intended]
                await self._conclude(task, recorder, TaskStatus.FAILED, error)
            else:
                await self._conclude(task, recorder, TaskStatus.COMPLETED)

        except JoinError as exc:
            await self._conclude(task, recorder, TaskStatus.FAILED, str(exc))
        except RecorderError as exc:
            await self._conclude(task, recorder, TaskStatus.FAILED, str(exc))
        except asyncio.CancelledError:
            # Аварийное/штатное завершение приложения: сохраняем материал.
            await self._conclude(task, recorder, TaskStatus.INTERRUPTED,
                                 "Приложение было остановлено во время записи.")
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("Необработанная ошибка задания %s", task.id)
            await self._conclude(task, recorder, TaskStatus.FAILED,
                                 f"Внутренняя ошибка: {exc.__class__.__name__}: {exc}")
        finally:
            self._detach_log()
            if recorder is not None:
                try:
                    await recorder.stop()
                except Exception:  # noqa: BLE001
                    pass
            if browser is not None:
                try:
                    await browser.close()
                except Exception:  # noqa: BLE001
                    pass
            self._release_slot(task)

    def _release_slot(self, task: Task) -> None:
        self._pipelines.pop(task.id, None)
        if task._slot is not None:
            self._free_slots.append(task._slot)
            log.info("Задание %s: слот %d освобождён", task.id, task._slot)
            task._slot = None

    async def _wait_until(self, task: Task) -> bool:
        """Ждёт времени начала. False — задание завершено (отмена/стоп)."""
        assert task.start_at is not None
        task.status = TaskStatus.SCHEDULED
        await self._persist_publish(task)
        log.info(
            "Задание %s запланировано на %s",
            task.id,
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(task.start_at)),
        )
        while time.time() < task.start_at:
            if task._cancel_requested:
                await self._conclude(
                    task, None, TaskStatus.CANCELLED,
                    "Запланированная встреча отменена пользователем.",
                )
                return False
            if task._stop_requested:
                await self._conclude(
                    task, None, TaskStatus.INTERRUPTED,
                    "Приложение было остановлено до начала встречи.",
                )
                return False
            await asyncio.sleep(1)
        return True

    async def _record_loop(
        self, task: Task, recorder: Recorder, page
    ) -> str:
        """Возвращает причину остановки: stopped | duration | ended | crash | disk."""
        max_s = task.max_duration_min * 60
        publish_counter = 0
        while True:
            await asyncio.sleep(1)

            if task._stop_requested:
                return "stopped"

            if task.started_at and (time.time() - task.started_at) >= max_s:
                task.warnings.append("Достигнута максимальная длительность.")
                return "duration"

            if not recorder.is_running:
                code = recorder.wait_or_exit()
                log.error("Процесс записи завершился (код %s)", code)
                return "crash"

            if not has_enough_space(self.storage_dir, self.cfg.min_free_space_gb):
                return "disk"

            # Завершение встречи / бот покинут.
            try:
                if await detect_meeting_ended(page):
                    task.warnings.append("Встреча завершена или бот покинут.")
                    return "ended"
            except Exception:  # noqa: BLE001
                # Страница недоступна — вероятно, сбой браузера.
                return "crash"

            task._live_size = recorder.current_size()
            publish_counter += 1
            if publish_counter >= 2:
                publish_counter = 0
                self._publish(task)

    # ------------------------------------------------------------ conclude
    async def _conclude(
        self,
        task: Task,
        recorder: Recorder | None,
        intended: TaskStatus,
        error: str | None = None,
    ) -> None:
        task.ended_at = time.time()
        if task.started_at is not None:
            task.duration_s = task.ended_at - task.started_at

        file_ok = True
        if recorder is not None:
            try:
                await recorder.stop()
                info = await recorder.finalize()
                task.file_path = info["file_path"]
                task.file_size = info["file_size"]
                if info.get("duration_s"):
                    task.duration_s = info["duration_s"]
            except RecorderError as exc:
                file_ok = False
                task.warnings.append(f"Не удалось сформировать MP4: {exc}")
                if recorder.mkv_path.exists():
                    task.file_path = str(recorder.mkv_path)

        if intended == TaskStatus.COMPLETED and (not file_ok or error):
            final = TaskStatus.FAILED
            if not task.error:
                task.error = "Итоговый файл не прошёл проверку."
        else:
            final = intended
            task.error = error

        task.status = final
        task._live_size = 0
        self._write_metadata(task)
        await self._persist_publish(task)
        log.info("Задание %s завершено: %s", task.id, final.value)

    # ------------------------------------------------------------- persist
    async def _persist_publish(self, task: Task, status: TaskStatus | None = None) -> None:
        if status is not None:
            task.status = status
        await self.repo.save(task)
        self._publish(task)

    def _publish(self, task: Task) -> None:
        self.bus.publish({"type": "task", "task": task.to_dict()})

    # ------------------------------------------------------------- metadata
    def _write_metadata(self, task: Task) -> None:
        if not task.metadata_path:
            return
        payload = {
            **task.to_dict(),
            "safe_url": safe_url(task.url),
            "created_at_iso": time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.localtime(task.created_at)
            ),
            "start_at_iso": time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.localtime(task.start_at)
            ) if task.start_at else None,
        }
        try:
            Path(task.metadata_path).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            log.warning("Не удалось записать metadata.json: %s", exc)

    # ------------------------------------------------------------- logging
    def _attach_log(self, path: Path) -> None:
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        handler.setLevel(logging.DEBUG)
        logging.getLogger().addHandler(handler)
        self._log_handler = handler

    def _detach_log(self) -> None:
        if self._log_handler is not None:
            logging.getLogger().removeHandler(self._log_handler)
            self._log_handler.close()
            self._log_handler = None

    # ------------------------------------------------------------- history
    async def load_history(self) -> None:
        """Подгружает завершённые задания из SQLite в память (для панели)."""
        rows = await self.repo.list(limit=200)
        for row in rows:
            task = Task.from_row(row)
            self._tasks[task.id] = task

    # ------------------------------------------------------------- shutdown
    async def shutdown(self, timeout: float = 30.0) -> None:
        """Грациозное завершение: доводит все активные записи до финализации."""
        active = self.active_tasks()
        if not active:
            return
        for task in active:
            task._stop_requested = True
        log.info("Shutdown: довожу %d активных записей до конца", len(active))
        pipelines = [p for p in self._pipelines.values() if not p.done()]
        if not pipelines:
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(*pipelines, return_exceptions=True), timeout=timeout
            )
        except (asyncio.TimeoutError, Exception):  # noqa: BLE001
            pass
