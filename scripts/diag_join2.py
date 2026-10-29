"""Диагностика полного входа: новые селекторы + поиск индикатора «в встрече»."""
import asyncio
import sys

from playwright.async_api import async_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://meet.it-expertise.ru/test_AI"
NAME = "DIAG-BOT"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await browser.new_context(locale="ru-RU")
        page = await ctx.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

        # ждём prejoin
        try:
            await page.wait_for_selector('[data-testid="prejoin.screen"]', timeout=15000)
            print("prejoin: OK")
        except Exception:
            print("prejoin: NOT FOUND")

        # имя
        inp = page.locator("#premeeting-name-input")
        if await inp.count():
            await inp.click()
            await inp.fill("")
            await inp.type(NAME)
            print("name filled:", NAME)
        else:
            print("name input: NOT FOUND")

        # жмём «Join meeting»
        jb = page.locator('[data-testid="prejoin.joinMeeting"]')
        if await jb.count():
            await jb.click()
            print("join clicked")
        else:
            print("join button: NOT FOUND")

        # ждём выход из prejoin / появление meeting
        import time
        deadline = time.monotonic() + 30
        joined = False
        while time.monotonic() < deadline:
            await page.wait_for_timeout(1000)
            prejoin_gone = (await page.locator('[data-testid="prejoin.screen"]').count()) == 0
            hangup = await page.locator("#hangupButton").count()
            main_toolbar = await page.locator(".mainToolbar").count()
            testid_toolbar = await page.locator('[data-testid="toolbar"]').count()
            if prejoin_gone and (hangup or main_toolbar or testid_toolbar):
                joined = True
                print(f"JOINED: prejoin_gone={prejoin_gone} hangup={hangup} "
                      f"mainToolbar={main_toolbar} testid_toolbar={testid_toolbar}")
                break
        if not joined:
            print("NOT JOINED after 30s")

        if joined:
            # дампуем индикаторы meeting
            info = await page.evaluate("""() => {
              const res = { testids: [], ids: [] };
              document.querySelectorAll('[data-testid]').forEach(e => res.testids.push(e.getAttribute('data-testid')));
              document.querySelectorAll('#hangupButton, .mainToolbar, #toolbarContainer, #filmStripContainer').forEach(e => res.ids.push(e.id||e.className));
              return res;
            }""")
            print("meeting testids:", sorted(set(info["testids"]))[:40])
            print("meeting ids:", info["ids"])

        await page.wait_for_timeout(2000)
        await browser.close()


asyncio.run(main())
