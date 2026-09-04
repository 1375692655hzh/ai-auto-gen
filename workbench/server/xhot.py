"""X 热帖榜(图文页·推荐信息右栏)。

为什么不是真流量排序: FxTwitter 抓取层只取正文, 没存 engagement 字段
(2026-09-04 盘点: store._COLS 无 likes/retweets/replies; sopilot 式"流量增速"
还需要时序快照, 更无从谈起)。本期热度分用库内可得信号:
  heat = dup_count × 3        同事件被多少源/账号报道(簇热度, 跨账号真传播信号)
       + 粉丝量级分            ≥100万+5 / ≥10万+3 / ≥1万+1(账号分量, 来自
                               data/workbench/x_profiles.json grok x-search 缓存)
粉丝缓存缺失的账号按 0 档计, 不阻塞出榜。
真流量版要做的话是板块一的活: fetchers/basic.py twitter_kol 解析 fxtwitter JSON
时把 favorites/retweets 存进 store, 再改这里读真实字段。
"""

import time
import urllib.parse

from . import proxy, x_profile_enricher

_WINDOWS = {"24h": 86400, "48h": 172800}


def _since_str(hours_sec: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - hours_sec))


def _follower_tier(n: int) -> int:
    if n >= 1_000_000:
        return 5
    if n >= 100_000:
        return 3
    if n >= 10_000:
        return 1
    return 0


def hot(range_: str = "24h", markets: str = "", limit: int = 12) -> dict:
    sec = _WINDOWS.get(range_, _WINDOWS["24h"])
    # since 含空格, 必须 urlencode(手拼串曾报 InvalidURL 502)
    qs = {"limit": 300, "dedup": 1, "display": 1, "since": _since_str(sec)}
    if markets:
        qs["markets"] = markets
    items = proxy.fetch_json("items?" + urllib.parse.urlencode(qs)).get("items") or []

    profiles = x_profile_enricher.load_cache()["profiles"]
    rows = []
    for it in items:
        h = str(it.get("author_handle") or "").lower()
        if not h:                                   # 非 X 池条目不掺和
            continue
        prof = profiles.get(h) or {}
        fol = int(prof.get("followers") or 0)
        dup = it.get("dup_count") or 1
        heat = round(dup * 3 + _follower_tier(fol), 1)
        rows.append({
            "id": it.get("id"), "time": it.get("time"), "url": it.get("url"),
            "handle": h, "name": it.get("source") or "@" + h,
            "followers": fol, "dup_count": dup, "heat": heat,
            "markets": it.get("markets") or [],
            "text": (it.get("text_display") or it.get("text") or "")[:160],
        })
    rows.sort(key=lambda r: (-r["heat"], r["time"] or ""))
    # 每账号限 2 条: 大粉丝媒体号(如 nikkei 391万粉)不加限会霸榜, 热帖榜要的是多样性
    picked, per_handle = [], {}
    for r in rows:
        if per_handle.get(r["handle"], 0) >= 2:
            continue
        per_handle[r["handle"]] = per_handle.get(r["handle"], 0) + 1
        picked.append(r)
        if len(picked) >= limit:
            break
    return {"items": picked, "range": range_,
            "rule": "同事件×3 + 粉丝量级(≥100万+5/≥10万+3/≥1万+1), 每账号限2条"}
