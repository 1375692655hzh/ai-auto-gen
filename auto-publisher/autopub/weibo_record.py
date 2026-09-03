"""微博'下一步'录像式诊断: 填内容→点下一步→每0.5s连拍截图+按钮状态, 还原全过程。"""
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "logs" / "weibo_seq"
OUT.mkdir(parents=True, exist_ok=True)

BUTTON_JS = """() => {
    const out = [];
    document.querySelectorAll('button').forEach(b => {
        const t = (b.innerText || '').trim();
        const r = b.getBoundingClientRect();
        if (t && t.length < 8 && r.width > 0)
            out.push(`${t}@${Math.round(r.x)},${Math.round(r.y)}${b.disabled ? '(禁)' : ''}`);
    });
    return out.join(' | ');
}"""


async def main():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(ROOT / "profiles" / "weibo"), headless=False,
            viewport={"width": 1380, "height": 950}, locale="zh-CN",
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"])
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        page.on("dialog", lambda d: print("[原生弹窗!]", (d.message or "")[:60], flush=True))
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
        await page.wait_for_timeout(3000)
        print("填完. 点下一步前按钮:", await page.evaluate(BUTTON_JS), flush=True)
        await page.locator('button:has-text("下一步")').first.click(timeout=8000)
        print("已点下一步, 开始录像...", flush=True)
        for i in range(24):                     # 12 秒, 每0.5s
            await page.wait_for_timeout(500)
            try:
                btns = await page.evaluate(BUTTON_JS)
                print(f"t={i * 0.5:.1f}s url={page.url[-28:]} 按钮: {btns[:150]}", flush=True)
            except Exception as e:
                print(f"t={i * 0.5:.1f}s ERR {str(e)[:50]}", flush=True)
            await page.screenshot(path=str(OUT / f"seq_{i:02d}.png"))
        await ctx.close()

asyncio.run(main())
