"""补充打开: 老虎社区(/community) + 长桥 + 富途 + 雪球, 窗口保持打开。"""
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent
TARGETS = {
    "laohu": "https://www.laohu8.com/community",
    "changqiao": "https://mp.longportapp.com/topics",
    "futu": "https://q.futunn.com/",
    "xueqiu": "https://xueqiu.com/",
    "zhihu": "https://zhuanlan.zhihu.com/p/2078176469025669460",
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
                        # 只补缺的 Cookie, 不覆盖 profile 里更新的
                        existing = {c["name"] for c in await ctx.cookies()}
                        to_add = [c for c in state["cookies"]
                                  if c["name"] not in existing]
                        if to_add:
                            await ctx.add_cookies(to_add)
                except Exception:
                    pass
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(2500)
                # 首渲染可能带旧/游客 token 显示未登录, 重载一次以登录态渲染
                await page.reload(wait_until="domcontentloaded", timeout=30000)
                print(f"[{name}] 已打开 {url}", flush=True)
            except Exception as e:
                print(f"[{name}] 打开失败: {e}", flush=True)
        print("保持运行中…", flush=True)
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
