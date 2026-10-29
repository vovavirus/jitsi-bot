"""Диагностика состояния ПОСЛЕ клика Join: дампит DOM, test-ids, ошибки."""
import asyncio
import sys

from playwright.async_api import async_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://meet.it-expertise.ru/test_AI"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await browser.new_context(locale="ru-RU")
        page = await ctx.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_selector('[data-testid="prejoin.screen"]', timeout=15000)
        inp = page.locator("#premeeting-name-input")
        await inp.click(); await inp.fill(""); await inp.type("DIAG-BOT2")
        await page.locator('[data-testid="prejoin.joinMeeting"]').click()
        print("join clicked, waiting 18s ...")
        await page.wait_for_timeout(18000)

        prejoin = await page.locator('[data-testid="prejoin.screen"]').count()
        print("prejoin still present:", prejoin)
        print("URL:", page.url)

        testids = await page.evaluate("""() => Array.from(new Set(
            Array.from(document.querySelectorAll('[data-testid]'))
            .map(e=>e.getAttribute('data-testid'))))""")
        print("all test-ids:", sorted(testids))

        # видимый текст (чтобы увидеть ошибки/сообщения)
        body_text = await page.evaluate("() => document.body.innerText.slice(0, 1200)")
        print("--- body text ---")
        print(body_text)

        with open("/tmp/after_join.html", "w", encoding="utf-8") as fh:
            fh.write(await page.evaluate("() => document.documentElement.outerHTML"))
        print("saved /tmp/after_join.html")
        await browser.close()


asyncio.run(main())
