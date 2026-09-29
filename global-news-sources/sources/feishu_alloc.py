"""账号选题限量分配引擎 v2(2026-09-25 MoA 定案; v2=review 门禁 3×P1 + 五方 MoA 复核修订)。

v1→v2 修订(全部有实证依据, 详见 data/tmp/moa_alloc_reviews.md):
- 预算簇内化(P1-2+跨簇串用, opus/grok): 占用=当前簇成员中 layer∈{comp,bench,tail} 的人数,
  不再数事件全局——后处理簇不再被先处理簇吃掉名额。pass/big 不占预算, 但接续时升级为
  comp(glm: pass 先冷后热组合泄漏 K+2 的修复)。
- 接续只给主展示层(pass/comp/big/tail), bench 永不转正(K3/grok/opus 共识)。
- owner 闭环(P1-1, 贪心去重版 opus/glm): E-S 排序后逐个取、取中即剔除同 owner 其余候选;
  覆盖挑号/L0 直通/备选三条路径; owner 身份=owner_open_id→owner→name 兜底(opus, 防
  缺省"?"塌缩成同一人); 注册表逐事件存 owner, 改名后仍拦同一人(grok)。
- 备选区结构性为空的修复(opus): K≥3 时预留 floor(K/3) 名额给备选(grok B 拍板的落实)。
- 大事件不覆写已有层(P2-1, glm 实证危害=永久全员接续); 帖数<命中数时只豁免前
  min(帖数,命中数) 个号, 其余走正常闸门(K3 M2/opus 截断)。
- 尾部加印三改(glm E8 实证绕 K 是 0.29 主因): ①每号按 hash(name|key) 排序取各自子集
  (打散); ②事件预算已满不得加印(grok); ③加印登记为 tail 层占预算。
- 空表兜底三段(grok 裁决): 备选转主推→P2/P3 加印→极端兜底(主推空时从自己命中按 FV
  取≤3 条, 可含 P0/P1, 不登记不占 K 但计入指标, note 标注)。绝不空表=绝不无反馈。
- 状态完整性(P2-4/P1-3): 注册表 events={事件键:{accounts:{名:{layer,owner}}}} 兼容
  v1 str 层值; 幽灵名(已删号)跳过查找不炸; 状态文件损坏改名 .bad 留证并显式失败——
  绝不当新一天静默重置 K。
- 指标三本账(grok/opus/glm): 竞争主推/大事件/尾部加印分开算 Jaccard, 验收只看竞争
  主推本; 门=尺同读 cfg.cluster_cos; 补空转计数。
- 渲染契约: 计划主推条目带 rep_url(大事件每号不同帖真正送达), 渲染层按它取帖不重建。

确定性纪律不变: 全程 md5 稳定哈希, 禁 random; slot 快照重跑不重算; 事件键不带档位。
状态: data/health/feishu-alloc.json; 自然日翻篇清注册表(24h 近似)。
"""
import hashlib
import json
import math
import os
import time
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "health"
_STATE = "feishu-alloc.json"

DEFAULT_CFG = {
    "mode": "off",            # off | shadow(只算指标不改推送) | draft(主推+备选替换全量)
    "quota_max": 18,          # opus: 主推目标 = min(18, 供给), 不足亮 short
    "bench_max": 10,          # grok: 备选区行数上限
    "pass_hits": 2,           # L0: 命中账号数 ≤2 直通
    "cluster_cos": 0.7,       # 分簇阈值, 与指标同类号对同口径(门=尺)
    "k_frac": {"P0": 0.20, "P1": 0.12, "P2": 0.06, "P3": 0.0},
    "k_cap": {"P0": 5, "P1": 3, "P2": 2, "P3": 1},
    "bench_reserve_div": 3,   # K≥3 时预留 floor(K/3) 名额给备选(opus 预留版)
    "big_event_min_cluster": 3,
    "big_event_per_slot": 1,
    "author_cap": 2,
    "fallback_rows": 3,       # 极端兜底行数上限(grok)
    "snap_keep": 50,
}

_BUDGET_LAYERS = ("comp", "bench", "tail")      # 占事件/簇预算的层
_MAIN_LAYERS = ("pass", "comp", "big", "tail")  # 接续(持续跟进)可用的层


def _state_path() -> Path:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    return _DATA_DIR / _STATE


class StateError(RuntimeError):
    """状态文件损坏/不可写——显式失败, 调用方必须中止本档(P2-4: 禁静默重置 K)。"""


def _load_state() -> dict:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        st = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(st, dict):
            raise ValueError("state root not object")
        return st
    except Exception as ex:                          # 损坏: 留证 + 显式失败
        try:
            os.replace(p, p.with_suffix(".bad"))
        except Exception:
            pass
        raise StateError(f"feishu-alloc state 损坏已隔离(.bad): {ex}") from ex


def _save_state(st: dict) -> None:
    p = _state_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)                               # 失败自然上抛(StateError 语义)


def _hash01(s: str) -> float:
    h = hashlib.md5(str(s).encode("utf-8")).hexdigest()
    return max(int(h[:16], 16) / float(1 << 64), 1e-12)


def _cos(a: dict, b: dict) -> float:
    ks = set(a) | set(b)
    if not ks:
        return 0.0
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na <= 0 or nb <= 0:
        return 0.0
    return sum(a.get(k, 0) * b.get(k, 0) for k in ks) / (na * nb)


def _owner_of(a: dict) -> str:
    """owner 身份兜底链(opus): owner_open_id → owner → name。防缺省塌缩(P1-1 前置)。"""
    return (str(a.get("owner_open_id") or "").strip()
            or str(a.get("owner") or "").strip()
            or str(a.get("name") or "").strip() or "??")


def _tickers(it: dict) -> list:
    try:
        ts = json.loads(it.get("tickers") or "[]")
    except Exception:
        ts = []
    return [str(t).strip().upper() for t in ts if str(t).strip()]


def event_key(it: dict) -> str:
    """事件归并键(保守): event_type|主ticker(第一个, 不排序——排序会改事件主体,
    opus/grok 双双否决 review 的排序建议); 无键退内容哈希(P2-5: 禁 id(it))。"""
    ev = str(it.get("event_type") or "").strip()
    ts = _tickers(it)
    if ev and ts:
        return f"{ev}|{ts[0]}"
    blob = f"{it.get('text') or ''}|{it.get('author_handle') or ''}|{it.get('time') or ''}"
    return "u|" + hashlib.md5(blob.encode("utf-8")).hexdigest()[:16]


def _fv(it: dict) -> int:
    try:
        return int(str(it.get("fv_s") or "0").split("·")[0])
    except Exception:
        return 0


def _tier(it: dict) -> str:
    t = str(it.get("fv_tier") or "P3")
    return t if t in ("P0", "P1", "P2", "P3") else "P3"


def cluster_events(cand: list) -> list:
    byk: dict[str, list] = {}
    for it in cand:
        byk.setdefault(event_key(it), []).append(it)
    events = []
    for k, its in byk.items():
        rep = max(its, key=lambda x: (_fv(x), float(x.get("_rate") or 0)))
        events.append({"key": k, "items": its, "rep": rep,
                       "topics": set(rep.get("topics") or ()),
                       "tier": _tier(rep), "fv": _fv(rep)})
    events.sort(key=lambda e: (-e["fv"], -float(e["rep"].get("_rate") or 0)))
    return events


def _k_day(tier: str, n: int, cfg: dict) -> int:
    frac = float(cfg["k_frac"].get(tier) or 0.0)
    cap = int(cfg["k_cap"].get(tier) or 1)
    return max(1, min(cap, math.ceil(frac * n))) if frac > 0 else min(cap, 1)


def _clusters(accs: list, cos_th: float) -> list:
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


def _w(a: dict) -> float:
    hit = [a["_mix"].get(t, 0) for t in a["_ev_topics_hit"]]
    return max(sum(hit) / 100.0, 0.05)


def _pick_weighted(ev_key_: str, slot: str, cands: list, k: int) -> list:
    """E-S 加权抽样 + 贪心 owner 去重(P1-1 修法, opus/glm): 按 E-S 分数降序逐个取,
    取中即剔除同 owner 其余候选; 池尽即止。同输入同结果。"""
    if k <= 0 or not cands:
        return []
    scored = sorted(cands, key=lambda a: -(_hash01(f"{ev_key_}|{slot}|{a['name']}")
                                           ** (1.0 / _w(a))))
    out, seen_owner = [], set()
    for a in scored:
        if a["_owner"] in seen_owner:
            continue
        out.append(a)
        seen_owner.add(a["_owner"])
        if len(out) >= k:
            break
    return out


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
    """主入口。v2 层语义: pass(直通)/comp(竞争主推)/bench(备选)/big(大事件)/tail(尾部加印);
    预算=簇内 comp+bench+tail; 接续只给主展示层; 输出 main 条目带 rep_url。"""
    cfg = dict(DEFAULT_CFG, **(cfg or {}))
    now = now or time.time()
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    st = _load_state()
    if st.get("day") != day:
        st = {"day": day}
    snaps = st.setdefault("snapshots", {})
    if slot in snaps and (snaps[slot] or {}).get("per_account"):
        out = dict(snaps[slot])
        out["from_snapshot"] = True
        return out

    accs = []
    for a in accounts or []:
        mix = {str(k): float(v) for k, v in (a.get("mix") or {}).items()
               if isinstance(v, (int, float)) and float(v) > 0}
        if mix:
            accs.append({"name": str(a.get("name") or "?"),
                         "owner": str(a.get("owner") or ""), "_mix": mix,
                         "_owner": _owner_of(a)})
    by_name = {a["name"]: a for a in accs}
    events = cluster_events(cand)
    ev_reg: dict = st.setdefault("events", {})   # 事件键 → {accounts: {名: {layer,owner}}}

    def entry(ev_key: str, name: str) -> dict:
        """注册条目; v1 str 层值兼容(schema 升级必须兼容读旧格式)。"""
        v = ((ev_reg.get(ev_key) or {}).get("accounts") or {}).get(name)
        if isinstance(v, dict):
            return v
        return {"layer": v, "owner": None} if v else {}

    def set_entry(ev_key: str, name: str, layer: str, owner) -> None:
        ev_reg.setdefault(ev_key, {}).setdefault("accounts", {})[name] = \
            {"layer": layer, "owner": owner}

    main_ev: dict[str, list] = {a["name"]: [] for a in accs}
    bench_ev: dict[str, list] = {a["name"]: [] for a in accs}
    avail_n: dict[str, int] = {a["name"]: 0 for a in accs}
    hits_n: dict[str, int] = {}                    # 事件键 → 本档命中号数(加印预算用)
    big_used = 0
    fv_sorted = sorted(e["fv"] for e in events)
    p97 = fv_sorted[min(int(len(fv_sorted) * 0.97), max(len(fv_sorted) - 1, 0))] \
        if fv_sorted else 101

    for ev in events:
        hits = [a for a in accs if a["_mix"] and (ev["topics"] & set(a["_mix"]))]
        if not hits:
            continue
        hits_n[ev["key"]] = len(hits)
        for a in hits:
            a["_ev_topics_hit"] = sorted(ev["topics"] & set(a["_mix"]),
                                         key=lambda t: -a["_mix"][t])
            avail_n[a["name"]] += 1

        # 大事件豁免: 不覆写已有层(P2-1); 只豁免未收号, 帖数<命中数时截断(K3 M2/opus)
        if (len(ev["items"]) >= int(cfg["big_event_min_cluster"]) and ev["fv"] >= p97
                and big_used < int(cfg["big_event_per_slot"])):
            fresh_hits = [a for a in hits if not entry(ev["key"], a["name"]).get("layer")]
            order = sorted(fresh_hits,
                           key=lambda a: _hash01(f"big|{ev['key']}|{a['name']}"))
            n_big = min(len(ev["items"]), len(order))
            big_used += 1
            for i, a in enumerate(order[:n_big]):
                it = ev["items"][i % len(ev["items"])]
                main_ev[a["name"]].append((ev, f"公共大事件·建议角度:"
                                         f"{_BIG_ANGLES[i % len(_BIG_ANGLES)]}", it))
                set_entry(ev["key"], a["name"], "big", a["_owner"])
            hits_rest = [a for a in hits if a not in order[:n_big]]
        else:
            hits_rest = hits

        # L0 直通: 命中≤2; 同 owner 只直通一个(P1-1 覆盖直通路径); 已收号接续
        fresh_rest = [a for a in hits_rest if not entry(ev["key"], a["name"]).get("layer")]
        if len(hits_rest) <= int(cfg["pass_hits"]):
            for a in hits_rest:
                if entry(ev["key"], a["name"]).get("layer"):
                    main_ev[a["name"]].append((ev, "持续跟进(已报道)", ev["rep"]))
            for a in _pick_weighted(ev["key"], slot + "|pass", fresh_rest,
                                    len(fresh_rest)):
                main_ev[a["name"]].append((ev, "低竞争直通", ev["rep"]))
                set_entry(ev["key"], a["name"], "pass", a["_owner"])
            continue

        # 竞争层: 分簇, 簇内预算(comp+bench+tail), 簇间互不占 K(P1-2+跨簇修订)
        for cl in _clusters(hits_rest, float(cfg["cluster_cos"])):
            if len(cl) <= 1:
                a = cl[0]
                if entry(ev["key"], a["name"]).get("layer"):
                    main_ev[a["name"]].append((ev, "持续跟进(已报道)", ev["rep"]))
                else:
                    main_ev[a["name"]].append((ev, "命中直通", ev["rep"]))
                    set_entry(ev["key"], a["name"], "pass", a["_owner"])
                continue
            k_day = _k_day(ev["tier"], len(cl), cfg)

            def occupied_now():
                return sum(1 for x in cl
                           if entry(ev["key"], x["name"]).get("layer") in _BUDGET_LAYERS)

            # 接续: 主展示层升主推; pass/big 升级 comp(glm 组合泄漏修复); bench 不转正
            for x in cl:
                e0 = entry(ev["key"], x["name"])
                if e0.get("layer") in ("pass", "big"):
                    main_ev[x["name"]].append((ev, "持续跟进(已报道)", ev["rep"]))
                    set_entry(ev["key"], x["name"], "comp",
                              e0.get("owner") or x["_owner"])
                elif e0.get("layer") in ("comp", "tail"):
                    main_ev[x["name"]].append((ev, "持续跟进(已报道)", ev["rep"]))
            occupied = occupied_now()
            owners_taken = set()
            for n, e0 in ((ev_reg.get(ev["key"]) or {}).get("accounts") or {}).items():
                o = (e0 or {}).get("owner") if isinstance(e0, dict) else None
                if o is None and n in by_name:
                    o = by_name[n]["_owner"]          # v1 旧条目回填当前 owner
                if o:
                    owners_taken.add(o)               # 幽灵名的存量 owner 照样拦人
            fresh = [a for a in cl if not entry(ev["key"], a["name"]).get("layer")
                     and a["_owner"] not in owners_taken]      # owner 独占(grok)
            # 备选预留(opus): K≥3 预留 floor(K/div), 否则备选结构性为空
            reserved = k_day // int(cfg["bench_reserve_div"]) if k_day >= 3 else 0
            rem_main = max(0, k_day - reserved - occupied)
            for a in _pick_weighted(ev["key"], slot, fresh, rem_main):
                main_ev[a["name"]].append((ev, "限量分配", ev["rep"]))
                set_entry(ev["key"], a["name"], "comp", a["_owner"])
            bench_rem = max(0, k_day - occupied_now())
            # 备选同样滤 owner(grok 终审: 备选落选名单不查 owner=兄弟号一主推一备选)
            losers = [a for a in cl if not entry(ev["key"], a["name"]).get("layer")
                      and a["_owner"] not in owners_taken]
            for a in _pick_weighted(ev["key"], slot + "|bench", losers, bench_rem):
                bench_ev[a["name"]].append((ev, f"备选(主推名额已满·K={k_day})"))
                set_entry(ev["key"], a["name"], "bench", a["_owner"])

    # ── 组装: 主推(min(quota_max,供给), opus) + 尾部加印(打散) + 兜底三段(grok) ──
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
        bench_keys = {e["key"] for e, _ in bench_ev[a["name"]]}

        # 尾部加印 v2: 每号按 hash(name|key) 取各自子集(glm 打散); 事件预算
        # (comp+bench+tail ≥ K_day(tier,本档命中数)) 已满不得加印(grok); 排除备选键
        # (P2-2); 加印登记 tail 占预算
        if len(main_flat) < q:
            held = {e["key"] for e, _, _ in main_flat} | bench_keys
            pool = []
            for e in events:
                if e["key"] in held or e["tier"] not in ("P2", "P3"):
                    continue
                if not (e["topics"] & set(a["_mix"])):
                    continue
                used = sum(1 for v in ((ev_reg.get(e["key"]) or {})
                                       .get("accounts") or {}).values()
                           if (v.get("layer") if isinstance(v, dict) else v)
                           in _BUDGET_LAYERS)
                if used < _k_day(e["tier"], hits_n.get(e["key"], 1), cfg):
                    pool.append(e)
            pool.sort(key=lambda e: _hash01(f"tail|{a['name']}|{e['key']}"))
            for e in pool:
                if len(main_flat) >= q:
                    break
                main_flat.append((e, "尾部加印·同类号也可能看到", e["rep"]))
                set_entry(e["key"], a["name"], "tail", a["_owner"])
        # 兜底三段(grok 裁决): ①备选转主推 ②加印(上) ③极端兜底(≤3行,不登记不占K)
        if not main_flat and bench_ev[a["name"]]:
            for e, note in bench_ev[a["name"]]:
                main_flat.append((e, "备选转主推", e["rep"]))
        if not main_flat and avail_n[a["name"]] > 0:
            pool = [e for e in events if e["topics"] & set(a["_mix"])]
            pool.sort(key=lambda e: -e["fv"])
            for e in pool[:int(cfg["fallback_rows"])]:
                main_flat.append((e, "极端兜底·同类号也会看到·本档竞争落选", e["rep"]))
        bench = [(e, n) for e, n in bench_ev[a["name"]]
                 if e["key"] not in {x[0]["key"] for x in main_flat}][:int(cfg["bench_max"])]
        per[a["name"]] = {
            "main": [{"key": e["key"], "note": n, "rep_url": r.get("url")}
                     for e, n, r in main_flat],
            "bench": [{"key": e["key"], "note": n} for e, n in bench],
            "quota": q, "short": len(main_flat) < q,
            "owner": a["owner"] or a["_owner"]}

    metrics = _metrics(accs, per, events, cfg)
    mj = metrics["books"]["comp"]["mean_jaccard"]
    short = [n for n, v in per.items() if v["short"]]
    out = {"per_account": per, "metrics": metrics, "day": day,
           "summary": {"accounts": len(accs), "events": len(events),
                       "big_events": big_used,
                       "mean_jaccard": round(mj, 3) if mj is not None else None,
                       "short_accounts": short,
                       "starve_accounts": metrics["starve_accounts"]}}
    snaps[slot] = out
    st.setdefault("metrics", {})[slot] = metrics
    if len(snaps) > int(cfg["snap_keep"]):            # 按插入序淘汰(修字典序乱删 P3)
        for k in list(snaps.keys())[:-int(cfg["snap_keep"])]:
            snaps.pop(k, None)
    if persist:
        _save_state(st)
    return out


def _metrics(accs: list, per: dict, events: list, cfg: dict) -> dict:
    """三本账 Jaccard(grok/opus/glm): 竞争主推/大事件/尾部加印+兜底, 门=尺同 cfg。"""

    def book_of(note: str) -> str:
        if "大事件" in note:
            return "big"
        if "加印" in note or "兜底" in note or "备选转主推" in note:
            return "tail"
        return "comp"

    pairs = []
    th = float(cfg["cluster_cos"])
    for i in range(len(accs)):
        for j in range(i + 1, len(accs)):
            if _cos(accs[i]["_mix"], accs[j]["_mix"]) > th:
                pairs.append((accs[i]["name"], accs[j]["name"]))
    books = {"comp": [], "big": [], "tail": []}
    for name, v in per.items():
        for m in v.get("main") or []:
            books[book_of(m.get("note") or "")].append((name, m["key"]))
    out_books = {}
    for bk, rows in books.items():
        keys_by_acc: dict[str, set] = {}
        for name, k in rows:
            keys_by_acc.setdefault(name, set()).add(k)
        js = []
        for n1, n2 in pairs:
            A, B = keys_by_acc.get(n1, set()), keys_by_acc.get(n2, set())
            u = A | B
            if u:
                js.append(len(A & B) / len(u))
        out_books[bk] = {"rows": len(rows), "pairs": len(js),
                         "mean_jaccard": round(sum(js) / len(js), 4) if js else None,
                         "max_jaccard": round(max(js), 4) if js else None}
    starve = [n for n, v in per.items() if not v["main"]]
    return {"books": out_books, "pairs_total": len(pairs),
            "starve_accounts": starve, "events_total": len(events)}
