"""富途发帖入口实测: 开 Chrome → 等登录 → 抓 q.futunn.com 登录后的发帖线索"""
import asyncio, json, sys
sys.path.insert(0, ".")
from pathlib import Path
from playwright.async_api import async_playwright

PROFILE = str(Path.home() / ".futu_autopub_chrome_profile")


async def main():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            PROFILE, headless=False,
            viewport={"width": 1280, "height": 900}, locale="zh-CN",
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"])
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        page.set_default_timeout(30000)
        await page.goto("https://q.futunn.com/nnq", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        url = page.url
        print("当前URL:", url)
        if "passport" in url or "login" in url:
            print(">>> 需要登录: 请在弹出的 Chrome 里扫码/验证码登录富途(最多等 3 分钟)")
            for _ in range(60):
                await page.wait_for_timeout(3000)
                if "passport" not in page.url and "login" not in page.url:
                    break
            print("登录后URL:", page.url)
        await page.goto("https://q.futunn.com/nnq", wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
        # 抓发帖线索
        clues = await page.evaluate("""() => {
            const out = {btns: [], editors: [], links: []};
            for (const b of document.querySelectorAll('button, [class*="btn"], [class*="publish"], [class*="post"], [class*="create"], [class*="write"], a')) {
                const t = (b.innerText || b.getAttribute('title') || '').trim();
                if (t && t.length <= 12 && /发|帖|写|创作|发布|动弹|post|write/i.test(t))
                    out.btns.push({tag: b.tagName, text: t, cls: (b.className+'').slice(0,80)});
            }
            out.editors = [...document.querySelectorAll('[contenteditable=true],textarea')].map(
                e => ({tag: e.tagName, cls: (e.className+'').slice(0,80), ph: e.getAttribute('placeholder') || ''}));
            for (const a of document.querySelectorAll('a[href]')) {
                const h = a.getAttribute('href') || '';
                if (/publish|post|create|write|compose/i.test(h)) out.links.push(h);
            }
            return out;
        }""")
        print(json.dumps(clues, ensure_ascii=False, indent=1))
        await ctx.close()

asyncio.run(main())
