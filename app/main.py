"""Точка входа приложения: FastAPI + панель управления."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_router
from app.api.ws import router as ws_router
from app.config import AppConfig
from app.core.events import EventBus
from app.core.orchestrator import Orchestrator
from app.storage.db import TaskRepository

STATIC_DIR = Path(__file__).parent / "static"

log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = AppConfig.load()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    repo = TaskRepository(db_path=Path(cfg.storage_dir) / ".bot.sqlite")
    await repo.init()
    interrupted = await repo.mark_interrupted()
    if interrupted:
        log.info("Помечено прерванных заданий: %d", interrupted)

    bus = EventBus()
    orchestrator = Orchestrator(cfg, repo, bus)
    await orchestrator.load_history()

    app.state.cfg = cfg
    app.state.bus = bus
    app.state.orchestrator = orchestrator
    log.info("Приложение запущено. Каталог хранения: %s", cfg.storage_dir)

    yield

    await orchestrator.shutdown()


app = FastAPI(title="Jitsi Recording Bot", version="0.1.0", lifespan=lifespan)
app.include_router(api_router)
app.include_router(ws_router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
