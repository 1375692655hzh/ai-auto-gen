"""BrowserPublisher —— 所有平台适配器的通用底座

封装从雪球/知乎验证过的 7 件套里的浏览器部分:
  - 启本机真 Chrome + 独立 profile + 反风控
  - 登录态轮询(等你手动登录)
  - 验证码/安全验证暂停(等你手动过)
  - 逐篇发布循环 + 节流 + 连续失败熔断 + 日上限
  - 截图留证

子类只需:
  类属性: name / profile_dir / compose_url / logged_in_keywords
  实现:   async publish_one(self, page, article, draft) -> dict(ok, url, note)
  可选覆盖: is_logged_in / 各种 selector
"""

import os
import sys
import shutil
import asyncio
from pathlib import Path
from datetime import datetime

SCREENSHOT_DIR = Path(__file__).resolve().parent.parent / "logs" / "screenshots"


def find_chrome() -> str:
    """跨平台找本机 Google Chrome 可执行文件。找不到返回 ""(改用 playwright 自带 Chromium)。"""
    cands = []
    if sys.platform == "darwin":                      # macOS
        cands = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    elif sys.platform.startswith("win"):              # Windows
        pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        pfx86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        cands = [
            os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(pfx86, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(local, r"Google\Chrome\Application\chrome.exe"),
        ]
    else:                                             # Linux
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            p = shutil.which(name)
            if p:
                cands.append(p)
        cands += ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
                  "/usr/bin/chromium-browser", "/usr/bin/chromium"]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return ""


class BrowserPublisher:
    name = "base"
    profile_dir = None                  # str(Path.home()/".xxx_chrome_profile")
    compose_url = None                  # 发文页 URL
    logged_in_keywords = []             # 页面含任一关键词 => 已登录
    logged_out_url_marks = ["signin", "/login", "/passport"]
    captcha_keywords = ["访问验证", "请按住滑块", "拖动滑块", "安全验证",
                        "行为异常", "请完成验证", "滑动验证"]

    def __init__(self, config: dict, state, logger):
        self.config = config or {}
        self.state = state
        self.logger = logger
        self.max_daily = int(self.config.get("max_daily", 10))
        self.stock_tags = self.config.get("stock_tags", "keep")

    # ---------- 子类实现 ----------

    async def publish_one(self, page, article: dict, draft: bool) -> dict:
        """返回 {"ok": bool, "url": str, "note": str}。子类必须实现。"""
        raise NotImplementedError

    async def prepare(self, page) -> None:
        """登录后、发布前的一次性准备(子类可覆盖,如抓热议榜)。默认无操作。"""
        return

    def resolve_title(self, article: dict) -> str:
        """取本平台标题: 若 title_overrides.json 有 {article_id: {platform: 标题}} 则用覆盖, 否则原标题。"""
        import json
        from pathlib import Path
        raw = article.get("title", "")
        try:
            ov = Path(__file__).resolve().parent.parent / "title_overrides.json"
            if ov.exists():
                m = json.loads(ov.read_text(encoding="utf-8"))
                t = (m.get(article.get("id", ""), {}) or {}).get(self.name)
                if t:
                    self.logger.info(f"[{self.name}] 标题覆盖: {t!r}")
                    return t
        except Exception:
            pass
        return raw

    # ---------- 登录态 ----------

    async def is_logged_in(self, page) -> bool:
        """默认判据:URL 不在登录页 + 页面含 logged_in_keywords 任一。"""
        try:
            url = (page.url or "").lower()
            if any(m in url for m in self.logged_out_url_marks):
                return False
            if not self.logged_in_keywords:
                return True
            html = await page.content()
            return any(kw in html for kw in self.logged_in_keywords)
        except Exception:
            return False

    async def wait_for_login(self, page, timeout_seconds: int = 240) -> bool:
        """打开发文页;未登录则提示手动登录并轮询。"""
        await page.goto(self.compose_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)
        if await self.is_logged_in(page):
            self.logger.info(f"[{self.name}] 已登录")
            return True

        self.logger.info("=" * 50)
        self.logger.info(f"[{self.name}] 需要登录!请在弹出的 Chrome 里手动完成登录")
        self.logger.info(f"登录成功后自动继续(最多等 {timeout_seconds}s)...")
        self.logger.info("=" * 50)
        await self._shot(page, "login")

        for _ in range(timeout_seconds // 3):
            await page.wait_for_timeout(3000)
            if await self.is_logged_in(page):
                self.logger.info(f"[{self.name}] 登录成功")
                await page.wait_for_timeout(2000)
                return True
        await self._shot(page, "login_timeout")
        self.logger.error(f"[{self.name}] 登录超时;当前 URL={page.url}")
        return False

    # ---------- 验证码/风控 ----------

    async def wait_for_captcha(self, page, timeout_seconds: int = 180) -> bool:
        """检测验证码/安全验证;有就截图 + 暂停等手动完成。True=无验证或已过。"""
        async def _blocked() -> bool:
            try:
                html = await page.content()
                return any(kw in html for kw in self.captcha_keywords)
            except Exception:
                return False

        if not await _blocked():
            return True
        self.logger.warning("=" * 50)
        self.logger.warning(f"[{self.name}] 触发验证码/安全验证!请在 Chrome 里手动完成")
        self.logger.warning(f"完成后自动继续(最多 {timeout_seconds}s)...")
        self.logger.warning("=" * 50)
        await self._shot(page, "captcha")
        for _ in range(timeout_seconds // 2):
            await page.wait_for_timeout(2000)
            if not await _blocked():
                self.logger.info(f"[{self.name}] 验证已通过")
                await page.wait_for_timeout(1500)
                return True
        self.logger.error(f"[{self.name}] 验证等待超时")
        return False

    # ---------- 主循环 ----------

    async def run(self, articles: list, draft: bool = False,
                  min_interval_seconds: int = 60,
                  max_consecutive_failures: int = 3):
        """启浏览器 → 登录 → 逐篇发。articles 已按需过滤(未发过的)。"""
        from playwright.async_api import async_playwright
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as p:
            launch_kwargs = dict(
                headless=False,
                viewport={"width": 1280, "height": 800},
                locale="zh-CN",
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],
            )
            chrome = find_chrome()
            if chrome:
                launch_kwargs["executable_path"] = chrome
                self.logger.info(f"[{self.name}] 使用本机 Chrome: {chrome}")
            else:
                # 没装独立 Chrome → 用 playwright 自带 Chromium(需先 playwright install chromium)
                self.logger.info(f"[{self.name}] 未找到本机 Chrome,改用 playwright 自带 Chromium")
            context = await p.chromium.launch_persistent_context(
                self.profile_dir, **launch_kwargs)
            # 抹掉自动化特征(风控检测 navigator.webdriver)
            await context.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            self.logger.info(f"[{self.name}] 浏览器 profile: {self.profile_dir}")
            page = context.pages[0] if context.pages else await context.new_page()
            page.set_default_timeout(60000)

            try:
                if not await self.wait_for_login(page):
                    return
                try:
                    await self.prepare(page)          # 发布前准备(如抓热议榜)
                except Exception as e:
                    self.logger.warning(f"[{self.name}] prepare 失败(不阻断): {e}")
                published = 0
                consecutive_failures = 0
                for article in articles:
                    if published >= self.max_daily:
                        self.logger.warning(
                            f"[{self.name}] 达单次上限 {self.max_daily},其余改天")
                        break
                    if consecutive_failures >= max_consecutive_failures:
                        self.logger.error(f"[{self.name}] 连续失败 {max_consecutive_failures} 次,停")
                        break
                    try:
                        result = await self.publish_one(page, article, draft)
                    except Exception as e:
                        result = {"ok": False, "url": "", "note": f"异常: {e}"}
                        self.logger.error(f"[{self.name}] 发布异常 ({article['id']}): {e}")
                        await self._shot(page, "exception")

                    if draft:
                        self.logger.info(f"[{self.name}] [草稿] {article['id']} 已填充+截图,未真发")
                    elif result.get("ok"):
                        published += 1
                        consecutive_failures = 0
                        self.state.mark(article["id"], self.name, "published",
                                        url=result.get("url", ""), note=result.get("note", ""))
                        self.logger.info(f"[{self.name}] 发布成功: {article['id']} {result.get('url','')}")
                    else:
                        consecutive_failures += 1
                        self.state.mark(article["id"], self.name, "failed",
                                        note=result.get("note", ""))
                        self.logger.error(f"[{self.name}] 发布失败: {article['id']} {result.get('note','')}")

                    # 篇间等待
                    if article is not articles[-1]:
                        await page.wait_for_timeout(min_interval_seconds * 1000)
                self.logger.info(f"[{self.name}] 本次完成,成功 {published}/{len(articles)}")
            except Exception as e:
                self.logger.error(f"[{self.name}] 流程异常: {e}")
            finally:
                await context.close()

    # ---------- 工具 ----------

    async def _shot(self, page, tag: str):
        try:
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%H%M%S")
            await page.screenshot(path=str(SCREENSHOT_DIR / f"{self.name}_{tag}_{ts}.png"))
        except Exception:
            pass

    async def try_fill(self, page, selectors, text: str, what: str) -> bool:
        """对一组候选 selector 逐个尝试 click+输入,成功即返回 True。"""
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() == 0:
                    continue
                await loc.click(timeout=6000)
                await page.wait_for_timeout(400)
                # 优先 fill(input/textarea),不行就键盘逐字(contenteditable)
                try:
                    await loc.fill(text, timeout=4000)
                except Exception:
                    await page.keyboard.type(text, delay=8)
                self.logger.info(f"[{self.name}] {what} 已填入 (selector={sel})")
                return True
            except Exception:
                continue
        self.logger.error(f"[{self.name}] {what} 没找到输入框(试了 {len(selectors)} 个 selector)")
        return False

    async def try_click(self, page, selectors, what: str) -> bool:
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() == 0:
                    continue
                await loc.click(timeout=6000)
                self.logger.info(f"[{self.name}] 已点击 {what} (selector={sel})")
                return True
            except Exception:
                continue
        self.logger.error(f"[{self.name}] {what} 按钮没点中(试了 {len(selectors)} 个 selector)")
        return False
