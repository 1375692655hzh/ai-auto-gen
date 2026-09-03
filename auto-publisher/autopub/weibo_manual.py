"""微博手动辅助发布: 自动填好标题正文, 窗口保持打开由人工/屏幕操控点发布。"""
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent


async def main():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(ROOT / "profiles" / "weibo"), headless=False,
            viewport={"width": 1380, "height": 950}, locale="zh-CN",
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"])
        sp = ROOT / "profiles/weibo.state.json"
        if sp.exists():
            state = json.loads(sp.read_text(encoding="utf-8"))
            existing = {c["name"] for c in await ctx.cookies()}
            to_add = [c for c in state.get("cookies", []) if c["name"] not in existing]
            if to_add:
                await ctx.add_cookies(to_add)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://card.weibo.com/article/v5/editor",
                        wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(6000)
        await page.locator("text=写文章").first.click(timeout=8000)
        await page.wait_for_timeout(5000)
        await page.locator('textarea[placeholder="请输入标题"]').first.fill("国服一哥KIMI马上来")
        b = page.locator("div.ProseMirror").first
        await b.click(timeout=6000)
        await page.keyboard.type(
            "记者获悉，月之暗面(Kimi)已于本周以保密形式向港交所递交A1文件，正式启动港股IPO流程。"
            "A1是企业申请在港交所上市时提交的正式申请表之一。Kimi方面回应上述消息称："
            "“对于市场传闻不予置评，目前暂无可以披露的信息。”同时据我们了解，"
            "Kimi也正在以500亿美元的投前估值推进新一轮融资。这很有可能是Kimi IPO前的最后一轮融资。",
            delay=5)
        await page.wait_for_timeout(2000)
        print("内容已填好, 窗口保持打开", flush=True)
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
