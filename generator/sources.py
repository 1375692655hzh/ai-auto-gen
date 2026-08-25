"""信息源抓取层:早报与分析文章的素材来源。

统一条目格式: {"time": "2026-08-26 09:30", "text": "...", "source": "sina7x24"}
单个来源挂了不影响其他来源(返回能拿到的部分)。
"""

import re
import time
import html

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s or "")
    return html.unescape(s).strip()


def fetch_sina_724(page_size: int = 100) -> list:
    """新浪财经 7×24 直播快讯。"""
    r = requests.get(
        "https://zhibo.sina.com.cn/api/zhibo/feed",
        params={"page": 1, "page_size": page_size, "zhibo_id": 152},
        headers={"User-Agent": UA, "Referer": "https://finance.sina.com.cn/"},
        timeout=15,
    )
    r.raise_for_status()
    items = (r.json().get("result") or {}).get("data") or {}
    feed = (items.get("feed") or {}).get("list") or []
    out = []
    for it in feed:
        text = _strip_html(it.get("rich_text", ""))
        t = (it.get("create_time") or "").strip()[:16]
        if text:
            out.append({"time": t, "text": text, "source": "新浪7×24"})
    return out


def fetch_eastmoney_fast(page_size: int = 50) -> list:
    """东方财富财经快讯(焦点栏目)。"""
    r = requests.get(
        "https://np-listapi.eastmoney.com/comm/web/getFastNewsList",
        params={"client": "web", "biz": "web_724", "fastColumn": "102",
                "sortEnd": "", "pageSize": page_size, "req_trace": int(time.time() * 1000)},
        headers={"User-Agent": UA, "Referer": "https://kuaixun.eastmoney.com/"},
        timeout=15,
    )
    r.raise_for_status()
    out = []
    for it in (r.json().get("data") or {}).get("fastNewsList") or []:
        title = (it.get("title") or "").strip()
        summary = (it.get("summary") or "").strip()
        text = f"{title}:{summary}" if title and summary else (title or summary)
        t = (it.get("showTime") or "").strip()[:16]
        if text:
            out.append({"time": t, "text": text, "source": "东财快讯"})
    return out


FETCHERS = {
    "sina_7x24": fetch_sina_724,
    "eastmoney_fast": fetch_eastmoney_fast,
}


def gather(cfg: dict | None = None, limit: int = 0) -> tuple:
    """按配置抓所有启用的来源,去重、按时间倒序。返回 (条目列表, 挂掉的来源)。"""
    if cfg is None:
        from common import load_cfg
        cfg = load_cfg().get("sources", {})
    items, failed = [], []
    for key, fn in FETCHERS.items():
        conf = cfg.get(key) or {}
        if not conf.get("enabled", False):
            continue
        try:
            got = fn(int(conf.get("page_size", 50)))
            if got:
                items.extend(got)
            else:
                failed.append(f"{key}(空结果)")
        except Exception as e:
            failed.append(f"{key}({type(e).__name__}: {str(e)[:80]})")
    # 去重:正文相同取时间新的
    seen, deduped = set(), []
    for it in sorted(items, key=lambda x: x["time"], reverse=True):
        k = re.sub(r"\s", "", it["text"])[:60]
        if k in seen:
            continue
        seen.add(k)
        deduped.append(it)
    if limit and len(deduped) > limit:
        deduped = deduped[:limit]
    return deduped, failed


def render_items(items: list) -> str:
    """把条目渲染成给模型看的清单。"""
    return "\n".join(f"[{it['time']}]({it['source']}) {it['text']}" for it in items)
