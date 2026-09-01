"""到期源调度刷新(单机数据站写侧, 拍板 2026-09-01)。

- 由 Windows 任务计划每 30min 触发: python cli.py sources refresh
- 只抓"到期"源: TTL 缓存未过期的 fetch_one 直接命中, 不打源站(礼貌下限不绕过)
- 排除: 聚合组 / dead 源 / browser_profile 登录态源(撞 Chrome 红线) /
  conf 显式 refresh:false(配额危源用这条出环, 如 alphavantage 25次/天)
- 域名闸门(同域串行+间隔) + 6 worker 并发; 单源故障记健康不炸整轮
- 写 SQLite 服务库 + 刷新账本 data/serve/refresh.json(禁手编) + 快照导出
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from sources.base import REGISTRY
from sources import health as _health
from sources import store as _store
from sources import limiter as _limiter

WORKERS = 6
BUDGET_MIN = 20                    # 单轮墙钟预算(30min 周期内必须收工)


def _ledger_path() -> Path:
    return _store._serve_dir() / "refresh.json"


def _cfg_refresh_flag(sid: str) -> bool:
    """conf 里 sources.<id>.refresh:false 可单独出环。"""
    try:
        from sources import _cfg_section
        return bool((_cfg_section().get(sid) or {}).get("refresh", True))
    except Exception:
        return True


def _planned() -> list[str]:
    out = []
    for sid, e in REGISTRY.items():
        m = e["meta"]
        if m["kind"] in ("peer_group", "extras_group"):
            continue
        if m.get("auth") == "browser_profile":
            continue                              # 登录态浏览器源不进自动环
        if _health.is_dead(sid):
            continue
        if not _cfg_refresh_flag(sid):
            continue
        out.append(sid)
    return out


def _fetch_one(sid: str) -> tuple[str, list, str]:
    from sources import fetch_one                 # 延迟 import 防环
    try:
        items, err = fetch_one(sid, fresh=False)  # 遵循 TTL: 未到期=缓存命中秒回
        return sid, items or [], err or ""
    except Exception as ex:
        return sid, [], f"{type(ex).__name__}: {str(ex)[:100]}"


def _install_domain_gate() -> None:
    """本进程内给 requests 装域名闸门(刷新进程专用, 不影响库的其他调用方)。"""
    import requests
    orig = requests.sessions.Session.request

    def gated(self, method, url, **kw):
        _limiter.gate(url)
        return orig(self, method, url, **kw)

    requests.sessions.Session.request = gated


def run(dry_run: bool = False, export: bool = True) -> dict:
    """跑一轮到期刷新。dry_run 只出计划。返回本轮报告 dict。"""
    started = time.time()
    plan = _planned()
    if dry_run:
        return {"planned": len(plan), "sources": plan, "dry_run": True}
    _install_domain_gate()

    rep = {"planned": len(plan), "ok": 0, "empty": 0, "failed": 0, "skipped": 0,
           "stored": 0, "failures": [], "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    ledger = {"round_started_at": rep["started_at"], "sources": {}}
    deadline = started + BUDGET_MIN * 60

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(_fetch_one, sid): sid for sid in plan}
        for fut in as_completed(futs):
            if time.time() > deadline:
                rep["skipped"] += 1
                continue
            sid, items, err = fut.result()
            t0 = time.time()
            if err:
                rep["failed"] += 1
                rep["failures"].append(f"{sid}({err})")
                ledger["sources"][sid] = {"status": "failed", "error": err[:120]}
                continue
            if not items:
                rep["empty"] += 1
                ledger["sources"][sid] = {"status": "empty"}
                continue
            rep["ok"] += 1
            n = _store.put(sid, REGISTRY[sid]["meta"], items)
            rep["stored"] += n
            ledger["sources"][sid] = {"status": "ok", "items": len(items),
                                      "new": n, "ms": int((time.time() - t0) * 1000)}

    rep["elapsed_s"] = int(time.time() - started)
    ledger["round_elapsed_s"] = rep["elapsed_s"]
    ledger["round_finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ledger["totals"] = {k: rep[k] for k in ("planned", "ok", "empty", "failed", "skipped", "stored")}
    try:
        p = _ledger_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass
    if export:
        try:
            _store.prune()                       # 每轮收尾顺带按保留窗清理
            rep["snapshot"] = _store.export_snapshot()
        except Exception as ex:
            rep["failures"].append(f"snapshot({type(ex).__name__})")
    return rep
