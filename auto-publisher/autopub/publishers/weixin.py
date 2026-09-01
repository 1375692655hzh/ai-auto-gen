"""微信公众号适配器(浏览器自动化)

发布链路参照 doocs/md 的成熟经验(md → 内联样式 HTML → 注入编辑器):
  wechat_render.render() 把文章 blocks 渲染成微信兼容的内联样式 HTML
  (本地图转 base64 内联, 编辑器收到 data URI 会自动转存素材库),
  再在公众号图文编辑器(ueditor iframe)里 execCommand('insertHTML') 注入。

安全设计: "真发"也只到 **保存为草稿**——群发每天次数有限且不可撤回,
始终留给人工在公众号后台最后点击。

前置: 首次运行弹出的 Chrome 里扫码登录(公众号管理员/运营者微信),
登录态落在独立 profile, 之后长期复用。
"""

import re
from pathlib import Path

import wechat_render
from .base import BrowserPublisher

HOME = "https://mp.weixin.qq.com/cgi-bin/home?t=home/index&lang=zh_CN"


class WeixinPublisher(BrowserPublisher):
    name = "weixin"
    profile_dir = str(Path.home() / ".weixin_autopub_chrome_profile")
    compose_url = HOME
    TITLE_MAX = 64                       # 公众号标题上限(64 字)

    async def is_logged_in(self, page) -> bool:
        """公众号登录态看 URL: 登录后所有 cgi-bin 页都带 token=。"""
        try:
            url = page.url or ""
            return "token=" in url or "cgi-bin/home" in url
        except Exception:
            return False

    # ---------- 工具 ----------

    async def _get_token(self, page) -> str:
        """进工作台首页, 从 URL 提取 token(新建图文 URL 必须带它)。"""
        await page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)
        m = re.search(r"[?&]token=(\d+)", page.url or "")
        if m:
            return m.group(1)
        # 首页没带 token 就从页面链接里捞一个
        html = await page.content()
        m = re.search(r"token=(\d+)", html)
        return m.group(1) if m else ""

    async def _open_editor(self, page, token: str) -> bool:
        edit = ("https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit_v2"
                f"&action=edit&isNew=1&type=77&create_type=0&token={token}&lang=zh_CN")
        await page.goto(edit, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        return await page.locator("#title").count() > 0

    async def _editor_frame(self, page):
        """公众号图文正文在 ueditor iframe 里; 等它出现并返回 Frame。"""
        loc = page.locator('iframe[id*="ueditor"], iframe[class*="ueditor"]').first
        await loc.wait_for(timeout=20000)
        for fr in page.frames:
            if fr != page.main_frame and ("ueditor" in (fr.name or "")
                                          or "ueditor" in (fr.url or "")):
                return fr
        return None

    # ---------- 主流程 ----------

    async def publish_one(self, page, article: dict, draft: bool) -> dict:
        import content as content_mod
        title = content_mod.strip_stock_tags(article["title"])
        if len(title) > self.TITLE_MAX:
            title = title[: self.TITLE_MAX]

        token = await self._get_token(page)
        if not token:
            await self._shot(page, "no_token")
            return {"ok": False, "url": "", "note": "未取到 token(登录态失效?)"}
        if not await self._open_editor(page, token):
            await self._shot(page, "no_editor_page")
            return {"ok": False, "url": "",
                    "note": "图文编辑页未打开(标题框未找到)"}

        # 标题
        try:
            t = page.locator("#title").first
            await t.click(timeout=8000)
            await t.fill(title)
        except Exception as e:
            await self._shot(page, "no_title")
            return {"ok": False, "url": "", "note": f"标题框未找到: {e}"}
        await page.wait_for_timeout(800)

        # 正文: 内联样式 HTML 一次性注入(富文本保留, 图片 base64)
        body_html = wechat_render.render(article.get("blocks", []),
                                         article.get("dir"))
        n_img = body_html.count("<img ")
        self.logger.info(f"[{self.name}] 注入正文: {len(body_html) // 1024}KB HTML, "
                         f"内嵌图 {n_img} 张")
        fr = await self._editor_frame(page)
        if fr is None:
            await self._shot(page, "no_editor_frame")
            return {"ok": False, "url": "", "note": "ueditor iframe 未找到"}
        try:
            body = fr.locator("body").first
            await body.click(timeout=8000)
            payload = body_html.replace("\\", "\\\\").replace("'", "\\'")
            await fr.evaluate(
                "html => { document.body.focus();"
                "document.execCommand('insertHTML', false, html); }", payload)
        except Exception as e:
            await self._shot(page, "inject_fail")
            return {"ok": False, "url": "", "note": f"正文注入失败: {e}"}
        await page.wait_for_timeout(2000)
        await self._shot(page, "content_filled")

        if draft:
            try:
                got = await fr.evaluate("() => document.body.innerText.length")
                self.logger.info(f"[{self.name}] [草稿]编辑器正文 {got} 字符 "
                                 "(未保存未发布)")
            except Exception:
                pass
            return {"ok": True, "url": "", "note": "draft(未发布)"}

        # 真发也只存草稿: 群发不可撤回+次数有限, 最后一步永远留给人工
        try:
            btn = page.get_by_text("保存为草稿", exact=False).first
            await btn.click(timeout=8000)
            await page.wait_for_timeout(4000)
            await self._shot(page, "saved_draft")
            return {"ok": True, "url": page.url,
                    "note": "已存公众号草稿(群发请到后台人工点击)"}
        except Exception as e:
            await self._shot(page, "save_draft_fail")
            return {"ok": False, "url": "",
                    "note": f"保存草稿失败(正文已注入, 可手动保存): {e}"}
