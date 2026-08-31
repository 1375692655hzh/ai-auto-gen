# -*- coding: utf-8 -*-
"""腾讯元宝对话自动化:用元宝的联网搜索取"当日 Gangtise投研日报"全文。

原理:元宝网页版登录一次(持久化 user-data-dir,存 output/yuanbao-profile),
之后无头复用登录态:新建对话 -> 发固定 prompt -> 等回答完成 -> 从 DOM 抓正文。

用法:
  py -3.11 generator/yuanbao_fetch.py --login    # 首次:打开有头浏览器,扫码登录后自动关闭
  py -3.11 generator/yuanbao_fetch.py            # 无头:取当日 gangtise 日报,JSON 存 output/daily/
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

GEN_ROOT = Path(__file__).resolve().parent
PROFILE_DIR = GEN_ROOT / "output" / "yuanbao-profile"
OUT_DIR = GEN_ROOT / "output" / "daily"

PROMPT = (
    "帮我收集当天最新的gangtise投研公众号文章，文章名一般是“Gangtise投研日报 | {mdy}星期{wd}”"
    "这种形式，我要的是当天的，周一到周五有这种文章，把最新的文章内容发我"
)

WEEKDAYS = "一二三四五六日"


def _new_page(ctx):
    page = ctx.new_page()
    page.goto("https://yuanbao.tencent.com/chat", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    return page


def _logged_in(page) -> bool:
    txt = page.inner_text("body")[:4000]
    return "未登录" not in txt and "登录" not in txt[:200]


def _ask_and_read(page, prompt: str, timeout_s: int = 180) -> str:
    # 关掉"下载元宝电脑版"推广弹窗(会挡住输入框)
    try:
        page.get_by_role("button", name=re.compile("关闭|Close")).first.click(timeout=2000)
        page.wait_for_timeout(800)
    except Exception:
        pass
    box = page.locator("div[contenteditable='true']").first
    box.click()
    box.fill(prompt)
    page.wait_for_timeout(500)
    # 发送:优先按钮,回退回车
    try:
        page.get_by_role("button", name="发送").click(timeout=3000)
    except Exception:
        box.press("Enter")
    # 等回答完成:停止生成按钮出现后消失
    page.wait_for_timeout(8000)
    deadline = datetime.datetime.now() + datetime.timedelta(seconds=timeout_s)
    stable, last_len = 0, -1
    while datetime.datetime.now() < deadline:
        page.wait_for_timeout(5000)
        try:
            streaming = page.get_by_text("停止生成").count() > 0
        except Exception:
            streaming = False
        txt = _read_answer(page)
        if not streaming and len(txt) > 200 and len(txt) == last_len:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        last_len = len(txt)
    return _read_answer(page)


def _read_answer(page) -> str:
    best = ""
    for sel in ("[class*='answer']", "[class*='markdown']", "[class*='response']", "[class*='bubble']"):
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                txt = loc.last.inner_text(timeout=5000)
                if len(txt) > len(best):
                    best = txt
        except Exception:
            continue
    return best.strip()


def run(prompt: str | None = None, headless: bool = True) -> dict:
    from playwright.sync_api import sync_playwright
    d = datetime.date.today()
    prompt = prompt or PROMPT.format(mdy=f"{d.month}月{d.day}日", wd=WEEKDAYS[d.weekday()])
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=headless,
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"])
        page = _new_page(ctx)
        try:
            if not _logged_in(page):
                return {"ok": False, "error": "未登录:先跑 --login 扫码"}
            text = _ask_and_read(page, prompt)
            src = re.search(r"https?://mp\.weixin\.qq\.com/s[^\s]+", text)
            return {"ok": bool(text) and "NOT_FOUND" not in text[:50],
                    "text": text, "date": d.isoformat(), "url": page.url,
                    "article_url": src.group(0) if src else ""}
        finally:
            ctx.close()


def login():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=False,
            viewport={"width": 1440, "height": 900})
        page = _new_page(ctx)
        if _logged_in(page):
            print("档案已登录,无需扫码")
        else:
            # 点登录按钮弹二维码,等用户扫码
            try:
                page.get_by_role("button", name="登录").click(timeout=5000)
            except Exception:
                pass
            print("请在弹出的浏览器里用微信扫码登录元宝…")
            deadline = datetime.datetime.now() + datetime.timedelta(minutes=5)
            while datetime.datetime.now() < deadline:
                page.wait_for_timeout(5000)
                if _logged_in(page):
                    break
        page.wait_for_timeout(5000)
        ctx.close()
        print("登录态已保存到", PROFILE_DIR)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true", help="首次扫码登录")
    ap.add_argument("--prompt", help="自定义提问")
    ap.add_argument("--show", action="store_true", help="有头模式(调试)")
    a = ap.parse_args()
    if a.login:
        login()
        return
    r = run(a.prompt, headless=not a.show)
    if r["ok"]:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUT_DIR / f"gangtise-元宝-{datetime.date.today():%Y%m%d}.json"
        out.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"OK {len(r['text'])}字 -> {out}")
        print(r["text"][:400])
    else:
        print("FAIL:", r.get("error") or r.get("text", "")[:200])
        sys.exit(1)


if __name__ == "__main__":
    main()
