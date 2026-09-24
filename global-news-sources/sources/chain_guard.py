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
  注意 MiniMax 模型名剥前缀后可能与 zen 前缀撞名(如 MiniMax-M3→mi), 死亡判定
  必须按 _ZEN_NODES 隔离, 否则 MiniMax 失败会连坐冷却 zen 池(二轮评审实证)。
- 部署假设: 每桥节点=静态住宅出口 IP(池键=日|IP|前缀 成立的前提);
  代理若 per-request 轮换出口, 池容量标定不可信。慢速渗漏(15min窗凑不够5次)
  的慢性死亡不触发熔断, 靠 order_chain failrate 降权兜底, 属已知限制。
- Zen 不回真实 Remaining —— 本模块是影子账本, 数字用 429 出现点校准, 不是官方真值。
- 软顶/计数按池(node|prefix|UTC日)——真配额键就是这粒度; 日软顶 150 是保守初值,
  429 出现点反推各池真容量后再分别收紧(软顶设低了会永远撞不到 429, 标定失去数据源)。

采集分两层(不重复计):
- zen_bridge.py 记全部 Zen 调用(logger=bridge, 带 egress_ip/info.tokens/cache);
- 调用侧(translate._chat / feishu 兜底)只记非桥调用(logger=caller, MiniMax 等)。

任何异常绝不上抛 —— 统计永远不许炸翻译。
"""
import contextlib
import itertools
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

_log = logging.getLogger(__name__)   # 锁/账本事故必须有声, 沉默=停摆数小时无人知

_LOCK = threading.Lock()                # 进程内线程锁(还有一道文件锁兜底)
_ZEN_PORT_NODE = {"20133": "jp", "20134": "hk", "20135": "hk2"}
_ZEN_NODES = tuple(_ZEN_PORT_NODE.values())
_SEQ = itertools.count(1)               # 事件序号: eid 同毫秒去重排序用
_SEEN_CAP = 4000                        # seen_eids 上限(防 state 膨胀, 去重窗口)


def _new_eid(now: float) -> str:
    return f"{int(now * 1000)}-{os.getpid()}-{next(_SEQ)}"

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
    except Exception as ex:
        # 0925 实机事故: root 手跑 record() 建出 root 属主 state.lock, ubuntu 服务
        # 全部静默拿不到锁, 账本停摆数小时只剩 pending 堆积。必须出声。
        hint = ("(属主/权限问题——若 root 手跑过翻译/账本命令, "
                "state.lock 可能已变 root 属主: chown ubuntu:ubuntu 恢复)"
                if isinstance(ex, PermissionError) else "")
        _log.warning("chain_guard: state.lock 打开失败%s: %s", hint, ex)
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
        if k == "win_min_calls" and cfg[k] < 1:
            cfg[k] = 1                      # 分母, 配 0 会除零且吞掉整条聚合
    try:
        cfg["win_fail_rate"] = float(cfg["win_fail_rate"])
    except Exception:
        cfg["win_fail_rate"] = DEFAULTS["win_fail_rate"]
    return cfg


def _norm_host_port(base_url: str) -> tuple[str, str]:
    """规范化出 (host, port): urlparse + localhost 归一, 防 'localhost:20133'
    漏判桥导致调用侧/桥双计、池键分裂。识别不了给 ('', '')。"""
    from urllib.parse import urlparse
    try:
        u = urlparse(str(base_url or "").strip())
        host = (u.hostname or "").lower()
        if host in ("localhost", "::1", "0.0.0.0"):
            host = "127.0.0.1"
        return host, str(u.port or "")
    except Exception:
        return "", ""


def is_bridge(base_url: str) -> bool:
    host, port = _norm_host_port(base_url)
    return host == "127.0.0.1" and port in _ZEN_PORT_NODE


def node_of(base_url: str) -> str:
    host, port = _norm_host_port(base_url)
    if host == "127.0.0.1" and port in _ZEN_PORT_NODE:
        return _ZEN_PORT_NODE[port]
    if "minimax" in str(base_url).lower():
        return "minimax"
    return "direct"


def model_prefix(model: str) -> str:
    m = str(model or "").strip()
    m = m[3:] if m.startswith("oc/") else m
    return (m[:2] or "??").lower()


def classify(status=None, exc=None, body: str = "") -> str:
    """错误分类: ok / 429_free / ua_freetier / 500_upstream / timeout / unreachable / other。
    状态码优先(含 requests 异常的 response.status_code), free-tier 文案降一级:
    包着 429 的拒绝必须归 429 才会被冷却, 只看文案会让池永远硬戳。
    unreachable=桥/连接不可达(请求没到上游, 桥无从记账, 只有调用侧能记)。"""
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
    if code == 429 or (code in (0, 429) and "429" in b[:80]):
        return "429_free"          # 正文兜底只在无码/429时生效, 防500文案里的"429"误归类
    if "FreeTier" in b or "free tier" in b.lower():
        return "ua_freetier"
    if "Connection" in name or "ConnectTimeout" in name:
        return "unreachable"       # 桥进程死/端口不通: 节点失明, 必须入账(算硬失败)
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


def _pending_path() -> Path:
    return usage_dir() / "pending.jsonl"


def _aggregate(st: dict, rec: dict, cfg: dict) -> bool:
    """单条记录聚合进 state(计数/recent)。调用方持文件锁。eid 去重, 返回是否新聚合。

    count_n=False 的质量修正记录(如桥流量 badjson): 只动 ok/fail 计数不动 n——
    桥已为该请求记过一次 n(含 ok), 此处补 fail, 两者合成 failrate≈1.0 把废池沉下去。"""
    eid = rec.get("eid") or ""
    seen = st.setdefault("seen_eids", {})
    if eid and eid in seen:
        return False
    if eid:
        seen[eid] = 1
        while len(seen) > _SEEN_CAP:
            seen.pop(next(iter(seen)))
    day = rec["utc_date"]
    node = rec["node"]
    prefix = rec["prefix"]
    ok = bool(rec["ok"])
    lat = int(rec.get("lat") or 0)
    count_n = rec.get("count_n", True)
    nodes = st.setdefault("nodes", {})
    nd = nodes.setdefault(f"{node}|{day}", {"n": 0, "ok": 0, "fail": 0,
                                            "lat_sum": 0, "tok": 0})
    if count_n:
        nd["n"] += 1
        nd["lat_sum"] += lat
        nd["tok"] += int(rec.get("total") or 0)
    nd["ok" if ok else "fail"] += 1
    pools = st.setdefault("pools", {})     # 池级日计数(真配额键=日|IP|前缀)
    pd = pools.setdefault(f"{node}|{prefix}|{day}", {"n": 0, "ok": 0,
                                                     "fail": 0, "lat_sum": 0})
    if count_n:
        pd["n"] += 1
        pd["lat_sum"] += lat
    pd["ok" if ok else "fail"] += 1
    recent = st.setdefault("recent", [])
    recent.append({"ts": rec["ts"], "node": node, "ok": ok,
                   "ecls": rec.get("ecls") or "ok", "prefix": prefix,
                   "eid": eid})
    return True


def _drain_queues(st: dict, cfg: dict) -> list:
    """补账队列排水: 上次崩溃残留的 replay.* + 本轮 rename 出来的 pending。
    返回待删队列路径(调用方在 _save_state 成功后再删; 删失败下轮 eid 去重兜底)。"""
    d = usage_dir()
    queues = sorted(d.glob("replay.*.jsonl"))
    pend = d / "pending.jsonl"
    if pend.exists():
        rp = d / f"replay.{time.time_ns()}.jsonl"
        try:
            os.replace(pend, rp)           # 锁内原子改名: 之后append进新pending, 不丢
            queues.append(rp)
        except Exception:
            queues.append(pend)
    for q in queues:
        try:
            for line in q.read_text(encoding="utf-8").splitlines():
                try:
                    _aggregate(st, json.loads(line), cfg)
                except Exception:
                    continue
        except Exception:
            continue
    return queues


def record(logger: str, node: str, model: str, ok: bool, ecls: str = "ok",
           latency_ms: int = 0, egress_ip: str = "", tokens: dict | None = None,
           failover_from: str = "", base_url: str = "",
           ts: float | None = None, count_n: bool = True) -> None:
    """记一次调用: JSONL 明细(无条件落) + 影子账本轮询聚合(文件锁内)。
    抢不到锁: 明细先进 pending.jsonl, 下轮锁内 rename-transaction 补聚合, 零丢失。
    ts=请求发起时刻(跨UTC日按发送时间计费, 非完成时刻); count_n=False=质量修正。
    绝不抛。"""
    try:
        now = float(ts) if ts else time.time()
        day = _utc_day(now)
        prefix = model_prefix(model)
        pool_key = f"{day}|{egress_ip or node}|{prefix}"
        rec = {"ts": int(now), "utc_date": day, "logger": logger, "node": node,
               "egress_ip": egress_ip, "model": model, "prefix": prefix,
               "pool_key": pool_key, "ok": bool(ok), "ecls": ecls,
               "lat": int(latency_ms), "failover_from": failover_from,
               "eid": _new_eid(now), "count_n": bool(count_n)}
        for k in ("prompt", "completion", "total", "cache_read"):
            v = (tokens or {}).get(k) or 0
            if v:
                rec[k] = int(v)
        line = json.dumps(rec, ensure_ascii=False)
        with open(usage_dir() / f"{day}.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")
        with _LOCK, _state_file_lock() as got:     # 线程锁+跨进程文件锁双保险
            if not got:
                # 抢不到: 进待补队列(append 单行原子), 下轮重放, 明细零丢失
                with open(_pending_path(), "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                return
            st = _load_state()
            cfg = guard_conf()
            _aggregate(st, rec, cfg)
            queues = _drain_queues(st, cfg)        # 先聚合完(含时序归并前)
            recent = st.get("recent", [])
            recent.sort(key=lambda r: (r.get("ts") or 0, r.get("eid") or ""))
            if len(recent) > cfg["recent_cap"]:
                del recent[:-cfg["recent_cap"]]
            _gc_state(st, day)
            _eval_breakers(st, time.time())
            _save_state(st)                        # 先落账
            for q in queues:                       # 成功后才删队列; 删失败eid去重兜底
                try:
                    q.unlink()
                except Exception:
                    pass
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


_QUOTA_ECLS = ("429_free", "ua_freetier")     # 配额类: 只冷配额槽, 不计入 IP 熔断
_HARD_ECLS = ("500_upstream", "timeout", "unreachable")


def _cool(tab: dict, key: str, until: float, reason: str) -> None:
    """冷却只延不缩: 已有更长冷却时保留(防短冷却覆盖长冷却)。"""
    old = tab.get(key) or {}
    if float(old.get("until") or 0) > until:
        return
    tab[key] = {"until": until, "reason": reason}


def _eval_breakers(st: dict, now: float) -> None:
    """熔断评估(须在 state 文件锁内调用; recent 已按 (ts,eid) 时间序归并)。

    冷却分槽(astra#5=grok#5, 单槽互覆是真bug):
    - pool_quota(429/ua_freetier): until 钉死**该事件自己所在 UTC 日**的翻篇点,
      已过期不再写(astra#4=grok#2: 午夜前429在午夜后重算曾被续封24h)。
    - pool_health(500/timeout/unreachable/模型级死亡): now+pool_cd_sec, 只延不缩。
    - 两槽同时查取更严。配额事件处理不受 IP 分支影响。

    死亡分级:
    - 硬失败同前缀在 ≥2 zen 节点各连击≥2 → 模型级死亡, 同步冷全部 zen 节点该前缀
      (排除 MiniMax 等外体系: MiniMax-M3 前缀也是 mi, 连坐会误冷全部 zen mi 池)。
    - 单节点单前缀连击(零成功) → 只冷池(grok#3: 别的前缀只是没被点到≠死了;
      astra#6: 模型级死亡的失败不再作为 IP 熔断证据)。
    - IP 熔断门槛: 零成功 且 硬失败跨越 ≥2 个未被模型死解释的前缀 且
      (硬failrate达标 或 有未解释连击)——单前缀场景一律只冷池, 不误杀整 IP。
    - 软错误(other)不打断 500 连击计数(只有 ok 清零); 有活前缀不熔断只降权。
    """
    cfg = guard_conf()
    win = [r for r in st.get("recent", []) if now - r["ts"] <= cfg["win_sec"]]
    by_node: dict[str, list] = {}
    for r in win:
        by_node.setdefault(r["node"], []).append(r)
    ip_break = st.setdefault("ip_break", {})          # node 级(=IP 级)熔断
    pool_quota = st.setdefault("pool_quota", {})      # node|prefix → 冷到事件日翻篇
    pool_health = st.setdefault("pool_health", {})    # node|prefix → 冷1h
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
    # 模型级死亡: 同前缀在 ≥2 个 zen 节点**各自连击≥2**(单节点1次+别节点1次
    # 只是两 IP 同时抖一下, 不够判死)。
    hard_nodes_by_p: dict[str, set] = {}
    for (node, p), n in hard_run.items():
        if node in _ZEN_NODES and n >= 2:
            hard_nodes_by_p.setdefault(p, set()).add(node)
    model_dead = {p for p, ns in hard_nodes_by_p.items() if len(ns) >= 2}
    for p in model_dead:
        for node in _ZEN_NODES:
            _cool(pool_health, f"{node}|{p}", now + cfg["pool_cd_sec"],
                  f"模型级死亡: {p} 在 {len(hard_nodes_by_p[p])} 节点齐灭")
    # 第二遍: 逐节点定级(仅 zen 节点: MiniMax/direct 无 IP 配额, 熔断它们只会
    # 把链掏空——MiniMax 是付费兜底, 失败再多也必须留在链尾)
    for node, rs in by_node.items():
        if node not in _ZEN_NODES:
            continue
        fails = [r for r in rs if not r["ok"]]
        ok = ok_by_node.get(node) or set()
        # 1) 配额事件: 钉死事件日翻篇, 不受 IP 分支影响, 已过期不重写
        for r in fails:
            if r["ecls"] in _QUOTA_ECLS:
                flip_r = _utc_flip_ts(float(r.get("ts") or now))
                if flip_r > now:
                    _cool(pool_quota, f"{node}|{r.get('prefix') or '??'}",
                          flip_r, f"{r['ecls']}→事件日UTC翻篇")
        # 2) 健康事件: 单前缀连击只冷池
        consec = {p for (n_, p), c in hard_run.items()
                  if n_ == node and c >= cfg["consec_fail"]}
        unexplained = consec - model_dead
        for p in unexplained:
            _cool(pool_health, f"{node}|{p}", now + cfg["pool_cd_sec"],
                  (f"500×{cfg['consec_fail']}+ 同节点 {sorted(ok)} 仍活(疑似模型级)"
                   if ok else
                   f"500×{cfg['consec_fail']}+ 零成功单前缀, 待跨节点证据"))
        # 3) IP 熔断: 零成功 + 硬失败跨≥2未被模型死解释的前缀 + 率/连击达标
        hard_pres = {r.get("prefix") or "??" for r in fails
                     if r["ecls"] in _HARD_ECLS} - model_dead
        n_hard = sum(1 for r in fails
                     if r["ecls"] in _HARD_ECLS
                     and (r.get("prefix") or "??") not in model_dead)
        if not ok and len(hard_pres) >= 2 and (
                (len(rs) >= cfg["win_min_calls"]
                 and n_hard / len(rs) >= cfg["win_fail_rate"])
                or unexplained):
            ip_break[node] = {
                "until": now + cfg["cooldown_sec"],
                "reason": f"零成功 | 硬前缀跨{len(hard_pres)}个 {sorted(hard_pres)}"
                          f" | 硬failrate {n_hard / len(rs):.0%}"}
    st["recent"] = win[-cfg["recent_cap"]:]


def _node_today(st: dict, node: str, now=None) -> dict:
    return (st.get("nodes") or {}).get(f"{node}|{_utc_day(now)}") or {}


def _pool_today(st: dict, node: str, prefix: str, now=None) -> dict:
    return (st.get("pools") or {}).get(f"{node}|{prefix}|{_utc_day(now)}") or {}


def _broken(kind: dict, key: str, now=None) -> str:
    info = (kind or {}).get(key) or {}
    left = float(info.get("until") or 0) - (now or time.time())
    if left <= 0:
        return ""
    m = int(left // 60)
    return f"{info.get('reason', '')}({m}min 后解)"


def _until_of(tab: dict, key: str) -> float:
    return float(((tab or {}).get(key) or {}).get("until") or 0)


def _pool_cooled(st: dict, node: str, prefix: str, now=None) -> str:
    """池冷却=配额槽与健康槽取更严(astra#5=grok#5)。legacy pool_break 只读兼容。"""
    now = now or time.time()
    key = f"{node}|{prefix}"
    tabs = [(st.get("pool_quota") or {}), (st.get("pool_health") or {}),
            (st.get("pool_break") or {})]
    best_until, best_info = 0.0, {}
    for tab in tabs:
        u = _until_of(tab, key)
        if u > best_until:
            best_until, best_info = u, (tab.get(key) or {})
    left = best_until - now
    if left <= 0:
        return ""
    return f"{best_info.get('reason', '')}({int(left // 60)}min 后解)"


def _mid(m: dict) -> str:
    return f"{m.get('base_url') or ''}|{m.get('model') or ''}"


_HYSTERESIS_SEC = 1800          # 滞回有效期: 超期强制重排(astra#9 防坏池永占链首)
_HYSTERESIS_HEAD_FR = 0.5       # 链首池 failrate 超此值强制重排


def order_chain(models: list) -> list:
    """预算排序: zen 段按影子账本(剔熔断/超池软顶, 用量少/失败率低/延迟低优先),
    非 zen(MiniMax 等)恒链尾保序。models = [dict(base_url, model, ...)]。

    读免锁: state 是 tmp+replace 原子快照, 读永不撕裂; 读不到可信 state 时
    保配置原序且不写滞回槽(astra#8: 绝不允许空账本放行/重排)。
    滞回: 可用集合相同且槽未过期(30min)且链首池 failrate<50% 才沿用上轮序——
    消除逐轮倾泻抖动, 又不让坏池永久冻结排序(astra#9)。"""
    cfg = guard_conf()
    if not cfg["enabled"]:
        return list(models)
    zen, other = [], []
    for m in models:
        (zen if is_bridge(m.get("base_url") or "") else other).append(m)
    if not zen:
        return list(models)
    now = time.time()
    st = _load_state()                  # 原子快照, 免锁
    if not st:
        return list(models)             # 无可信账本: 配置原序, 不写槽
    scored = []
    for m in zen:
        node = node_of(m.get("base_url") or "")
        pre = model_prefix(m.get("model"))
        pd = _pool_today(st, node, pre, now)
        n = int(pd.get("n") or 0)
        br = _broken(st.get("ip_break") or {}, node, now)
        pbr = _pool_cooled(st, node, pre, now)
        if br or pbr or n >= cfg["daily_soft_cap"]:
            continue                            # 熔断/超池软顶: 本轮摘除
        fails = int(pd.get("fail") or 0)
        rate = fails / n if n else 0.0
        avg_lat = (pd.get("lat_sum") or 0) / n if n else 0.0
        scored.append((n, rate, avg_lat, m))
    scored.sort(key=lambda t: (t[0], t[1], t[2]))
    fresh = [m for *_, m in scored]
    fresh_ids = [_mid(m) for m in fresh]
    # 滞回: 可用集合不变沿用上轮序。按链指纹分键——translate/feishu 两条链
    # 集合不同, 共用单槽会互相覆写导致滞回退化(二轮评审 P2); md5 非内置hash
    # (跨进程随机)。
    import hashlib
    fp = hashlib.md5("\n".join(sorted(fresh_ids)).encode("utf-8")).hexdigest()[:10]
    slot = f"chain_order:{fp}"
    with _LOCK, _state_file_lock() as got:
        if not got:
            return fresh + other
        st = _load_state()
        prev = st.get(slot) or {}
        if isinstance(prev, list):      # 旧格式兼容(0925 实机炸点): 老代码存纯 id 列表
            prev = {"ids": prev, "ts": 0}   # ts=0=视为过期, 本轮重排后重写新格式
        prev_ids = prev.get("ids") or []
        head_fr = 0.0
        if prev_ids:
            hb, hm = prev_ids[0].rsplit("|", 1)
            hp = _pool_today(st, node_of(hb), model_prefix(hm), now)
            hn = int(hp.get("n") or 0)
            head_fr = (int(hp.get("fail") or 0) / hn) if hn else 0.0
        if (set(prev_ids) == set(fresh_ids) and len(prev_ids) == len(fresh_ids)
                and now - float(prev.get("ts") or 0) < _HYSTERESIS_SEC
                and head_fr < _HYSTERESIS_HEAD_FR):
            by_id = {_mid(m): m for m in fresh}
            ordered = [by_id[i] for i in prev_ids if i in by_id]
            st[slot] = {"ids": [_mid(m) for m in ordered], "ts": now}
            _save_state(st)
            return ordered + other
        st[slot] = {"ids": fresh_ids, "ts": now}
        _save_state(st)
    return fresh + other


def admit(base_url: str, model: str) -> bool:
    """轮内准入(astra#1): 每个请求前重查熔断/软顶(读免锁原子快照, 成本≈一次文件读)。
    云端实证: 一轮内新产生的熔断拦不住后续批次, 死节点被反复戳(jp单轮24次)。
    非 zen/无账本时恒 True, 绝不误伤 MiniMax 兜底。"""
    try:
        cfg = guard_conf()
        if not cfg["enabled"] or not is_bridge(base_url):
            return True
        st = _load_state()
        if not st:
            return True
        now = time.time()
        node = node_of(base_url)
        pre = model_prefix(model)
        if _broken(st.get("ip_break") or {}, node, now):
            return False
        if _pool_cooled(st, node, pre, now):
            return False
        pd = _pool_today(st, node, pre, now)
        return int(pd.get("n") or 0) < cfg["daily_soft_cap"]
    except Exception:
        return True                     # 统计永不许卡翻译


def usage_report(days: int = 1) -> str:
    """聚合近 N 天 JSONL: 节点×模型成本表 + 节点日请求(防封主表) + 熔断现状。"""
    out = []
    agg: dict[tuple, dict] = {}
    node_day: dict[tuple, dict] = {}
    pool_day: dict[tuple, dict] = {}
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
                pk_ = (k[0], k[1], r.get("prefix") or "??")
                pool_day.setdefault(pk_, {"n": 0})["n"] += 1
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
    out.append("-- 节点日请求(防 IP 级总量闸, 若存在) --")
    out.append(f"{'日期':<11}{'节点':<9}{'日请求':>6}{'失败':>5}")
    for (day, node) in sorted(node_day, reverse=True):
        d = node_day[(day, node)]
        out.append(f"{day:<11}{node:<9}{d['n']:>6}{d['fail']:>5}")
    out.append("-- 池日用量(软顶余量: 配额键=池; 到顶即摘除至翻篇) --")
    out.append(f"{'日期':<11}{'池':<14}{'请求':>6}{'/软顶':>7}{'余量':>7}")
    for (day, node, pre) in sorted(pool_day, reverse=True):
        if node not in _ZEN_NODES:
            continue
        cap = cfg["daily_soft_cap"]
        n = pool_day[(day, node, pre)]["n"]
        mark = " ⚠到顶" if n >= cap else ""
        out.append(f"{day:<11}{node + '|' + pre:<14}{n:>6}{cap:>7}{cap - n:>7}{mark}")
    st = _load_state()
    now = time.time()
    # 待补账积压: 持续 >0 = 锁拿不到的事故信号(0925 root 属主锁致停摆实证),
    # 正常锁竞争 drained 后应为 0。
    backlog = 0
    d = usage_dir()
    pend = d / "pending.jsonl"
    if pend.exists():
        try:
            backlog += sum(1 for _ in pend.open(encoding="utf-8"))
        except Exception:
            backlog += 1
    backlog += len(list(d.glob("replay.*.jsonl")))
    if backlog:
        out.append(f"⚠ 待补账积压 {backlog} 条——锁持续拿不到, 查 state.lock 属主/权限")
    out.append("-- 熔断现状 --")
    ib = st.get("ip_break") or {}
    any_br = False
    for node in ("jp", "hk", "hk2", "minimax"):
        r = _broken(ib, node, now)
        if r:
            any_br = True
            out.append(f"  [IP熔断] {node}: {r}")
    # 分槽展示: 配额槽(冷到事件日翻篇) 与 健康槽(冷1h); legacy pool_break 兼容
    for slot_name, tab, tag in (("pool_quota", st.get("pool_quota") or {}, "配额"),
                                ("pool_health", st.get("pool_health") or {}, "健康"),
                                ("pool_break", st.get("pool_break") or {}, "池")):
        for key in sorted(tab):             # 动态: 池键=node|prefix, 不硬编码
            r = _broken(tab, key, now)
            if r:
                any_br = True
                out.append(f"  [{tag}熔断] {key.replace('|', '/')}: {r}")
    if not any_br:
        out.append("  无活跃熔断")
    nd = _node_today(st, "minimax", now)
    if nd.get("n"):
        out.append(f"-- MiniMax 今日: {nd['n']} 次 / {nd.get('tok', 0)} tok --")
    return "\n".join(out)
