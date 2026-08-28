"""知乎专栏 自动发布适配器(富文本, Draft.js + markdown 快捷输入)

  发文页 = https://zhuanlan.zhihu.com/write
  profile = ~/.zhihu_chrome_profile (复用 stock-media 登录态; 失效则弹窗登录)
  标题 = textarea[placeholder*="标题"] (最多100字)
  正文 = div.public-DraftEditor-content (Draft.js)
  ★ 知乎 markdown 快捷: 行首 "# "→h2(大标题), "## "→h3(小标题, 知乎只两级), "- "→列表; 加粗 Cmd+B(→ span font-weight:bold)
  保留 Word 格式: heading→## / 加粗→Cmd+B / 列表→- ; 图片走工具栏上传
  股票: 知乎无 cashtag, 正文"名字(代码)"留纯文本
  发布 = "发布"按钮 → 设置话题(可选)→ 确认; 成功跳 /p/{id}
"""

import re
from pathlib import Path

from .base import BrowserPublisher
import content as content_mod


class ZhihuPublisher(BrowserPublisher):
    name = "zhihu"
    # 独立 profile(不复用 stock-media 的 .zhihu_chrome_profile=财报情报站);
    # auto-publisher 固定发花街S姐, 首次弹窗手动登录
    profile_dir = str(Path.home() / ".zhihu_autopub_chrome_profile")
    compose_url = "https://zhuanlan.zhihu.com/write"
    logged_out_url_marks = ["signin", "/login"]

    TITLE_SEL = 'textarea[placeholder*="标题"]'
    BODY_SEL = '.public-DraftEditor-content'
    TITLE_MAX = 100
    skip_images = False      # 配图已调通: 工具栏图片→模态input→插入图片

    async def is_logged_in(self, page) -> bool:
        try:
            url = (page.url or "").lower()
            if any(m in url for m in self.logged_out_url_marks):
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
        if len(title) > self.TITLE_MAX:
            title = title[: self.TITLE_MAX]
        blocks = article.get("blocks", [])
        # 图表缺口补全: 知乎图片常传不上, 把依赖图表的位置用文字说明替代(保留标题/加粗等格式不动)
        if self.config.get("fill_chart_gaps", True) and any(b["type"] == "image" for b in blocks):
            try:
                import chart_gap
                # 表格图人工转写(articles/_tables/<文章名>.json), 表格类图最可靠地文字化
                trans = chart_gap.load_transcriptions(article["id"])
                blocks = chart_gap.fill_chart_gaps(blocks, self.logger, transcriptions=trans)
            except Exception as e:
                self.logger.warning(f"[{self.name}] 图表补全失败(用原blocks): {e}")
        n_head = sum(1 for b in blocks if b["type"] == "heading")
        n_img = sum(1 for b in blocks if b["type"] == "image")
        self.logger.info(f"[{self.name}] 准备发: {article['id']} | 标题={title[:28]!r} "
                         f"| {len(blocks)}块(标题{n_head}/图{n_img})")

        await page.goto(self.compose_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        if not await self.wait_for_captcha(page):
            return {"ok": False, "url": "", "note": "验证码未过"}

        # 标题
        try:
            t = page.locator(self.TITLE_SEL).first
            await t.click(timeout=8000)
            await t.fill(title)
        except Exception as e:
            await self._shot(page, "no_title")
            return {"ok": False, "url": "", "note": f"标题框未找到: {e}"}
        await page.wait_for_timeout(800)

        # 正文(Draft.js + markdown 快捷)
        if not await self._type_body(page, blocks, article.get("dir")):
            await self._shot(page, "no_editor")
            return {"ok": False, "url": "", "note": "正文编辑器未找到"}
        await page.wait_for_timeout(1500)
        await self._shot(page, "content_filled")

        if draft:
            try:
                html = await page.evaluate(f"()=>document.querySelector('{self.BODY_SEL}').innerHTML")
                dump = Path(__file__).resolve().parent.parent / "logs" / "zhihu_draft_dump.html"
                dump.write_text(html, encoding="utf-8")
                tags = {t: len(re.findall(f"<{t}[ >]", html)) for t in ("h2", "h3", "li", "img")}
                bold = html.count("font-weight: bold")
                self.logger.info(f"[{self.name}] [草稿]HTML: {tags} 加粗{bold} → logs/zhihu_draft_dump.html")
            except Exception as e:
                self.logger.warning(f"[{self.name}] dump 失败: {e}")
            return {"ok": True, "url": "", "note": "draft(未发布)"}

        return await self._do_publish(page)

    async def _type_body(self, page, blocks, art_dir=None) -> bool:
        """两遍法: Pass1 全部正文一次性输完(图位置留占位标记行, 100%完整不受图影响);
        Pass2 找占位行逐个插图(失败跳过, 绝不动已输完的正文)。"""
        ed = page.locator(self.BODY_SEL).first
        if await ed.count() == 0:
            return False
        await ed.click(timeout=8000)
        await page.wait_for_timeout(400)

        # ===== Pass1: 输入全部正文, 图位置打唯一占位标记 =====
        # 知乎 Draft.js 列表会自动续行: "- " 起 bullet 后每次 Enter 续 bullet 且不退出。
        # 所以: 进列表只打一次 "- "(列表内不再打, 否则变字面文本);
        #       退出列表(下一块非列表)要按两次 Enter(空 bullet→普通段落), 否则后续标题/正文全被吸进列表、markdown 不触发。
        heads = 0
        img_marks = []          # [(mark_text, src)]
        first = True
        prev_list = False       # 上一块是不是列表项
        img_idx = 0
        for blk in blocks:
            if blk["type"] == "hr":
                continue
            is_list = blk["type"] == "list_item"
            if blk["type"] == "image":
                if self.skip_images:
                    continue
                if not first:
                    await page.keyboard.press("Enter")
                    if prev_list:                       # 从列表出来: 多按一次退出 bullet
                        await page.keyboard.press("Enter")
                first = False
                prev_list = False
                mark = f"@@IMG{img_idx}@@"      # 唯一占位标记(纯ASCII, 正文不会出现)
                img_marks.append((mark, blk.get("src", "")))
                await page.keyboard.type(mark, delay=10)
                img_idx += 1
                continue
            # 文本/标题/列表
            if not first:
                await page.keyboard.press("Enter")
                if prev_list and not is_list:           # 从列表→非列表: 再按一次 Enter 退出 bullet
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(80)
            first = False
            if blk["type"] == "heading":
                # 知乎只有两级标题: "# "→h2(大), "## "→h3(小)。
                # 原文 H1(一、二、章节)→大标题; H2/H3(2.1 小节)→小标题。保留两级层级。
                prefix = "# " if blk.get("level", 2) <= 1 else "## "
                await page.keyboard.type(prefix, delay=40)
                await page.wait_for_timeout(120)
                heads += 1
            elif is_list and not prev_list:
                # 仅"进入列表"时打 "- "; 列表内靠 Enter 自动续 bullet, 不能再打 "- "(会变字面)
                await page.keyboard.type("- ", delay=40)
                await page.wait_for_timeout(120)
            await self._type_runs(page, blk.get("runs", []), is_heading=(blk["type"] == "heading"))
            prev_list = is_list
        self.logger.info(f"[{self.name}] Pass1 正文已输入(块{len(blocks)} 标题{heads} 图占位{len(img_marks)})")

        # ===== Pass2: 逐个占位标记 → 选中替换为图片(失败则把标记删掉, 不留垃圾) =====
        imgs_ok = imgs_fail = 0
        if not self.skip_images:
            for mark, src in img_marks:
                if await self._replace_mark_with_image(page, mark, src, art_dir):
                    imgs_ok += 1
                else:
                    imgs_fail += 1
        # 兜底: 清掉所有残留占位标记(@@IMGn@@), 防止失败的图留下标记文本
        try:
            await page.evaluate("""() => {
                const ed = document.querySelector('.public-DraftEditor-content');
                if (!ed) return;
                const walker = document.createTreeWalker(ed, NodeFilter.SHOW_TEXT);
                let node;
                while ((node = walker.nextNode())) {
                    if (/@@IMG\\d+@@/.test(node.nodeValue))
                        node.nodeValue = node.nodeValue.replace(/@@IMG\\d+@@/g, '');
                }
            }""")
        except Exception:
            pass
        self.logger.info(f"[{self.name}] Pass2 配图: 成功{imgs_ok}/失败{imgs_fail}")
        return True

    async def _replace_mark_with_image(self, page, mark, src, art_dir) -> bool:
        """定位占位标记文本 → 选中删除 → 在该位置插图。失败则只删标记(不影响正文)。"""
        from pathlib import Path as _P
        path = _P(src)
        if not path.is_absolute() and art_dir:
            path = _P(art_dir) / src
        # 把光标定位到标记处并选中标记(用浏览器查找选区)
        located = await page.evaluate("""(mark) => {
            const ed = document.querySelector('.public-DraftEditor-content');
            if (!ed) return false;
            // 在编辑器里找含 mark 的文本节点
            const walker = document.createTreeWalker(ed, NodeFilter.SHOW_TEXT);
            let node;
            while ((node = walker.nextNode())) {
                const i = node.nodeValue.indexOf(mark);
                if (i >= 0) {
                    const r = document.createRange();
                    r.setStart(node, i);
                    r.setEnd(node, i + mark.length);
                    const s = window.getSelection();
                    s.removeAllRanges(); s.addRange(r);
                    return true;
                }
            }
            return false;
        }""", mark)
        if not located:
            return False
        # 删掉标记(选中态按删除)→ 光标停在原位置
        await page.keyboard.press("Backspace")
        await page.wait_for_timeout(200)
        if not path.exists():
            self.logger.warning(f"[{self.name}] 配图不存在: {path}")
            return False
        # 在当前光标位置插图
        ok = await self._upload_image_at_cursor(page, str(path))
        return ok

    async def _focus_end(self, page):
        """把光标焦点强制移到编辑器内容末尾(图片上传/模态后焦点会跑掉, 防后续正文打到别处)。"""
        try:
            ed = page.locator(self.BODY_SEL).first
            await ed.click(timeout=4000)
            await page.evaluate("""(sel) => {
                const ed = document.querySelector(sel);
                if (!ed) return;
                ed.focus();
                const s = window.getSelection(), r = document.createRange();
                r.selectNodeContents(ed); r.collapse(false);
                s.removeAllRanges(); s.addRange(r);
            }""", self.BODY_SEL)
            await page.keyboard.press("End")
        except Exception:
            pass

    async def _type_runs(self, page, runs, is_heading=False):
        for r in runs:
            text = r.get("text", "")
            if r.get("stock"):
                text = r["stock"][1]               # 知乎无cashtag, 用显示名
            if not text:
                continue
            bold = r.get("bold") and not is_heading  # 标题不额外加粗(本身大)
            italic = r.get("italic") and not is_heading
            if bold:
                await page.keyboard.press("ControlOrMeta+b")
            if italic:
                await page.keyboard.press("ControlOrMeta+i")
            await page.keyboard.type(text, delay=4)
            if italic:
                await page.keyboard.press("ControlOrMeta+i")
            if bold:
                await page.keyboard.press("ControlOrMeta+b")

    async def _upload_image(self, page, src, art_dir) -> bool:
        """知乎配图: 点工具栏图片按钮 → 模态 input setInputFiles → 点"插入图片"。"""
        if not src:
            return False
        path = Path(src)
        if not path.is_absolute() and art_dir:
            path = Path(art_dir) / src
        if not path.exists():
            self.logger.warning(f"[{self.name}] 配图不存在: {path}")
            return False
        try:
            before = await page.locator(f'{self.BODY_SEL} img').count()
            # 点工具栏"图片"按钮(可能弹模态, 也可能直接 filechooser)
            btn = page.locator('button.ToolbarButton').filter(has_text="图片").first
            try:
                async with page.expect_file_chooser(timeout=4000) as fc:
                    await btn.click()
                ch = await fc.value
                await ch.set_files(str(path))
            except Exception:
                # 弹的是模态 → 喂模态内 file input
                await page.wait_for_timeout(1500)
                inp = page.locator('input[type="file"]').last
                await inp.set_input_files(str(path))
            await page.wait_for_timeout(3000)        # 等上传到知乎CDN
            # 模态里点"插入图片"
            for lab in ("插入图片", "插入", "确定"):
                b = page.locator(f'button:has-text("{lab}")').first
                try:
                    if await b.count() > 0 and await b.is_visible():
                        await b.click(timeout=3000)
                        break
                except Exception:
                    continue
            for _ in range(20):                      # 等图进编辑器
                await page.wait_for_timeout(500)
                if await page.locator(f'{self.BODY_SEL} img').count() > before:
                    self.logger.info(f"[{self.name}] 配图已上传: {path.name}")
                    await page.keyboard.press("End")
                    return True
            self.logger.warning(f"[{self.name}] 配图未嵌入: {path.name}")
            await self._close_img_modal(page)
            return False
        except Exception as e:
            self.logger.warning(f"[{self.name}] 配图失败 {path.name}: {str(e)[:60]}")
            await self._close_img_modal(page)
            return False

    async def _upload_image_at_cursor(self, page, path_str) -> bool:
        """在当前光标位置插图(光标已由 Pass2 定位到占位处)。机制同 _upload_image。"""
        try:
            before = await page.locator(f'{self.BODY_SEL} img').count()
            btn = page.locator('button.ToolbarButton').filter(has_text="图片").first
            try:
                async with page.expect_file_chooser(timeout=4000) as fc:
                    await btn.click()
                ch = await fc.value
                await ch.set_files(path_str)
            except Exception:
                await page.wait_for_timeout(1500)
                inp = page.locator('input[type="file"]').last
                await inp.set_input_files(path_str)
            await page.wait_for_timeout(3000)
            for lab in ("插入图片", "插入", "确定"):
                b = page.locator(f'button:has-text("{lab}")').first
                try:
                    if await b.count() > 0 and await b.is_visible():
                        await b.click(timeout=3000)
                        break
                except Exception:
                    continue
            for _ in range(20):
                await page.wait_for_timeout(500)
                if await page.locator(f'{self.BODY_SEL} img').count() > before:
                    self.logger.info(f"[{self.name}] 配图已插入(占位处): {path_str.split('/')[-1]}")
                    return True
            self.logger.warning(f"[{self.name}] 配图未嵌入: {path_str.split('/')[-1]}")
            await self._close_img_modal(page)
            return False
        except Exception as e:
            self.logger.warning(f"[{self.name}] 配图失败: {str(e)[:50]}")
            await self._close_img_modal(page)
            return False

    async def _close_img_modal(self, page):
        """关掉图片上传模态(取消/关闭/Escape), 防止挡住编辑器导致后续正文丢。"""
        for sel in ['button:has-text("取消")', '[class*="Modal"] [class*="close"]', '[class*="close"]']:
            try:
                c = page.locator(sel).first
                if await c.count() > 0 and await c.is_visible():
                    await c.click(timeout=2000)
                    await page.wait_for_timeout(300)
                    return
            except Exception:
                continue
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(300)
        except Exception:
            pass

    async def _do_publish(self, page) -> dict:
        def published():
            return bool(re.search(r"zhihu\.com/p/\d+", page.url)) and "/edit" not in page.url

        # 点"发布"露出设置面板
        opened = await self.try_click(
            page, ['button:has-text("发布")'], "发布")
        if not opened:
            await self._shot(page, "no_publish")
            return {"ok": False, "url": "", "note": "发布按钮未找到"}
        await page.wait_for_timeout(2500)
        await self._shot(page, "publish_panel")

        # 设置面板里最终"发布" + 风控处理
        for _ in range(2):
            try:
                b = page.get_by_role("button", name="发布", exact=True).last
                if await b.count() > 0:
                    await b.click(timeout=5000)
            except Exception:
                pass
            await page.wait_for_timeout(4000)
            if published():
                break
            await self.wait_for_captcha(page)
            if published():
                break
            await page.wait_for_timeout(2000)

        await page.wait_for_timeout(1500)
        await self._shot(page, "result")
        if published():
            return {"ok": True, "url": page.url, "note": "知乎发布成功(/p/确认)"}
        return {"ok": False, "url": page.url, "note": f"未跳 /p/(仍在 {page.url})"}
