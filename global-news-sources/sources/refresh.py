"""到期源调度刷新(单机数据站写侧, 拍板 2026-09-01; 稳定性加固 2026-09-07)。

- 由 Windows 任务计划每 15min 触发: python cli.py sources refresh
- 只抓"到期"源: TTL 缓存未过期的 fetch_one 直接命中, 不打源站(礼貌下限不绕过)
- 排除: 聚合组 / dead 源(半开探针除外) / browser_profile 登录态源(撞 Chrome 红线) /
  conf 显式 refresh:false(配额危源用这条出环, 如 alphavantage 25次/天)
- 单实例锁(msvcrt 字节锁, 进程死亡内核自动释放): 计划任务/控制台/手跑三入口互斥
- 域名闸门(同域串行+间隔) + 6 worker 并发; 单源故障记健康不炸整轮
- 抓取段墙钟预算 BUDGET_MIN=12(15min 周期内必须收工), 到点取消未启动 future;
  在途请求由闸门统一钳制超时(connect≤8s/read≤30s)保证有界
- 轮末 LLM 收尾(llm_tag/translate)另有 TAIL_BUDGET_S 预算, 超支即跳过(规则结果兜底)
- 写 SQLite 服务库 + 刷新账本 data/serve/refresh.json(禁手编) + 快照导出
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FutTimeout
from datetime import datetime, timedelta
from pathlib import Path

from sources.base import REGISTRY
from sources import health as _health
from sources import store as _store
from sources import limiter as _limiter

WORKERS = 6
BUDGET_MIN = 12                    # 抓取段墙钟预算(15min 触发周期内必须收工)
TAIL_BUDGET_S = 180                # 轮末 LLM 收尾段总预算
DEAD_PROBE_AFTER_H = 6             # dead 源死满 N 小时后允许半开探针
DEAD_PROBE_MAX = 3                 # 每轮最多带几个 dead 源试针

try:
    import msvcrt                  # Windows 字节锁(进程死亡内核自动释放)
except ImportError:                 # 非 Windows 环境降级为无锁(本仓运行环境是 Windows)
    msvcrt = None

_LOCK_FH = None                     # 模块级持有句柄, 防 GC 提前释放锁


def _ledger_path() -> Path:
    return _store._serve_dir() / "refresh.json"


def _acquire_lock() -> bool:
    """单实例锁: 拿不到说明已有 refresh 在跑(计划任务/控制台/手跑任一)。

    锁文件 data/serve/refresh.lock 第 1 字节; 进程崩溃/被杀时内核自动释放,
    无陈旧锁问题。锁内写 PID/时间戳仅供人工诊断, 不作为解锁依据。
    """
    global _LOCK_FH
    if msvcrt is None:
        return True
    p = _store._serve_dir() / "refresh.lock"
    p.parent.mkdir(parents=True, exist_ok=True)
    fh = open(p, "a+b")
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        fh.close()
        return False
    fh.seek(0)
    fh.truncate()
    fh.write(f"pid={os.getpid()} started={datetime.now():%F %T}".encode())
    fh.flush()
    _LOCK_FH = fh
    return True


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
    # dead 源半开探针: 死满 DEAD_PROBE_AFTER_H 小时的源每轮最多带 DEAD_PROBE_MAX 个
    # 试一针, 成功即由 health.record(True) 自动复活——堵住"单向死亡"致计划源数缩水
    cutoff = (datetime.now() - timedelta(hours=DEAD_PROBE_AFTER_H)).strftime("%Y-%m-%d %H:%M")
    probes = []
    for sid, e in REGISTRY.items():
        if sid in out:
            continue
        m = e["meta"]
        if m["kind"] in ("peer_group", "extras_group") or m.get("auth") == "browser_profile":
            continue
        if not _cfg_refresh_flag(sid):
            continue
        rec = _health.get(sid)
        if rec.get("status") != "dead":
            continue
        if rec.get("last_fail", "") >= cutoff:    # last_fail 缺失(旧数据)视为早该探
            continue
        probes.append(sid)
        if len(probes) >= DEAD_PROBE_MAX:
            break
    return out + probes


def _fetch_one(sid: str) -> tuple[str, list, str]:
    from sources import fetch_one                 # 延迟 import 防环
    try:
        items, err = fetch_one(sid, fresh=False)  # 遵循 TTL: 未到期=缓存命中秒回
        return sid, items or [], err or ""
    except Exception as ex:
        return sid, [], f"{type(ex).__name__}: {str(ex)[:100]}"


def _clamp_timeout(t):
    """统一钳制请求超时: connect≤8s / read≤30s, 缺省 (5,20)。

    单值超时(全库现状) connect/read 共享且 read 只对字节间隔生效, 慢速滴水的
    服务器能把一个请求拖到天荒地老——钳死后在途 future 墙钟有界。
    """
    try:
        if t is None:
            return (5, 20)
        if isinstance(t, (int, float)):
            return (5, min(float(t), 30.0))
        if isinstance(t, tuple):
            c, r = t
            return (min(float(c), 8.0) if c else 5,
                    min(float(r), 30.0) if r else 20)
    except Exception:
        pass
    return (5, 20)


def _install_domain_gate() -> None:
    """本进程内给 requests 装域名闸门+超时钳制+代理直连兜底(刷新进程专用)。"""
    import requests
    orig = requests.sessions.Session.request

    def gated(self, method, url, **kw):
        _limiter.gate(url)
        kw["timeout"] = _clamp_timeout(kw.get("timeout"))
        try:
            return orig(self, method, url, **kw)
        except (requests.exceptions.ProxyError, requests.exceptions.SSLError):
            # 系统代理(Clash 等)间歇故障会经 trust_env 污染全部请求:
            # 显式绕过环境代理直连重试一次; 直连也不通则异常照常冒泡记健康
            kw["proxies"] = {"http": None, "https": None}
            return orig(self, method, url, **kw)

    requests.sessions.Session.request = gated


def run(dry_run: bool = False, export: bool = True) -> dict:
    """跑一轮到期刷新。dry_run 只出计划(不加锁, 供监控随时调用)。返回本轮报告 dict。"""
    started = time.time()
    plan = _planned()
    if dry_run:
        return {"planned": len(plan), "sources": plan, "dry_run": True}
    if not _acquire_lock():
        print(f"[{datetime.now():%H:%M:%S}] refresh 已有实例在跑, 本轮跳过", flush=True)
        return {"planned": 0, "ok": 0, "empty": 0, "failed": 0, "skipped": 0,
                "stored": 0, "failures": ["另一实例在跑, 本轮放弃(单实例锁)"],
                "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "elapsed_s": 0, "locked_out": True}
    _install_domain_gate()

    rep = {"planned": len(plan), "ok": 0, "empty": 0, "failed": 0, "skipped": 0,
           "stored": 0, "failures": [], "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    ledger = {"round_started_at": rep["started_at"], "sources": {}}

    print(f"[{datetime.now():%H:%M:%S}] refresh 轮开始: 计划 {len(plan)} 源", flush=True)
    pool = ThreadPoolExecutor(max_workers=WORKERS)
    futs = {pool.submit(_fetch_one, sid): sid for sid in plan}
    try:
        for fut in as_completed(futs, timeout=BUDGET_MIN * 60):
            sid, items, err = fut.result()
            t0 = time.time()
            if err:
                rep["failed"] += 1
                rep["failures"].append(f"{sid}({err})")
                ledger["sources"][sid] = {"status": "failed", "error": err[:120]}
            elif not items:
                rep["empty"] += 1
                ledger["sources"][sid] = {"status": "empty"}
            else:
                rep["ok"] += 1
                try:
                    n = _store.put(sid, REGISTRY[sid]["meta"], items)
                except Exception as ex:
                    n = 0
                    rep["failures"].append(f"store.put:{sid}({type(ex).__name__}: {str(ex)[:60]})")
                rep["stored"] += n
                ledger["sources"][sid] = {"status": "ok", "items": len(items),
                                          "new": n, "ms": int((time.time() - t0) * 1000)}
            done = rep["ok"] + rep["empty"] + rep["failed"]
            print(f"[{datetime.now():%H:%M:%S}] [{done}/{rep['planned']}] {sid} "
                  + (f"FAIL {err[:60]}" if err else ("空" if not items else f"+{len(items)}"))
                  + f" ({int((time.time() - t0) * 1000)}ms)", flush=True)
    except (FutTimeout, TimeoutError):
        pending = [f for f in futs if not f.done()]
        for f in pending:
            f.cancel()
        rep["skipped"] = sum(1 for f in pending if f.cancelled())
        overtime = sorted(futs[f] for f in pending if f.running())
        rep["overtime"] = overtime
        rep["failures"].append(
            f"超预算{BUDGET_MIN}min: 取消未启动 {rep['skipped']} 源"
            + (f", 在途待自然超时 {len(overtime)} 源({', '.join(overtime[:5])})" if overtime else "")
            + "; 下轮 TTL 到期补抓")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)   # 不 join: 在途请求由超时钳制收尾

    rep["fetch_elapsed_s"] = int(time.time() - started)
    # 轮末收尾: 模糊归并(不丢弃只挂簇) → M4 LLM 精标(规则兜底) → 翻译; 各受尾预算约束
    tail_deadline = time.time() + TAIL_BUDGET_S
    try:
        from sources import store as _st
        rep["dedup"] = _st.link_dups()
    except Exception as ex:
        rep["failures"].append(f"link_dups({type(ex).__name__}: {str(ex)[:60]})")
    if time.time() < tail_deadline:
        try:
            from sources import llm_tag
            rep["llm_tag"] = llm_tag.run(rep["started_at"])
        except Exception as ex:
            rep["failures"].append(f"llm_tag({type(ex).__name__}: {str(ex)[:60]})")
    else:
        rep["failures"].append("轮末预算耗尽, llm_tag 跳过(规则打标已兜底, 下轮补)")
    if time.time() < tail_deadline:
        try:
            from sources import translate
            rep["translate"] = translate.run(rep["started_at"])
        except Exception as ex:
            rep["failures"].append(f"translate({type(ex).__name__}: {str(ex)[:60]})")
    else:
        rep["failures"].append("轮末预算耗尽, translate 跳过(下轮补)")
    rep["elapsed_s"] = int(time.time() - started)        # 全程耗时(含 LLM 收尾段)
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
    print(f"[{datetime.now():%H:%M:%S}] refresh 轮结束: 成功 {rep['ok']}/空 {rep['empty']}/"
          f"失败 {rep['failed']}/跳过 {rep['skipped']} | 入库 {rep['stored']} 条 | "
          f"抓取 {rep['fetch_elapsed_s']}s / 全程 {rep['elapsed_s']}s", flush=True)
    return rep
