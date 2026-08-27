"""微博(weibo.com)自动发布 —— 首页 composer(文字 + 图片)

形态:「头条文章」(card.weibo.com/article)已下线, 现用首页发微博框:
  文本框 textarea[placeholder*="新鲜事"] + 图片 input[type=file][accept*=image]
适合发"早报长图 + 简介文字"的短内容; 长文拆条不在此做。
风控: 微博检测最严, 篇间隔和日上限保持保守(config 默认 8)。
"""

import re
from pathlib import Path

import content as content_mod
from .base import BrowserPublisher


class WeiboPublisher(BrowserPublisher):
    name = "weibo"
    profile_dir = str(Path.home() / ".weibo_chrome_profile")
    compose_url = "https://weibo.com/"
    logged_in_keywords = ["发微博", "我的主页", "首页"]

    BOX_SEL = 'textarea[placeholder*="新鲜事"]'

    async def publish_one(self, page, article: dict, draft: bool) -> dict:
        title = content_mod.strip_stock_tags(article["title"])
        blocks = article.get("blocks", [])
        # 文字 = 标题 + 正文拼成一条(微博以图为主文字为辅)
        texts = []
        for blk in blocks:
            if blk["type"] == "image":
                continue
            t = "".join(r.get("text", "") for r in blk.get("runs", []))
            t = content_mod.strip_stock_tags(t).strip()
            if t:
                texts.append(("• " if blk["type"] == "list_item" else "") + t)
        body = title + "\n" + "\n".join(texts)
        imgs = [b for b in blocks if b["type"] == "image"]
        self.logger.info(f"[{self.name}] 准备发: {article['id']} | 文字{len(body)}字 图{len(imgs)}张")

        await page.goto(self.compose_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        if not await self.wait_for_captcha(page):
            return {"ok": False, "url": "", "note": "验证码未过"}

        box = page.locator(self.BOX_SEL).first
        if await box.count() == 0:
            await self._shot(page, "no_box")
            return {"ok": False, "url": "", "note": "发微博框没找到(可能未登录)"}
        await box.click(timeout=8000)
        await page.wait_for_timeout(500)
        await page.keyboard.type(body[:2000], delay=6)
        await page.wait_for_timeout(500)

        # 配图(最多9张)
        imgs_ok = 0
        for blk in imgs[:9]:
            if await self._upload_image(page, blk.get("src", ""), article.get("dir")):
                imgs_ok += 1
        self.logger.info(f"[{self.name}] 配图: 成功{imgs_ok}/{len(imgs)}")

        await page.wait_for_timeout(1000)
        await self._shot(page, "content_filled")
        if draft:
            return {"ok": True, "url": "", "note": "draft(未发布)"}

        ok = await self.try_click(page, ['button:has-text("发送")', 'a:has-text("发送")'], "发送")
        if not ok:
            await self._shot(page, "no_send")
            return {"ok": False, "url": "", "note": "发送按钮没点中"}
        # 成功提示: toast 或输入框清空
        for _ in range(15):
            await page.wait_for_timeout(1000)
            try:
                txt = await page.evaluate("""() => {
                    for (const e of document.querySelectorAll('[class*="toast"],[class*="Toast"],[class*="message"],[class*="Message"],[class*="result"]')) {
                        const t=(e.innerText||'').trim();
                        if (t && (t.includes('成功')||t.includes('失败'))) return t;
                    }
                    return '';
                }""")
                boxval = await page.evaluate(
                    "() => (document.querySelector('textarea')||{value:'x'}).value")
                if txt or boxval == "":
                    if txt and "失败" in txt:
                        return {"ok": False, "url": "", "note": txt}
                    self.logger.info(f"[{self.name}] 发布成功: {txt or '输入框已清空'}")
                    return {"ok": True, "url": "", "note": txt}
            except Exception:
                pass
        return {"ok": False, "url": "", "note": "发布结果未知(超时)"}

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
            # 上传成功的预览在 [class*="picbed"] 容器里(上传后生成 sinaimg 链接)
            def _n():
                return page.locator('[class*="picbed"] img, [class*="pic"] img[src*="sinaimg"]').count()
            before = await _n()
            inp = page.locator('input[type=file][accept*="image"]').first
            await inp.set_input_files(str(path))
            for _ in range(30):
                await page.wait_for_timeout(500)
                if await _n() > before:
                    self.logger.info(f"[{self.name}] 配图已上传: {path.name}")
                    return True
            self.logger.warning(f"[{self.name}] 配图未确认: {path.name}")
            return False
        except Exception as e:
            self.logger.warning(f"[{self.name}] 配图失败 {path.name}: {str(e)[:60]}")
            return False
