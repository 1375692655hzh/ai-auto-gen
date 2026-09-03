"""一键登录平台 —— 同事拿到工具后的第一步

用法:
  py login.py                 # 逐个登录 config 里 enabled=true 的所有平台
  py login.py xueqiu zhihu    # 只登录指定平台
  py login.py all             # 全部已注册平台

流程: 弹出该平台专属浏览器窗口 → 你扫码/验证码登录 → 自动检测登录态 → 关窗保存。
登录态存在 autopub/profiles/<平台>/, 一次登录长期有效(除非平台踢下线)。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from publishers import REGISTRY           # noqa: E402
from publish_all import load_config       # noqa: E402

LOGIN_URLS = {                            # 登录检测落点: 发文页(登录墙会自动跳登录)
    "xueqiu": "https://mp.xueqiu.com/writeV2/?position=pc_home_post",
    "zhihu": "https://zhuanlan.zhihu.com/write",
    "laohu": "https://nl.tigerbrokers.com/community#/post",
    "eastmoney": "https://guba.eastmoney.com/",
    "weibo": "https://weibo.com/new?publishtype=article",
    "futu": "https://q.futunn.com/editor?feed_type=4",
    "changqiao": "https://mp.longportapp.com/topics/new",
    "bilibili": "https://member.bilibili.com/platform/upload/video/frame",
    "douyin": "https://creator.douyin.com/creator-micro/content/upload",
    "tonghuashun": "https://t.10jqka.com.cn/",
    "weixin": "https://mp.weixin.qq.com/",
}


async def login_one(plat: str):
    from playwright.async_api import async_playwright
    from publishers.base import browser_channel
    if plat not in REGISTRY:
        print(f"未知平台: {plat} (已注册: {list(REGISTRY)})")
        return False
    cfg = (load_config().get("platforms") or {}).get(plat, {})
    pub = REGISTRY[plat](cfg, None, _QuietLogger())
    url = getattr(pub, "compose_url", None) or LOGIN_URLS.get(plat)
    print(f"\n===== [{plat}] =====")
    print(f"即将打开专属浏览器, 登录后自动关闭窗口保存。落点: {url}")
    async with async_playwright() as p:
        kwargs = dict(headless=False, viewport={"width": 1280, "height": 900},
                      locale="zh-CN",
                      args=["--disable-blink-features=AutomationControlled"],
                      ignore_default_args=["--enable-automation"])
        ch = browser_channel()
        if ch != "chromium":
            kwargs["channel"] = ch
        ctx = await p.chromium.launch_persistent_context(pub.profile_dir, **kwargs)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        page.set_default_timeout(60000)
        await page.goto(url, wait_until="domcontentloaded")
        ok = False
        print("等待登录(最多 10 分钟, 登录成功自动继续)...")

        async def _cookie_sig():
            try:
                cs = await page.context.cookies()
                return sorted((c["name"], c["value"][:6]) for c in cs)
            except Exception:
                return None

        async def _reload():
            try:
                await page.reload(wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2500)
            except Exception:
                pass

        # 首渲染可能带旧/游客 token 显示未登录(Cookie 其实有效), 重载一次再判
        await page.wait_for_timeout(3000)
        if await pub.is_logged_in(page):
            ok = True
        else:
            await _reload()
            ok = await pub.is_logged_in(page)
        last_sig = await _cookie_sig()
        for _ in range(200):
            if ok:
                break
            await page.wait_for_timeout(3000)
            sig = await _cookie_sig()
            if sig != last_sig:      # Cookie 罐变化=登录刚完成(可能在别的tab) → 重载看真态
                last_sig = sig
                await _reload()
            try:
                if await pub.is_logged_in(page):
                    ok = True
                    break
            except Exception:
                pass
        await page.wait_for_timeout(2000)
        if ok:
            # 登录 Cookie 存成 storage_state 文件, 每次发布启动时自动注入。
            # (不少平台的登录 Cookie 是会话级, 浏览器一关就丢; 存档后永不丢)
            import json, time
            try:
                state = await ctx.storage_state()
                # 会话 Cookie 补上 30 天有效期
                for c in state.get("cookies", []):
                    if c.get("expires", -1) == -1:
                        c["expires"] = int(time.time()) + 30 * 86400
                sp = Path(pub.profile_dir).with_suffix(".state.json")
                sp.write_text(json.dumps(state), encoding="utf-8")
                print(f"  登录 Cookie 已存档: {sp} ({len(state.get('cookies', []))} 条)")
            except Exception as e:
                print("  Cookie 存档失败(登录仍在, 但可能需要偶尔重登):", e)
        await ctx.close()
    print(f"[{plat}] {'✅ 登录成功, 已保存到 ' + pub.profile_dir if ok else '❌ 未确认登录态(可重跑本命令)'}")
    return ok


class _QuietLogger:
    def info(self, m): print(" ", m)
    def warning(self, m): print(" ", m)
    def error(self, m): print(" ", m)


async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args == ["all"]:
        plats = list(REGISTRY)
    elif args:
        plats = args
    else:
        cfg = load_config()
        plats = [p for p, c in (cfg.get("platforms") or {}).items()
                 if c.get("enabled") and p in REGISTRY]
    print(f"将登录: {plats}")
    for plat in plats:
        await login_one(plat)


if __name__ == "__main__":
    asyncio.run(main())
