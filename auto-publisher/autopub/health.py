"""auto-publisher 健康体检 —— 一条命令看清"问题在哪"

检查项:
  1. 待发队列   articles/ 里还有几篇没发(含文件名)
  2. 发布账本   state.json 每篇×每平台状态, 重点标出 failed/uncertain 及原因备注
  3. 平台登录态 各平台用真实登录态打开发文页检测(会话过期是最大故障源)
  4. 最近日志  publish_all.log / webrun.log 里最近的 ERROR(带时间, 便于对账)

用法:
  py health.py            # 全量体检(含登录态检测, 每平台约10秒)
  py health.py --fast     # 跳过登录检测, 秒出
  py health.py --all      # 登录检测覆盖全部注册平台(默认只查 config 启用的)

报告同时写入 logs/health_report_<时间>.txt; 控制台"一键体检"调用的也是这里。
"""

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from publishers import REGISTRY            # noqa: E402
from publish_all import load_config        # noqa: E402

LOG_FILES = [ROOT / "logs" / "publish_all.log", ROOT / "logs" / "webrun.log"]


# ---------- 1. 待发队列 ----------

def check_queue() -> dict:
    arts_dir = ROOT / (load_config().get("articles_dir") or "articles")
    files = [f.name for f in sorted(arts_dir.glob("*.md")) + sorted(arts_dir.glob("*.docx"))
             if not f.name.startswith("~$")] if arts_dir.exists() else []
    return {"count": len(files), "files": files}


# ---------- 2. 发布账本 ----------

def check_ledger() -> dict:
    sp = ROOT / "state.json"
    if not sp.exists():
        return {"articles": {}, "problems": []}
    try:
        data = json.loads(sp.read_text(encoding="utf-8"))
    except Exception as e:
        return {"articles": {}, "problems": [f"state.json 损坏无法读取: {e}"]}
    problems = []
    for aid, plats in (data or {}).items():
        for p, info in (plats or {}).items():
            st = (info or {}).get("status", "")
            if st in ("failed", "uncertain"):
                note = (info or {}).get("note", "")
                t = (info or {}).get("time", "")
                hint = ("需人工到平台后台核实(按安全设计不会自动重试)"
                        if st == "uncertain" else "可单独补发: python publish_all.py "
                        f"--file {aid} --platforms {p}")
                problems.append({"article": aid, "platform": p, "status": st,
                                 "note": note, "time": t, "hint": hint})
    return {"articles": data or {}, "problems": problems}


# ---------- 3. 平台登录态 ----------

def enabled_platforms() -> list:
    cfg = load_config().get("platforms") or {}
    return [p for p in cfg if cfg[p].get("enabled") and p in REGISTRY]


async def _check_one(p, name: str) -> dict:
    from playwright.async_api import async_playwright
    t0 = time.time()
    cfg = (load_config().get("platforms") or {}).get(name, {}) or {}
    pub = REGISTRY[name](cfg, None, _Quiet())
    prof = ROOT / "profiles" / name
    basic = {"platform": name, "sec": round(time.time() - t0, 1)}
    if not prof.exists():
        return {**basic, "logged_in": False, "why": "从未登录(profile 不存在), 先跑 python login.py " + name}
    try:
        async with async_playwright() as pw:
            ctx = await pw.chromium.launch_persistent_context(
                str(prof), headless=True, viewport={"width": 1280, "height": 900},
                locale="zh-CN")
            try:
                sp = ROOT / f"profiles/{name}.state.json"
                if sp.exists():
                    state = json.loads(sp.read_text(encoding="utf-8"))
                    if state.get("cookies"):
                        # 只补缺的 Cookie, 不覆盖 profile 里更新的(旧存档会打回新 token)
                        existing = {c["name"] for c in await ctx.cookies()}
                        to_add = [c for c in state["cookies"]
                                  if c["name"] not in existing]
                        if to_add:
                            await ctx.add_cookies(to_add)
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                page.set_default_timeout(30000)
                await page.goto(pub.compose_url, wait_until="domcontentloaded",
                                timeout=45000)
                await page.wait_for_timeout(4000)
                if not await pub.is_logged_in(page):
                    # 渲染滞后兜底: 重载一次再判(与 wait_for_login 同逻辑)
                    try:
                        await page.reload(wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_timeout(3000)
                    except Exception:
                        pass
                ok = await pub.is_logged_in(page)
                why = "" if ok else "登录态失效(会话被平台踢下线), 跑 python login.py " + name + " 重扫"
                return {**basic, "logged_in": ok, "why": why,
                        "sec": round(time.time() - t0, 1)}
            finally:
                await ctx.close()
    except Exception as e:
        msg = str(e)
        if "Target closed" in msg or "已打开" in msg or "singleton" in msg.lower() \
           or "ProcessSingleton" in msg:
            why = "profile 正被占用(登录/发布窗口开着), 关掉窗口后再体检"
        else:
            why = f"检测异常: {msg[:80]}"
        return {**basic, "logged_in": None, "why": why, "sec": round(time.time() - t0, 1)}


class _Quiet:
    def info(self, m): pass
    def warning(self, m): pass
    def error(self, m): pass


async def check_logins_async(names: list) -> list:
    """异步版: 可在已运行的事件循环里 await(发布主流程用)。"""
    return [await _check_one(None, n) for n in names]


def check_logins(names: list) -> list:
    """同步版: 命令行/Flask 等无事件循环环境用。"""
    return asyncio.run(check_logins_async(names))


# ---------- 4. 最近日志错误 ----------

def check_recent_errors(limit: int = 12) -> list:
    out = []
    for lf in LOG_FILES:
        if not lf.exists():
            continue
        try:
            lines = lf.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        errs = [ln.strip() for ln in lines if "[ERROR]" in ln]
        for ln in errs[-limit:]:
            out.append({"file": lf.name, "line": ln[:160]})
    return out[-limit * 2:]


# ---------- 汇总 ----------

def run_health(fast: bool = False, all_platforms: bool = False) -> dict:
    queue = check_queue()
    ledger = check_ledger()
    errors = check_recent_errors()
    plats = list(REGISTRY) if all_platforms else enabled_platforms()
    logins = [] if fast else check_logins(plats)
    report = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "queue": queue, "ledger_problems": ledger["problems"],
        "logins": logins, "recent_errors": errors,
    }
    _write_report(report)
    return report


def _write_report(rep: dict) -> None:
    lines = [f"体检报告  {rep['time']}", "=" * 60]
    q = rep["queue"]
    lines.append(f"\n[待发队列] {q['count']} 篇")
    lines += [f"  · {f}" for f in q["files"]] or ["  (空)"]
    lines.append(f"\n[账本问题] {len(rep['ledger_problems'])} 条")
    for pb in rep["ledger_problems"]:
        lines.append(f"  ❌ {pb['article']} × {pb['platform']} {pb['status']}"
                     f" | {pb['note'][:50]} | {pb['time']}")
        lines.append(f"     → {pb['hint']}")
    lines.append(f"\n[平台登录态] {len(rep['logins'])} 个")
    for lg in rep["logins"]:
        mark = "✅" if lg["logged_in"] else ("⚠️ " if lg["logged_in"] is None else "❌")
        lines.append(f"  {mark} {lg['platform']:14s} {lg['why'] or '正常'} ({lg['sec']}s)")
    lines.append(f"\n[最近日志错误] {len(rep['recent_errors'])} 条")
    for e in rep["recent_errors"]:
        lines.append(f"  · [{e['file']}] {e['line']}")
    text = "\n".join(lines)
    out = ROOT / "logs" / f"health_report_{datetime.now():%Y%m%d_%H%M}.txt"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text, encoding="utf-8")
    rep["report_file"] = str(out)
    rep["report_text"] = text


def main():
    ap = argparse.ArgumentParser(description="auto-publisher 健康体检")
    ap.add_argument("--fast", action="store_true", help="跳过登录态检测")
    ap.add_argument("--all", action="store_true", help="登录检测覆盖全部注册平台")
    args = ap.parse_args()
    rep = run_health(fast=args.fast, all_platforms=args.all)
    print(rep["report_text"])
    print(f"\n报告已存: {rep['report_file']}")


if __name__ == "__main__":
    main()
