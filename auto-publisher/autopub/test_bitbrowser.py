"""一次性验证: 比特浏览器开窗 → CDP 接管 → 检查雪球登录态 → 截图 → 关窗"""
import asyncio, sys
sys.path.insert(0, ".")

import bitbrowser

WID = "8eb4ae1e9a6e407e8ebe87f333889811"


async def main():
    from playwright.async_api import async_playwright
    info = bitbrowser.open_window(WID)
    print("ws:", info.get("ws"), "http:", info.get("http"))
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(info.get("ws") or info.get("http"))
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        page.set_default_timeout(60000)
        await page.goto("https://xueqiu.com/", wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)
        html = await page.content()
        logged = any(k in html for k in ("我的资产", "写作", "icon-avatar", "user-avatar"))
        cookie_ok = any(c["name"] == "xq_a_token" for c in await ctx.cookies("https://xueqiu.com"))
        print("页面关键词判登录:", logged, "| xq_a_token cookie:", cookie_ok)
        try:
            await page.screenshot(path="logs/screenshots/bb_xueqiu_check.png",
                                  full_page=False, timeout=15000,
                                  animations="disabled")
        except Exception as e:
            print("截图失败(不影响验证):", type(e).__name__)
        # 打印发文入口是否存在(登录后导航栏有"写作")
        print("有'写作'按钮:", await page.locator("text=写作").count() > 0)
        await browser.close()
    bitbrowser.close_window(WID)
    print("done")


asyncio.run(main())
