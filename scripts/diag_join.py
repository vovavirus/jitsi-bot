"""Диагностика: сохраняет полный HTML страницы и ищет кнопку входа."""
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
        await page.wait_for_timeout(7000)

        html = await page.evaluate("() => document.documentElement.outerHTML")
        with open("/tmp/page.html", "w", encoding="utf-8") as fh:
            fh.write(html)
        print("saved /tmp/page.html bytes:", len(html))

        # Все элементы, похожие на кнопку входа.
        data = await page.evaluate("""() => {
          const out = [];
          const sel = 'button, a, [role=button], [data-testid*=join i], [id*=join i]';
          document.querySelectorAll(sel).forEach(e => {
            const t = (e.innerText||'').trim().replace(/\\s+/g,' ');
            if (!t && !e.id && !e.getAttribute('data-testid')) return;
            out.push({
              tag: e.tagName,
              id: e.id,
              cls: e.className && e.className.toString().slice(0,80),
              testid: e.getAttribute('data-testid'),
              text: t.slice(0,60),
              visible: !!(e.offsetParent)
            });
          });
          return out;
        }""")
        print("--- join-ish elements ---")
        for d in data:
            print(d)

        await browser.close()


asyncio.run(main())
