"""东方财富 财富号长文 自动发布适配器

校准来源: 2026-06-03 真站抓取
  发文页 = https://mp.eastmoney.com/collect/pc_article/index.html#/ (点"发长文"进的财富号编辑器)
  登录入口 = https://i.eastmoney.com/ (未登录跳 passport2.eastmoney.com/pub/login)
  标题 = input[placeholder*="标题"] (限 1-64 字)
  正文 = div.cfh_editor_area[contenteditable] (ProseMirror, 同老虎家族)
  加粗 = Cmd+B; 斜体 = Cmd+I (ProseMirror 标准, 实测生效)
  标题 = 点 .em_icon_heading 开下拉 → .em_icon_heading2(大标题/h2) 或 .em_icon_heading3(小标题/h3)
  图片 = 点 .em_icon_image → 模态 input[type=file] 传 → 点"插入"
  发布 = button.button_publish (可能需先填发文设置)
  起始有"草稿载入"提示条要先关
  股票: 编辑器内打 $ 不联想; 暂按 $名字(代码)$ 纯文本(东财发布后可能自动成卡片, 待验证)
"""

import re
from pathlib import Path

from .base import BrowserPublisher
import content as content_mod


class EastmoneyPublisher(BrowserPublisher):
    name = "eastmoney"
    # 独立 profile(原 .eastmoney_chrome_profile 登的是鹏哥投研小号, 非花街S姐);
    # auto-publisher 固定发花街S姐, 首次弹窗手动登录
    profile_dir = str(Path.home() / ".eastmoney_autopub_chrome_profile")
    compose_url = "https://mp.eastmoney.com/collect/pc_article/index.html#/"
    login_url = "https://i.eastmoney.com/"
    logged_out_url_marks = ["passport", "/login", "/pub/login"]

    TITLE_SEL = 'input[placeholder*="标题"]'
    BODY_SEL = 'div.cfh_editor_area[contenteditable="true"]'
    HEADING_BTN = '.em_icon_heading'
    H_BIG = '.em_icon_heading2'      # 大标题 (Word H1)
    H_SMALL = '.em_icon_heading3'    # 小标题 (Word H2/H3)
    IMAGE_BTN = '.em_icon_image'
    PUBLISH_BTN = 'button.button_publish, .button_publish'
    TITLE_MAX = 64

    OK_KW = ("成功", "已发布", "发布成功")
    FAIL_KW = ("失败", "违规", "敏感", "频繁", "禁止", "不能", "请选择", "请填写", "请输入")

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

    async def _dismiss_prompts(self, page):
        """关掉'草稿载入'等提示条(否则拦截工具栏点击)。"""
        for sel in ['.prompt_wrapper .close', '.prompt_wrapper [class*="close"]',
                    '[class*="prompt"] [class*="close"]', '.notice_close']:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click(timeout=1500)
                    await page.wait_for_timeout(300)
            except Exception:
                pass

    _cur_title = ""

    async def publish_one(self, page, article: dict, draft: bool) -> dict:
        title = content_mod.strip_stock_tags(self.resolve_title(article))
        if len(title) > self.TITLE_MAX:
            self.logger.warning(f"[{self.name}] 标题 {len(title)}字 超{self.TITLE_MAX}, 截断")
            title = title[: self.TITLE_MAX]
        self._cur_title = title
        blocks = article.get("blocks", [])
        # 表格图文字化: 东财能正常显示图, 但表格类图常上传超时。有转写(articles/_tables/<文章名>.json)的
        # 表格图换成文字(参考知乎), 其余图仍照常上传(only_transcribed=True)。
        if any(b["type"] == "image" for b in blocks):
            try:
                import chart_gap
                trans = chart_gap.load_transcriptions(article["id"])
                if trans:
                    blocks = chart_gap.fill_chart_gaps(blocks, self.logger,
                                                       transcriptions=trans, only_transcribed=True)
            except Exception as e:
                self.logger.warning(f"[{self.name}] 表格文字化失败(用原blocks): {e}")
        n_head = sum(1 for b in blocks if b["type"] == "heading")
        n_img = sum(1 for b in blocks if b["type"] == "image")
        self.logger.info(f"[{self.name}] 准备发: {article['id']} | 标题={title[:30]!r} "
                         f"| {len(blocks)}块(标题{n_head}/图{n_img})")

        await page.goto(self.compose_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        await self._dismiss_prompts(page)
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
        await page.wait_for_timeout(1500)
        await self._shot(page, "content_filled")

        if draft:
            try:
                html = await page.evaluate("()=>document.querySelector('.cfh_editor_area').innerHTML")
                dump = Path(__file__).resolve().parent.parent / "logs" / "eastmoney_draft_dump.html"
                dump.write_text(html, encoding="utf-8")
                tags = {t: len(re.findall(f"<{t}[ >]", html)) for t in ("h2", "h3", "strong", "em", "img", "p")}
                self.logger.info(f"[{self.name}] [草稿]HTML结构: {tags} → logs/eastmoney_draft_dump.html")
            except Exception as e:
                self.logger.warning(f"[{self.name}] dump 失败: {e}")
            return {"ok": True, "url": "", "note": "draft(未发布)"}

        # 发布(发文设置可能必填 → 见 _do_publish)
        return await self._do_publish(page)

    # ---------- 正文富文本 ----------

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
        heads = imgs_ok = imgs_fail = 0
        wrote_any = False          # 是否已经写入过内容(决定要不要先换行)
        for blk in blocks:
            if blk["type"] == "hr":
                continue
            if blk["type"] == "image":
                # 图片单独成行: 前面换行 → 上传 → 失败则把这空行删掉(不留空行)
                if wrote_any:
                    await page.keyboard.press("Enter")
                if await self._upload_image(page, blk.get("src", ""), art_dir):
                    imgs_ok += 1
                    wrote_any = True
                    await self._cursor_to_end(page)
                else:
                    imgs_fail += 1
                    if wrote_any:
                        # 删掉刚才为图片预留的空行(防止留空行触发东财内容检测)
                        await page.keyboard.press("Backspace")
                continue
            # 文本/标题/列表块: 跳过纯空白块, 有内容才换行+输入
            runs = blk.get("runs", [])
            text = "".join(content_mod.clean_spaces(r.get("text", "")) for r in runs if not r.get("stock"))
            has_content = bool(text.strip()) or any(r.get("stock") for r in runs)
            if not has_content:
                continue
            if wrote_any:
                await page.keyboard.press("Enter")
            if blk["type"] == "list_item":
                await page.keyboard.type("• ", delay=6)
            await self._type_runs(page, runs)
            wrote_any = True
            if blk["type"] == "heading":
                await self._apply_heading(page, blk.get("level", 2))
                heads += 1
        # 清理: 删掉编辑器里的连续空段落/空行(图片失败等可能残留, 触发东财内容检测)
        try:
            removed = await page.evaluate("""() => {
                const ed = document.querySelector('.cfh_editor_area');
                if (!ed) return 0;
                let n = 0;
                // 删除完全空的块级元素(p/div 无文本无图)
                ed.querySelectorAll('p, div').forEach(el => {
                    if (el === ed) return;
                    const txt = (el.innerText || '').replace(/\\s|\\u00a0/g, '');
                    const hasMedia = el.querySelector('img, video, [class*=stock], a');
                    if (!txt && !hasMedia && el.parentElement === ed) { el.remove(); n++; }
                });
                return n;
            }""")
            if removed:
                self.logger.info(f"[{self.name}] 清理空行/空段落: {removed} 个")
        except Exception as e:
            self.logger.warning(f"[{self.name}] 清理空行异常: {str(e)[:40]}")
        self.logger.info(f"[{self.name}] 正文已输入(块{len(blocks)} 标题{heads} 配图 成功{imgs_ok}/失败{imgs_fail})")
        return True

    async def _type_runs(self, page, runs):
        for r in runs:
            if r.get("stock"):
                code, name = r["stock"]
                await page.keyboard.type(f"${name}({code})$", delay=5)   # 东财: 纯文本标签
                continue
            text = content_mod.clean_spaces(r.get("text", ""))   # 清多余空格
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

    async def _cursor_to_end(self, page):
        """把光标强制放到编辑器内容末尾(防止模态交互后丢焦点)。"""
        try:
            await page.locator(self.BODY_SEL).first.click(timeout=4000)
            await page.evaluate("""() => {
                const ed = document.querySelector('.cfh_editor_area');
                if (!ed) return;
                ed.focus();
                const sel = window.getSelection(); const r = document.createRange();
                r.selectNodeContents(ed); r.collapse(false);
                sel.removeAllRanges(); sel.addRange(r);
            }""")
        except Exception:
            pass

    async def _modal_open(self, page) -> bool:
        """图片模态特征: 可见的 取消(.btn_cancel)/插入(.btn_confirm)/本地上传。"""
        try:
            for sel in ('.btn_confirm', '.btn_cancel', '.list_upload_btn'):
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    return True
            return False
        except Exception:
            return False

    async def _close_modal(self, page):
        """关掉残留图片弹窗(取消 / Escape)。"""
        if not await self._modal_open(page):
            return
        try:
            c = page.locator('.btn_cancel').first
            if await c.count() > 0 and await c.is_visible():
                await c.click(timeout=2000)
                await page.wait_for_timeout(400)
                return
        except Exception:
            pass
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(300)
        except Exception:
            pass

    async def _apply_heading(self, page, level: int):
        """选中本行 → 开标题下拉 → Word H1→大标题, H2+→小标题(用文字点击, 已验证)。"""
        await self._close_modal(page)
        await page.keyboard.press("Home")
        await page.keyboard.down("Shift")
        await page.keyboard.press("End")
        await page.keyboard.up("Shift")
        label = "大标题" if level <= 1 else "小标题"
        try:
            await page.locator(self.HEADING_BTN).first.click(timeout=6000)
            await page.wait_for_timeout(500)
            await page.get_by_text(label, exact=True).first.click(timeout=4000)
            await page.wait_for_timeout(400)
        except Exception as e:
            self.logger.warning(f"[{self.name}] 标题应用失败({label}): {str(e)[:60]}")
        # 关键: 点工具栏下拉会丢编辑器焦点, 若紧跟 Enter 会把刚应用的标题行吞掉
        # (尤其首行标题)。应用后强制重聚焦到编辑器末尾, 确保后续 Enter/输入落在正确位置。
        await self._cursor_to_end(page)
        await page.wait_for_timeout(250)

    async def _upload_image(self, page, src, art_dir) -> bool:
        if not src:
            return False
        path = Path(src)
        if not path.is_absolute() and art_dir:
            path = Path(art_dir) / src
        if not path.exists():
            self.logger.warning(f"[{self.name}] 配图不存在, 跳过: {path}")
            return False
        await self._close_modal(page)
        try:
            before = await page.locator('.cfh_editor_area img').count()
            await page.locator(self.IMAGE_BTN).first.click(timeout=8000)
            await page.wait_for_timeout(1500)               # 等上传模态
            # 确保在"上传图片/本地上传"tab(避免复用时停在图片库)
            try:
                tab = page.get_by_text("上传图片", exact=True).first
                if await tab.count() > 0 and await tab.is_visible():
                    await tab.click(timeout=2000)
                    await page.wait_for_timeout(400)
            except Exception:
                pass
            inp = page.locator('input[type="file"]').last
            await inp.set_input_files(str(path))
            # 反复点"插入"并检查编辑器图+1: 上传未完成时点是空操作, 传完那次才成功
            ok = False
            clicked = False
            for _ in range(40):                              # 最多 ~24s
                await page.wait_for_timeout(600)
                b = page.locator('.btn_confirm').first
                try:
                    if await b.count() > 0 and await b.is_visible():
                        await b.click(timeout=2000)
                        clicked = True
                except Exception:
                    pass
                if await page.locator('.cfh_editor_area img').count() > before:
                    ok = True
                    break
            if ok:
                self.logger.info(f"[{self.name}] 配图已上传: {path.name}")
                if await self._modal_open(page):
                    await self._close_modal(page)
                return True
            self.logger.warning(f"[{self.name}] 配图未嵌入(insert点={clicked}): {path.name}")
            await self._close_modal(page)
            return False
        except Exception as e:
            self.logger.warning(f"[{self.name}] 配图上传失败 {path.name}: {str(e)[:80]}")
            await self._close_modal(page)
            return False

    # ---------- 发布 ----------

    async def _check_agreement(self, page) -> None:
        """勾上"已阅读并同意《财富号作者发文规范》《东方财富社区管理规定》"的 checkbox。"""
        try:
            checked = await page.evaluate("""() => {
                // 兜底1: i.check-icon 等自定义图标(父级文案含"已阅读并同意")
                for (const e of document.querySelectorAll('[class*="check-icon"],[class*="checkIcon"],[class*="agree"]')) {
                    const t = (e.parentElement && e.parentElement.innerText) || '';
                    if (/已阅读并同意/.test(t) && e.offsetParent) { e.click(); return true; }
                }
                // 找"已阅读并同意"文案附近的 checkbox / radio
                const labels = [...document.querySelectorAll('*')].filter(e =>
                    e.children.length <= 3 && /已阅读并同意|发文规范|社区管理规定/.test(e.innerText||''));
                for (const lab of labels) {
                    const box = lab.querySelector('input[type=checkbox],input[type=radio]')
                        || (lab.previousElementSibling && lab.previousElementSibling.matches('input,[class*=check],[class*=radio]') ? lab.previousElementSibling : null)
                        || lab.parentElement.querySelector('input[type=checkbox],[class*=checkbox],[class*=check-box]');
                    if (box) {
                        if (box.tagName === 'INPUT') { if (!box.checked) box.click(); return box.checked; }
                        // 自定义 checkbox: 点它
                        box.click(); return true;
                    }
                    // 整个 label 区域可点
                    const ck = lab.querySelector('[class*=checkbox],[class*=check]');
                    if (ck) { ck.click(); return true; }
                }
                return null;
            }""")
            await page.wait_for_timeout(500)
            # 兜底: Playwright 点击"已阅读并同意"前面的勾选框
            if checked is None:
                try:
                    cb = page.locator('text=已阅读并同意').first
                    if await cb.count() > 0:
                        box = cb.locator('xpath=preceding-sibling::*[1] | xpath=../input | xpath=..//input').first
                        if await box.count() > 0:
                            await box.click(timeout=2000)
                            checked = True
                except Exception:
                    pass
            self.logger.info(f"[{self.name}] 同意框勾选: {checked}")
        except Exception as e:
            self.logger.warning(f"[{self.name}] 勾同意框异常: {str(e)[:50]}")

    async def _do_publish(self, page) -> dict:
        """发布: 勾同意框 → 点发布 → 处理弹窗(同意规范/分类/最终确认)→ 判定。"""
        url_before = page.url
        # 首次发文必须勾"已阅读并同意《财富号作者发文规范》"内联 checkbox(否则发布卡住)
        await self._check_agreement(page)
        for attempt in range(5):
            # 关掉"不文明用语"等浮层提示(可能遮挡发布按钮)
            try:
                await page.evaluate("""() => {
                    document.querySelectorAll('[class*=prompt],[class*=tip],[class*=notice],[class*=toast]').forEach(e=>{
                        if (/不文明|不合适|不再提示|提示/.test(e.innerText||'')) {
                            const c = e.querySelector('[class*=close],.close') || e;
                            try { c.click(); } catch(_){}
                            e.style.display='none';
                        }
                    });
                }""")
            except Exception:
                pass
            await self._click_publish(page, attempt)
            await page.wait_for_timeout(2500)
            await self._shot(page, f"pub_{attempt}")
            acted = await self._handle_publish_dialog(page)
            # "请同意规范"弹窗出现时, 勾选状态已被重置 → 重新勾上下轮重试
            await self._check_agreement(page)
            await page.wait_for_timeout(2500)
            # 内容拦截检测(东财敏感词过滤): 弹"不文明/不合适发布用语"等 = 发布失败
            block = await page.evaluate("""() => {
                const t = document.body.innerText || '';
                const m = t.match(/[^。\\n]{0,30}(不文明|不合适发布|违规|敏感词|含有违禁|存在风险|涉及)[^。\\n]{0,30}/);
                return m ? m[0].trim() : '';
            }""")
            if block:
                await self._shot(page, "blocked")
                return {"ok": False, "url": page.url, "note": f"内容被拦截: {block[:40]}"}
            # 明确成功弹窗
            ok_popup = await page.evaluate("""() => {
                const ds = [...document.querySelectorAll('[class*=dialog],[class*=modal],[class*=prompt]')]
                    .filter(e => e.getBoundingClientRect().width > 0);
                return ds.some(e => /发布(文章)?成功|提交成功/.test(e.innerText || ''));
            }""")
            if ok_popup:
                break
            if "articlelist" in page.url:
                break
            if not acted:
                await page.wait_for_timeout(2000)
        # 已跳到文章列表页 = 发布对话框走完、提交成功(用户手动验证: 点发布后跳 articlelist 即成功)
        jumped = "articlelist" in page.url
        # 权威判定: 去文章管理列表查这篇标题(带回审核状态)。抓取可能漏/延迟, 故不作唯一依据。
        status = await self._check_in_list(page, self._cur_title)
        if status["found"]:
            self.logger.info(f"[{self.name}] 文章已进列表, 审核状态: {status['state']}")
            return {"ok": True, "url": status.get("url", ""),
                    "note": f"已提交({status['state']})"}
        if jumped:
            self.logger.info(f"[{self.name}] 已跳转文章列表(提交成功, 列表项抓取未命中)")
            return {"ok": True, "url": page.url, "note": "已提交(跳列表确认)"}
        await self._shot(page, "publish_stuck")
        return {"ok": False, "url": page.url, "note": "文章未进列表(疑被拦截或卡住)"}

    async def _click_publish(self, page, attempt) -> bool:
        """可靠点击东财发布按钮(它是 div.button_publish 在底部, 普通 click 易失效)。
        滚动到可见 → Playwright 真实点击 → 兜底用 JS 派发真实鼠标事件序列。
        """
        loc = page.locator('.button_publish').first
        try:
            if await loc.count() == 0:
                self.logger.warning(f"[{self.name}] 发布按钮(.button_publish)未找到")
                return False
            await loc.scroll_into_view_if_needed(timeout=4000)
            await page.wait_for_timeout(400)
        except Exception:
            pass
        # 方式1: Playwright 真实点击(含 hover+mousedown+mouseup)
        try:
            await loc.click(timeout=5000)
            self.logger.info(f"[{self.name}] 已点发布(playwright click) attempt={attempt}")
            return True
        except Exception as e:
            self.logger.warning(f"[{self.name}] playwright click 失败: {str(e)[:50]}")
        # 方式2: JS 派发完整鼠标事件序列(div 按钮可能只听这些)
        try:
            ok = await page.evaluate("""() => {
                const el = document.querySelector('.button_publish');
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const x = r.x + r.width/2, y = r.y + r.height/2;
                for (const type of ['pointerdown','mousedown','pointerup','mouseup','click']) {
                    el.dispatchEvent(new MouseEvent(type, {bubbles:true, cancelable:true, view:window,
                        clientX:x, clientY:y}));
                }
                return true;
            }""")
            self.logger.info(f"[{self.name}] 已点发布(JS鼠标事件) ok={ok}")
            return bool(ok)
        except Exception as e:
            self.logger.warning(f"[{self.name}] JS 点发布失败: {str(e)[:50]}")
            return False

    async def _check_in_list(self, page, title: str) -> dict:
        """去文章管理列表, 查标题匹配的最新一篇 → 返回 {found, state, url}。
        state ∈ 已发布/审核中/未通过/未知。这是东财发布是否成功的权威判据(提交成功就进列表)。
        """
        key = (title or "").strip()[:12]
        try:
            await page.goto("https://mp.eastmoney.com/collect/pc_writer/index.html#/content/articlelist",
                            wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(6000)
            r = await page.evaluate("""(key) => {
                if (!key) return {found:false};
                // 找文本含标题 key 的列表条目, 取其所在卡片的状态标签
                const nodes = [...document.querySelectorAll('*')].filter(e =>
                    e.children.length <= 3 && (e.innerText||'').trim().includes(key));
                if (!nodes.length) return {found:false};
                // 取最靠上(最新)的那条, 向上找卡片容器读状态
                let el = nodes[0];
                let card = el;
                for (let i=0;i<6 && card.parentElement;i++) card = card.parentElement;
                const t = (card.innerText||'');
                let state = '未知';
                if (/未通过/.test(t)) state='未通过';
                else if (/审核中|待审核/.test(t)) state='审核中';
                else if (/已发布|已发表/.test(t)) state='已发布';
                // 找公开链接
                let url='';
                card.querySelectorAll('a[href]').forEach(a=>{const h=a.getAttribute('href')||'';
                    if(/(news|article|a\\/)/.test(h) && /eastmoney/.test(h) && !url) url=h;});
                return {found:true, state, url};
            }""", key)
            return r or {"found": False}
        except Exception as e:
            self.logger.warning(f"[{self.name}] 查列表异常: {str(e)[:40]}")
            return {"found": False}

    async def _handle_publish_dialog(self, page) -> bool:
        """处理发布弹窗序列, 点了任意一个返回 True。
        ① 同意《财富号作者发文规范》提示 → 确定
        ② 发文设置分类(请选择)→ 选第一项
        ③ 最终确认发布。
        """
        acted = False
        try:
            dlg_txt = await page.evaluate("""() => {
                const ds=[...document.querySelectorAll('[class*="dialog"],[class*="prompt"],[class*="modal"]')]
                  .filter(e=>e.getBoundingClientRect().width>0);
                return ds.map(e=>e.innerText||'').join(' ').slice(0,400);
            }""")
        except Exception:
            dlg_txt = ""
        # ① 同意规范
        if any(k in dlg_txt for k in ("请同意", "发文规范", "管理规定")):
            for lab in ("确定", "同意", "我已阅读", "确认"):
                b = page.locator(f'button:has-text("{lab}")').first
                try:
                    if await b.count() > 0 and await b.is_visible():
                        await b.click(timeout=3000)
                        self.logger.info(f"[{self.name}] 已同意发文规范({lab})")
                        acted = True
                        await page.wait_for_timeout(1200)
                        break
                except Exception:
                    continue
        # ② 分类(请选择)
        try:
            sel = page.locator('input[placeholder="请选择"], .el-input__inner[placeholder*="请选择"]').first
            if await sel.count() > 0 and await sel.is_visible():
                await sel.click()
                await page.wait_for_timeout(800)
                opt = page.locator('.el-select-dropdown__item:visible, li[class*="option"]:visible').first
                if await opt.count() > 0:
                    await opt.click(timeout=3000)
                    self.logger.info(f"[{self.name}] 已选分类")
                    acted = True
                    await page.wait_for_timeout(600)
        except Exception:
            pass
        # ③ 弹窗内最终确认
        try:
            for lab in ("确定发布", "确认发布", "立即发布"):
                b = page.locator(f'[class*="dialog"] button:has-text("{lab}"), [class*="modal"] button:has-text("{lab}")').first
                if await b.count() > 0 and await b.is_visible():
                    await b.click(timeout=3000)
                    self.logger.info(f"[{self.name}] 已点最终确认({lab})")
                    acted = True
                    await page.wait_for_timeout(1200)
                    break
        except Exception:
            pass
        return acted
