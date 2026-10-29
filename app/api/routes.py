"""REST API управления записью."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pathlib import Path
from pydantic import BaseModel, Field

from app.core.models import Task
from app.core.orchestrator import Orchestrator, StartRejectionError

router = APIRouter(prefix="/api")


class StartRequest(BaseModel):
    url: str
    name: str | None = None
    bot_name: str = Field(default="Владимир Русин AI")
    max_duration_min: int = Field(default=180, ge=1, le=24 * 60)


def _orch(request: Request) -> Orchestrator:
    return request.app.state.orchestrator


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/defaults")
async def defaults(request: Request) -> dict:
    cfg = request.app.state.cfg
    return {
        "default_bot_name": cfg.default_bot_name,
        "default_max_duration_min": cfg.default_max_duration_min,
    }


@router.post("/tasks", status_code=202)
async def start_task(request: Request, body: StartRequest) -> dict:
    cfg = request.app.state.cfg
    try:
        task: Task = await _orch(request).start(
            url=body.url,
            name=body.name or "",
            bot_name=body.bot_name or cfg.default_bot_name,
            max_duration_min=body.max_duration_min or cfg.default_max_duration_min,
        )
    except StartRejectionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return task.to_dict()


@router.get("/tasks")
async def list_tasks(request: Request) -> list[dict]:
    return [t.to_dict() for t in _orch(request).history()]


@router.get("/tasks/{task_id}")
async def get_task(request: Request, task_id: str) -> dict:
    task = _orch(request).get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Задание не найдено.")
    return task.to_dict()


@router.post("/tasks/{task_id}/stop")
async def stop_task(request: Request, task_id: str) -> dict:
    try:
        task = _orch(request).stop(task_id)
    except StartRejectionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return task.to_dict()


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(request: Request, task_id: str) -> dict:
    try:
        task = _orch(request).cancel(task_id)
    except StartRejectionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return task.to_dict()


@router.get("/tasks/{task_id}/download")
async def download(request: Request, task_id: str) -> FileResponse:
    task = _orch(request).get(task_id)
    if task is None or not task.file_path:
        raise HTTPException(status_code=404, detail="Файл записи не найден.")

    cfg = request.app.state.cfg
    storage = Path(cfg.storage_dir).resolve()
    target = Path(task.file_path).resolve()
    # Защита: отдаём только файлы внутри каталога хранения.
    if storage not in target.parents and target.parent != storage:
        raise HTTPException(status_code=403, detail="Запрещено.")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Файл отсутствует.")

    return FileResponse(
        path=str(target),
        filename=target.name,
        media_type="video/mp4",
    )
