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

        # 封面: 优先上传视频管线产出的 cover.png, 没有才用系统推荐帧
        await self._set_cover(page, article)

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

    async def _set_cover(self, page, article: dict) -> None:
        """封面: 优先上传 article["cover"](视频管线产出的当期封面), 否则推荐帧第 N 张。"""
        cover = article.get("cover")
        if cover and Path(cover).exists():
            await self._upload_cover(page, cover)
            return
        await self._pick_recommended_cover(page)

    async def _upload_cover(self, page, cover: str) -> None:
        """封面设置 → 编辑器"上传封面"区域 → 最后一个 file input 选图 → 完成。
        (实测: 该区域点击后 file input 动态出现, 取 .last)"""
        try:
            opened = await self._open_cover_editor(page)
            if not opened:
                self.logger.warning(f"[{self.name}] 封面设置入口没找到, 跳过封面")
                return
            await page.wait_for_timeout(2500)
            area = None
            for _ in range(8):                            # 编辑器加载慢, 最多再等 ~16s
                area = await page.evaluate("""() => {
                    for (const e of document.querySelectorAll('span,div,button')) {
                        if (e.offsetParent && e.children.length<=1
                            && (e.innerText||'').trim()==='上传封面') {
                            const r = e.getBoundingClientRect();
                            return {x: r.x + r.width/2, y: r.y + r.height/2};
                        }
                    }
                    return null;
                }""")
                if area:
                    break
                await page.wait_for_timeout(2000)
            if not area:
                raise RuntimeError("上传封面区域没找到")
            await page.mouse.click(area["x"], area["y"])
            await page.wait_for_timeout(1500)
            await page.locator('input[type=file]').last.set_input_files(str(cover))
            await page.wait_for_timeout(4000)               # 等裁剪预览生成
            clicked = await page.evaluate("""() => {
                for (const e of document.querySelectorAll('button,span,div')) {
                    if (e.offsetParent && e.children.length<=1 && (e.innerText||'').trim()==='完成') {
                        e.click(); return true;
                    }
                }
                return false;
            }""")
            if not clicked:
                raise RuntimeError("完成按钮没点中")
            self.logger.info(f"[{self.name}] 封面已上传: {Path(cover).name}")
        except Exception as e:
            self.logger.warning(f"[{self.name}] 封面上传异常({str(e)[:50]}), 改用推荐帧")
            await self._pick_recommended_cover(page)

    async def _open_cover_editor(self, page) -> bool:
        """打开封面编辑器。必须真实 locator 点击(JS 点击触发不了 React 弹层)。"""
        for entry in ('封面设置', '添加封面'):
            for _ in range(8):                             # 推荐封面要等视频处理, 最多 ~24s
                loc = page.locator(f'text={entry}').first
                if await loc.count() > 0:
                    try:
                        await loc.click(timeout=4000)
                        await page.wait_for_timeout(2000)
                        # 编辑器开着的标志: 出现"上传封面"区域或推荐缩略图
                        ok = await page.evaluate("""() =>
                            [...document.querySelectorAll('span,div')].some(e =>
                                e.offsetParent && e.children.length<=1
                                && (e.innerText||'').trim()==='上传封面')
                            || document.querySelectorAll('.img-item-cover').length > 0""")
                        if ok:
                            return True
                    except Exception:
                        pass
                await page.wait_for_timeout(3000)
        return False

    async def _pick_recommended_cover(self, page) -> None:
        """封面: 系统推荐缩略图(.img-item-cover)取第 N 张(cover_index, 默认1)。"""
        idx = max(0, int(self.config.get("cover_index", 1)) - 1)
        try:
            opened = await self._open_cover_editor(page)
            if not opened:
                self.logger.warning(f"[{self.name}] 封面设置入口没找到(视频可能还在处理), 跳过封面")
                return
            await page.wait_for_timeout(2500)
            r = await page.evaluate("""(idx) => {
                const thumbs = [...document.querySelectorAll('.img-item-cover')].filter(e=>e.offsetParent);
                if (!thumbs.length) return 0;
                thumbs[Math.min(idx, thumbs.length-1)].click();
                return thumbs.length;
            }""", idx)
            if not r:
                self.logger.warning(f"[{self.name}] 推荐封面缩略图没出现, 跳过")
                return
            await page.wait_for_timeout(1200)
            await page.evaluate("""() => {
                for (const e of document.querySelectorAll('button, span, div')) {
                    if (e.offsetParent && e.children.length<=1 && (e.innerText||'').trim()==='完成') {
                        e.click(); return;
                    }
                }
            }""")
            self.logger.info(f"[{self.name}] 封面已选: 推荐第{idx+1}张(共{r}张)")
        except Exception as e:
            self.logger.warning(f"[{self.name}] 封面设置异常(不阻断): {str(e)[:50]}")

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
