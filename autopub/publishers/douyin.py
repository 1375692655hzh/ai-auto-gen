"""抖音创作者中心视频发布适配器

流程: creator.douyin.com/creator-micro/content/upload
  选文件 → 自动跳发布页(post/video) → 富文本简介(.ql-editor) →
  draft: 暂存离开 / 真发: 发布
话题: 简介里 #话题 会变成话题标签(抖音编辑器原生支持)。
文章约定: article["video"] = 视频文件路径(见 publish_video.py)
"""

from pathlib import Path

from .base import BrowserPublisher


class DouyinPublisher(BrowserPublisher):
    name = "douyin"
    profile_dir = str(Path.home() / ".douyin_chrome_profile")
    compose_url = "https://creator.douyin.com/creator-micro/content/upload"
    logged_in_keywords = ["作品发布", "创作服务"]

    async def publish_one(self, page, article: dict, draft: bool) -> dict:
        video = article.get("video")
        if not video or not Path(video).exists():
            return {"ok": False, "url": "", "note": f"视频文件不存在: {video}"}
        title = article["title"]
        # 抖音发布页有独立的"作品标题"输入框; 简介编辑器单独填(不要塞标题, 会重复)
        desc = article.get("body") or title
        tags = article.get("tags") or ["财经", "早报"]
        topic = " ".join("#" + t for t in tags)
        full_desc = (desc[:400] + "\n" + topic)[:1000]

        await page.goto(self.compose_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(6000)

        # 若发布页没出现 → 选文件上传。
        # "已有视频"的判据必须严格: 只有页面上有"重新上传/更换视频"标志才算,
        # 否则页面残留的任意 contenteditable 会误判导致跳过上传发出旧视频/空稿件
        fname = Path(video).name
        has_video = await page.evaluate(
            "() => { const t = document.body.innerText;"
            "        return t.includes('重新上传') || t.includes('更换视频'); }")
        if not has_video:
            editor = page.locator('.ql-editor, [contenteditable="true"]').first
            if await editor.count() > 0:
                # 有编辑器但没有视频标志: 可能是上次残留的空发布页, 刷新一次再传
                self.logger.warning(f"[{self.name}] 页面有编辑器但无视频(残留?), 刷新后重新上传")
                await page.goto(self.compose_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(5000)
            inp = page.locator('input[type=file][accept*="video"], input[type=file]').first
            await inp.set_input_files(str(video))
            self.logger.info(f"[{self.name}] 开始上传: {fname}")
            for _ in range(60):
                await page.wait_for_timeout(2000)
                if await page.locator('.ql-editor, [contenteditable="true"]').count() > 0:
                    break
            else:
                await self._shot(page, "no_form")
                return {"ok": False, "url": "", "note": "上传后发布页没出现"}
        else:
            self.logger.info(f"[{self.name}] 发布页已有视频(不重复上传)")
        await page.wait_for_timeout(3000)

        # 标题(独立输入框)
        for tip in ("我知道了", "知道了"):
            await self._click_text(page, tip)
        tinput = page.locator('input[placeholder*="作品标题"]').first
        if await tinput.count() > 0:
            await tinput.click()
            await tinput.fill(title)
            self.logger.info(f"[{self.name}] 标题已填: {title[:30]}")
        else:
            self.logger.warning(f"[{self.name}] 标题输入框没找到")

        # 简介(编辑器, 只放摘要+话题)
        editor = page.locator('.ql-editor, [contenteditable="true"]').first
        await editor.click(timeout=8000)
        await page.keyboard.type(full_desc, delay=10)
        self.logger.info(f"[{self.name}] 简介已填({len(full_desc)}字, 话题{len(tags)}个)")
        await self._shot(page, "form_filled")

        if draft:
            # 暂存离开: 它在固定底栏, 有时被弹层挡住 → 先关提示再点, 失败重试
            ok = False
            for _ in range(3):
                await self._click_text(page, "我知道了")
                await self._click_text(page, "知道了")
                ok = await self._click_text(page, "暂存离开")
                if ok:
                    break
                await page.wait_for_timeout(1500)
            if ok:
                self.logger.info(f"[{self.name}] 已点暂存离开")
                await page.wait_for_timeout(1500)
                await self._click_text(page, "确定", exact=True)
            return {"ok": bool(ok), "url": "", "note": "draft(暂存)" if ok else "暂存按钮没点中"}

        ok = await self._click_text(page, "发布", exact=True)
        if not ok:
            await self._shot(page, "no_publish")
            return {"ok": False, "url": "", "note": "发布按钮没点中"}
        for _ in range(20):
            await page.wait_for_timeout(1500)
            done = await page.evaluate("""() => {
                const t = document.body.innerText;
                return t.includes('发布成功') || t.includes('内容管理');
            }""")
            if done:
                return {"ok": True, "url": "", "note": "发布成功"}
        return {"ok": False, "url": "", "note": "发布结果未知(超时)"}

    async def _click_text(self, page, text: str, exact: bool = False) -> bool:
        try:
            return await page.evaluate("""([text, exact]) => {
                for (const e of document.querySelectorAll('button, [class*="btn"], span')) {
                    const t = (e.innerText || '').trim();
                    if (e.offsetParent && e.children.length <= 2
                        && (exact ? t === text : t.includes(text))) {
                        (e.closest('button') || e).click(); return true;
                    }
                }
                return false;
            }""", [text, exact])
        except Exception:
            return False
