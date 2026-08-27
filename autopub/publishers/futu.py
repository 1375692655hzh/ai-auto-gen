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
        # 文末关联股票 chip(正文抽取, 编辑器 $ 联想)
        await self._append_stock_tags(page, article)
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

    async def _append_stock_tags(self, page, article: dict) -> None:
        """文末空一行, 打 $名字 → stock-popup 联想 → 点匹配项成 nnstock chip。
        抽取失败/联想无结果 → 回退纯文本, 不卡主流程。"""
        n = int(self.config.get("stock_tags_count", 3))
        if n <= 0:
            return
        try:
            import stocks as stocks_mod
            text = article["title"] + "\n" + (article.get("body") or "")
            hits = stocks_mod.extract(text, top=n)
        except Exception as e:
            self.logger.warning(f"[{self.name}] 股票抽取失败(跳过tag): {e}")
            return
        if not hits:
            return
        # 光标移文末 + 空行
        try:
            await page.evaluate("""() => {
                const ed=document.querySelector('.ProseMirror'); if(!ed)return;
                ed.focus(); const s=window.getSelection(), r=document.createRange();
                r.selectNodeContents(ed); r.collapse(false); s.removeAllRanges(); s.addRange(r);
            }""")
            await page.keyboard.press("Enter")
        except Exception:
            pass
        ok = 0
        for code, name, market in hits:
            if await self._insert_stock_tag(page, name, code):
                ok += 1
            await page.keyboard.type(" ", delay=8)
        self.logger.info(f"[{self.name}] 文末股票chip: {ok}/{len(hits)} "
                         f"{[f'{nm}({cd})' for cd, nm, _ in hits]}")

    async def _insert_stock_tag(self, page, name: str, code: str) -> bool:
        """编辑器内打 $名字 → #stock-popup 出候选 → 点 code+name 都匹配的项。"""
        try:
            before = await page.locator('.ProseMirror .nnstock').count()
            await page.keyboard.type("$", delay=100)
            await page.wait_for_timeout(500)
            await page.keyboard.type(name, delay=80)
            for _ in range(10):                               # 最多 ~5s 等联想
                await page.wait_for_timeout(500)
                clicked = await page.evaluate("""([name, code]) => {
                    const p = document.querySelector('#stock-popup, [class*="stock-popup"]');
                    if (!p) return false;
                    const items = [...p.querySelectorAll('[class*="list__item"], [class*="item"]')];
                    for (const it of items) {
                        const t = (it.innerText || '').replace(/\\s+/g, ' ');
                        if (t.includes(code) && t.includes(name)) { it.click(); return true; }
                    }
                    return false;
                }""", [name, code])
                if clicked:
                    await page.wait_for_timeout(800)
                    if await page.locator('.ProseMirror .nnstock').count() > before:
                        return True
            # 无匹配 → 清理残留的 $名字
            await page.keyboard.press("Escape")
            for _ in range(len(name) + 1):
                await page.keyboard.press("Backspace")
            await page.keyboard.type(f"{name}({code})", delay=5)
            self.logger.warning(f"[{self.name}] 股票联想无匹配, 留纯文本: {name}")
            return False
        except Exception as e:
            self.logger.warning(f"[{self.name}] 股票tag失败 {name}: {str(e)[:50]}")
            return False

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
