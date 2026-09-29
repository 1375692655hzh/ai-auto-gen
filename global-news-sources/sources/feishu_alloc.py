"""账号选题限量分配引擎(2026-09-25 MoA 五方定案, 用户拍板 A=opus行数 B=grok备选)。

问题: doc 模式全量命中(_doc_order_all)使同类账号收到高度重叠清单 → 发布同质化。
方案(五方共识骨架+终审修订): 事件归并(跨档登记) → 三层闸门(直通/竞争限量/保底)
→ 竞争层按簇 K 限量 + 稳定哈希加权挑号(MVP 第一步, 无账本; 第二步换信贷账本)
→ opus 行数 min(上限,供给) → grok 备选区(主推+备选 ≤ K) → 尾部加印保底。

终审修订落实:
- L0 删"平均余弦"(astra/opus/grok 三家): 只留命中数≤2 直通; 其余按 mix 余弦>0.7
  分簇, 簇内限量, 簇间互不占 K。
- 事件键不带推送档位 + 24h(自然日)跨档登记(opus/astra): 同事件次日新帖不再重分,
  K 按全天累计, 已收账号优先接续(报道连续性)。
- 主推行数 = min(quota_max, 该号可用事件数), 不足在表头亮出来(opus); 不暗中凑数。
- 备选区计入同一 K 预算、按人分列(grok): 主推人数+备选人数 ≤ K_day; 满额的帖
  不出现在任何号的备选区。
- 同 owner 多号独占(grok): 同事件主推只进一个号。
- 确定性纪律: 全程稳定哈希(md5), 禁 random(), 同输入同结果(opus/glm);
  分配计划按 slot 落快照, 同档重跑读快照不重算(opus)。
- 大事件豁免: 每档最多 1 个, 全员覆盖但同簇不同帖 + 角度提示(opus/glm)。

已知限制(MVP 第一步, 无信贷账本):
- 挑号用稳定哈希加权抽样(Efraimidis-Spirakis), 跨档公平靠"已收优先接续"而非账本;
  第二步按 grok 信贷方案替换挑号函数即可, 接口不变。
- registry 在分配时即提交(先落盘再推送, astra 事务化); 推送失败不回滚(该号本档
  漏收, 次档靠接续优先自然补)——无账本阶段无退款语义, 快照保证重跑不发散。
- 角度模板只是提示列: 本方案保证选题集合互斥, 不保证成稿差异(grok 终审写死)。

状态: data/health/feishu-alloc.json = {day, events:{key:{accounts:{name:layer}}},
snapshots:{slot:{...}}, metrics:{slot:{...}}}; 自然日翻篇清 events。
"""
import hashlib
import json
import math
import os
import re
import time
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "health"
_STATE = "feishu-alloc.json"

DEFAULT_CFG = {
    "mode": "off",            # off | shadow(只算指标不改推送) | draft(主推+备选替换全量)
    "quota_max": 18,          # opus: 主推目标 = min(18, 供给), 不足亮缺口
    "bench_max": 10,          # grok: 备选区行数上限
    "pass_hits": 2,           # L0: 命中账号数 ≤2 直通(终审删平均余弦后的唯一直通道)
    "cluster_cos": 0.7,       # 分簇阈值(mix 余弦), 与指标"同类号对"同口径(门=尺)
    "k_frac": {"P0": 0.20, "P1": 0.12, "P2": 0.06, "P3": 0.0},
    "k_cap": {"P0": 5, "P1": 3, "P2": 2, "P3": 1},
    "big_event_min_cluster": 3,   # 簇内帖数≥3 且 FV≥P97 → 公共大事件
    "big_event_per_slot": 1,
    "author_cap": 2,          # 同作者在单号主推最多行数, 填不满 80% 才放宽到 4
    "snap_keep": 50,
}


def _state_path() -> Path:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    return _DATA_DIR / _STATE


def _load_state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(st: dict) -> None:
    try:
        p = _state_path()
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass


def _hash01(s: str) -> float:
    """稳定哈希 → [0,1)。md5 跨进程确定(禁 random(), opus/glm 纪律)。"""
    h = hashlib.md5(str(s).encode("utf-8")).hexdigest()
    v = int(h[:16], 16) / float(1 << 64)
    return max(v, 1e-12)                      # 防 0 的幂运算下溢


def _cos(a: dict, b: dict) -> float:
    ks = set(a) | set(b)
    if not ks:
        return 0.0
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na <= 0 or nb <= 0:
        return 0.0
    return sum(a.get(k, 0) * b.get(k, 0) for k in ks) / (na * nb)


def _tickers(it: dict) -> list:
    try:
        ts = json.loads(it.get("tickers") or "[]")
    except Exception:
        ts = []
    return [str(t).strip().upper() for t in ts if str(t).strip()]


def event_key(it: dict) -> str:
    """事件归并键(保守): 有 event_type 且有主 ticker → (类型,主ticker);
    其余退回 URL 不合并(误并成本高于漏并, 终审共识)。键不含推送档位(opus)。"""
    ev = str(it.get("event_type") or "").strip()
    ts = _tickers(it)
    if ev and ts:
        return f"{ev}|{ts[0]}"
    return "u|" + str(it.get("url") or id(it))


def _fv(it: dict) -> int:
    try:
        return int(str(it.get("fv_s") or "0").split("·")[0])
    except Exception:
        return 0


def _tier(it: dict) -> str:
    t = str(it.get("fv_tier") or "P3")
    return t if t in ("P0", "P1", "P2", "P3") else "P3"


def cluster_events(cand: list) -> list:
    """候选帖 → 事件列表。代表帖=FV 最高(不以转述条数抬分, astra);
    topics 取代表帖(保守, 防并集放大命中)。"""
    byk: dict[str, list] = {}
    for it in cand:
        byk.setdefault(event_key(it), []).append(it)
    events = []
    for k, its in byk.items():
        rep = max(its, key=lambda x: (_fv(x), _rate_num(x)))
        events.append({"key": k, "items": its, "rep": rep,
                       "topics": set(rep.get("topics") or ()),
                       "tier": _tier(rep), "fv": _fv(rep)})
    events.sort(key=lambda e: (-e["fv"], -_rate_num(e["rep"])))
    return events


def _rate_num(it: dict) -> float:
    return float(it.get("_rate") or 0.0)


def _k_day(tier: str, n: int, cfg: dict) -> int:
    """全天累计接收上限 = max(1, min(绝对帽, ⌈比例×簇内号数⌉))(grok 比例公式)。"""
    frac = float(cfg["k_frac"].get(tier) or 0.0)
    cap = int(cfg["k_cap"].get(tier) or 1)
    return max(1, min(cap, math.ceil(frac * n))) if frac > 0 else min(cap, 1)


def _clusters(accs: list, cos_th: float = 0.7) -> list:
    """命中账号按 mix 余弦>cos_th 并查集分簇(终审: 删全局平均余弦);
    阈值与指标同类号对同口径(门=尺, K3 终审对齐要求)。"""
    parent = {i: i for i in range(len(accs))}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(accs)):
        for j in range(i + 1, len(accs)):
            if _cos(accs[i]["_mix"], accs[j]["_mix"]) > cos_th:
                parent[find(i)] = find(j)
    out: dict[int, list] = {}
    for i, a in enumerate(accs):
        out.setdefault(find(i), []).append(a)
    return list(out.values())


def _pick_weighted(event_key_: str, slot: str, cands: list, k: int) -> list:
    """稳定哈希加权抽样(E-S): key = hash01^(1/w), w=该号对事件主主题的 mix 权重。
    同输入同结果; 无 random()。"""
    def w(a):
        m = a["_mix"]
        hit = [m.get(t, 0) for t in a["_ev_topics_hit"]]
        return max(sum(hit) / 100.0, 0.05)
    scored = [(_hash01(f"{event_key_}|{slot}|{a['name']}") ** (1.0 / w(a)), a)
              for a in cands]
    scored.sort(key=lambda t: -t[0])
    return [a for _, a in scored[:k]]


def _split_quota(mix: dict, total: int) -> dict:
    """与 feishu._split_quota 同义复刻(避免循环 import; 语义改动须双向同步)。"""
    themes = [t for t, p in mix.items() if p and p > 0]
    if not themes:
        return {}
    total = max(total, len(themes))
    raw = {t: mix[t] / sum(mix[t] for t in themes) * total for t in themes}
    quota = {t: max(1, int(raw[t])) for t in themes}
    while sum(quota.values()) > total:
        cut = [t for t in themes if quota[t] > 1]
        if not cut:
            break
        t_cut = max(cut, key=lambda t: (quota[t] - raw[t], raw[t]))
        quota[t_cut] -= 1
    while sum(quota.values()) < total:
        quota[max(themes, key=lambda t: raw[t] - quota[t])] += 1
    return quota


_BIG_ANGLES = ("快讯首发", "数据拆解", "反方观点", "影响分析", "历史对比", "资金面视角")


def allocate(cand: list, accounts: list, slot: str, cfg: dict | None = None,
             persist: bool = True, now: float | None = None) -> dict:
    """主入口: cand(已带 topics/fv_s/fv_tier/_rate/views) + accounts(yaml 账号卡)
    → {per_account:{name:{main,bench,ordered,quota,short,note}}, metrics, summary}。
    slot 同名重跑读快照(opus 事务化); persist=False 供 dry_run 不落盘。"""
    cfg = dict(DEFAULT_CFG, **(cfg or {}))
    now = now or time.time()
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    st = _load_state()
    if st.get("day") != day:                    # 自然日翻篇: 跨档登记清零(24h 近似)
        st = {"day": day}
    snap = (st.setdefault("snapshots", {}) or {}).get(slot)
    if snap and snap.get("per_account"):
        out = snap
        out["from_snapshot"] = True
        return out

    accs = []
    for a in accounts or []:
        mix = {str(k): float(v) for k, v in (a.get("mix") or {}).items()
               if isinstance(v, (int, float)) and float(v) > 0}
        if mix:
            accs.append({"name": str(a.get("name") or "?"),
                         "owner": str(a.get("owner") or "?"), "_mix": mix})
    events = cluster_events(cand)
    reg: dict = st.setdefault("events", {})     # key → {accounts:{name:layer}}

    main_ev: dict[str, list] = {a["name"]: [] for a in accs}   # name → [(ev, note)]
    bench_ev: dict[str, list] = {a["name"]: [] for a in accs}
    avail_n: dict[str, int] = {a["name"]: 0 for a in accs}
    big_used = 0
    fv_sorted = sorted(e["fv"] for e in events)
    p97 = fv_sorted[min(int(len(fv_sorted) * 0.97), max(len(fv_sorted) - 1, 0))] if fv_sorted else 101

    for ev in events:
        hits = [a for a in accs if a["_mix"] and (ev["topics"] & set(a["_mix"]))]
        for a in hits:
            a["_ev_topics_hit"] = sorted(ev["topics"] & set(a["_mix"]),
                                         key=lambda t: -a["_mix"][t])
        for a in hits:
            avail_n[a["name"]] += 1
        if not hits:
            continue
        got = reg.setdefault(ev["key"], {}).setdefault("accounts", {})
        # 大事件豁免: 每档≤1, 全员覆盖但同簇不同帖+角度提示
        if (len(ev["items"]) >= int(cfg["big_event_min_cluster"]) and ev["fv"] >= p97
                and big_used < int(cfg["big_event_per_slot"])):
            big_used += 1
            order = sorted(hits, key=lambda a: _hash01(f"big|{ev['key']}|{a['name']}"))
            for i, a in enumerate(order):
                it = ev["items"][i % len(ev["items"])]
                ang = _BIG_ANGLES[i % len(_BIG_ANGLES)]
                main_ev[a["name"]].append((ev, f"公共大事件·建议角度:{ang}", it))
                got[a["name"]] = "big"
            continue
        # L0 直通: 命中数≤2 无竞争(终审删平均余弦, 只留这条)
        if len(hits) <= int(cfg["pass_hits"]):
            for a in hits:
                main_ev[a["name"]].append((ev, "低竞争直通", ev["rep"]))
                got[a["name"]] = "pass"
            continue
        # 竞争层: 分簇, 簇内按 K_day 限量(全天累计), 簇间互不占 K
        for cl in _clusters(hits, float(cfg["cluster_cos"])):
            if len(cl) <= 1:
                a = cl[0]
                main_ev[a["name"]].append((ev, "命中直通", ev["rep"]))
                got[a["name"]] = "pass"
                continue
            k_day = _k_day(ev["tier"], len(cl), cfg)
            comp_n = sum(1 for v in got.values() if v == "comp")
            rem = k_day - comp_n
            # 接续优先(opus): 已收账号(今日任意层收过)直接续新帖, 不耗新名额
            for a in [x for x in cl if x["name"] in got]:
                main_ev[a["name"]].append((ev, "持续跟进(已报道)", ev["rep"]))
            owners_taken = {next(x["owner"] for x in accs if x["name"] == n)
                            for n in got}
            fresh = [a for a in cl if a["name"] not in got
                     and a["owner"] not in owners_taken]      # owner 独占(grok)
            if rem > 0 and fresh:
                picks = _pick_weighted(ev["key"], slot, fresh, rem)
                for a in picks:
                    main_ev[a["name"]].append((ev, "限量分配", ev["rep"]))
                    got[a["name"]] = "comp"
            # 备选(grok): 主推+备选 ≤ K_day; 落选号看到的只有未满额的帖
            comp_n2 = sum(1 for v in got.values() if v == "comp")
            bench_rem = k_day - comp_n2
            losers = [a for a in cl if a["name"] not in got]
            if bench_rem > 0 and losers:
                for a in _pick_weighted(ev["key"], slot + "|bench", losers, bench_rem):
                    bench_ev[a["name"]].append((ev, f"备选(主推名额已满·K={k_day})"))
                    got[a["name"]] = "bench"

    # ── 组装: 主推(min(quota_max,供给), opus) + 尾部加印 + 备选截断 ──
    per = {}
    for a in accs:
        q = min(int(cfg["quota_max"]), max(avail_n[a["name"]], 1))
        quota = _split_quota(a["_mix"], q)
        order = sorted(a["_mix"], key=lambda t: -a["_mix"][t])
        buckets: dict[str, list] = {t: [] for t in order}
        taken: set = set()
        author_n: dict = {}
        evs = main_ev[a["name"]]
        evs.sort(key=lambda p: -(p[0]["fv"]))
        relaxed = len(evs) < 0.8 * q
        for e, note, rep in evs:
            if e["key"] in taken:
                continue
            an = str(rep.get("author_handle") or "")
            cap = 4 if relaxed else int(cfg["author_cap"])
            if author_n.get(an, 0) >= cap:
                continue
            for t in sorted(e["topics"] & set(a["_mix"]), key=lambda t: -a["_mix"][t]):
                if len(buckets[t]) < quota.get(t, 0):
                    buckets[t].append((e, note, rep))
                    taken.add(e["key"])
                    author_n[an] = author_n.get(an, 0) + 1
                    break
        main_flat = [x for t in order for x in buckets[t]]
        # 尾部加印(P2/P3, P0/P1 的 K 不放宽): 只补未满额, 不空表
        if len(main_flat) < q:
            held = {e["key"] for e, _, _ in main_flat}
            pool = [e for e in events
                    if e["key"] not in held and e["topics"] & set(a["_mix"])
                    and e["tier"] in ("P2", "P3")]
            for e in pool:
                if len(main_flat) >= q:
                    break
                main_flat.append((e, "尾部加印·同类号也可能看到", e["rep"]))
                held.add(e["key"])
        bench = bench_ev[a["name"]][:int(cfg["bench_max"])]
        per[a["name"]] = {
            "main": [{"key": e["key"], "note": n, "rep_url": r.get("url")}
                     for e, n, r in main_flat],
            "bench": [{"key": e["key"], "note": n} for e, n in bench],
            "quota": q, "short": len(main_flat) < q,
            "owner": a["owner"]}

    metrics = _metrics(accs, per, events, cfg)
    mj = metrics["mean_jaccard"]
    out = {"per_account": per, "metrics": metrics, "day": day,
           "summary": {"accounts": len(accs), "events": len(events),
                       "big_events": big_used,
                       "mean_jaccard": round(mj, 3) if mj is not None else None,
                       "short_accounts": metrics["short_accounts"]}}
    st.setdefault("snapshots", {})[slot] = out
    st.setdefault("metrics", {})[slot] = metrics
    snaps = st["snapshots"]
    if len(snaps) > int(cfg["snap_keep"]):
        for k in sorted(snaps)[:-int(cfg["snap_keep"])]:
            snaps.pop(k, None)
    if persist:
        _save_state(st)
    return out


def _metrics(accs: list, per: dict, events: list, cfg: dict) -> dict:
    """同类对(余弦>0.7, 与分簇同口径=门尺一致)主推事件 Jaccard + 配额/空转。"""
    pairs = []
    for i in range(len(accs)):
        for j in range(i + 1, len(accs)):
            if _cos(accs[i]["_mix"], accs[j]["_mix"]) > 0.7:
                A = {x["key"] for x in per[accs[i]["name"]]["main"]}
                B = {x["key"] for x in per[accs[j]["name"]]["main"]}
                u = A | B
                pairs.append(len(A & B) / len(u) if u else 0.0)
    short = [n for n, v in per.items() if v["short"]]
    return {"pairs": len(pairs),
            "mean_jaccard": round(sum(pairs) / len(pairs), 4) if pairs else None,
            "max_jaccard": round(max(pairs), 4) if pairs else None,
            "short_accounts": short,
            "events_total": len(events)}
