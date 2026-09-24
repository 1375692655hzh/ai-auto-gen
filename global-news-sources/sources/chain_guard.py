"""翻译链额度守卫(2026-09-24 用户裁决, 设计=grok 机制分析+本仓实测合成)。

Zen 免费档机制(实测+社区逆向, 细节按假设对待用本账本校准):
- 三 zen 桶 = 同一 opencode 账号 × 三个住宅出口 IP; 配额/封禁键 = IP 级, 非账号级。
- 额度按「请求次数」计(不按 token): 池键 ≈ UTC日 + IP + 模型前缀(前2字符),
  big-pickle(bi) 与 mimo-v2.5-free(mi) 各算各的日桶; 无独立 rateLimit 的默认免费
  模型共用一个 default 日桶。重置按 UTC 日(国内早 8 点翻篇)。
- 两类死法要分开: 429 = 单池日限打满(只冷却该池, 同 IP 别的模型还能用);
  500/超时 = 上游拒——若该节点上其他模型仍成功 = 模型级死亡(只冷该前缀池,
  如 2026-09-24 mimo 三桶齐灭但 big-pickle 仍活); 若全部在用前缀齐灭 = 整 IP
  信誉死(两个免费模型一起停)。jp 2026-09-24 之死是后者, mimo 是前者。
- MiniMax = 另一体系(付费按 token), 无 IP 配额, 恒链尾兜底。
- Zen 不回真实 Remaining —— 本模块是影子账本, 数字用 429 出现点校准, 不是官方真值。
- 软顶/计数按池(node|prefix|UTC日)——真配额键就是这粒度; 日软顶 150 是保守初值,
  429 出现点反推各池真容量后再分别收紧(软顶设低了会永远撞不到 429, 标定失去数据源)。

采集分两层(不重复计):
- zen_bridge.py 记全部 Zen 调用(logger=bridge, 带 egress_ip/info.tokens/cache);
- 调用侧(translate._chat / feishu 兜底)只记非桥调用(logger=caller, MiniMax 等)。

任何异常绝不上抛 —— 统计永远不许炸翻译。
"""
import contextlib
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

_LOCK = threading.Lock()                # 进程内线程锁(还有一道文件锁兜底)
_ZEN_PORT_NODE = {"20133": "jp", "20134": "hk", "20135": "hk2"}
_ZEN_NODES = tuple(_ZEN_PORT_NODE.values())

# guard 配置缺省(可被 config.local.yaml sources.translate.guard 覆盖)
DEFAULTS = {"enabled": True, "daily_soft_cap": 150,     # 单池(node|prefix)单 UTC 日请求软顶
            "win_sec": 900, "win_fail_rate": 0.3, "win_min_calls": 5,
            "consec_fail": 3, "cooldown_sec": 3600, "pool_cd_sec": 3600,
            "recent_cap": 600}


def _utc_day(ts=None) -> str:
    return datetime.fromtimestamp(ts or time.time(), timezone.utc).strftime("%Y-%m-%d")


def _utc_flip_ts(now: float) -> float:
    """下一个 UTC 日翻篇点(国内早 8 点)epoch。429/日配额类冷却应冷到翻篇而非滑窗续期。"""
    dt = datetime.fromtimestamp(now, timezone.utc)
    nxt = dt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return nxt.timestamp() + 60          # 60s 余量, 避免边界上抢跑


@contextlib.contextmanager
def _state_file_lock(wait: float = 2.0):
    """state.json 跨进程互斥(三桥常驻进程+refresh/feishu 轮进程共享账本)。
    拿不到锁就让本轮聚合跳过(绝不等死翻译); JSONL 明细 append 不受影响。"""
    fh = None
    try:
        fh = open(usage_dir() / "state.lock", "a+b")
    except Exception:
        yield False
        return
    got = False
    try:
        import msvcrt
        deadline = time.time() + wait
        while time.time() < deadline:
            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                got = True
                break
            except OSError:
                time.sleep(0.05)
    except ImportError:
        try:
            import fcntl
            deadline = time.time() + wait
            while time.time() < deadline:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    got = True
                    break
                except OSError:
                    time.sleep(0.05)
        except Exception:
            got = True                     # 极端平台无锁原语: 退化为旧行为
    try:
        yield got
    finally:
        if got:
            try:
                if hasattr(fh, "seek"):
                    fh.seek(0)
                try:
                    import msvcrt
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                except ImportError:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
        try:
            fh.close()
        except Exception:
            pass


def usage_dir() -> Path:
    from sources import data_dir
    p = Path(data_dir()) / "zen-usage"
    p.mkdir(parents=True, exist_ok=True)
    return p


def guard_conf() -> dict:
    """读 sources.translate.guard 覆盖段; 读不到用 DEFAULTS。"""
    cfg = dict(DEFAULTS)
    try:
        from sources import _cfg_section
        g = (_cfg_section().get("translate") or {}).get("guard") or {}
        for k in cfg:
            if k in g:
                cfg[k] = g[k]
    except Exception:
        pass
    cfg["enabled"] = bool(cfg.get("enabled", True))
    for k in ("daily_soft_cap", "win_sec", "consec_fail", "cooldown_sec",
              "pool_cd_sec", "recent_cap", "win_min_calls"):
        try:
            cfg[k] = int(cfg[k])
        except Exception:
            cfg[k] = DEFAULTS[k]
    try:
        cfg["win_fail_rate"] = float(cfg["win_fail_rate"])
    except Exception:
        cfg["win_fail_rate"] = DEFAULTS["win_fail_rate"]
    return cfg


def is_bridge(base_url: str) -> bool:
    b = str(base_url or "")
    return "127.0.0.1:2013" in b        # 20133/20134/20135 zen 桥


def node_of(base_url: str) -> str:
    if is_bridge(base_url):
        for port, node in _ZEN_PORT_NODE.items():
            if f"127.0.0.1:{port}" in str(base_url):
                return node
        return "zen"
    if "minimax" in str(base_url):
        return "minimax"
    return "direct"


def model_prefix(model: str) -> str:
    m = str(model or "").strip()
    m = m[3:] if m.startswith("oc/") else m
    return (m[:2] or "??").lower()


def classify(status=None, exc=None, body: str = "") -> str:
    """错误分类: ok / 429_free / ua_freetier / 500_upstream / timeout / other。
    状态码优先(含 requests 异常的 response.status_code), free-tier 文案降一级:
    包着 429 的拒绝必须归 429 才会被冷却, 只看文案会让池永远硬戳。"""
    if exc is None and not status and not body:
        return "ok"
    b = str(body or "")
    code = getattr(exc, "code", None) or getattr(exc, "status", None) or status or 0
    if not code and exc is not None:
        code = getattr(getattr(exc, "response", None), "status_code", None) or 0
    try:
        code = int(code)
    except Exception:
        code = 0
    name = type(exc).__name__ if exc is not None else ""
    msg = f"{name} {getattr(exc, 'args', '')} {b}"
    if code == 429 or "429" in b[:80]:
        return "429_free"
    if "FreeTier" in b or "free tier" in b.lower():
        return "ua_freetier"
    if "Timeout" in name or "timed out" in msg:
        return "timeout"
    if code >= 500 or "upstream_http_5" in b or "UnknownError" in b:
        return "500_upstream"
    return "other"


def _state_path() -> Path:
    return usage_dir() / "state.json"


def _load_state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(st: dict) -> None:
    p = _state_path()
    tmp = p.with_suffix(f".tmp{time.time_ns()}")
    tmp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def record(logger: str, node: str, model: str, ok: bool, ecls: str = "ok",
           latency_ms: int = 0, egress_ip: str = "", tokens: dict | None = None,
           failover_from: str = "", base_url: str = "") -> None:
    """记一次调用: JSONL 明细 + 影子账本轮询聚合 + 熔断评估。绝不抛。"""
    try:
        now = time.time()
        day = _utc_day(now)
        prefix = model_prefix(model)
        pool_key = f"{day}|{egress_ip or node}|{prefix}"
        rec = {"ts": int(now), "utc_date": day, "logger": logger, "node": node,
               "egress_ip": egress_ip, "model": model, "prefix": prefix,
               "pool_key": pool_key, "ok": bool(ok), "ecls": ecls,
               "lat": int(latency_ms), "failover_from": failover_from}
        for k in ("prompt", "completion", "total", "cache_read"):
            v = (tokens or {}).get(k) or 0
            if v:
                rec[k] = int(v)
        line = json.dumps(rec, ensure_ascii=False)
        with open(usage_dir() / f"{day}.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")
        with _LOCK, _state_file_lock() as got:     # 线程锁+跨进程文件锁双保险
            if not got:
                return                             # 抢不到: 明细已落, 聚合下轮补
            st = _load_state()
            nodes = st.setdefault("nodes", {})
            nd = nodes.setdefault(f"{node}|{day}", {"n": 0, "ok": 0, "fail": 0,
                                                    "lat_sum": 0, "tok": 0})
            nd["n"] += 1
            nd["ok" if ok else "fail"] += 1
            nd["lat_sum"] += int(latency_ms)
            nd["tok"] += int((tokens or {}).get("total") or 0)
            pools = st.setdefault("pools", {})     # 池级日计数(真配额键=日|IP|前缀)
            pd = pools.setdefault(f"{node}|{prefix}|{day}", {"n": 0, "ok": 0,
                                                             "fail": 0, "lat_sum": 0})
            pd["n"] += 1
            pd["ok" if ok else "fail"] += 1
            pd["lat_sum"] += int(latency_ms)
            recent = st.setdefault("recent", [])
            recent.append({"ts": now, "node": node, "ok": bool(ok), "ecls": ecls,
                           "prefix": prefix})
            cfg = guard_conf()
            if len(recent) > cfg["recent_cap"]:
                del recent[:len(recent) - cfg["recent_cap"]]
            _gc_state(st, day)
            _eval_breakers(st, now)
            _save_state(st)
    except Exception:
        pass


def _gc_state(st: dict, today: str) -> None:
    """清理 7 天前的 nodes/pools 计数键(防 state.json 无限增长)。"""
    cutoff = _utc_day(time.time() - 7 * 86400)
    for k in list((st.get("nodes") or {}).keys()):
        if k.rsplit("|", 1)[-1] < cutoff:
            del st["nodes"][k]
    for k in list((st.get("pools") or {}).keys()):
        if k.rsplit("|", 1)[-1] < cutoff:
            del st["pools"][k]


_QUOTA_ECLS = ("429_free", "ua_freetier")     # 配额类: 只冷池, 不计入 IP 熔断 failrate
_HARD_ECLS = ("500_upstream", "timeout")


def _eval_breakers(st: dict, now: float) -> None:
    """熔断评估(须在 state 文件锁内调用)。

    死亡分级:
    - 配额类(429/ua_freetier) → node|prefix 池冷却到 UTC 翻篇(日桶已空, 冷 1h 只是空转探测;
      旧滑动窗续期会把 14 分钟前的 429 被后续每条成功记录无限续命)。
    - 硬失败(500/timeout) 同前缀在 ≥2 节点窗口内齐灭 → 模型级死亡: 全部 zen 节点
      同步冷该前缀池(省得每个节点各烧 3 次探测才反应; 09-24 mimo 三桶齐灭实证)。
    - 硬失败仅单节点、该节点窗口内又无任何成功前缀 → 整 IP 信誉死, 冷节点
      (保守: 单节点视角分不清"该节点独死"还是"模型全灭但别的节点没人用"——
       mi 池没测过不代表活着, IP 死了连坐是对的)。
    - 软错误(other)不打断 500 连击计数(只有 ok 清零); 有成功前缀时不熔断,
      降级交给 order_chain 的 failrate 降权。
    """
    cfg = guard_conf()
    win = [r for r in st.get("recent", []) if now - r["ts"] <= cfg["win_sec"]]
    by_node: dict[str, list] = {}
    for r in win:
        by_node.setdefault(r["node"], []).append(r)
    ip_break = st.setdefault("ip_break", {})          # node 级(=IP 级)熔断
    pool_break = st.setdefault("pool_break", {})      # node|prefix 级
    flip = _utc_flip_ts(now)
    # 第一遍: 逐节点逐前缀算时间序尾部连续硬失败 + 成功前缀集
    hard_run: dict[tuple[str, str], int] = {}
    ok_by_node: dict[str, set] = {}
    for node, rs in by_node.items():
        run: dict[str, int] = {}
        ok: set[str] = set()
        for r in rs:                      # recent 保持时间序
            p = r.get("prefix") or "??"
            if r["ok"]:
                run[p] = 0
                ok.add(p)
            elif r["ecls"] in _HARD_ECLS:
                run[p] = run.get(p, 0) + 1     # 仅 ok 清零; other/429 不打断连击
            hard_run[(node, p)] = run.get(p, 0)
        ok_by_node[node] = ok
    # 模型级死亡: 同前缀在 ≥2 节点有硬失败
    hard_nodes_by_p: dict[str, set] = {}
    for (node, p), n in hard_run.items():
        if n:
            hard_nodes_by_p.setdefault(p, set()).add(node)
    model_dead = {p for p, ns in hard_nodes_by_p.items() if len(ns) >= 2}
    for p in model_dead:
        for node in _ZEN_NODES:
            pool_break[f"{node}|{p}"] = {
                "until": now + cfg["pool_cd_sec"],
                "reason": f"模型级死亡: {p} 在 {len(hard_nodes_by_p[p])} 节点齐灭"}
    # 第二遍: 逐节点定级
    for node, rs in by_node.items():
        fails = [r for r in rs if not r["ok"]]
        ok = ok_by_node.get(node) or set()
        consec = {p for (n_, p), c in hard_run.items()
                  if n_ == node and c >= cfg["consec_fail"]}
        unexplained = consec - model_dead
        if not ok and (
                (len(rs) >= cfg["win_min_calls"]
                 and len([r for r in fails if r["ecls"] not in _QUOTA_ECLS]) / len(rs)
                 >= cfg["win_fail_rate"])
                or unexplained):
            # 整 IP 信誉死(如 jp): 该节点所有在用前缀全灭 → 冷节点
            # (failrate 剔除配额类: 全 429 是池满不是 IP 死, 只该冷池)
            ip_break[node] = {"until": now + cfg["cooldown_sec"],
                              "reason": f"零成功 | 未解释硬前缀 {sorted(unexplained)}"
                              f" | 非配额failrate "
                              f"{len([r for r in fails if r['ecls'] not in _QUOTA_ECLS]) / len(rs):.0%}"}
            continue
        for p in consec - model_dead:
            # 连击未达模型级: 单池冷。同节点有活前缀=疑似模型级死亡;
            # 零成功=该前缀可能在这 IP 独死, 待跨节点证据升级
            pool_break[f"{node}|{p}"] = {
                "until": now + cfg["pool_cd_sec"],
                "reason": (f"500×{cfg['consec_fail']}+ 同节点 {sorted(ok)} 仍活(疑似模型级)"
                           if ok else
                           f"500×{cfg['consec_fail']}+ 零成功, 待跨节点证据")}
        for r in fails:
            if r["ecls"] in _QUOTA_ECLS:   # 配额类只冷到翻篇
                pool_break[f"{node}|{r.get('prefix') or '??'}"] = {
                    "until": flip, "reason": f"{r['ecls']}→UTC翻篇"}
    st["recent"] = win[-cfg["recent_cap"]:]


def _node_today(st: dict, node: str, now=None) -> dict:
    return (st.get("nodes") or {}).get(f"{node}|{_utc_day(now)}") or {}


def _broken(kind: dict, key: str, now=None) -> str:
    info = (kind or {}).get(key) or {}
    left = float(info.get("until") or 0) - (now or time.time())
    if left <= 0:
        return ""
    m = int(left // 60)
    return f"{info.get('reason', '')}({m}min 后解)"


def _pool_today(st: dict, node: str, prefix: str, now=None) -> dict:
    return (st.get("pools") or {}).get(f"{node}|{prefix}|{_utc_day(now)}") or {}


def _mid(m: dict) -> str:
    return f"{m.get('base_url') or ''}|{m.get('model') or ''}"


def order_chain(models: list) -> list:
    """预算排序: zen 段按影子账本(剔熔断/超池软顶, 用量少/失败率低/延迟低优先),
    非 zen(MiniMax 等)恒链尾保序。models = [dict(base_url, model, ...)]。

    滞回: 可用集合与上轮相同则沿用上轮链序——消除每 15min 重排导致的
    "逐轮换一个节点倾泻到软顶"抖动(新 IP 被单轮打满比均匀分摊危险)。"""
    cfg = guard_conf()
    if not cfg["enabled"]:
        return list(models)
    zen, other = [], []
    for m in models:
        (zen if is_bridge(m.get("base_url") or "") else other).append(m)
    if not zen:
        return list(models)
    now = time.time()
    with _LOCK, _state_file_lock() as got:
        st = _load_state() if got else {}
    scored = []
    for m in zen:
        node = node_of(m.get("base_url") or "")
        pre = model_prefix(m.get("model"))
        pd = _pool_today(st, node, pre, now)
        n = int(pd.get("n") or 0)
        br = _broken(st.get("ip_break") or {}, node, now)
        pbr = _broken(st.get("pool_break") or {}, f"{node}|{pre}", now)
        if br or pbr or n >= cfg["daily_soft_cap"]:
            continue                            # 熔断/超池软顶: 本轮摘除
        fails = int(pd.get("fail") or 0)
        rate = fails / n if n else 0.0
        avg_lat = (pd.get("lat_sum") or 0) / n if n else 0.0
        scored.append((n, rate, avg_lat, m))
    scored.sort(key=lambda t: (t[0], t[1], t[2]))
    fresh = [m for *_, m in scored]
    fresh_ids = [_mid(m) for m in fresh]
    # 滞回: 集合不变沿用上次序
    with _LOCK, _state_file_lock() as got:
        if not got:
            return fresh + other
        st = _load_state()
        prev = st.get("chain_order") or []
        if set(prev) == set(fresh_ids) and len(prev) == len(fresh_ids):
            by_id = {_mid(m): m for m in fresh}
            ordered = [by_id[i] for i in prev if i in by_id]
            st["chain_order"] = [_mid(m) for m in ordered]
            _save_state(st)
            return ordered + other
        st["chain_order"] = fresh_ids
        _save_state(st)
    return fresh + other


def usage_report(days: int = 1) -> str:
    """聚合近 N 天 JSONL: 节点×模型成本表 + 节点日请求(防封主表) + 熔断现状。"""
    out = []
    agg: dict[tuple, dict] = {}
    node_day: dict[tuple, dict] = {}
    for i in range(days):
        day = _utc_day(time.time() - i * 86400)
        p = usage_dir() / f"{day}.jsonl"
        if not p.exists():
            continue
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                k = (r.get("utc_date") or day, r.get("node") or "?",
                     r.get("model") or "?")
                a = agg.setdefault(k, {"n": 0, "ok": 0, "fail": 0, "lat": 0,
                                       "prompt": 0, "completion": 0, "cache": 0,
                                       "ecls": {}})
                a["n"] += 1
                a["ok" if r.get("ok") else "fail"] += 1
                a["lat"] += r.get("lat") or 0
                a["prompt"] += r.get("prompt") or 0
                a["completion"] += r.get("completion") or 0
                a["cache"] += r.get("cache_read") or 0
                e = r.get("ecls") or "ok"
                a["ecls"][e] = a["ecls"].get(e, 0) + 1
                nk = (k[0], k[1])
                nd_ = node_day.setdefault(nk, {"n": 0, "fail": 0})
                nd_["n"] += 1
                nd_["fail"] += 0 if r.get("ok") else 1
        except Exception:
            continue
    cfg = guard_conf()
    out.append(f"== 翻译链用量(近{days}天, UTC日) guard: 池软顶={cfg['daily_soft_cap']}/池(节点|前缀)/日 "
               f"熔断窗={cfg['win_sec']}s@{cfg['win_fail_rate']:.0%} ==")
    out.append("-- 节点×模型(成本/质量表) --")
    out.append(f"{'日期':<11}{'节点':<9}{'模型':<18}{'请求':>4}{'失败':>4}"
               f"{'prompt_tok':>11}{'compl_tok':>10}{'cache读':>10}{'均延迟ms':>9}  错误分布")
    for (day, node, model) in sorted(agg, reverse=True):
        a = agg[(day, node, model)]
        lat = a["lat"] / a["n"] if a["n"] else 0
        errs = ",".join(f"{k}×{v}" for k, v in sorted(a["ecls"].items())
                        if k != "ok" and v) or "-"
        out.append(f"{day:<11}{node:<9}{model:<18}{a['n']:>4}{a['fail']:>4}"
                   f"{a['prompt']:>11}{a['completion']:>10}{a['cache']:>10}"
                   f"{lat:>9.0f}  {errs}")
    out.append("-- 节点日请求(防封主表: Zen 免费档按请求数限) --")
    out.append(f"{'日期':<11}{'节点':<9}{'日请求':>6}{'失败':>5}{'/软顶':>7}")
    for (day, node) in sorted(node_day, reverse=True):
        d = node_day[(day, node)]
        cap = cfg["daily_soft_cap"] if node in ("jp", "hk", "hk2") else "-"
        mark = " ⚠超顶" if isinstance(cap, int) and d["n"] >= cap else ""
        out.append(f"{day:<11}{node:<9}{d['n']:>6}{d['fail']:>5}{str(cap):>7}{mark}")
    st = _load_state()
    now = time.time()
    out.append("-- 熔断现状 --")
    ib = st.get("ip_break") or {}
    pb = st.get("pool_break") or {}
    any_br = False
    for node in ("jp", "hk", "hk2", "minimax"):
        r = _broken(ib, node, now)
        if r:
            any_br = True
            out.append(f"  [IP熔断] {node}: {r}")
    for key in sorted(pb):                  # 动态: 池键=node|prefix, 不硬编码
        r = _broken(pb, key, now)
        if r:
            any_br = True
            out.append(f"  [池熔断] {key.replace('|', '/')}: {r}")
    if not any_br:
        out.append("  无活跃熔断")
    nd = _node_today(st, "minimax", now)
    if nd.get("n"):
        out.append(f"-- MiniMax 今日: {nd['n']} 次 / {nd.get('tok', 0)} tok --")
    return "\n".join(out)
