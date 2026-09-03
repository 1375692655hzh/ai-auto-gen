"""微博 长文(头条文章)自动发布 —— card.weibo.com 文章编辑器

2026-09-01 重写: 弃用首页"发短微博框"(只适合短内容+九图), 改走头条文章编辑器。
  编辑器 = https://card.weibo.com/article/v5/editor (裸进会续用最近一份草稿)
  新文章 = 落地后点「写文章」→ 自动生成全新空草稿(#/draft/<新id>), 不覆盖旧草稿
  标题   = textarea[placeholder="请输入标题"]
  导语   = textarea[placeholder="导语（选填）"] (选填, 不填)
  正文   = div.ProseMirror (tiptap 富文本, 支持加粗/斜体)
  发布   = 「下一步」→ 确认页的「发布」
  登录铁判据 = 编辑器页有标题框(未登录会被甩到 newlogin 落地页)
风控: 微博检测最严, 篇间隔和日上限保持保守(config 默认 8)。
"""

import re
from pathlib import Path

import content as content_mod
from .base import BrowserPublisher


class WeiboPublisher(BrowserPublisher):
    name = "weibo"
    profile_dir = str(Path.home() / ".weibo_chrome_profile")
    compose_url = "https://card.weibo.com/article/v5/editor"
    logged_out_url_marks = ["signin", "/login", "/passport", "newlogin"]

    TITLE_SEL = 'textarea[placeholder="请输入标题"]'
    LEAD_SEL = 'textarea[placeholder="导语（选填）"]'
    BODY_SEL = 'div.ProseMirror[contenteditable="true"]'
    NEW_ARTICLE_SEL = ['text=写文章', 'span:text-is("写文章")']
    NEXT_STEP_SEL = ['button:has-text("下一步")', 'text=下一步']
    PUBLISH_SEL = ['button:has-text("发布")', 'text=发布']

    async def is_logged_in(self, page) -> bool:
        # 铁判据: 编辑器的标题框渲染(未登录被甩 newlogin)。给页面渲染留重试。
        try:
            url = (page.url or "").lower()
            if any(m in url for m in self.logged_out_url_marks):
                return False
            for _ in range(6):
                if await page.locator(self.TITLE_SEL).count() > 0:
                    return True
                await page.wait_for_timeout(1000)
            return False
        except Exception:
            return False

    async def publish_one(self, page, article: dict, draft: bool) -> dict:
        title = content_mod.strip_stock_tags(self.resolve_title(article))
        blocks = article.get("blocks", [])
        n_head = sum(1 for b in blocks if b["type"] == "heading")
        n_img = sum(1 for b in blocks if b["type"] == "image")
        self.logger.info(f"[{self.name}] 准备发长文: {article['id']} | 标题={title[:36]!r} "
                         f"| {len(blocks)}块(标题{n_head}/图{n_img})")

        await page.goto(self.compose_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        if not await self.wait_for_captcha(page):
            return {"ok": False, "url": "", "note": "验证码未过"}

        # 开新草稿(不覆盖已有草稿); 点不动则清空当前编辑器兜底
        if not await self.try_click(page, self.NEW_ARTICLE_SEL, "写文章(新草稿)"):
            self.logger.warning(f"[{self.name}] 没点到写文章, 清空当前编辑器兜底")
            await self._clear_editor(page)
        await page.wait_for_timeout(4000)

        # 标题
        if not await self.try_fill(page, [self.TITLE_SEL], title, "标题"):
            await self._shot(page, "no_title")
            return {"ok": False, "url": "", "note": "标题框没找到"}

        # 正文(富文本: 段落/加粗/斜体/列表项)
        if not await self._type_body(page, blocks):
            await self._shot(page, "no_editor")
            return {"ok": False, "url": "", "note": "正文编辑器没找到"}
        await page.wait_for_timeout(1500)
        await self._shot(page, "content_filled")

        # 草稿模式: 到此为止
        if draft:
            self.logger.info(f"[{self.name}] [草稿] {article['id']} 已填充+截图,未真发")
            return {"ok": True, "url": "", "note": "draft(未发布)"}

        # 发布: 下一步 → 确认页 → 发布
        # ⚠️ 微博的"是否確認發布文章"是浏览器原生 confirm() 弹窗(不在 DOM 里),
        # Playwright 默认自动 dismiss(=点取消), 发布永远被取消 —— 必须注册 accept 处理器
        import asyncio as _aio
        page.on("dialog",
                lambda d: (self.logger.info(
                               f"[{self.name}] 已自动接受原生确认弹窗: {(d.message or '')[:40]}"),
                           _aio.ensure_future(d.accept())))
        await page.wait_for_timeout(2000)
        # 点下一步进入"设置封面"步(底部主按钮变"发布") —— 点击偶发无效(渲染时机),
        # 重试直到按钮真的变成"发布"为止, 最多5轮
        advanced = False
        for attempt in range(5):
            nxt = page.locator('button:has-text("下一步")').first
            try:
                if await nxt.count() > 0:
                    # 按钮状态诊断
                    st = await page.evaluate('''() => {
                        const b = [...document.querySelectorAll('button')]
                            .find(x => (x.innerText || '').includes('下一步'));
                        if (!b) return null;
                        const r = b.getBoundingClientRect();
                        return {dis: b.disabled, cls: (b.className + '').slice(0, 60),
                                x: Math.round(r.x), y: Math.round(r.y)};
                    }''')
                    self.logger.info(f"[{self.name}] 下一步按钮状态: {st}")
                    await nxt.click(timeout=6000)
                    self.logger.info(f"[{self.name}] 已点击 下一步 (第{attempt + 1}次)")
                    await page.wait_for_timeout(2500)
                    if await page.locator('button:has-text("发布")').count() > 0:
                        advanced = True
                        break
                    # Playwright 点击无效 → JS 直click兜底
                    await page.evaluate('''() => {
                        const b = [...document.querySelectorAll('button')]
                            .find(x => (x.innerText || '').includes('下一步'));
                        if (b) b.click();
                    }''')
                    self.logger.info(f"[{self.name}] JS兜底click 下一步 (第{attempt + 1}次)")
            except Exception as e:
                self.logger.warning(f"[{self.name}] 下一步尝试异常: {str(e)[:60]}")
            await page.wait_for_timeout(3000)
            if await page.locator('button:has-text("发布")').count() > 0:
                advanced = True
                break
        await self._shot(page, "confirm_page")
        if not advanced:
            await self._shot(page, "no_publish_step")
            return {"ok": False, "url": "",
                    "note": "下一步未生效(页面没切到封面步, 看截图核对内容/校验)"}
        pub_btn = page.locator('button:has-text("发布")').first
        try:
            await pub_btn.click(timeout=8000)
            self.logger.info(f"[{self.name}] 已点击 发布(封面步底部按钮)")
        except Exception as e:
            await self._shot(page, "no_publish_btn")
            return {"ok": False, "url": "", "note": f"发布按钮点击失败: {e}"}
        await page.wait_for_timeout(2000)
        # 终确认弹窗("是否确认发布文章xxx吗") —— 按钮可能是 span/div 伪按钮(非<button>),
        # 用精确文本匹配; 可能延迟数秒或在 iframe, 轮询 12s
        for _ in range(12):
            await page.wait_for_timeout(1000)
            clicked = False
            for fr in page.frames:
                for word in ('确认', '確認'):
                    try:
                        loc = fr.locator(f'text="{word}"').first
                        if await loc.count() > 0:
                            await loc.click(timeout=4000)
                            self.logger.info(f"[{self.name}] 已点击 终确认弹窗({word})")
                            clicked = True
                            break
                    except Exception:
                        continue
                if clicked:
                    break
            if clicked:
                break
        await page.wait_for_timeout(5000)
        if not await self.wait_for_captcha(page):
            return {"ok": False, "url": "", "note": "发布后验证码未过"}
        await self._shot(page, "result")
        return await self._verify_published(page)

    async def _clear_editor(self, page) -> None:
        """清空标题+正文(兜底路径用)。"""
        for sel in (self.TITLE_SEL, self.BODY_SEL):
            try:
                loc = page.locator(sel).first
                if await loc.count() == 0:
                    continue
                await loc.click(timeout=6000)
                await page.keyboard.press("ControlOrMeta+A")
                await page.keyboard.press("Backspace")
                await page.wait_for_timeout(300)
            except Exception:
                pass

    async def _type_body(self, page, blocks: list) -> bool:
        """按 blocks 输入正文: 段落/标题/列表项, 保留加粗/斜体; hr 跳过。
        (v1 不传图: 文章编辑器传图入口未校准, 图相关段落降级为文字)"""
        loc = page.locator(self.BODY_SEL).first
        if await loc.count() == 0:
            return False
        await loc.click(timeout=6000)
        await page.wait_for_timeout(400)
        first = True
        for blk in blocks:
            if blk["type"] in ("hr", "image"):
                continue
            if not first:
                await page.keyboard.press("Enter")
            first = False
            if blk["type"] == "list_item":
                await page.keyboard.type("• ", delay=6)
            for r in blk.get("runs", []):
                text = r.get("text", "")
                if not text:
                    continue
                if r.get("bold"):
                    await page.keyboard.press("ControlOrMeta+b")
                if r.get("italic"):
                    await page.keyboard.press("ControlOrMeta+i")
                await page.keyboard.type(text, delay=5)
                if r.get("italic"):
                    await page.keyboard.press("ControlOrMeta+i")
                if r.get("bold"):
                    await page.keyboard.press("ControlOrMeta+b")
        return True

    async def _verify_published(self, page) -> dict:
        """发布成功判定: 跳出编辑器/出现成功提示视为已发; 抓不到链接就标待核实。"""
        try:
            txt = await page.evaluate(
                "() => document.body ? (document.body.innerText||'') : ''")
            url = page.url
            if any(k in txt for k in ("发布成功", "已发布")):
                return {"ok": True, "url": url, "note": "已发(成功提示, 链接待核实)"}
            if "/editor" not in url:      # 已离开编辑器 → 多半进了文章页/列表页
                return {"ok": True, "url": url, "note": "已发(已跳出编辑器, 链接待核实)"}
        except Exception:
            pass
        await self._shot(page, "verify_unclear")
        return {"ok": False, "url": page.url,
                "note": "未知结果(已点发布未确认)——请到微博后台人工核实"}
