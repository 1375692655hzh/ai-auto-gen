"""长桥证券社区(longportapp.com)长文自动发布

入口: 首页 composer "写长文" → https://mp.longportapp.com/topics/new
编辑器: 标题 input.article-title(限50字) + 正文 .ck-content(CKEditor 5)
图片: input[type=file][accept*=image] 直接 set_input_files
发布: 头部"发布"按钮
"""

import re
from pathlib import Path

import content as content_mod
from .base import BrowserPublisher


class ChangqiaoPublisher(BrowserPublisher):
    name = "changqiao"
    profile_dir = str(Path.home() / ".changqiao_chrome_profile")
    compose_url = "https://mp.longportapp.com/topics/new"
    logged_in_keywords = []            # 未登录会跳登录页, 用编辑器加载判据

    TITLE_SEL = "input.article-title"
    BODY_SEL = ".ck-content"

    async def is_logged_in(self, page) -> bool:
        try:
            for _ in range(8):
                if await page.locator(self.TITLE_SEL).count() > 0:
                    return True
                await page.wait_for_timeout(1000)
            return False
        except Exception:
            return False

    async def publish_one(self, page, article: dict, draft: bool) -> dict:
        title = content_mod.strip_stock_tags(article["title"])[:50]
        blocks = article.get("blocks", [])
        n_img = sum(1 for b in blocks if b["type"] == "image")
        self.logger.info(f"[{self.name}] 准备发: {article['id']} | 标题={title[:28]!r} "
                         f"| {len(blocks)}块/图{n_img}")

        await page.goto(self.compose_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        if not await self.wait_for_captcha(page):
            return {"ok": False, "url": "", "note": "验证码未过"}

        if not await self.try_fill(page, [self.TITLE_SEL], title, "标题"):
            await self._shot(page, "no_title")
            return {"ok": False, "url": "", "note": "标题框没找到(可能未登录)"}

        if not await self._type_body(page, blocks, article.get("dir")):
            await self._shot(page, "no_editor")
            return {"ok": False, "url": "", "note": "正文编辑器没找到"}
        await page.wait_for_timeout(1500)
        # 长桥硬校验: 正文必须 >30 字, 否则"确认发布"点击静默无效
        body_len = 0
        try:
            body_len = len(await page.evaluate(
                "() => (document.querySelector('.ck-content')||{innerText:''}).innerText.replace(/\\s/g,'')"))
        except Exception:
            pass
        if body_len <= 30:
            self.logger.error(f"[{self.name}] 正文仅 {body_len} 字(长桥要求>30), 跳过发布")
            return {"ok": False, "url": "", "note": f"正文{body_len}字, 长桥要求>30字"}
        await self._shot(page, "content_filled")

        if draft:
            try:
                html = await page.evaluate(
                    "()=>document.querySelector('.ck-content').innerHTML")
                dump = Path(__file__).resolve().parent.parent / "logs" / "changqiao_draft_dump.html"
                dump.write_text(html, encoding="utf-8")
                self.logger.info(f"[{self.name}] [草稿] 已 dump → logs/changqiao_draft_dump.html")
            except Exception as e:
                self.logger.warning(f"[{self.name}] dump 失败: {e}")
            return {"ok": True, "url": "", "note": "draft(未发布)"}

        return await self._do_publish(page)

    async def _type_body(self, page, blocks, art_dir=None) -> bool:
        loc = page.locator(self.BODY_SEL).first
        if await loc.count() == 0:
            return False
        await loc.click(timeout=6000)
        await page.wait_for_timeout(400)
        first = True
        for blk in blocks:
            if blk["type"] == "hr":
                continue
            if not first:
                await page.keyboard.press("Enter")
            first = False
            if blk["type"] == "image":
                await self._upload_image(page, blk.get("src", ""), art_dir)
                continue
            if blk["type"] == "list_item":
                await page.keyboard.type("• ", delay=6)
            for run in blk.get("runs", []):
                text = content_mod.strip_stock_tags(run.get("text", ""))
                if not text:
                    continue
                if run.get("bold"):
                    await page.keyboard.press("Control+B")
                    await page.keyboard.type(text, delay=6)
                    await page.keyboard.press("Control+B")
                else:
                    await page.keyboard.type(text, delay=6)
        return True

    async def _upload_image(self, page, src, art_dir) -> bool:
        if not src:
            return False
        path = Path(src)
        if not path.is_absolute() and art_dir:
            path = Path(art_dir) / src
        if not path.exists():
            self.logger.warning(f"[{self.name}] 配图不存在: {path}")
            return False
        try:
            before = await page.locator('.ck-content img, .ck-content figure').count()
            inp = page.locator('input[type=file][accept*="image"]').first
            await inp.set_input_files(str(path))
            for _ in range(30):
                await page.wait_for_timeout(500)
                if await page.locator('.ck-content img, .ck-content figure').count() > before:
                    self.logger.info(f"[{self.name}] 配图已上传: {path.name}")
                    await page.keyboard.press("ArrowRight")
                    return True
            self.logger.warning(f"[{self.name}] 配图未嵌入: {path.name}")
            return False
        except Exception as e:
            self.logger.warning(f"[{self.name}] 配图失败 {path.name}: {str(e)[:60]}")
            return False

    async def _do_publish(self, page) -> dict:
        # 两步发布: 点"发布"→弹出"添加到合集"卡片→点"确认发布"
        if not await self.try_click(page, ['button:has-text("发布")'], "发布"):
            await self._shot(page, "no_publish")
            return {"ok": False, "url": "", "note": "发布按钮没点中"}
        await page.wait_for_timeout(1500)
        if not await self.try_click(page, ['button:has-text("确认发布")'], "确认发布"):
            await self._shot(page, "no_confirm")
            return {"ok": False, "url": "", "note": "确认发布按钮没点中"}
        # 成功: URL 从 /topics/new 变为 /topics/<id>/edit
        for _ in range(20):
            await page.wait_for_timeout(1000)
            try:
                url = page.url or ""
            except Exception:
                return {"ok": True, "url": "", "note": "发布后页面跳转"}
            if "/topics/new" not in url:
                m = re.search(r"/topics/(\d+)", url)
                tid = m.group(1) if m else ""
                final = (f"https://longportapp.com/zh-CN/topics/{tid}" if tid else url)
                self.logger.info(f"[{self.name}] 发布后跳转: {url[:70]}")
                return {"ok": True, "url": final, "note": ""}
        return {"ok": False, "url": "", "note": "发布结果未知(超时,可能正文字数不足30)"}
