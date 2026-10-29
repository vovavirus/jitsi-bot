"""Автоматизация входа во встречу Jitsi (prejoin + подтверждение входа).

Селекторы подобраны под реальный сервер meet.it-expertise.ru (актуальная
версия Jitsi Meet web-client с prejoin-экраном `prejoin.screen`).
Для каждого элемента есть несколько вариантов селекторов, чтобы устоять
к изменениям версий.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from urllib.parse import urlparse

from playwright.async_api import Page

log = logging.getLogger("jitsi.join")


class JoinError(RuntimeError):
    """Ошибочное состояние при подключении (пароль, допуск, тайм-аут...)."""


# --- Селекторы (актуальный Jitsi Meet, prejoin.screen) ---
PREJOIN_SELECTORS = [
    '[data-testid="prejoin.screen"]',
    ".prejoinPage",
    "#prejoinPage",
]
NAME_INPUT_SELECTORS = [
    "#premeeting-name-input",
    '[data-testid="prejoin.displayName"]',
    "#displayNameInput",
    "input.displayname-input",
]
JOIN_BUTTON_SELECTORS = [
    '[data-testid="prejoin.joinMeeting"]',
    "#prejoinButton",
    '[data-testid="join-button"]',
]
# Подтверждение входа: элементы страницы встречи. Точный признак «вошли» —
# наличие этих элементов И исчезновение prejoin (в состоянии «ожидание
# модератора» prejoin остаётся, а «Waiting for a moderator» детектится как ошибка).
MEETING_READY_SELECTORS = [
    "#videoconference_page",
    "#videospace",
    "#largeVideoContainer",
    ".hangup-button",
    "#new-toolbox",
]
# Индикаторы неподдерживаемых сценариев (пароль).
ERROR_SELECTORS = [
    ".roomPasswordDialog",
    "#roomPassword",
    '.dialog [data-testid="roomPassword"]',
    ".passwordInput",
]
# Тексты диалогов-«ожидание» (модератор/допуск) — ищем по содержимому модалки.
_WAITING_RE = re.compile(
    r"moderator|модератор|waiting for|ожидание|permission to join|разрешение|допуск",
    re.IGNORECASE,
)


def room_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return path.split("/")[-1] if path else "meeting"


def safe_url(url: str) -> str:
    """URL без query/fragment (не логируем возможные секретные параметры)."""
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


async def _visible(page: Page, selectors: list[str]) -> str | None:
    """Возвращает первый видимый селектор или None (без ожидания)."""
    for sel in selectors:
        try:
            if await page.locator(sel).first.is_visible(timeout=200):
                return sel
        except Exception:  # noqa: BLE001
            continue
    return None


async def _fill_name(page: Page, bot_name: str) -> bool:
    for sel in NAME_INPUT_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=500):
                await loc.click()
                await loc.fill("")
                await loc.type(bot_name, delay=20)
                log.info("Имя бота установлено: %s (селектор %s)", bot_name, sel)
                return True
        except Exception:  # noqa: BLE001
            continue
    log.warning("Не найдено поле имени бота")
    return False


async def _click_join(page: Page) -> bool:
    for sel in JOIN_BUTTON_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=500):
                await loc.click()
                log.info("Нажата кнопка входа (селектор %s)", sel)
                return True
        except Exception:  # noqa: BLE001
            continue
    # Фолбэк: кнопка по тексту (локализация).
    for text in ("Присоединиться", "Join meeting", "Join"):
        try:
            btn = page.get_by_role("button", name=text).first
            if await btn.is_visible(timeout=500):
                await btn.click()
                log.info("Нажата кнопка входа по тексту: %s", text)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def _detect_error(page: Page) -> str | None:
    """Возвращает сообщение об ошибке, если встреча закрыта/ждёт допуск, иначе None."""
    for sel in ERROR_SELECTORS:
        if await _visible(page, [sel]):
            return "Встреча защищена паролем. Подключение с паролем не поддерживается."

    # Модалка «ожидание модератора/допуска».
    dialogs = page.locator('[role="dialog"], [aria-modal="true"], .modal')
    for i in range(await dialogs.count()):
        try:
            txt = (await dialogs.nth(i).inner_text()) or ""
        except Exception:  # noqa: BLE001
            continue
        if _WAITING_RE.search(txt):
            return (
                "Встреча ожидает модератора или допуск. "
                "Автоматический вход невозможен — требуется присутствующий модератор."
            )
    return None


async def join_meeting(
    page: Page,
    url: str,
    bot_name: str,
    timeout_s: int,
) -> str:
    """Подключает бота к встрече. Возвращает название комнаты.

    Бросает JoinError при тайм-ауте, пароле, ожидании допуска/модератора
    или недоступности.
    """
    room = room_from_url(url)
    log.info("Открываю встречу: %s (комната: %s)", safe_url(url), room)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    except Exception as exc:  # noqa: BLE001
        raise JoinError(f"Встреча недоступна: {exc.__class__.__name__}")

    deadline = time.monotonic() + timeout_s
    join_clicked = False

    while time.monotonic() < deadline:
        # 1) Недопустимые сценарии (пароль / ожидание модератора).
        err = await _detect_error(page)
        if err:
            raise JoinError(err)

        # 2) Успешный вход: есть meeting-элемент И prejoin исчез.
        ready = await _visible(page, MEETING_READY_SELECTORS)
        prejoin_visible = await _visible(page, PREJOIN_SELECTORS)
        if ready and prejoin_visible is None:
            log.info("Вход подтверждён по состоянию интерфейса (%s)", ready)
            await asyncio.sleep(2)  # даём WebRTC поднять потоки
            return room

        # 3) Prejoin: вводим имя и жмём «Присоединиться».
        if not join_clicked and prejoin_visible:
            await _fill_name(page, bot_name)
            join_clicked = await _click_join(page) or join_clicked

        await asyncio.sleep(0.5)

    raise JoinError(
        f"Не удалось войти во встречу за {timeout_s} секунд. "
        "Возможно, встреча закрыта, ждёт модератора или недоступна."
    )


async def detect_meeting_ended(page: Page) -> bool:
    """Возвращает True, если встреча завершена или бот покинут из комнаты."""
    ended_selectors = [
        "#leavePage",
        '[data-testid="leavePage"]',
        "[class*=LeavePage]",
        "#closePage",
    ]
    return await _visible(page, ended_selectors) is not None
