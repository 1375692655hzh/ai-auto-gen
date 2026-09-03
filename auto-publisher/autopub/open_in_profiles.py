"""用各平台的专属登录浏览器(profiles/<平台>)打开指定页面, 窗口保持打开。"""
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent
TARGETS = {
    "zhihu": "https://zhuanlan.zhihu.com/p/2078176469025669460",
    "laohu": "https://www.laohu8.com/",
    "eastmoney": "https://mp.eastmoney.com/collect/pc_article/index.html#/",
    "weibo": "https://weibo.com/",
}


async def main():
    async with async_playwright() as p:
        for name, url in TARGETS.items():
            prof = ROOT / "profiles" / name
            if not prof.exists():
                print(f"[{name}] profile 不存在, 跳过")
                continue
            ctx = await p.chromium.launch_persistent_context(
                str(prof), headless=False, viewport={"width": 1280, "height": 900},
                locale="zh-CN", args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"])
            sp = ROOT / f"profiles/{name}.state.json"
            if sp.exists():
                try:
                    state = json.loads(sp.read_text(encoding="utf-8"))
                    if state.get("cookies"):
                        await ctx.add_cookies(state["cookies"])
                except Exception:
                    pass
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                print(f"[{name}] 已打开 {url}")
            except Exception as e:
                print(f"[{name}] 打开失败: {e}")
        print("全部窗口已打开, 保持运行中(关掉窗口即可退出)…", flush=True)
        await asyncio.Event().wait()   # 一直挂着, 窗口留给用户看


if __name__ == "__main__":
    asyncio.run(main())
