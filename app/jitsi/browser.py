"""Управление браузером Chromium (Playwright) для подключения к Jitsi."""
from __future__ import annotations

import logging
from typing import Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    async_playwright,
    Playwright,
)

from app.config import AppConfig

log = logging.getLogger("jitsi.browser")


class JitsiBrowser:
    """Запускает Chromium на виртуальном экране, без камеры и микрофона."""

    def __init__(self, cfg: AppConfig, env: dict[str, Any]) -> None:
        self.cfg = cfg
        self.env = env
        self._playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def start(self) -> Page:
        self._playwright = await async_playwright().start()

        launch_args = [
            # Запуск в контейнере: песочница Chromium требует привилегий,
            # которых нет в Docker. Это обоснованное исключение (изолированный контейнер).
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            # Окно занимает весь виртуальный экран 1920x1080.
            f"--window-size={self.cfg.video.width},{self.cfg.video.height}",
            "--window-position=0,0",
            "--start-fullscreen",
            # Автоплей аудио встречи без пользовательского жеста.
            "--autoplay-policy=no-user-gesture-required",
            "--lang=ru",
            "--force-color-profile=srgb",
        ]

        self.browser = await self._playwright.chromium.launch(
            headless=False,
            args=launch_args,
            env=self.env,
        )
        self.context = await self.browser.new_context(
            viewport={"width": self.cfg.video.width, "height": self.cfg.video.height},
            locale="ru-RU",
            ignore_https_errors=True,
        )
        # Камера и микрофон НЕ выдаются: запросы на media-permission отклоняются,
        # поэтому бот не отправляет свои камеру/микрофон.
        self.context.set_default_timeout(30_000)
        self.page = await self.context.new_page()
        return self.page

    async def close(self) -> None:
        try:
            if self.context is not None:
                await self.context.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self.browser is not None:
                await self.browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._playwright is not None:
                await self._playwright.stop()
        except Exception:  # noqa: BLE001
            pass
        self.page = None
        self.context = None
        self.browser = None
        self._playwright = None
