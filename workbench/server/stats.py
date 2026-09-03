"""统计聚合(资讯页右栏 + 来源详情子页的数据供给)。

学同事看板(aag-看板/信源工作台.html)的思路, 但聚合放在服务端:
拉取 /v1/items 全量(≤4 页 × 1000, 与看板同上限) + /v1/sources + /v1/status,
服务端聚合好直接给前端成品, 浏览器不用搬几千条数据。
60s 进程内缓存, 避免每次切页都重拉。
"""

import time
import urllib.parse
from collections import Counter

from . import proxy, xaccounts

_cache = {"at": 0.0, "data": None}
_CACHE_TTL = 60.0
_PAGE, _MAX_PAGES = 1000, 4          # 与看板同: store.query 单页硬顶 1000


def _fetch_items() -> tuple[list, bool]:
    items, cursor = [], ""
    for _ in range(_MAX_PAGES):
        qs = f"items?limit={_PAGE}&dedup=1&display=1"
        if cursor:                       # cursor 形如 "2026-09-01 21:49|<hash>", 含空格须转义
            qs += "&cursor=" + urllib.parse.quote(cursor, safe="")
        d = proxy.fetch_json(qs)
        items.extend(d.get("items") or [])
        cursor = d.get("next_cursor") or ""
        if not cursor:
            return items, False
    return items, True                  # 截断标记: 库里还有更多


def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


def aggregate() -> dict:
    if _cache["data"] and time.time() - _cache["at"] < _CACHE_TTL:
        return _cache["data"]

    health = proxy.fetch_json("health")
    status = proxy.fetch_json("status")
    sources = proxy.fetch_json("sources").get("sources") or []
    raw_items, truncated = _fetch_items()

    now = _now_str()
    # 预测市场类源会把结算日(数年后)写进 time, 聚合前剔除(看板同款处理)
    items = [i for i in raw_items if (i.get("time") or "") <= now]
    future_n = len(raw_items) - len(items)

    def count(fn):
        c = Counter()
        for i in items:
            v = fn(i)
            vals = [v] if isinstance(v, str) else (v or [])
            for x in vals:
                if x:
                    c[x] += 1
        return [[k, n] for k, n in c.most_common()]

    per_source = Counter(i.get("source_id") for i in items)
    per_source_name = {}
    for i in items:
        per_source_name.setdefault(i.get("source_id"), i.get("source") or i.get("source_id"))

    # X 池按账号产量(右栏独立卡; 名称 join 池档案, 缺档案回退 @handle)
    x_count = Counter(str(i.get("author_handle") or "").lower()
                      for i in items if i.get("author_handle"))
    x_pool = xaccounts.load_accounts()

    refresh = (status.get("refresh") or {})
    rs = refresh.get("sources") or {}
    round_bad = [k for k, v in rs.items() if v.get("status") != "ok"]
    new_round = sum(v.get("new", 0) for v in rs.values())

    sources_detail = []
    for s in sources:
        r = rs.get(s["id"]) or {}
        sources_detail.append({
            "id": s["id"], "title": s.get("title") or s["id"],
            "kind": s.get("kind", ""), "channel": s.get("channel", ""),
            "positioning": s.get("positioning", ""), "brief": s.get("brief", ""),
            "markets": s.get("markets") or [], "health": s.get("health", ""),
            "enabled": bool(s.get("enabled", True)), "ttl_min": s.get("ttl_min"),
            "ms": r.get("ms"), "round_items": r.get("items"), "round_new": r.get("new"),
            "count": per_source.get(s["id"], 0),
            "pool_accounts": xaccounts.pool_account_count(s["id"]),
        })

    store = health.get("store") or {}
    data = {
        "total": store.get("items"), "clusters": store.get("clusters"),
        "fetched": len(items), "truncated": truncated, "future_excluded": future_n,
        "span": [items[-1].get("time"), items[0].get("time")] if items else None,
        "refresh": {"round_started_at": refresh.get("round_started_at"),
                    "new": new_round, "sources_total": len(rs),
                    "sources_ok": len(rs) - len(round_bad), "bad": round_bad},
        "dead": status.get("health_dead") or [],
        "markets": count(lambda i: i.get("markets")),
        "kinds": count(lambda i: i.get("kind")),
        "channels": count(lambda i: i.get("channel")),
        "item_types": count(lambda i: i.get("item_type")),
        "positionings": count(lambda i: i.get("positioning")),
        "sectors_l1": count(lambda i: [str(s).split(">")[0] for s in (i.get("sectors") or [])]),
        "events": count(lambda i: i.get("event_type")),
        "top_sources": [[per_source_name.get(sid, sid), n, sid]
                        for sid, n in per_source.most_common(14)],
        "x_accounts": [[(x_pool.get(h) or {}).get("name") or "@" + h, n, h]
                       for h, n in x_count.most_common(10)],
        "x_pool_size": len(x_pool),
        "tickers": count(lambda i: i.get("tickers"))[:14],
        "sources": sources_detail,
    }
    _cache["at"] = time.time()
    _cache["data"] = data
    return data
