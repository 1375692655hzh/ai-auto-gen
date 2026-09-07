"""内容生成·信息检索 —— 给勾选素材回查全面信息(纯只读检索, 零 LLM)。

素材(basket 条目)往往只有 200 字截断/仅标题。三路回查:
- A 锚定回原文: 素材 id(X 帖=status_id, 资讯=数据站条目 id)与数据站近窗条目
  内存精确匹配 → 补全全文/标题/簇信息(dedup=0 宽拉, 防素材本身是簇成员被滤);
- B 同事件多源: 锚条目 cluster_id 非空 → 同窗滤同簇成员, 按来源去重取 ≤5;
- C 同标的扩展: 只读加载板块一 tagger.enrich 抽 tickers/matched_terms →
  近窗条目按相关性(同簇30>同标的20>同类事件5+簇大小)排序取 ≤8, 逐条标 why。

红线7: 对板块一只读 —— 仅 proxy GET /items + importlib 加载 tagger 词典;
零写入、零 LLM、结果不落盘。/v1/items 无 id/cluster 直查参数(板块一不改动),
「一次宽拉 + 内存匹配」是既定取舍(单次素材 ≤8 条的规模下可行)。
"""

import importlib.util
import re
import sys
import time
import types
import urllib.parse
from datetime import datetime
from pathlib import Path

from . import proxy

REPO = Path(__file__).resolve().parents[2]
TAGGER_FILE = REPO / "global-news-sources" / "sources" / "tagger.py"
TAXONOMY_FILE = REPO / "global-news-sources" / "sources" / "taxonomy.py"

MAX_SEEDS = 8            # 单次检索素材上限(前端只送勾选项)
RELATED_CAP = 8          # 每素材补充条目上限(含同簇)
CLUSTER_CAP = 5          # 同簇多源上限(按来源去重)
_STATUS_RE = re.compile(r"(?:x|twitter)\.com/(\w+)/status/(\d+)")
_EMPTY_TAGS = {"tickers": [], "event_type": "", "matched_terms": []}


def _load_enrich():
    """只读加载板块一 tagger.enrich(纯规则词典)。优先常规 import(cli.py 已挂
    板块一上 sys.path); 独立进程兜底走 importlib 文件级(xaccounts 先例),
    预注册 sources 包满足 tagger._self_check 的包内 import; 都失败降级空标。"""
    try:
        from sources.tagger import enrich
        return enrich
    except Exception:
        pass
    try:
        spec_t = importlib.util.spec_from_file_location("aag_tax_ro", TAXONOMY_FILE)
        tax = importlib.util.module_from_spec(spec_t)
        spec_t.loader.exec_module(tax)
        pkg = types.ModuleType("sources")
        pkg.__path__ = []
        sys.modules.setdefault("sources", pkg)
        sys.modules["sources.taxonomy"] = tax
        spec = importlib.util.spec_from_file_location("aag_tagger_ro", TAGGER_FILE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.enrich
    except Exception:
        return None


_ENRICH = None


def _enrich(text: str) -> dict:
    global _ENRICH
    if _ENRICH is None:
        _ENRICH = _load_enrich() or (lambda t: dict(_EMPTY_TAGS))
    try:
        return _ENRICH(text or "") or dict(_EMPTY_TAGS)
    except Exception:
        return dict(_EMPTY_TAGS)


def _parse_ts(s: str):
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).timestamp()
        except Exception:
            pass
    return None


def _fmt_ts(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def _items(params: dict) -> list:
    d = proxy.fetch_json("items?" + urllib.parse.urlencode(params))
    return d.get("items") or []


def _status_id(url: str):
    m = _STATUS_RE.search(url or "")
    return m.group(2) if m else None


def _hit_view(it: dict) -> dict:
    return {"id": it.get("id"), "source": it.get("source"), "time": it.get("time"),
            "title": it.get("title") or "", "text": (it.get("text") or "")[:200],
            "url": it.get("url"), "tickers": it.get("tickers") or [],
            "dup_count": int(it.get("dup_count") or 1)}


def run(body: dict) -> dict:
    """POST /wb-api/retrieve 主体: {items:[{id,time,source,text,url}], window_h?}。"""
    seeds = [s for s in (body.get("items") or []) if isinstance(s, dict)][:MAX_SEEDS]
    if not seeds:
        return {"groups": [], "meta": {"queries": 0, "scanned": 0, "window_h": 0}}
    try:
        window_h = min(max(int(body.get("window_h") or 24), 6), 72)
    except Exception:
        window_h = 24
    now = time.time()

    tss = [t for t in (_parse_ts(s.get("time") or "") for s in seeds) if t]
    base = (min(tss) if tss else now) - window_h * 3600
    pool = _items({"since": _fmt_ts(base), "limit": 2000, "dedup": 1})   # 代表条池: A 路锚定
    pool_all = None                                                      # B 路按需: 含簇成员
    queries, groups = 1, []

    for s in seeds:
        sid_status = _status_id(s.get("url") or "")

        # ── A 锚定回原文: id / status_id 精确匹配 ──
        anchor = None
        for it in pool:
            if s.get("id") and it.get("id") == s["id"]:
                anchor = it
                break
            if sid_status and _status_id(it.get("url") or "") == sid_status:
                anchor = it
                break
        hydrated = None
        if anchor:
            hydrated = {"source": anchor.get("source"), "time": anchor.get("time"),
                        "url": anchor.get("url"), "title": anchor.get("title") or "",
                        "full": (anchor.get("text") or "")[:2000],
                        "full_src": (anchor.get("text_src") or "")[:2000],
                        "cluster_id": anchor.get("cluster_id") or "",
                        "dup_count": int(anchor.get("dup_count") or 1)}

        taken_ids = {s.get("id"), (anchor or {}).get("id")}
        # 空 url 不参与去重(部分快讯条目无 url, 否则会互相互杀)
        taken_urls = {u for u in (s.get("url"), (anchor or {}).get("url")) if u}
        cid = (hydrated or {}).get("cluster_id") or ""
        related = []

        # ── B 同事件多源: 同簇成员(dedup=0 才含成员), 按来源去重取最新 ──
        if cid and (hydrated or {}).get("dup_count", 1) > 1:
            if pool_all is None:
                a_ts = _parse_ts((anchor or {}).get("time") or "")
                pool_all = _items({"since": _fmt_ts((a_ts or base) - 12 * 3600),
                                   "limit": 500, "dedup": 0})
                queries += 1
            seen_src = set()
            for it in sorted(pool_all, key=lambda x: x.get("time") or "", reverse=True):
                if it.get("cluster_id") != cid or it.get("id") in taken_ids \
                        or (it.get("url") and it.get("url") in taken_urls) \
                        or not it.get("source") or it["source"] in seen_src:
                    continue
                h = _hit_view(it)
                h["why"] = ["同事件×" + str(h["dup_count"])] if h["dup_count"] > 1 else ["同事件"]
                related.append(h)
                taken_ids.add(it.get("id"))
                if it.get("url"):
                    taken_urls.add(it.get("url"))
                if len(related) >= CLUSTER_CAP:
                    break

        # ── C 同标的/关键词近窗扩展(锚定命中优先继承全文打标: 素材常是截断文本) ──
        tags = _enrich((s.get("title") or "") + " " + (s.get("text") or ""))
        if anchor:
            tags = {"tickers": anchor.get("tickers") or tags["tickers"],
                    "event_type": anchor.get("event_type") or tags["event_type"],
                    "matched_terms": anchor.get("matched_terms") or tags["matched_terms"]}
        hint = ""
        if tags["tickers"] or tags["matched_terms"]:
            ts0 = _parse_ts(s.get("time") or "")
            seed_since = _fmt_ts((ts0 or now) - 24 * 3600)
            if tags["tickers"]:
                kw = ""
                hits = _items({"tickers": ",".join(tags["tickers"]),
                               "since": seed_since, "limit": 100, "dedup": 1})
            else:
                kw = tags["matched_terms"][0]
                hits = _items({"q": kw, "since": seed_since, "limit": 50, "dedup": 1})
            queries += 1
            cand = []
            for it in hits:
                if it.get("id") in taken_ids \
                        or (it.get("url") and it.get("url") in taken_urls):
                    continue
                inter = set(it.get("tickers") or []) & set(tags["tickers"])
                in_cluster = bool(cid) and it.get("cluster_id") == cid
                if tags["tickers"] and not inter and not in_cluster:
                    continue                     # 有标的时丢弃无交集条目防噪
                same_evt = bool(tags["event_type"]) \
                    and it.get("event_type") == tags["event_type"]
                score = (30 if in_cluster else 0) + (20 if inter else 0) \
                    + (5 if same_evt else 0) + min(int(it.get("dup_count") or 1), 5)
                why = []
                if in_cluster:
                    why.append("同事件")
                if inter:
                    why.append("同标的 " + "+".join(sorted(inter)[:3]))
                elif not tags["tickers"] and kw:
                    why.append("关键词 " + kw)
                cand.append((score, it.get("time") or "", why, it))
            cand.sort(key=lambda x: (x[0], x[1]), reverse=True)
            for _, _, why, it in cand:
                if len(related) >= RELATED_CAP:
                    break
                h = _hit_view(it)
                h["why"] = why
                related.append(h)

        if not hydrated and not related:
            hint = ("手抄素材无链接, 按关键词也未检到" if not s.get("url")
                    else "窗口内未检到补充信息(素材可能超出保留窗: 快讯48h/文章7d)")
            if not tags["tickers"] and not tags["matched_terms"]:
                hint = "未识别到标的/关键词, 无法扩展检索"

        groups.append({"seed_id": s.get("id"), "hydrated": hydrated,
                       "related": related, "hint": hint,
                       "tags": {"tickers": tags["tickers"],
                                "event_type": tags["event_type"]}})

    return {"groups": groups,
            "meta": {"queries": queries, "scanned": len(pool), "window_h": window_h}}
