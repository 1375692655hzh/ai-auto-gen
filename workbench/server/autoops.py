"""自动化任务执行 + 发布入队(workbench 侧编排; 2026-09-11 施工收尾)。

页面现状: 图文页「自动化任务」CRUD 一直真实(data/workbench/automation.json),
缺的是调度与执行;「内容发布」的确认发布是死桩。本模块补齐:
- 任务调度: schtasks 直调 pyw(免 wscript 链, 09-10 常驻事故教训)登记
  `aag-wb-auto-<id>`; daily/workday(周一~五)/weekly 三种频率。
- run_one(task): 运行时取种子(数据站可达用其条目, 纯工作台退 SoPilot 热帖)
  → gcompose.run_compose 成稿 → 产物按 target 落位: draft=草稿箱,
  queue=发布仓 articles/(AAG_AUTOPUB_ROOT 三级解析, 未就位 exit 4)。
  direct(按配置发布)仍留桩——红线: 真发必须 `publish run --draft` + 人工确认。
- enqueue_draft(draft): 把草稿箱一篇写成发布仓待发 md(推入待发队列)。
执行全部发生在 CLI 子进程(run-auto / enqueue), 端点只 Popen, 零外呼红线不破。
"""
import json
import re
import subprocess
import time
from pathlib import Path

from . import config

REPO = Path(__file__).resolve().parents[2]
TASK_PREFIX = "aag-wb-auto-"


def _log(msg: str) -> None:
    from datetime import datetime
    p = REPO / "data/workbench/auto_run.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")


# ── schtasks 调度(仅 Windows; 非 Windows 任务仍保存, 立即运行可用) ──────────
# 中文系统 schtasks 输出 GBK; 服务进程 PYTHONUTF8=1 下 text=True 默认按 utf-8 解
# 会当场 UnicodeDecodeError(stdout 读空)——必须显式 gbk+replace(09-11 同款坑)。
_SCH = {"encoding": "gbk", "errors": "replace"}
def _win() -> bool:
    import shutil
    import os
    return os.name == "nt" and bool(shutil.which("schtasks"))


def _task_name(tid: str) -> str:
    return TASK_PREFIX + re.sub(r"[^A-Za-z0-9_-]", "", tid)


def _sched_args(sched: dict) -> list | None:
    """schedule{kind,time,weekday} → schtasks 频率参数; 非法返回 None。"""
    kind = (sched or {}).get("kind") or "daily"
    hhmm = str((sched or {}).get("time") or "08:00")
    if not re.match(r"^\d{2}:\d{2}$", hhmm):
        return None
    if kind == "daily":
        return ["/sc", "daily", "/st", hhmm]
    if kind == "workday":
        return ["/sc", "weekly", "/d", "MON,TUE,WED,THU,FRI", "/st", hhmm]
    if kind == "weekly":
        wd = {"1": "MON", "2": "TUE", "3": "WED", "4": "THU",
              "5": "FRI", "6": "SAT", "0": "SUN"}.get(str((sched or {}).get("weekday")))
        return ["/sc", "weekly", "/d", wd, "/st", hhmm] if wd else None
    return None


def register_task(task: dict) -> dict:
    """登记(或更新)计划任务; 幂等 /f 覆盖。返回 {ok, msg}。"""
    if not _win():
        return {"ok": False, "msg": "非 Windows 或无 schtasks: 任务已保存, 用「立即运行」或到点跑 CLI"}
    args = _sched_args(task.get("schedule"))
    if not args:
        return {"ok": False, "msg": "调度时间不合法(需 HH:MM)"}
    # pyw 无窗执行(到点不弹控制台); 日志由 autoops._log 落 data/workbench/auto_run.log
    import shutil
    import sys
    pyw = shutil.which("pyw") or shutil.which("pyw.exe")
    if pyw:
        tr = f'"{pyw}" -3.11 "{REPO / "cli.py"}" workbench run-auto --id {task["id"]}'
    else:
        tr = f'"{sys.executable}" "{REPO / "cli.py"}" workbench run-auto --id {task["id"]}'
    cmd = ["schtasks", "/create", "/tn", _task_name(task["id"]),
           "/tr", tr, *args, "/f"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30, **_SCH)
    except Exception as e:
        return {"ok": False, "msg": f"登记失败: {e}"}
    if p.returncode == 0:
        return {"ok": True, "msg": "已登记计划任务"}
    return {"ok": False, "msg": "schtasks 登记失败(可能无权限), 可手动登记: " + " ".join(cmd)}


def unregister_task(tid: str) -> None:
    if _win():
        subprocess.run(["schtasks", "/delete", "/tn", _task_name(tid), "/f"],
                       capture_output=True, timeout=30)


def set_task_enabled(tid: str, on: bool) -> dict:
    if not _win():
        return {"ok": False, "msg": "非 Windows 无计划任务; 启停只影响标记"}
    p = subprocess.run(["schtasks", "/change", "/tn", _task_name(tid),
                        "/ENABLE" if on else "/DISABLE"],
                       capture_output=True, text=True, timeout=30, **_SCH)
    return {"ok": p.returncode == 0, "msg": "" if p.returncode == 0 else "schtasks 启停失败"}


def task_next_run(tid: str) -> str:
    """下次运行时间(查询失败/未登记返回 '')。"""
    if not _win():
        return ""
    try:
        p = subprocess.run(["schtasks", "/query", "/tn", _task_name(tid), "/fo", "LIST"],
                           capture_output=True, text=True, timeout=15, **_SCH)
        for ln in (p.stdout or "").splitlines():
            if "下次运行时间" in ln or "Next Run Time" in ln:
                v = ln.split(":", 1)[1].strip()
                return "" if v.upper().startswith("N/A") else v
    except Exception:
        pass
    return ""


# ── 执行(CLI 进程内) ────────────────────────────────────────────────────────
def _seeds(limit: int = 6) -> list:
    """运行时种子: SoPilot 财经热帖优先(内容垂直, 供应商风控友好, 贴合蹭热点成稿),
    退数据站 X 条目。种子文本剥 URL——智谱内容安全(1301)对 t.co 短链敏感,
    而成稿本来就不带链接。"""
    def _clean(t: str) -> str:
        return re.sub(r"https?://\S+", "", t or "").strip()[:2000]
    items = []
    try:
        from . import x_surge
        rows = x_surge.rss_view(sort="prob", limit=limit)["items"]
        items = [{"id": r["status_id"], "time": r.get("time") or "", "source": r.get("name") or "",
                  "text": _clean(r.get("text")), "url": r.get("url") or "",
                  "body": _clean(r.get("text"))}
                 for r in rows if _clean(r.get("text"))]
    except Exception:
        pass
    if not items:
        try:
            from . import proxy
            d = proxy.fetch_json("items?limit=200&display=1&dedup=1")
            rows = [r for r in (d.get("items") or [])
                    if (r.get("url") or "").startswith("https://x.com/")]
            rows.sort(key=lambda r: r.get("time") or "", reverse=True)
            items = [{"id": str(r.get("id") or r.get("url", "")[-24:]),
                      "time": r.get("time") or "", "source": r.get("source") or r.get("author") or "",
                      "text": _clean(r.get("text_display") or r.get("text")),
                      "url": r.get("url") or "", "body": _clean(r.get("text"))}
                     for r in rows[:limit]]
        except Exception:
            pass
    return items


def _autopub_articles_dir():
    """发布仓 articles/ 三级解析(AAG_AUTOPUB_ROOT > 兄弟仓 > 仓内旧路径), 对齐 cli.py。"""
    import os
    env = os.environ.get("AAG_AUTOPUB_ROOT")
    cands = [Path(env) if env else None,
             REPO.parent / "ai-auto-publisher" / "autopub",
             REPO / "autopub"]
    for c in cands:
        if c and (c / "state.json").exists():
            return c / "articles", 0
    return None, 4


def _safe_fname(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|\r\n]+', "_", (title or "未命名").strip())[:60] or "未命名"


def _record(tid: str, **fields) -> None:
    rows = config.load_automation()
    for r in rows:
        if r.get("id") == tid:
            r.update(fields)
            break
    config.save_automation(rows)


def run_one(tid: str) -> tuple[dict, int]:
    """CLI 入口: 取种子 → 成稿 → 按 target 落位 → 记 last_*。"""
    task = next((t for t in config.load_automation() if t.get("id") == tid), None)
    if not task:
        return {"error": "task_not_found", "hint": "任务不存在(可能已删除)"}, 4
    if not task.get("enabled", True):
        return {"error": "task_disabled", "hint": "任务已停用"}, 3

    from . import gcompose
    seeds = _seeds()
    if not seeds:
        _record(tid, last_run_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                last_status="failed", last_result="无种子素材(数据站与 SoPilot 都没取到)")
        return {"error": "no_seeds", "hint": "数据站与 SoPilot 热帖都无数据, 本轮跳过"}, 3
    modules = [m for m in (task.get("modules") or []) if m in gcompose.MODULES]
    if "retrieve" not in modules:
        modules = ["retrieve", *modules]            # 无检索时种子太薄, 自动补
    defaults = (config.load().get("gen_defaults") or {})
    request = {"items": seeds, "modules": modules,
               "lang": defaults.get("lang") or "zh",
               "tier": defaults.get("tier") or "free",
               "template": task.get("template") or ""}
    result, code = {"error": "not_run"}, 3
    for take in (len(seeds), 3, 1):                # 风控退避: 整包被拒→缩种子重试(400 不计费)
        request["items"] = seeds[:take]
        try:
            result, code = gcompose.run_compose(request)
        except Exception as e:
            _record(tid, last_run_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                    last_status="failed", last_result=f"compose_crash: {e}"[:120])
            return {"error": str(e)[:120]}, 3
        if code == 0:
            break
        hint = str(result.get("hint") or "")
        if "敏感" not in hint and "风险" not in hint and "risk" not in hint.lower():
            break                                  # 非风控失败(配置/解析)重试无意义
    if code != 0:
        _record(tid, last_run_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                last_status="failed", last_result=result.get("error", "")[:120])
        return {"error": result.get("error", ""), "hint": result.get("hint", "")}, code

    post = gcompose.post_get(result.get("id")) or {}
    title = (post.get("title") or "").strip() or time.strftime("auto-%m%d %H:%M")
    content = post.get("content") or ""
    target = ((task.get("publish") or {}).get("target")) or "draft"
    if target == "queue":
        arts, _miss = _autopub_articles_dir()
        if arts is None:
            _record(tid, last_run_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                    last_status="failed", last_result="发布仓未就位(exit 4)")
            return {"error": "autopub_missing",
                    "hint": "发布仓 ai-auto-publisher 未就位(AAG_AUTOPUB_ROOT/兄弟目录)"}, 4
        arts.mkdir(parents=True, exist_ok=True)
        out = arts / f"{_safe_fname(title)}.md"
        out.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
        where = str(out)
    elif target == "direct":
        _record(tid, last_run_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                last_status="done", last_result=f"{result.get('id')}(真发留桩: publish run --draft)")
        _log(f"{task.get('name')} 生成 {result.get('id')} — direct 通道留桩(红线: 真发须 --draft+人工确认)")
        return {"id": result.get("id"), "target": "direct_stub",
                "hint": "已生成; 真发走 python cli.py publish run --draft → 确认后去 --draft"}, 0
    else:                                            # draft
        rows = config.load_drafts()
        rows.append({"id": "d" + time.strftime("%m%d%H%M%S"),
                     "title": title, "content": content,
                     "modules": modules, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        config.save_drafts(rows)
        where = f"草稿箱「{title}」"
    _record(tid, last_run_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            last_status="done", last_result=where[:120])
    _log(f"{task.get('name')} → {where}")
    return {"id": result.get("id"), "target": target, "where": where[:160]}, 0


def enqueue_draft(draft_id: str) -> tuple[dict, int]:
    """CLI 入口: 草稿箱一篇 → 发布仓 articles/ 待发 md。"""
    d = next((r for r in config.load_drafts() if r.get("id") == draft_id), None)
    if not d:
        return {"error": "draft_not_found"}, 404
    arts, _miss = _autopub_articles_dir()
    if arts is None:
        return {"error": "autopub_missing",
                "hint": "发布仓 ai-auto-publisher 未就位(AAG_AUTOPUB_ROOT/兄弟目录)"}, 4
    arts.mkdir(parents=True, exist_ok=True)
    out = arts / f"{_safe_fname(d.get('title'))}.md"
    out.write_text(f"# {d.get('title') or ''}\n\n{d.get('content') or ''}\n", encoding="utf-8")
    _log(f"enqueue 草稿 {draft_id} → {out.name}")
    return {"ok": True, "file": out.name, "dir": str(arts),
            "next": "python cli.py publish run --draft 验证 → 用户确认后去掉 --draft 真发"}, 0
