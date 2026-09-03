"""老虎社区(laohu8)自动发布适配器 —— 写长文

校准来源: 2026-06-03 真站抓取
  发文页 = https://www.laohu8.com/post/write (写长文, 直接打开就是编辑器)
  标题   = input[placeholder*="标题"]  (计数器 /300, 长标题OK; 标题不支持股票卡片→纯文本)
  正文   = div.ProseMirror[contenteditable]  (ProseMirror 富文本)
  发布   = button.handle-btn.btn-primary 文字"发布" (旁边有 保存/预览)
  股票卡片: 正文里打 $ + 代码(如 600519) → 弹 li.pmeditor-community-menu-item
            → 点候选插入真卡片 (直接打 $名字(代码)$ 整串不行, 会"暂无数据")
"""

import re
from pathlib import Path

from .base import BrowserPublisher
import content as content_mod

# 正文里的股票标签: $名字(SH600519)$ / $SH600519$ / $600519$ / $英伟达(NVDA)$
STOCK_TAG_RE = re.compile(r"\$([^\$]{1,40})\$")


def _parse_stock_key(inner: str):
    """从 $...$ 内部解析 (搜索用代码, 显示名/fallback)。
    "贵州茅台(SH600519)" -> ("600519", "贵州茅台")
    "SH600519"/"600519"  -> ("600519", "600519")
    "英伟达(NVDA)"        -> ("NVDA", "英伟达")
    """
    m = re.search(r"\(([^()]+)\)", inner)
    if m:
        code, name = m.group(1).strip(), inner[:m.start()].strip()
    else:
        code = name = inner.strip()
    code = re.sub(r"^(?:SH|SZ|sh|sz)", "", code).strip()
    return code, (name or code)


class LaohuPublisher(BrowserPublisher):
    name = "laohu"
    profile_dir = str(Path.home() / ".laohu_chrome_profile")
    compose_url = "https://www.laohu8.com/post/write?source=NavigationBar"
    logged_out_url_marks = ["/auth/login", "signin", "passport"]

    TITLE_SELECTORS = ['input[placeholder*="标题"]']
    BODY_SELECTOR = 'div.ProseMirror[contenteditable="true"]'
    PUBLISH_SELECTORS = [
        'button.handle-btn.btn-primary:has-text("发布")',
        'button.handle-btn:has-text("发布")',
    ]
    STOCK_ITEM_SEL = 'li.pmeditor-community-menu-item'

    OK_TOAST_KW = ("成功", "已发布", "发布完成")
    FAIL_TOAST_KW = ("失败", "违规", "敏感", "频繁", "限流", "禁止", "不能", "请输入")

    COMMUNITY_URL = "https://www.laohu8.com/community"
    hot_stocks = []          # [(ticker, name), ...] 由 prepare() 填

    async def prepare(self, page) -> None:
        """抓热议榜前 N(默认3)只, 供文末追加。"""
        n = int(self.config.get("append_hot", 3))
        if n <= 0:
            return
        try:
            await page.goto(self.COMMUNITY_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(4000)
            items = await page.evaluate("""(n) => {
                const out=[];
                document.querySelectorAll('.hot-stocks-list > li').forEach(li=>{
                    const s=li.querySelector('.item-symbol'), nm=li.querySelector('.item-name');
                    if(s && s.innerText.trim())
                        out.push({ticker:s.innerText.trim(), name:(nm?nm.innerText.trim():'')});
                });
                return out.slice(0, n);
            }""", n)
            self.hot_stocks = [(it["ticker"], it["name"]) for it in (items or [])]
            self.logger.info(f"[{self.name}] 热议榜前{n}: "
                             f"{[f'{t}/{nm}' for t, nm in self.hot_stocks]}")
        except Exception as e:
            self.logger.warning(f"[{self.name}] 抓热议榜失败: {e}")
            self.hot_stocks = []

    async def is_logged_in(self, page) -> bool:
        try:
            url = (page.url or "").lower()
            if any(m in url for m in self.logged_out_url_marks):
                return False
            # 重试: 页面可能还没渲染完
            for _ in range(6):
                if await page.locator(self.TITLE_SELECTORS[0]).count() > 0:
                    return True
                await page.wait_for_timeout(1000)
            return False
        except Exception:
            return False

    _cur_title = ""

    async def publish_one(self, page, article: dict, draft: bool) -> dict:
        title = content_mod.strip_stock_tags(self.resolve_title(article))   # 标题纯文本(支持平台覆盖)
        self._cur_title = title
        blocks = article.get("blocks", [])
        if len(title) > 300:
            self.logger.warning(f"[{self.name}] 标题 {len(title)} 字超上限300")
        elif len(title) < 5:
            self.logger.warning(f"[{self.name}] 标题仅 {len(title)} 字, 老虎建议≥5字")
        n_head = sum(1 for b in blocks if b["type"] == "heading")
        n_img = sum(1 for b in blocks if b["type"] == "image")
        n_stock = sum(1 for b in blocks for r in b.get("runs", []) if r.get("stock"))
        self.logger.info(f"[{self.name}] 准备发: {article['id']} | 标题={title[:36]!r} "
                         f"| {len(blocks)}块(标题{n_head}/图{n_img}) | 股票标签{n_stock}个")

        await page.goto(self.compose_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(4000)
        if not await self.wait_for_captcha(page):
            return {"ok": False, "url": "", "note": "验证码未过"}

        # 1. 标题
        if not await self.try_fill(page, self.TITLE_SELECTORS, title, "标题"):
            await self._shot(page, "no_title")
            return {"ok": False, "url": "", "note": "标题框没找到"}

        # 2. 正文: 富文本模式(保留标题/加粗/斜体/列表 + 股票卡片 + 配图), 用 blocks
        ok = await self._type_body_rich(page, article.get("blocks", []), article.get("dir"))
        if not ok:
            await self._shot(page, "no_editor")
            return {"ok": False, "url": "", "note": "正文编辑器没找到"}
        await page.wait_for_timeout(1500)
        await self._shot(page, "content_filled")

        # 3. 草稿模式: dump 编辑器 HTML 供结构核对
        if draft:
            try:
                html = await page.evaluate(
                    "() => document.querySelector('.ProseMirror').innerHTML")
                from pathlib import Path as _P
                dump = _P(__file__).resolve().parent.parent / "logs" / "laohu_draft_dump.html"
                dump.write_text(html, encoding="utf-8")
                import re as _re
                tags = {t: len(_re.findall(f"<{t}[ >]", html))
                        for t in ("h2", "strong", "em", "p")}
                cards = html.count("stock") + len(_re.findall(r"\$[^$<]+\$", html))
                self.logger.info(f"[{self.name}] [草稿]HTML结构: {tags} | 股票卡片迹象~{cards} "
                                 f"| dump→logs/laohu_draft_dump.html")
            except Exception as e:
                self.logger.warning(f"[{self.name}] HTML dump 失败: {e}")
            return {"ok": True, "url": "", "note": "draft(未发布)"}

        # 4. 发布
        url_before = page.url
        if not await self.try_click(page, self.PUBLISH_SELECTORS, "发布"):
            await self._shot(page, "no_publish_btn")
            return {"ok": False, "url": "", "note": "发布按钮没点中"}
        await page.wait_for_timeout(4000)
        if not await self.wait_for_captcha(page):
            return {"ok": False, "url": "", "note": "发布后验证码未过"}
        await page.wait_for_timeout(2500)
        await self._shot(page, "result")
        return await self._verify_published(page, url_before)

    # ---------- 正文输入 ----------

    async def _focus_editor(self, page) -> bool:
        loc = page.locator(self.BODY_SELECTOR).first
        if await loc.count() == 0:
            return False
        await loc.click(timeout=6000)
        await page.wait_for_timeout(400)
        await page.keyboard.press("ControlOrMeta+A")
        await page.keyboard.press("Backspace")
        await page.wait_for_timeout(200)
        return True

    HEADING_BTN = '.pmeditor-community-toolbar-btn.btn-heading'
    IMAGE_BTN = '.pmeditor-community-toolbar-btn.btn-image'

    async def _type_body_rich(self, page, blocks: list, art_dir=None) -> bool:
        """按 blocks 输入正文, 保留格式:
          heading -> 输入后点 H 变 <h2>; paragraph/list_item -> runs(加粗/斜体/股票卡片)
          image -> 点传图按钮上传(B 阶段); hr -> 跳过
        """
        if not await self._focus_editor(page):
            return False
        hbtn = page.locator(self.HEADING_BTN).first
        cards_ok = cards_fail = heads = imgs_ok = imgs_fail = 0
        first = True
        for blk in blocks:
            if blk["type"] == "hr":
                continue
            if not first:
                await page.keyboard.press("Enter")
            first = False
            if blk["type"] == "image":
                if await self._upload_image(page, blk.get("src", ""), art_dir):
                    imgs_ok += 1
                else:
                    imgs_fail += 1
                continue
            if blk["type"] == "list_item":
                await page.keyboard.type("• ", delay=6)
            co, cf = await self._type_runs(page, blk.get("runs", []))
            cards_ok += co
            cards_fail += cf
            if blk["type"] == "heading":
                # 选中本行 → 点 H → 变 h2 → 取消选中到行尾
                await page.keyboard.press("Home")
                await page.keyboard.down("Shift")
                await page.keyboard.press("End")
                await page.keyboard.up("Shift")
                try:
                    await hbtn.click(timeout=4000)
                    heads += 1
                except Exception:
                    pass
                await page.keyboard.press("End")
                # 校验: 点工具栏 H 偶尔会把选中的标题文字吞掉(尤其首个标题), 留下空 h2。
                # 若当前行(光标所在块)变空, 把标题文字补打回去。
                await page.wait_for_timeout(150)
                cur_empty = await page.evaluate("""() => {
                    const sel = window.getSelection();
                    if (!sel || !sel.rangeCount) return false;
                    let node = sel.anchorNode;
                    while (node && node.nodeType === 3) node = node.parentElement;
                    const block = node ? node.closest('h1,h2,h3,h4,p,li') : null;
                    return block ? !((block.textContent || '').trim()) : false;
                }""")
                if cur_empty:
                    self.logger.info(f"[{self.name}] 标题被吞→补打: "
                                     f"{''.join(r.get('text','') for r in blk.get('runs',[]))[:20]!r}")
                    await self._type_runs(page, blk.get("runs", []))
                    await page.keyboard.press("End")
        # 文末追加热议榜前 N 只(股票卡片)
        hot_ok = await self._append_hot_footer(page)
        self.logger.info(f"[{self.name}] 正文已输入(块{len(blocks)} 标题{heads} "
                         f"配图 成功{imgs_ok}/失败{imgs_fail} "
                         f"股票卡片 成功{cards_ok}/失败{cards_fail} 热议卡片{hot_ok})")
        return True

    async def _upload_image(self, page, src: str, art_dir) -> bool:
        """上传一张配图。src 可为绝对路径(docx 内嵌已抽出)或相对 art_dir(md 外链)。"""
        from pathlib import Path
        if not src:
            return False
        path = Path(src)
        if not path.is_absolute() and art_dir:
            path = Path(art_dir) / src
        if not path.exists():
            self.logger.warning(f"[{self.name}] 配图不存在, 跳过: {path}")
            return False
        try:
            before = await page.locator('.ProseMirror img').count()
            btn = page.locator(self.IMAGE_BTN).first
            async with page.expect_file_chooser(timeout=10000) as fc_info:
                await btn.click()
            chooser = await fc_info.value
            await chooser.set_files(str(path))
            # 等上传完成: 新 <img> 出现且 src 变成 http(传到 CDN)
            for _ in range(30):                 # 最多 ~15s
                await page.wait_for_timeout(500)
                done = await page.evaluate("""(before) => {
                    const imgs=[...document.querySelectorAll('.ProseMirror img')];
                    if(imgs.length<=before) return false;
                    const last=imgs[imgs.length-1];
                    return (last.src||'').startsWith('http');
                }""", before)
                if done:
                    self.logger.info(f"[{self.name}] 配图已上传: {path.name}")
                    # 关键: 图插入后是"节点选中"态, 按 ArrowRight 取消选中并把光标移到图后,
                    # 否则下一块的 Enter/输入会把图删掉(实测 ArrowDown/End 都不行)
                    await page.keyboard.press("ArrowRight")
                    return True
            self.logger.warning(f"[{self.name}] 配图上传超时: {path.name}")
            return False
        except Exception as e:
            self.logger.warning(f"[{self.name}] 配图上传失败 {path.name}: {e}")
            return False

    async def _append_hot_footer(self, page) -> int:
        """文末空一行 + "热议关注:" + 热议榜前 N 只股票卡片。返回成功卡片数。"""
        if not self.hot_stocks:
            return 0
        await page.keyboard.press("Enter")
        await page.keyboard.press("Enter")
        ok = 0
        for i, (ticker, name) in enumerate(self.hot_stocks):
            if i > 0:
                await page.keyboard.type(" ", delay=8)
            if await self._insert_stock_card(page, ticker):
                ok += 1
            else:
                await page.keyboard.type(f"{name}({ticker})", delay=6)
        return ok

    async def _type_runs(self, page, runs: list):
        """输入一个块的 runs;返回 (卡片成功数, 失败数)。"""
        co = cf = 0
        for r in runs:
            if r.get("stock"):
                code = r["stock"][0]
                if await self._insert_stock_card(page, code):
                    co += 1
                else:
                    await page.keyboard.type(r["stock"][1], delay=6)
                    cf += 1
                continue
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
        return co, cf

    async def _insert_stock_card(self, page, code: str) -> bool:
        """打 $ + code → 等下拉 → 点匹配候选插卡片。失败则清掉已打的 $code 返回 False。"""
        try:
            await page.keyboard.type("$", delay=120)
            await page.wait_for_timeout(500)
            await page.keyboard.type(code, delay=100)
            item = page.locator(self.STOCK_ITEM_SEL)
            for _ in range(12):                       # 最多等 3s
                if await item.count() > 0:
                    break
                await page.wait_for_timeout(250)
            if await item.count() == 0:
                for _ in range(len(code) + 1):        # 清掉 $code
                    await page.keyboard.press("Backspace")
                return False
            # 选代码精确匹配的候选, 否则第一个
            target = item.first
            for i in range(await item.count()):
                t = (await item.nth(i).inner_text()) or ""
                if code in t:
                    target = item.nth(i)
                    break
            await target.click(timeout=4000)
            await page.wait_for_timeout(400)
            return True
        except Exception as e:
            self.logger.warning(f"[{self.name}] 插股票卡片失败 {code}: {e}")
            return False

    # ---------- 成功判定 ----------

    async def _verify_published(self, page, url_before: str) -> dict:
        # 先看 toast(发成功/失败会闪现)
        ok_toast = False
        for _ in range(8):                               # ~4s 抓 toast
            try:
                toast = await page.evaluate("""() => {
                    const sels = ['[class*="toast"]','[class*="Toast"]','[class*="message"]',
                                  '[class*="notify"]','[role=alert]','.ant-message'];
                    for (const s of sels){ const el=document.querySelector(s);
                      if (el && el.innerText && el.innerText.trim()) return el.innerText.trim(); }
                    return '';
                }""")
                # 兜底: 老虎成功 toast 的 class 不固定, 直接扫全页文字找"发帖成功/即将跳转"
                body_txt = await page.evaluate("() => document.body ? (document.body.innerText||'') : ''")
            except Exception:
                toast = ""
                body_txt = ""
            if toast and any(k in toast for k in self.FAIL_TOAST_KW):
                return {"ok": False, "url": page.url, "note": f"失败 toast: {toast!r}"}
            hit = (toast or "") + " " + (body_txt or "")
            if "发帖成功" in hit or "即将跳转" in hit or any(k in hit for k in self.OK_TOAST_KW):
                ok_toast = True
                break
            await page.wait_for_timeout(500)
        # "发帖成功"绿条=可靠成功信号(用户实测), 不能被主页查询误判推翻。
        # 抓到成功 toast 即判成功; 主页能查到就附真实链接, 查不到(新帖延迟)也不推翻。
        url = await self._find_my_post(page, self._cur_title)
        if url:
            return {"ok": True, "url": url, "note": "已发(主页查到帖子)"}
        if ok_toast:
            return {"ok": True, "url": page.url, "note": "已发(发帖成功toast确认, 主页延迟未查到链接)"}
        return {"ok": False, "url": page.url, "note": "主页未查到该帖, 未发成功(可能仅存草稿)"}

    async def _personal_home(self, page) -> str:
        """个人主页 URL: config 配了 personal_url 直接用(首页抓的可能抓错人),
        没配才退回从首页 a[href*=/personal/] 抓。"""
        cfg_url = (self.config or {}).get("personal_url")
        if cfg_url:
            return cfg_url
        try:
            await page.goto("https://www.laohu8.com/", wait_until="domcontentloaded",
                            timeout=30000)
            await page.wait_for_timeout(2000)
            me = await page.evaluate("""() => {
                const a = document.querySelector('a[href*="/personal/"]');
                return a ? a.getAttribute('href') : '';
            }""")
            return (me if me.startswith("http") else "https://www.laohu8.com" + me) if me else ""
        except Exception:
            return ""

    async def _find_my_post(self, page, title: str) -> str:
        """去个人主页, 用标题匹配查这篇帖子的真实 /post/{id} 链接。
        发布后新帖上主页有延迟 → 重试几轮(每轮重载主页), 查不到才算没发成功。
        标题匹配宽松: 主页标题可能截断, 用前8字 + 去空格比对。
        """
        raw = (title or "").strip()
        if len(raw) < 5:
            return ""
        # 取标题前8字且去掉空格(主页显示可能截断/空格不一致)
        key = re.sub(r"\s+", "", raw)[:8]
        # 先定位个人主页 URL(config personal_url 优先)
        home = await self._personal_home(page)
        if not home:
            return ""
        for attempt in range(5):                         # 重试5轮(新帖上主页有延迟)
            try:
                await page.goto(home, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2500)
                url = await page.evaluate("""(key) => {
                    for (const a of document.querySelectorAll('a[href*="/post/"]')) {
                        const h = a.getAttribute('href') || '';
                        const t = (a.innerText || '').replace(/\\s+/g,'').trim();
                        const m = h.match(/\\/post\\/(\\d+)/);
                        if (m && !h.includes('/edit') && !h.includes('comment') && key && t.includes(key))
                            return 'https://www.laohu8.com/post/' + m[1];
                    }
                    return '';
                }""", key)
                if url:
                    return url
            except Exception:
                pass
            await page.wait_for_timeout(2000)
        return ""

    async def _already_posted(self, page, title: str) -> bool:
        """查个人主页近期帖子标题, 命中(标题前缀匹配)则认为已发过。"""
        key = (title or "").strip()[:16]
        if len(key) < 6:
            return False
        try:
            # 个人主页(config personal_url 优先)
            url = await self._personal_home(page)
            if not url:
                return False
            await page.goto(url, wait_until="domcontentloaded", timeout=40000)
            await page.wait_for_timeout(3000)
            titles = await page.evaluate("""() => {
                const out = [];
                document.querySelectorAll('a[href*="/post/"]').forEach(a => {
                    const t = (a.innerText || '').replace(/\\s+/g,' ').trim();
                    if (t && t.length > 6) out.push(t);
                });
                return out.slice(0, 20);
            }""")
            return any(key in t or t[:16] == key for t in titles)
        except Exception:
            return False

    async def _get_latest_post_url(self, page) -> str:
        """发完后重载个人主页, 抓最新一篇帖子的真实 /post/{id} 链接。"""
        # 去个人主页, 用标题匹配本次发的帖子(不靠"第一个/post/", 那可能是旧帖/评论链接)
        key = (self._cur_title or "").strip()[:14]
        try:
            home = await self._personal_home(page)
            if home:
                await page.goto(home, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)
            # 标题匹配的帖子链接
            href = await page.evaluate("""(key) => {
                for (const a of document.querySelectorAll('a[href*="/post/"]')) {
                    const h = a.getAttribute('href') || '';
                    const t = (a.innerText || '').replace(/\\s+/g,' ').trim();
                    const m = h.match(/\\/post\\/(\\d+)/);
                    if (m && !h.includes('/edit') && !h.includes('comment')
                        && key && t.includes(key))
                        return 'https://www.laohu8.com/post/' + m[1];
                }
                return '';
            }""", key)
            return href or ""
        except Exception:
            return ""
