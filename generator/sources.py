"""信息源抓取层:早报与分析文章的素材来源。

统一条目格式: {"time": "2026-08-26 09:30", "text": "...", "source": "sina7x24"}
单个来源挂了不影响其他来源(返回能拿到的部分)。
"""

import re
import time
import html
import datetime

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


def fetch_jin10_flash(page_size: int = 50) -> list:
    """金十数据快讯(中文全球, 400-700条/天, 时间精确到秒)。"""
    import json
    r = requests.get(
        "https://www.jin10.com/flash_newest.js",
        headers={"User-Agent": UA, "Referer": "https://www.jin10.com/"},
        timeout=15,
    )
    r.raise_for_status()
    m = re.search(r"var newest\s*=\s*(\[.*\])\s*;?\s*$", r.text.strip(), re.S)
    arr = json.loads(m.group(1)) if m else []
    out = []
    for it in arr[:int(page_size)]:
        text = _strip_html(((it.get("data") or {}).get("content") or ""))
        t = (it.get("time") or "").strip()[:16]
        if text and t:
            out.append({"time": t, "text": text, "source": "金十数据"})
    return out


def fetch_fxstreet_flash(page_size: int = 30) -> list:
    """FXStreet 外汇/央行快讯(英文, 秒级 GMT 时间戳, 周末停更——周六早班恰抓完整周五美盘)。"""
    import json
    r = requests.get("https://www.fxstreet.com/rss/news",
                     headers={"User-Agent": UA, "Referer": "https://www.fxstreet.com/"},
                     timeout=15)
    r.raise_for_status()
    out = []
    for it in re.findall(r"<item>(.*?)</item>", r.text, re.S):
        def tag(t, s=it):
            m = re.search(rf"<{t}>(.*?)(?:</{t}>|</item>)", s, re.S)
            return re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", m.group(1), flags=re.S) if m else ""
        title = _strip_html(tag("title"))
        pub = tag("pubDate").strip()
        try:
            dt = datetime.datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %Z")
        except ValueError:
            continue
        bj = (dt + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
        if title:
            out.append({"time": bj, "text": title, "source": "FXStreet"})
    return out[:int(page_size)]


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


# ---------- 同行早报文章(参考价值高于纯快讯) ----------

def _em_search_articles(keyword: str, page_size: int = 5) -> list:
    """东方财富站内搜索:拿同行早报文章(新华财经《财经早知道》等),content 即正文摘要。"""
    import json as _json
    param = _json.dumps({
        "uid": "", "keyword": keyword, "type": ["cmsArticleWebOld"],
        "client": "web", "clientType": "web", "clientVersion": "curr",
        "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default",
                                       "pageIndex": 1, "pageSize": page_size,
                                       "preTag": "", "postTag": ""}},
    }, ensure_ascii=False, separators=(",", ":"))
    r = requests.get(
        "https://search-api-web.eastmoney.com/search/jsonp",
        params={"cb": "cb", "param": param},
        headers={"User-Agent": UA, "Referer": "https://so.eastmoney.com/"},
        timeout=15,
    )
    r.raise_for_status()
    body = re.sub(r"^cb\(|\)$", "", r.text.strip())
    arts = (((_json.loads(body).get("result") or {}).get("cmsArticleWebOld")) or [])
    return [{
        "time": (a.get("date") or "")[:16],
        "title": _strip_html(a.get("title", "")),
        "text": _strip_html(a.get("content", "")),
        "media": a.get("mediaName", ""),
        "url": a.get("url", ""),
    } for a in arts if a.get("title") and a.get("date", "").startswith(str(datetime.date.today().year))]


def _fetch_em_article_body(url: str, cap: int = 12000) -> str:
    """抓东财文章页全文:定位 id=ContentBody,截到常见结束标记,去 HTML。"""
    url = url.replace("http://", "https://")
    r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
    r.raise_for_status()
    h = r.text
    i = h.find('id="ContentBody"')
    if i < 0:
        return ""
    seg = h[i:i + cap]
    for end in ("免责声明", "责编", "返回东方财富首页", 'class="res-edit"'):
        j = seg.find(end)
        if j > 0:
            seg = seg[:j]
    return _strip_html(seg)[:4000]


def fetch_eastmoney_zaozhidao(keywords: list | None = None) -> list:
    """按关键词搜同行早报文章,只保留近 36 小时内的,正文补抓全文。"""
    if not keywords:
        keywords = ["早知道", "财经早知道"]
    cutoff = datetime.datetime.now() - datetime.timedelta(hours=36)
    out, seen = [], set()
    for kw in keywords:
        try:
            arts = _em_search_articles(kw)
        except Exception:
            continue  # 单个关键词失败不影响其他
        for a in arts:
            key = a["title"][:20]
            if key in seen:
                continue
            seen.add(key)
            try:
                when = datetime.datetime.strptime(a["time"], "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            if when < cutoff:
                continue
            a["source"] = f"东财·{a.get('media') or kw}"
            # 摘要太短,补抓全文;抓不到就退回摘要
            if a["url"] and len(a["text"]) < 400:
                try:
                    full = _fetch_em_article_body(a["url"])
                    if len(full) > len(a["text"]):
                        a["text"] = full
                except Exception:
                    pass
            out.append(a)
    return out


def fetch_wscn_breakfast(limit: int = 2) -> list:
    """华尔街见闻「早餐FM-Radio」系列文章(搜索接口只有摘要, 正文用内容 API 补抓)。"""
    import datetime as _dt
    r = requests.get(
        "https://api-one-wscn.awtmt.com/apiv1/search/article",
        params={"query": "早餐", "limit": limit * 3, "cursor": ""},
        headers={"User-Agent": UA},
        timeout=15,
    )
    r.raise_for_status()
    out = []
    cutoff = _dt.datetime.now() - _dt.timedelta(hours=36)
    for it in (r.json().get("data") or {}).get("items") or []:
        title = _strip_html(it.get("title", ""))
        if not title or ("早餐" not in title and "早报" not in title):
            continue
        if it.get("is_paid"):
            continue
        ts = it.get("display_time") or 0
        if ts and _dt.datetime.fromtimestamp(ts) < cutoff:
            continue
        uri = (it.get("uri") or "").split("?")[0]
        out.append({
            "time": _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "",
            "title": title,
            "text": _wscn_full_text(uri) or _strip_html(it.get("content", "")),
            "media": "华尔街见闻",
            "url": uri,
            "source": "华尔街见闻",
        })
        if len(out) >= limit:
            break
    return out


def _wscn_full_text(uri: str) -> str:
    """wscn 内容 API 抓全文: /articles/<id> → apiv1/content/articles/<id>。"""
    m = re.search(r"/articles/(\d+)", uri or "")
    if not m:
        return ""
    try:
        r = requests.get(f"https://api-one-wscn.awtmt.com/apiv1/content/articles/{m.group(1)}",
                         params={"extract": 0},
                         headers={"User-Agent": UA, "Referer": "https://wallstreetcn.com/"},
                         timeout=15)
        r.raise_for_status()
        content = ((r.json().get("data") or {}).get("content")) or ""
        text = html.unescape(re.sub(r"<[^>]+>", "\n", content))
        return re.sub(r"\n\s*\n+", "\n", text).strip()
    except Exception:
        return ""


REF_FETCHERS = {
    "eastmoney_zaozhidao": lambda conf: fetch_eastmoney_zaozhidao(conf.get("keywords")),
    "wscn_breakfast": lambda conf: fetch_wscn_breakfast(int(conf.get("count", 2))),
}


def gather_refs(cfg: dict | None = None) -> tuple:
    """抓同行早报文章,按时间倒序。返回 (文章列表, 挂掉的来源)。"""
    if cfg is None:
        from common import load_cfg
        cfg = load_cfg().get("sources", {})
    refs, failed = [], []
    for key, fn in REF_FETCHERS.items():
        conf = cfg.get(key) or {}
        if not conf.get("enabled", False):
            continue
        try:
            got = fn(conf)
            refs.extend(got) if got else failed.append(f"{key}(空结果)")
        except Exception as e:
            failed.append(f"{key}({type(e).__name__}: {str(e)[:60]})")
    refs.sort(key=lambda x: x["time"], reverse=True)
    return refs, failed


def render_refs(refs: list) -> str:
    """同行早报渲染成给模型看的参考材料。"""
    parts = []
    for r in refs:
        parts.append(f"《{r['title']}》({r['media']} {r['time']})\n{r['text']}")
    return "\n\n".join(parts)


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
