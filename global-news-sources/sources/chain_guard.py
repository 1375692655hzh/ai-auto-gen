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

采集分两层(不重复计):
- zen_bridge.py 记全部 Zen 调用(logger=bridge, 带 egress_ip/info.tokens/cache);
- 调用侧(translate._chat / feishu 兜底)只记非桥调用(logger=caller, MiniMax 等)。

任何异常绝不上抛 —— 统计永远不许炸翻译。
"""
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.Lock()
_ZEN_PORT_NODE = {"20133": "jp", "20134": "hk", "20135": "hk2"}

# guard 配置缺省(可被 config.local.yaml sources.translate.guard 覆盖)
DEFAULTS = {"enabled": True, "daily_soft_cap": 150,     # 单节点单 UTC 日请求软顶(429 校准后再收紧)
            "win_sec": 900, "win_fail_rate": 0.3, "win_min_calls": 5,
            "consec_fail": 3, "cooldown_sec": 3600, "pool_cd_sec": 3600,
            "recent_cap": 600}


def _utc_day(ts=None) -> str:
    return datetime.fromtimestamp(ts or time.time(), timezone.utc).strftime("%Y-%m-%d")


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
    """错误分类: ok / 429_free / 500_upstream / timeout / ua_freetier / other。"""
    if exc is None and not status and not body:
        return "ok"
    b = str(body or "")
    if "FreeTier" in b or "free tier" in b.lower():
        return "ua_freetier"
    code = getattr(exc, "code", None) or getattr(exc, "status", None) or status or 0
    try:
        code = int(code)
    except Exception:
        code = 0
    name = type(exc).__name__ if exc is not None else ""
    msg = f"{name} {getattr(exc, 'args', '')} {b}"
    if code == 429 or "429" in b[:80]:
        return "429_free"
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
        with _LOCK:
            st = _load_state()
            nodes = st.setdefault("nodes", {})
            nd = nodes.setdefault(f"{node}|{day}", {"n": 0, "ok": 0, "fail": 0,
                                                    "lat_sum": 0, "tok": 0})
            nd["n"] += 1
            nd["ok" if ok else "fail"] += 1
            nd["lat_sum"] += int(latency_ms)
            nd["tok"] += int((tokens or {}).get("total") or 0)
            recent = st.setdefault("recent", [])
            recent.append({"ts": now, "node": node, "ok": bool(ok), "ecls": ecls,
                           "prefix": prefix})
            if len(recent) > guard_conf()["recent_cap"]:
                del recent[:len(recent) - guard_conf()["recent_cap"]]
            _eval_breakers(st, now)
            _save_state(st)
    except Exception:
        pass


def _eval_breakers(st: dict, now: float) -> None:
    cfg = guard_conf()
    win = [r for r in st.get("recent", []) if now - r["ts"] <= cfg["win_sec"]]
    by_node: dict[str, list] = {}
    for r in win:
        by_node.setdefault(r["node"], []).append(r)
    ip_break = st.setdefault("ip_break", {})          # node 级(=IP 级)熔断
    pool_break = st.setdefault("pool_break", {})      # node|prefix 级(429/模型级 500)
    for node, rs in by_node.items():
        fails = [r for r in rs if not r["ok"]]
        rate = len(fails) / len(rs)
        # 逐前缀统计: 时间序尾部连续硬失败 + 是否有成功前缀
        run: dict[str, int] = {}
        ok_prefixes: set[str] = set()
        hard_prefixes: set[str] = set()
        for r in rs:                      # recent 保持时间序
            p = r.get("prefix") or "??"
            if r["ok"]:
                run[p] = 0
                ok_prefixes.add(p)
            elif r["ecls"] in ("500_upstream", "timeout"):
                run[p] = run.get(p, 0) + 1
                if run[p] >= cfg["consec_fail"]:
                    hard_prefixes.add(p)
            else:
                run[p] = 0
        if not ok_prefixes and (
                (len(rs) >= cfg["win_min_calls"] and rate >= cfg["win_fail_rate"])
                or hard_prefixes):
            # 整 IP 信誉死(如 jp): 该节点所有在用前缀全灭 → 冷节点
            ip_break[node] = {"until": now + cfg["cooldown_sec"],
                              "reason": f"15min failrate {rate:.0%} | hard前缀 {sorted(hard_prefixes)}"}
            continue
        # 模型级死亡(同前缀跨 IP 全死, 如 09-24 mimo 三桶齐灭): 只冷单池,
        # 保住同 IP 上还活着的模型(big-pickle 在 hk/hk2 仍活)
        for p in hard_prefixes:
            pool_break[f"{node}|{p}"] = {
                "until": now + cfg["pool_cd_sec"],
                "reason": f"500×{cfg['consec_fail']}+ 但同节点 {sorted(ok_prefixes)} 仍活(模型级死亡)"}
        for r in fails:
            if r["ecls"] == "429_free":   # 429 只冷却该 node|prefix 单池
                pool_break[f"{node}|{r.get('prefix') or '??'}"] = {
                    "until": now + cfg["pool_cd_sec"], "reason": "429_free"}
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


def order_chain(models: list) -> list:
    """预算排序: zen 段按影子账本(剔熔断/超软顶, 剩余请求多/失败率低/延迟低优先),
    非 zen(MiniMax 等)恒链尾保序。models = [dict(base_url, model, ...)]。"""
    cfg = guard_conf()
    if not cfg["enabled"]:
        return list(models)
    zen, other = [], []
    for m in models:
        (zen if is_bridge(m.get("base_url") or "") else other).append(m)
    if not zen:
        return list(models)
    now = time.time()
    with _LOCK:
        st = _load_state()
    scored = []
    for m in zen:
        node = node_of(m.get("base_url") or "")
        nd = _node_today(st, node, now)
        n = int(nd.get("n") or 0)
        br = _broken(st.get("ip_break") or {}, node, now)
        pbr = _broken(st.get("pool_break") or {},
                      f"{node}|{model_prefix(m.get('model'))}", now)
        if br or pbr or n >= cfg["daily_soft_cap"]:
            continue                            # 熔断/超软顶: 本轮摘除
        fails = int(nd.get("fail") or 0)
        rate = fails / n if n else 0.0
        avg_lat = (nd.get("lat_sum") or 0) / n if n else 0.0
        scored.append((n, rate, avg_lat, m))
    scored.sort(key=lambda t: (t[0], t[1], t[2]))
    return [m for *_ , m in scored] + other


def usage_report(days: int = 1) -> str:
    """聚合近 N 天 JSONL: 节点×模型成本表 + 节点日请求(防封主表) + 熔断现状。"""
    out = []
    agg: dict[tuple, dict] = {}
    node_day: dict[tuple, dict] = {}
    today = _utc_day()
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
    out.append(f"== 翻译链用量(近{days}天, UTC日) guard: cap={cfg['daily_soft_cap']}/节点/日 "
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
        for pre in ("bi", "mi"):
            r = _broken(pb, f"{node}|{pre}", now)
            if r:
                any_br = True
                out.append(f"  [池熔断] {node}/{pre}: {r}")
    if not any_br:
        out.append("  无活跃熔断")
    if today == _utc_day():
        nd = _node_today(st, "minimax", now)
        if nd.get("n"):
            out.append(f"-- MiniMax 今日: {nd['n']} 次 / {nd.get('tok', 0)} tok --")
    return "\n".join(out)
