"""推荐信息打分(图文页·推荐信息子页)。

规则透明可解释(v1, 分数构成随响应返回, UI 可展开"为什么推荐"):
  dup_count×3        簇热度: 同一事件被多少个源报道(聚合去重时的 dup_count)
  官方/机构源 +2     positioning ∈ 官方/机构(2026-09-03 双标签制口径, 旧 channel 枚举废弃)
  重大事件 +2        event_type ∈ macro/policy/earnings
  情绪非中性 +1      有方向的信息更有内容价值
  标的数 ×0.5        提及具体标的更有可操作性
"""

import urllib.parse

from . import proxy

_TRUSTED_POS = {"官方", "机构"}
_BIG_EVENT = {"macro", "policy", "earnings"}


def score_of(it: dict) -> tuple[float, list]:
    parts = []
    dup = it.get("dup_count") or 1
    if dup > 1:
        parts.append((f"同事件×{dup}", dup * 3))
    if it.get("positioning") in _TRUSTED_POS:
        parts.append(("官方/机构源", 2))
    if it.get("event_type") in _BIG_EVENT:
        parts.append((f"重大事件·{it['event_type']}", 2))
    if it.get("sentiment") and it["sentiment"] != "neutral":
        parts.append(("有情绪方向", 1))
    tk = len(it.get("tickers") or [])
    if tk:
        parts.append((f"提及{tk}个标的", tk * 0.5))
    return round(sum(p[1] for p in parts), 1), parts


def recommend(since: str = "", markets: str = "", kinds: str = "",
              channels: str = "", positionings: str = "",
              item_types: str = "", limit: int = 50, sort: str = "score") -> dict:
    qs = urllib.parse.urlencode({
        "limit": min(max(limit * 4, 100), 500),   # 取足量再打分排序截 top N
        "dedup": 1, "display": 1,
        **{k: v for k, v in {"since": since, "markets": markets,
                             "kinds": kinds, "channels": channels,
                             "positionings": positionings,
                             "item_types": item_types}.items() if v},
    })
    d = proxy.fetch_json("items?" + qs)
    items = d.get("items") or []
    for it in items:
        it["score"], it["score_parts"] = score_of(it)
    if sort == "time":                            # 时间排序: 新的在前, 分数照算照显
        items.sort(key=lambda i: i.get("time") or "", reverse=True)
    else:
        items.sort(key=lambda i: (-i["score"], i.get("time") or ""))
    return {"total": len(items), "items": items[:limit], "sort": sort,
            "rule": "dup_count×3 + 官方/机构源+2 + 重大事件+2 + 情绪方向+1 + 标的×0.5"}
