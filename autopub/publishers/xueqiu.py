"""雪球长文 自动发布适配器(创作者中心 发布长文, ProseMirror 富文本)

  发文页 = https://mp.xueqiu.com/writeV2/?position=pc_home_post (首页发帖框点"长文"进的页面)
  profile = ~/.xueqiu_autopub_chrome_profile (花街S姐; 平头哥投研仅作排版参考, 不发那)
  标题 = textarea[placeholder="请输入标题"]
  正文 = div.ProseMirror (同老虎/东财家族)
  加粗=Cmd+B / 斜体=Cmd+I; 工具栏: 0=B 1=I 2=H 3=链接 4=图片 ... 9=$
  股票 cashtag: 打 $ + 代码 → index_suggestions 下拉 → 点候选插入 chip
  发布 = "发布"按钮(封面/分享范围/声明有默认值)
  内容: 富文本保留标题/加粗/斜体, 正文里"名字(代码)"识别成股票插 cashtag
"""

import re
from pathlib import Path

from .base import BrowserPublisher
import content as content_mod


class XueqiuPublisher(BrowserPublisher):
    name = "xueqiu"
    profile_dir = str(Path.home() / ".xueqiu_autopub_chrome_profile")
    compose_url = "https://mp.xueqiu.com/writeV2/?position=pc_home_post"
    logged_out_url_marks = ["/login", "passport", "/service/login"]

    TITLE_SEL = 'textarea[placeholder*="标题"], textarea.title_title_1p5'
    BODY_SEL = 'div.ProseMirror'
    TOOLBAR_ITEM = '[class*="toolbar_item_container"]'
    H_INDEX = 2
    IMG_INDEX = 4
    SUGGEST_WRAP = '[class*="suggestions__wrap"], [class*="index_suggestions"]'

    async def is_logged_in(self, page) -> bool:
        # 注意: writeV2 不登录也会渲染编辑器(有标题框), 不能用"有标题框"判断。
        # 铁判据: xq_a_token Cookie 存在且非空。
        try:
            return any(c["name"] == "xq_a_token" and c["value"]
                       for c in await page.context.cookies())
        except Exception:
            return False

    HOT_US_URL = "https://xueqiu.com"
    hot_stocks = []          # [(code, name)] 雪球美股热榜前 N, prepare() 填

    async def prepare(self, page) -> None:
        """抓雪球美股热榜前 N(默认3)。健壮版: 等容器加载 + 点美股tab + 重试, 不足N不罢休。"""
        n = int(self.config.get("append_hot", 3))
        if n <= 0:
            return
        self.hot_stocks = []
        for attempt in range(4):                         # 最多 4 轮
            try:
                await page.goto(self.HOT_US_URL, wait_until="domcontentloaded", timeout=60000)
                # 等热股榜容器真正出现(而非固定 sleep)
                try:
                    await page.wait_for_selector('.stock-hot__container, [class*="stock-hot"]', timeout=15000)
                except Exception:
                    pass
                await page.wait_for_timeout(1500)
                # 点"美股"tab
                await page.evaluate("""() => {
                    const host=document.querySelector('[class*="stock-hot"]');
                    const scope=host?host.parentElement:document;
                    const t=[...scope.querySelectorAll('*')].filter(e=>e.children.length===0&&(e.innerText||'').trim()==='美股');
                    if(t.length) t[0].click();
                }""")
                # 轮询等美股榜数据填充(切tab后异步加载)
                items = []
                for _ in range(12):                      # 最多 ~6s
                    await page.wait_for_timeout(500)
                    items = await page.evaluate("""(n) => {
                        const box=document.querySelector('.stock-hot__container.board, .stock-hot__container');
                        if(!box) return [];
                        const out=[], seen=new Set();
                        box.querySelectorAll('a[href*="/S/"]').forEach(a=>{
                            const m=(a.getAttribute('href')||'').match(/\\/S\\/([A-Za-z0-9.]+)/);
                            // 只要美股(纯字母代码), 排除可能残留的 A股(数字)
                            if(m && !seen.has(m[1]) && /^[A-Z.]+$/.test(m[1])){ seen.add(m[1]);
                                out.push({code:m[1], name:(a.innerText||'').replace(/\\s+/g,' ').trim().slice(0,16)}); }
                        });
                        return out.slice(0, n);
                    }""", n)
                    if len(items) >= n:
                        break
                if len(items) >= n:
                    self.hot_stocks = [(it["code"], it["name"]) for it in items]
                    self.logger.info(f"[{self.name}] 美股热榜前{n}(第{attempt+1}轮): "
                                     f"{[f'{c}/{nm}' for c,nm in self.hot_stocks]}")
                    return
                self.logger.warning(f"[{self.name}] 第{attempt+1}轮只抓到{len(items)}只, 重试...")
            except Exception as e:
                self.logger.warning(f"[{self.name}] 第{attempt+1}轮抓热榜异常: {str(e)[:60]}")
        self.logger.error(f"[{self.name}] 抓美股热榜失败(4轮均不足{n}只), 文末将不加 cashtag")

    async def publish_one(self, page, article: dict, draft: bool) -> dict:
        title = content_mod.strip_stock_tags(article["title"])
        # 雪球长文限插 3 个 cashtag → 正文不插, 只在文末加热榜前3。
        # 正文里的"名字(代码)"保持纯文本(不转 stock run)。
        blocks = article.get("blocks", [])
        n_head = sum(1 for b in blocks if b["type"] == "heading")
        n_img = sum(1 for b in blocks if b["type"] == "image")
        self.logger.info(f"[{self.name}] 准备发: {article['id']} | 标题={title[:28]!r} "
                         f"| {len(blocks)}块(标题{n_head}/图{n_img}) | 文末热榜{len(self.hot_stocks)}股")

        # 守卫: 配了 append_hot 却没抓到足量热榜 → 不发(避免发出没热榜的残缺版)
        want_hot = int(self.config.get("append_hot", 3))
        if want_hot > 0 and len(self.hot_stocks) < want_hot and not draft:
            self.logger.error(f"[{self.name}] 热榜只抓到{len(self.hot_stocks)}/{want_hot}只, 跳过发布(下次重试)")
            return {"ok": False, "url": "", "note": f"热榜抓取不足({len(self.hot_stocks)}/{want_hot})"}

        await page.goto(self.compose_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        if not await self.wait_for_captcha(page):
            return {"ok": False, "url": "", "note": "验证码未过"}

        # 标题
        if not await self.try_fill(page, [self.TITLE_SEL], title, "标题"):
            await self._shot(page, "no_title")
            return {"ok": False, "url": "", "note": "标题框没找到"}

        # 正文
        if not await self._type_body_rich(page, blocks, article.get("dir")):
            await self._shot(page, "no_editor")
            return {"ok": False, "url": "", "note": "正文编辑器没找到"}
        # 文末加雪球美股热榜前3 cashtag(雪球长文限3个)
        hot_ok = await self._append_hot_footer(page)
        if hot_ok:
            self.logger.info(f"[{self.name}] 文末热榜 cashtag: {hot_ok}/{len(self.hot_stocks)}")
        await page.wait_for_timeout(1500)
        await self._shot(page, "content_filled")

        if draft:
            try:
                html = await page.evaluate("()=>document.querySelector('.ProseMirror').innerHTML")
                dump = Path(__file__).resolve().parent.parent / "logs" / "xueqiu_draft_dump.html"
                dump.write_text(html, encoding="utf-8")
                tags = {t: len(re.findall(f"<{t}[ >]", html)) for t in ("h1", "h2", "h3", "b", "strong", "i", "em", "img", "p")}
                cashtags = html.count("/S/") + len(re.findall(r"\$[^$<]{1,18}\([A-Z0-9]+\)\$", html))
                self.logger.info(f"[{self.name}] [草稿]HTML: {tags} cashtag~{cashtags} → logs/xueqiu_draft_dump.html")
            except Exception as e:
                self.logger.warning(f"[{self.name}] dump 失败: {e}")
            return {"ok": True, "url": "", "note": "draft(未发布)"}

        return await self._do_publish(page)

    # ---------- 富文本 ----------

    async def _focus_editor(self, page) -> bool:
        loc = page.locator(self.BODY_SEL).first
        if await loc.count() == 0:
            return False
        await loc.click(timeout=6000)
        await page.wait_for_timeout(400)
        await page.keyboard.press("Meta+A")
        await page.keyboard.press("Backspace")
        await page.wait_for_timeout(200)
        return True

    async def _type_body_rich(self, page, blocks, art_dir=None) -> bool:
        if not await self._focus_editor(page):
            return False
        # ===== Pass 1: 全部当普通段落打完(全 <p>, 零继承) =====
        heading_texts = []
        imgs_ok = imgs_fail = co = cf = 0
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
            runs = blk.get("runs", [])
            if blk["type"] == "heading":
                runs = [{**r, "bold": False, "italic": False} for r in runs]
                txt = "".join(r.get("text", "") for r in runs).strip()
                if txt:
                    heading_texts.append(txt)
            a, b = await self._type_runs(page, runs)
            co += a
            cf += b

        # ===== Pass 2: 按文字点到标题行 → 快捷键设 h4(光标在块内, 不选区不Enter, 只影响该行) =====
        heads = 0
        for txt in heading_texts:
            try:
                loc = page.get_by_text(txt[:20], exact=False).first
                if await loc.count() == 0:
                    continue
                await loc.click(timeout=4000)
                await page.wait_for_timeout(150)
                await page.keyboard.press("Meta+Alt+1")
                await page.wait_for_timeout(200)
                heads += 1
            except Exception as e:
                self.logger.warning(f"[{self.name}] 标题设置失败 {txt[:12]!r}: {str(e)[:36]}")
        self.logger.info(f"[{self.name}] 正文已输入(块{len(blocks)} 标题{heads}/{len(heading_texts)} "
                         f"图 {imgs_ok}/{imgs_fail} cashtag {co}/{cf})")
        return True

    async def _append_hot_footer(self, page) -> int:
        """文末空一行 + 3 个雪球美股热榜 cashtag。返回成功插入数。"""
        if not self.hot_stocks:
            return 0
        # 光标移到编辑器内容末尾(Pass2 点过标题行, 焦点在别处)
        try:
            await page.locator(self.BODY_SEL).first.click(timeout=4000)
            await page.evaluate("""() => {
                const ed=document.querySelector('.ProseMirror'); if(!ed)return;
                ed.focus(); const s=window.getSelection(), r=document.createRange();
                r.selectNodeContents(ed); r.collapse(false); s.removeAllRanges(); s.addRange(r);
            }""")
        except Exception:
            pass
        await page.keyboard.press("Enter")
        ok = 0
        for i, (code, name) in enumerate(self.hot_stocks):
            if i > 0:
                await page.keyboard.type("  ", delay=8)
            # 热榜股票来自雪球本身, 必可匹配 → 失败重试一次再 fallback
            inserted = await self._insert_cashtag(page, code)
            if not inserted:
                await page.wait_for_timeout(600)
                inserted = await self._insert_cashtag(page, code)
            if inserted:
                ok += 1
            else:
                self.logger.warning(f"[{self.name}] 热榜 cashtag 两次失败, 留纯文本: {code}")
                await page.keyboard.type(f"{name}({code})", delay=6)
        return ok

    async def _type_runs(self, page, runs):
        co = cf = 0
        for r in runs:
            if r.get("stock"):
                code, name = r["stock"]
                if await self._insert_cashtag(page, code):
                    co += 1
                else:
                    # 精确匹配不上 → 留纯文本"名字(代码)", 不写 $ 避免雪球错配
                    await page.keyboard.type(f"{name}({code})", delay=5)
                    cf += 1
                continue
            text = r.get("text", "")
            if not text:
                continue
            if r.get("bold"):
                await page.keyboard.press("Meta+b")
            if r.get("italic"):
                await page.keyboard.press("Meta+i")
            await page.keyboard.type(text, delay=5)
            if r.get("italic"):
                await page.keyboard.press("Meta+i")
            if r.get("bold"):
                await page.keyboard.press("Meta+b")
        return co, cf

    async def _insert_cashtag(self, page, code: str) -> bool:
        """打 $ + 代码 → 雪球联想 → 只在候选代码【精确等于】目标时点选, 否则跳过(宁缺勿错)。"""
        target = re.sub(r"^(SH|SZ)", "", code.upper())
        target = re.sub(r"\.[A-Z]+$", "", target)
        before = await page.locator('.ProseMirror a[href*="/S/"]').count()
        try:
            await page.keyboard.type("$", delay=100)
            await page.wait_for_timeout(500)
            await page.keyboard.type(code, delay=90)
            for _ in range(24):                          # 最多 ~6s 等联想 + 精确匹配(网络慢容错)
                await page.wait_for_timeout(250)
                status = await page.evaluate("""(target) => {
                    document.querySelectorAll('[data-autopub-pick]').forEach(e=>e.removeAttribute('data-autopub-pick'));
                    const wrap = document.querySelector('[class*="suggestions__wrap"], [class*="index_suggestions"]');
                    if(!wrap) return 'nowrap';
                    const rows = [...wrap.querySelectorAll('*')].filter(e=>{
                        const t=(e.innerText||'').trim();
                        return t && t.length<50 && /\\([^)]{1,12}\\)\\s*$/.test(t)
                               && e.querySelectorAll('*').length <= 3;
                    });
                    if(!rows.length) return 'norows';
                    for(const r of rows){
                        const m=(r.innerText||'').match(/\\(([^)]+)\\)\\s*$/);
                        if(!m) continue;
                        let c=m[1].toUpperCase().replace(/^(SH|SZ)/,'').replace(/\\.[A-Z]+$/,'').trim();
                        if(c===target){ r.setAttribute('data-autopub-pick','1'); return 'marked'; }
                    }
                    return 'nomatch';
                }""", target)
                if status == "marked":
                    try:
                        await page.locator('[data-autopub-pick="1"]').first.click(timeout=2000)
                    except Exception:
                        pass
                    await page.wait_for_timeout(400)
                    # 验证 chip 真的插入(链接数 +1)
                    if await page.locator('.ProseMirror a[href*="/S/"]').count() > before:
                        return True
            # 失败: 关下拉 + 安全删掉已打的 $code(只删查询, 不碰其它内容)
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(150)
            await page.keyboard.down("Shift")
            for _ in range(len(code) + 1):
                await page.keyboard.press("ArrowLeft")
            await page.keyboard.up("Shift")
            await page.keyboard.press("Backspace")
            return False
        except Exception as e:
            self.logger.warning(f"[{self.name}] cashtag 失败 {code}: {str(e)[:50]}")
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
            return False

    async def _apply_heading(self, page, level: int):
        """选中本行 → 点工具栏 H → 点回该 h4 元素恢复焦点+取消选中 → End。
        关键: 不恢复焦点则标题文字仍被选中, 下一 Enter 会把它删掉;
              恢复后 Enter 自然生成 <p>(实测无 h4 继承)。
        """
        await page.keyboard.press("Home")
        await page.keyboard.down("Shift")
        await page.keyboard.press("End")
        await page.keyboard.up("Shift")
        try:
            await page.locator(self.TOOLBAR_ITEM).nth(self.H_INDEX).click(timeout=4000)
            await page.wait_for_timeout(400)
            h = page.locator('.ProseMirror h4').last
            if await h.count() > 0:
                await h.click(timeout=3000)        # 恢复焦点 + 取消选中
            await page.keyboard.press("End")
        except Exception as e:
            self.logger.warning(f"[{self.name}] 标题应用失败: {str(e)[:50]}")

    async def _upload_image(self, page, src, art_dir) -> bool:
        if not src:
            return False
        path = Path(src)
        if not path.is_absolute() and art_dir:
            path = Path(art_dir) / src
        if not path.exists():
            self.logger.warning(f"[{self.name}] 配图不存在: {path}")
            return False
        async def _try_once() -> bool:
            # 关掉编辑器残留的联想/股票下拉, 否则工具栏点击会被挡, 文件框弹不出
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
            await page.wait_for_timeout(300)
            before = await page.locator('.ProseMirror img').count()
            try:
                async with page.expect_file_chooser(timeout=8000) as fc:
                    await page.locator(self.TOOLBAR_ITEM).nth(self.IMG_INDEX).click()
                ch = await fc.value
                await ch.set_files(str(path))
            except Exception:
                inp = page.locator('input[type="file"]').last
                await inp.set_input_files(str(path))
            for _ in range(30):
                await page.wait_for_timeout(500)
                if await page.locator('.ProseMirror img').count() > before:
                    self.logger.info(f"[{self.name}] 配图已上传: {path.name}")
                    await page.keyboard.press("ArrowRight")
                    return True
            return False

        try:
            if await _try_once():
                return True
            self.logger.warning(f"[{self.name}] 配图第1次未嵌入, 重试: {path.name}")
            if await _try_once():
                return True
            self.logger.warning(f"[{self.name}] 配图未嵌入: {path.name}")
            return False
        except Exception as e:
            self.logger.warning(f"[{self.name}] 配图失败 {path.name}: {str(e)[:60]}")
            return False

    # ---------- 发布 ----------

    async def _do_publish(self, page) -> dict:
        # 关掉残留下拉 + 等草稿自动保存(长文保存慢, 立即点发布无效)
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        await page.wait_for_timeout(4000)
        # 底部"发布"按钮(避开左侧边栏"发布"菜单): 取最靠右下角的可见 发布 按钮
        clicked = False
        try:
            btns = page.locator('button:has-text("发布")')
            n = await btns.count()
            best = None
            for i in range(n):
                b = btns.nth(i)
                if not await b.is_visible():
                    continue
                box = await b.bounding_box()
                if box and box["x"] > 400:        # 排除左侧边栏(x小)
                    if best is None or box["x"] > best[0]:
                        best = (box["x"], b)
            if best:
                await best[1].click(timeout=5000)
                clicked = True
                self.logger.info(f"[{self.name}] 已点击底部发布按钮 (x={int(best[0])})")
        except Exception as e:
            self.logger.warning(f"[{self.name}] 发布按钮定位异常: {str(e)[:40]}")
        if not clicked:
            await self._shot(page, "no_publish")
            return {"ok": False, "url": "", "note": "发布按钮没点中"}
        # 轮询抓"发布成功"toast(它只闪现几秒, 一次性检查会错过)
        for _ in range(24):                              # 最多 ~7s
            await page.wait_for_timeout(300)
            try:
                txt = await page.evaluate("""() => {
                    for (const e of document.querySelectorAll(
                        '[class*="toast"],[class*="message"],[class*="tip"],[class*="Message"]')) {
                        const t=(e.innerText||'').trim();
                        if (t && (t.includes('发布成功') || t.includes('成功'))) return t;
                        if (t && (t.includes('失败') || t.includes('违规') || t.includes('敏感'))) return 'FAIL:'+t;
                    }
                    return '';
                }""")
            except Exception:
                txt = ""
            if txt.startswith("FAIL:"):
                await self._shot(page, "fail")
                return {"ok": False, "url": page.url, "note": txt[5:][:40]}
            if txt:
                await self._shot(page, "ok")
                real = await self._get_latest_post_url(page)
                return {"ok": True, "url": real or page.url,
                        "note": "发布成功(toast)" + ("" if real else "[链接待核实]")}
            if re.search(r"xueqiu\.com/\d+/\d+", page.url):
                return {"ok": True, "url": page.url, "note": "URL确认"}
        await self._shot(page, "result")
        return {"ok": False, "url": page.url, "note": "未见成功toast"}

    async def _get_latest_post_url(self, page) -> str:
        """发布成功后, 去个人主页抓最新一篇帖子的真实链接 xueqiu.com/{uid}/{pid}。"""
        try:
            await page.goto("https://xueqiu.com/", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2500)
            me = await page.evaluate("""() => {
                const a = document.querySelector('a[href^="/u/"]');
                return a ? a.getAttribute('href') : '';
            }""")
            if not me:
                return ""
            uid = me.replace("/u/", "").strip()
            await page.goto(f"https://xueqiu.com/u/{uid}", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            href = await page.evaluate("""(uid) => {
                for (const a of document.querySelectorAll(`a[href*="/${uid}/"]`)) {
                    const h = a.getAttribute('href') || '';
                    if (new RegExp(`/${uid}/\\\\d{6,}`).test(h)) return h;
                }
                return '';
            }""", uid)
            if href:
                return href if href.startswith("http") else ("https://xueqiu.com" + href)
            return ""
        except Exception:
            return ""
