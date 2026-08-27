"""富途牛牛圈(q.futunn.com)专栏自动发布

入口: 首页 feed 页的"发专栏"→ 新标签页 https://q.futunn.com/editor?feed_type=4
编辑器: 标题 textarea.title-input + 正文 div.ProseMirror(与雪球同款)
图片: 页面有 input[type=file], 直接 set_input_files(不走工具栏)
发布: 右上角"发布"按钮(填入内容后出现)
"""

import re
from pathlib import Path

import content as content_mod
from .base import BrowserPublisher


class FutuPublisher(BrowserPublisher):
    name = "futu"
    profile_dir = str(Path.home() / ".futu_chrome_profile")
    compose_url = "https://q.futunn.com/editor?feed_type=4"
    logged_in_keywords = []            # 登录判据用 is_logged_in 的 URL 法

    TITLE_SEL = "textarea.title-input"
    BODY_SEL = "div.ProseMirror"

    async def is_logged_in(self, page) -> bool:
        """编辑器页未登录会被踢到 passport; 编辑器加载成功即视为已登录。"""
        try:
            if "passport" in (page.url or ""):
                return False
            for _ in range(8):
                if await page.locator(self.TITLE_SEL).count() > 0:
                    return True
                await page.wait_for_timeout(1000)
            return False
        except Exception:
            return False

    async def publish_one(self, page, article: dict, draft: bool) -> dict:
        title = content_mod.strip_stock_tags(article["title"])
        blocks = article.get("blocks", [])
        n_img = sum(1 for b in blocks if b["type"] == "image")
        self.logger.info(f"[{self.name}] 准备发: {article['id']} | 标题={title[:28]!r} "
                         f"| {len(blocks)}块/图{n_img}")

        await page.goto(self.compose_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        if not await self.wait_for_captcha(page):
            return {"ok": False, "url": "", "note": "验证码未过"}

        # 标题
        if not await self.try_fill(page, [self.TITLE_SEL], title, "标题"):
            await self._shot(page, "no_title")
            return {"ok": False, "url": "", "note": "标题框没找到(可能未登录)"}

        # 正文
        if not await self._type_body(page, blocks, article.get("dir")):
            await self._shot(page, "no_editor")
            return {"ok": False, "url": "", "note": "正文编辑器没找到"}
        await page.wait_for_timeout(1500)
        await self._shot(page, "content_filled")

        if draft:
            try:
                html = await page.evaluate(
                    "()=>document.querySelector('.ProseMirror').innerHTML")
                dump = Path(__file__).resolve().parent.parent / "logs" / "futu_draft_dump.html"
                dump.write_text(html, encoding="utf-8")
                self.logger.info(f"[{self.name}] [草稿] 已 dump → logs/futu_draft_dump.html")
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
        """富途编辑器没有正文图片的 file input(封面图 input 类型不符),
        实测可走"粘贴": 构造 ClipboardEvent 直接粘进 ProseMirror。"""
        if not src:
            return False
        path = Path(src)
        if not path.is_absolute() and art_dir:
            path = Path(art_dir) / src
        if not path.exists():
            self.logger.warning(f"[{self.name}] 配图不存在: {path}")
            return False
        try:
            import base64
            b64 = base64.b64encode(path.read_bytes()).decode()
            before = await page.locator('.ProseMirror img').count()
            await page.evaluate("""async ([b64, mime]) => {
                const blob = await (await fetch('data:' + mime + ';base64,' + b64)).blob();
                const file = new File([blob], 'img.' + (mime.split('/')[1]), {type: blob.type});
                const dt = new DataTransfer();
                dt.items.add(file);
                const ev = new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true});
                document.querySelector('.ProseMirror').dispatchEvent(ev);
            }""", [b64, "image/png" if path.suffix.lower() == ".png" else "image/jpeg"])
            for _ in range(30):
                await page.wait_for_timeout(500)
                if await page.locator('.ProseMirror img').count() > before:
                    self.logger.info(f"[{self.name}] 配图已粘贴上传: {path.name}")
                    await page.keyboard.press("ArrowRight")
                    return True
            self.logger.warning(f"[{self.name}] 配图未嵌入: {path.name}")
            return False
        except Exception as e:
            self.logger.warning(f"[{self.name}] 配图失败 {path.name}: {str(e)[:60]}")
            return False

    async def _do_publish(self, page) -> dict:
        # 真实发布按钮: 右上角 .submit-btn 文案"发表"(注意别点成"同步")
        ok = await self.try_click(page, [
            '.submit-btn',
            'button:has-text("发表")',
        ], "发表")
        if not ok:
            await self._shot(page, "no_publish")
            return {"ok": False, "url": "", "note": "发布按钮没点中"}
        # 成功标志: 页面从 /editor 跳走
        for _ in range(20):
            await page.wait_for_timeout(1000)
            try:
                url = page.url or ""
            except Exception:
                return {"ok": True, "url": "", "note": "发布后页面跳转"}
            if "/editor" not in url:
                self.logger.info(f"[{self.name}] 发布后跳转: {url[:70]}")
                return {"ok": True, "url": url, "note": ""}
        return {"ok": False, "url": "", "note": "发布结果未知(超时)"}
