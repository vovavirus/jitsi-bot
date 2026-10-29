"""Диагностика meeting-DOM: заходит в комнату (модератор уже внутри) и дампит индикаторы."""
import asyncio
import sys

from playwright.async_api import async_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://meet.it-expertise.ru/bot_realtest"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await browser.new_context(locale="ru-RU")
        page = await ctx.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_selector('[data-testid="prejoin.screen"]', timeout=15000)
            inp = page.locator("#premeeting-name-input")
            if await inp.count():
                await inp.click(); await inp.fill(""); await inp.type("DIAG-MEET")
            await page.locator('[data-testid="prejoin.joinMeeting"]').click()
            print("join clicked, waiting 20s ...")
            await page.wait_for_timeout(20000)
        except Exception as e:
            print("join flow error:", e)

        prejoin = await page.locator('[data-testid="prejoin.screen"]').count()
        print("prejoin present:", prejoin)

        testids = await page.evaluate("""() => Array.from(new Set(
            Array.from(document.querySelectorAll('[data-testid]'))
            .map(e=>e.getAttribute('data-testid'))))""")
        print("ALL test-ids:", sorted(testids))

        checks = {
            "#hangupButton": await page.locator("#hangupButton").count(),
            ".mainToolbar": await page.locator(".mainToolbar").count(),
            "[data-testid=toolbar]": await page.locator('[data-testid="toolbar"]').count(),
            "#toolbarContainer": await page.locator("#toolbarContainer").count(),
            "[data-testid*=hangup i]": await page.locator('[data-testid*="hangup" i]').count(),
            "#largeVideo": await page.locator("#largeVideo").count(),
            ".app": await page.locator(".app").count(),
            "[class*=toolbar i]": await page.locator('[class*="toolbar" i]').count(),
        }
        print("selector checks:", checks)

        # элемент с текстом «Выйти»/«Leave»
        body_text = (await page.evaluate("() => document.body.innerText"))[:400]
        print("--- body text (head) ---")
        print(body_text)

        with open("/tmp/meeting.html", "w", encoding="utf-8") as fh:
            fh.write(await page.evaluate("() => document.documentElement.outerHTML"))
        print("saved /tmp/meeting.html")
        await browser.close()


asyncio.run(main())
