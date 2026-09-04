"""统计聚合(资讯页右栏 + 来源详情子页的数据供给)。

学同事看板(aag-看板/信源工作台.html)的思路, 但聚合放在服务端:
拉取 /v1/items(单页 1000, 页数不设限, 按时间倒序在窗口下界提前收工) + /v1/sources + /v1/status,
条目类统计只计**近 24h**、赛道模块只计**近 48h**(2026-09-04 拍板), 服务端聚合好直接给前端成品,
浏览器不用搬几千条数据。60s 进程内缓存, 避免每次切页都重拉。
"""

import time
import urllib.parse
from collections import Counter

from . import proxy, xaccounts

_cache = {"at": 0.0, "data": None}
_CACHE_TTL = 60.0
_PAGE = 1000                         # store.query 单页硬顶 1000, 页数不设限
_MAX_PAGES = 500                     # 跑飞保护(=50万条), 不是数据上限: 正常靠窗口截停/翻尽游标
_WINDOW_HOURS = 24                   # 右栏条目统计口径: 只计近 24h
_SECTORS_WINDOW_HOURS = 48           # 赛道模块(筛选模块2)口径: 只计近 48h


def _fmt(dt_epoch: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(dt_epoch))


def _fetch_items(cutoff: str) -> tuple[list, bool]:
    items, cursor = [], ""
    for _ in range(_MAX_PAGES):
        qs = f"items?limit={_PAGE}&dedup=1&display=1"
        if cursor:                       # cursor 形如 "2026-09-01 21:49|<hash>", 含空格须转义
            qs += "&cursor=" + urllib.parse.quote(cursor, safe="")
        d = proxy.fetch_json(qs)
        page = d.get("items") or []
        items.extend(page)
        cursor = d.get("next_cursor") or ""
        if not cursor:
            return items, False
        # store 按时间倒序分页: 整页都早于 24h 下界, 后续页必然更早, 提前收工(不算截断)
        if page and (page[-1].get("time") or "") < cutoff:
            return items, False
    return items, True                  # 仅跑飞保护触发: 视为截断


def aggregate() -> dict:
    if _cache["data"] and time.time() - _cache["at"] < _CACHE_TTL:
        return _cache["data"]

    health = proxy.fetch_json("health")
    status = proxy.fetch_json("status")
    sources = proxy.fetch_json("sources").get("sources") or []

    now = _fmt(time.time())
    # 双窗口: 右栏条目统计=24h, 赛道模块=48h(2026-09-04 拍板)。串比较=时间比较(同格式)。
    cutoff = _fmt(time.time() - _WINDOW_HOURS * 3600)
    cutoff_48 = _fmt(time.time() - _SECTORS_WINDOW_HOURS * 3600)
    raw_items, truncated = _fetch_items(cutoff_48)      # 翻页到 48h 下界即提前收工

    # 预测市场类源会把结算日(数年后)写进 time, 聚合前剔除(看板同款处理);
    # 48h 窗口内再切出 24h 子集供条目类统计
    items_48 = [i for i in raw_items if cutoff_48 <= (i.get("time") or "") <= now]
    future_n = len(raw_items) - len([i for i in raw_items if (i.get("time") or "") <= now])
    items = [i for i in items_48 if (i.get("time") or "") >= cutoff]
    out_of_window = len(items_48) - len(items)

    def count(fn, pool=None):
        c = Counter()
        for i in (pool if pool is not None else items):
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
        "window": "24h", "since": cutoff,
        "sectors_window": "48h", "sectors_since": cutoff_48, "sectors_fetched": len(items_48),
        "fetched": len(items), "truncated": truncated, "future_excluded": future_n,
        "out_of_window": out_of_window,
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
        "sectors_48h": count(lambda i: [str(s).split(">")[0] for s in (i.get("sectors") or [])],
                             pool=items_48),
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


def invalidate() -> None:
    """来源启停等写动作后调: 60s 缓存立即作废, 下次聚合拿到新注册表状态。"""
    _cache["at"] = 0.0
    _cache["data"] = None
