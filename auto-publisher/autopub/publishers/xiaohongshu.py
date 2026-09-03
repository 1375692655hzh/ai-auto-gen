"""小红书 自动发布适配器 —— 创作者中心 写长文(待真站校准)

  发文页 = https://creator.xiaohongshu.com/publish/publish?source=official
           (页首三个 tab: 上传图文 / 发布视频 / 写长文; 发文章点"写长文")
  登录铁判据 = web_session Cookie 非空(游客只有 a1/webId 等设备 cookie)。
  ⚠️ 状态: 登录可用; 发布流程(写长文 tab/编辑器/发布按钮的 selector)未在真站校准过,
     先用 --draft 走一遍核对截图, 再真发。
"""

import re
from pathlib import Path

from .base import BrowserPublisher
import content as content_mod

# 正文里的股票标签: $名字(SH600519)$ → 纯文本
STOCK_TAG_RE = re.compile(r"\$([^\$]{1,40})\$")


class XiaohongshuPublisher(BrowserPublisher):
    name = "xiaohongshu"
    profile_dir = str(Path.home() / ".xiaohongshu_chrome_profile")
    compose_url = "https://creator.xiaohongshu.com/publish/publish?source=official"
    logged_out_url_marks = ["login", "signin", "passport"]

    LONGFORM_TAB_SELECTORS = [
        'span:text-is("写长文")',
        'div[class*="tab"]:has-text("写长文")',
        'text=写长文',
    ]
    TITLE_SELECTORS = [
        'input[placeholder*="标题"]',
        'textarea[placeholder*="标题"]',
    ]
    BODY_SELECTORS = [
        'div.ProseMirror[contenteditable="true"]',
        'div.ql-editor[contenteditable="true"]',
        'div[contenteditable="true"]',
    ]
    PUBLISH_SELECTORS = [
        'button:has-text("发布")',
        'div[class*="submit"] button',
    ]

    OK_TOAST_KW = ("成功", "已发布", "发布完成")
    FAIL_TOAST_KW = ("失败", "违规", "敏感", "频繁", "限流", "禁止", "不能", "请输入")

    async def is_logged_in(self, page) -> bool:
        # 铁判据: 创作中心的登录凭证 Cookie 非空。
        # 注意 web_session 是主站(www)的; 创作中心(creator)用 access-token/x-user-id。
        try:
            have = {c["name"]: c["value"] for c in await page.context.cookies()}
            return (bool(have.get("access-token-creator.xiaohongshu.com"))
                    and bool(have.get("x-user-id-creator.xiaohongshu.com")))
        except Exception:
            return False

    async def publish_one(self, page, article: dict, draft: bool) -> dict:
        title = content_mod.strip_stock_tags(self.resolve_title(article))
        body = content_mod.strip_stock_tags(
            content_mod.flatten(article.get("body", "")))
        self.logger.info(f"[{self.name}] 准备发: {article['id']} | 标题={title[:36]!r} "
                         f"| 正文 {len(body)} 字")

        await page.goto(self.compose_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(4000)
        if not await self.wait_for_captcha(page):
            return {"ok": False, "url": "", "note": "验证码未过"}

        # 切到"写长文" tab(默认落在上传图文)
        if not await self.try_click(page, self.LONGFORM_TAB_SELECTORS, "写长文tab"):
            self.logger.warning(f"[{self.name}] 没找到写长文tab, 按当前页面继续")

        # 标题
        if not await self.try_fill(page, self.TITLE_SELECTORS, title, "标题"):
            await self._shot(page, "no_title")
            return {"ok": False, "url": "", "note": "标题框没找到"}

        # 正文: 纯文本扁平输入(不保留富文本格式; 校准后再升级)
        if not await self.try_fill(page, self.BODY_SELECTORS, body, "正文"):
            await self._shot(page, "no_editor")
            return {"ok": False, "url": "", "note": "正文编辑器没找到"}
        await page.wait_for_timeout(1500)
        await self._shot(page, "content_filled")

        # 草稿模式: 到此为止
        if draft:
            await self._shot(page, "draft")
            self.logger.info(f"[{self.name}] [草稿] {article['id']} 已填充+截图,未真发")
            return {"ok": True, "url": "", "note": "draft(未发布)"}

        # 发布
        url_before = page.url
        if not await self.try_click(page, self.PUBLISH_SELECTORS, "发布"):
            await self._shot(page, "no_publish_btn")
            return {"ok": False, "url": "", "note": "发布按钮没点中"}
        await page.wait_for_timeout(5000)
        if not await self.wait_for_captcha(page):
            return {"ok": False, "url": "", "note": "发布后验证码未过"}
        await self._shot(page, "result")

        # 成功判定: toast / 跳转到内容管理页
        try:
            txt = await page.evaluate(
                "() => document.body ? (document.body.innerText||'') : ''")
            if any(k in txt for k in self.FAIL_TOAST_KW[:3]):
                return {"ok": False, "url": page.url, "note": f"疑似失败提示, 需人工核实"}
            if page.url != url_before or any(k in txt for k in self.OK_TOAST_KW):
                return {"ok": True, "url": page.url, "note": "已发(待人工核实链接)"}
        except Exception:
            pass
        return {"ok": False, "url": page.url, "note": "未知结果(已点发布未确认)——请到平台后台人工核实"}
