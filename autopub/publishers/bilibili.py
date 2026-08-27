"""B站(bilibili)视频投稿适配器

流程: member.bilibili.com/platform/upload/video/frame
  选文件(多文件累加!先查队列避免重复) → 等表单 → 标题 → 标签(联想) →
  分区(通常按标题自动推荐; 可配 zones 默认点选) → 存草稿(draft) / 立即投稿
文章约定: article["video"] = 视频文件路径(见 publish_video.py)
"""

import asyncio
from pathlib import Path

from .base import BrowserPublisher


class BilibiliPublisher(BrowserPublisher):
    name = "bilibili"
    profile_dir = str(Path.home() / ".bilibili_chrome_profile")
    compose_url = "https://member.bilibili.com/platform/upload/video/frame"
    logged_in_keywords = ["投稿"]

    async def publish_one(self, page, article: dict, draft: bool) -> dict:
        video = article.get("video")
        if not video or not Path(video).exists():
            return {"ok": False, "url": "", "note": f"视频文件不存在: {video}"}
        title = article["title"][:80]
        tags = article.get("tags") or ["财经", "早报"]

        await page.goto(self.compose_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(6000)

        # 队列检查(上传框是多文件累加, 已有视频绝不重复选文件!)
        has_item = await page.evaluate(
            "() => document.body.innerText.includes('重新上传') || "
            "document.body.innerText.includes('上传完成')")
        if not has_item:
            inp = page.locator('input[type=file][accept*="mp4"]').first
            await inp.set_input_files(str(video))
            self.logger.info(f"[{self.name}] 开始上传: {Path(video).name} "
                             f"({Path(video).stat().st_size // 1024}KB)")
        else:
            self.logger.info(f"[{self.name}] 上传队列已有视频, 不重复上传")

        # 等表单出现(标题框)
        for _ in range(60):
            await page.wait_for_timeout(2000)
            if await page.locator('input[placeholder*="标题"]').count() > 0:
                break
        else:
            await self._shot(page, "no_form")
            return {"ok": False, "url": "", "note": "上传后表单没出现"}
        await page.wait_for_timeout(2000)

        # 标题
        t = page.locator('input[placeholder*="标题"]').first
        await t.click()
        await t.fill("")
        await t.fill(title)
        self.logger.info(f"[{self.name}] 标题已填: {title[:30]}")

        # 标签(逐个: 输入→联想→点选)
        ok_tags = 0
        for tag in tags[:10]:
            if await self._add_tag(page, tag):
                ok_tags += 1
        self.logger.info(f"[{self.name}] 标签: {ok_tags}/{len(tags[:10])}")

        # 分区: 页面常按标题自动推荐(hot-tag 自动选中); 没有就点配置的默认分区
        await self._ensure_zone(page)

        await self._shot(page, "form_filled")
        if draft:
            await self._click_text_btn(page, "存草稿")
            return {"ok": True, "url": "", "note": "draft(存草稿)"}
        ok = await self._click_text_btn(page, "立即投稿")
        if not ok:
            return {"ok": False, "url": "", "note": "立即投稿按钮没点中"}
        # 等成功提示/跳转
        for _ in range(20):
            await page.wait_for_timeout(1500)
            txt = await page.evaluate(
                "() => document.body.innerText.includes('稿件投递成功') || "
                "document.body.innerText.includes('投稿成功')")
            if txt:
                return {"ok": True, "url": "", "note": "投稿成功"}
        return {"ok": False, "url": "", "note": "投稿结果未知(超时)"}

    async def _add_tag(self, page, tag: str) -> bool:
        try:
            box = page.locator('input[placeholder*="标签"]').first
            if await box.count() == 0:
                return False
            await box.click()
            await box.fill(tag)
            await page.wait_for_timeout(1200)
            # 联想列表第一项
            item = page.locator(
                '[class*="tag-suggest"] li, [class*="tagSuggest"] li, '
                '[class*="suggest"] [class*="item"]').first
            if await item.count() > 0:
                await item.click(timeout=3000)
                return True
            await page.keyboard.press("Enter")
            return True
        except Exception as e:
            self.logger.warning(f"[{self.name}] 标签 {tag} 失败: {str(e)[:40]}")
            return False

    async def _ensure_zone(self, page) -> None:
        """分区: 已自动推荐则跳过; 否则点 config zones 里的默认链(如 ['资讯'])."""
        try:
            zones = self.config.get("zones") or ["资讯"]
            cur = await page.evaluate("""() => {
                for (const e of document.querySelectorAll('[class*="zone"] [class*="selected"], '
                     + '[class*="select-item-cont"]')) {
                    if (e.offsetParent) return (e.innerText||'').trim();
                }
                return '';
            }""")
            if cur:
                self.logger.info(f"[{self.name}] 分区已选: {cur}")
                return
            for z in zones:
                clicked = await self._click_text_btn(page, z, exact=True)
                if clicked:
                    await page.wait_for_timeout(1000)
        except Exception as e:
            self.logger.warning(f"[{self.name}] 分区选择异常(不阻断): {e}")

    async def _click_text_btn(self, page, text: str, exact: bool = False) -> bool:
        try:
            r = await page.evaluate("""([text, exact]) => {
                for (const e of document.querySelectorAll('button, [class*="btn"], span, a')) {
                    const t = (e.innerText || '').trim();
                    if (e.offsetParent && e.children.length <= 2
                        && (exact ? t === text : t.includes(text))) {
                        (e.closest('button') || e).click(); return true;
                    }
                }
                return false;
            }""", [text, exact])
            if r:
                self.logger.info(f"[{self.name}] 已点击 {text}")
            return r
        except Exception:
            return False
