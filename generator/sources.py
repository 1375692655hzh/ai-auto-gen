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


def _rss_title_flash(url: str, source: str, page_size: int, referer: str) -> list:
    """英文快讯 RSS 通用解析: CDATA 标题 + RFC822 GMT pubDate → 北京时间。"""
    r = requests.get(url, headers={"User-Agent": UA, "Referer": referer}, timeout=15)
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
            out.append({"time": bj, "text": title, "source": source})
    return out[:int(page_size)]


def fetch_fxstreet_flash(page_size: int = 30) -> list:
    """FXStreet 外汇/央行快讯(英文, 周末停更——周六早班恰抓完整周五美盘)。
    资产类别源(用户 2026-08-30 许可)。注意: 2026-08-30 起本站出口 IP 被 Cloudflare 整站 403, 源默认禁用待恢复。"""
    return _rss_title_flash("https://www.fxstreet.com/rss/news", "FXStreet", page_size,
                            "https://www.fxstreet.com/")


def fetch_investinglive_flash(page_size: int = 30) -> list:
    """investingLive 外汇/美股/宏观快讯(英文, 原 ForexLive, 周末停更)。
    资产类别源(用户 2026-08-30 许可外汇类): FXStreet 被 403 后的同赛道顶替, 三家交叉轮已验证该站。"""
    return _rss_title_flash("https://www.investinglive.com/feed/", "investingLive", page_size,
                            "https://www.investinglive.com/")


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


# ---------- 备用源(public-apis 名录收录 2026-08-30; 全部默认禁用, 主源失效时顶班) ----------
# 启用方式: 需 key 的把 key 写进 autopub/secret.local.json(或同名大写环境变量),
# 再把 sources/builtin.py 对应注册的 default_enabled 改 True。

_BJ = datetime.timezone(datetime.timedelta(hours=8))


def _secret(key: str) -> str:
    """备用源 API key: 同名大写环境变量优先, 否则 autopub/secret.local.json 对应字段。"""
    import json
    import os
    from pathlib import Path
    if os.environ.get(key.upper()):
        return os.environ[key.upper()]
    p = Path(__file__).resolve().parent.parent / "autopub" / "secret.local.json"
    if p.exists():
        try:
            return str(json.loads(p.read_text(encoding="utf-8")).get(key, "") or "")
        except Exception:
            pass
    return ""


def fetch_marketaux_news(page_size: int = 30) -> list:
    """MarketAux 美股市场新闻(备用): 标题+关联 ticker 标注。免费档约 100 次/天。
    key: MARKETAUX_API_KEY 或 secret.local.json 的 marketaux_api_key。"""
    key = _secret("marketaux_api_key")
    if not key:
        raise RuntimeError("marketaux_api_key 未配置(secret.local.json 或 MARKETAUX_API_KEY)")
    r = requests.get("https://api.marketaux.com/v1/news/all",
                     params={"api_token": key, "language": "en",
                             "limit": min(int(page_size), 50), "must_have_entities": "true"},
                     headers={"User-Agent": UA}, timeout=15)
    r.raise_for_status()
    out = []
    for it in (r.json().get("data") or []):
        title = (it.get("title") or "").strip()
        if not title:
            continue
        t = ""
        pub = (it.get("published_at") or "")[:19]              # ISO8601 UTC
        if pub:
            try:
                t = (datetime.datetime.strptime(pub, "%Y-%m-%dT%H:%M:%S")
                     + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
            except ValueError:
                pass
        ticks = ",".join(e["symbol"] for e in (it.get("entities") or []) if e.get("symbol"))
        out.append({"time": t, "text": title + (f" [{ticks}]" if ticks else ""),
                    "source": "MarketAux"})
    return out


def fetch_finnhub_news(page_size: int = 30) -> list:
    """Finnhub 美股市场新闻(备用): general 类市场 headline 流。免费档 60 次/分钟。
    key: FINNHUB_API_KEY 或 secret.local.json 的 finnhub_api_key。"""
    key = _secret("finnhub_api_key")
    if not key:
        raise RuntimeError("finnhub_api_key 未配置(secret.local.json 或 FINNHUB_API_KEY)")
    r = requests.get("https://finnhub.io/api/v1/news",
                     params={"category": "general", "token": key},
                     headers={"User-Agent": UA}, timeout=15)
    r.raise_for_status()
    out = []
    for it in (r.json() or [])[:int(page_size)]:
        title = (it.get("headline") or "").strip()
        ts = it.get("datetime") or 0                            # Unix 秒
        t = datetime.datetime.fromtimestamp(int(ts), _BJ).strftime("%Y-%m-%d %H:%M") if ts else ""
        if title:
            out.append({"time": t, "text": title, "source": "Finnhub"})
    return out


def fetch_alphavantage_news(page_size: int = 30) -> list:
    """Alpha Vantage 美股新闻+情绪标签(备用): NEWS_SENTIMENT feed。
    免费档仅 25 次/天, 只适合应急顶班。key: ALPHAVANTAGE_API_KEY 或 secret.local.json。"""
    key = _secret("alphavantage_api_key")
    if not key:
        raise RuntimeError("alphavantage_api_key 未配置(secret.local.json 或 ALPHAVANTAGE_API_KEY)")
    r = requests.get("https://www.alphavantage.co/query",
                     params={"function": "NEWS_SENTIMENT", "sort": "LATEST",
                             "limit": min(int(page_size), 50), "apikey": key},
                     headers={"User-Agent": UA}, timeout=20)
    r.raise_for_status()
    out = []
    for it in (r.json().get("feed") or []):
        title = (it.get("title") or "").strip()
        if not title:
            continue
        t = ""
        pub = (it.get("time_published") or "")                 # 20260830T123000 (UTC)
        if re.match(r"\d{8}T\d{6}", pub):
            t = (datetime.datetime.strptime(pub, "%Y%m%dT%H%M%S")
                 + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
        senti = it.get("overall_sentiment_label") or ""
        out.append({"time": t, "text": title + (f" ({senti})" if senti else ""),
                    "source": "AlphaVantage"})
    return out


def fetch_sec_edgar_filings(page_size: int = 30, form_type: str = "8-K") -> list:
    """SEC EDGAR 最新申报(备用, 美股公告): 默认 8-K 重大事件, Atom feed 含公司名/表单/时刻。
    官方免费; SEC 政策要求申报式 UA(代码内已带); 限速 10 次/秒。美股公告唯一官方源。"""
    r = requests.get("https://www.sec.gov/cgi-bin/browse-edgar",
                     params={"action": "getcurrent", "type": form_type, "dateb": "",
                             "owner": "include", "count": int(page_size), "output": "atom"},
                     headers={"User-Agent": "ai-auto-gen research contact@example.com"},
                     timeout=15)
    r.raise_for_status()
    out = []
    for e in re.findall(r"<entry>(.*?)</entry>", r.text, re.S):
        ti = re.search(r"<title>(.*?)</title>", e, re.S)
        up = re.search(r"<updated>(.*?)</updated>", e, re.S)
        title = html.unescape(re.sub(r"\s+", " ", ti.group(1)).strip()) if ti else ""
        t = ""
        if up:
            try:
                t = (datetime.datetime.fromisoformat(up.group(1).strip())
                     .astimezone(_BJ).strftime("%Y-%m-%d %H:%M"))
            except ValueError:
                pass
        if title:
            out.append({"time": t, "text": title, "source": "SEC EDGAR"})
    return out[:int(page_size)]


def fetch_frankfurter_fx() -> list:
    """Frankfurter 汇率快照(备用): ECB 参考汇率, USD 基准 → CNY/HKD/JPY/KRW/TRY/EUR。
    免费无 key; 每交易日一更(欧洲下午, 约北京 23 点), 周末无新值; ECB 口径不含 TWD。"""
    r = requests.get("https://api.frankfurter.dev/v1/latest",
                     params={"base": "USD", "symbols": "CNY,HKD,JPY,KRW,TRY,EUR"}, timeout=15)
    r.raise_for_status()
    d = r.json()
    rates = d.get("rates") or {}
    if not rates:
        return []
    body = " | ".join(f"{k} {v}" for k, v in rates.items())
    now = datetime.datetime.now(_BJ).strftime("%Y-%m-%d %H:%M")
    return [{"time": now, "text": f"USD 基准汇率(ECB 参考, 数据日期 {d.get('date')}): {body}",
             "source": "Frankfurter"}]


def fetch_goldprice_metals() -> list:
    """goldprice.dev 金价快照(备用): XAU 现货折算 24K~10K 每克金价(31 币种, 默认 USD)。
    免费无 key。注意: 名录描述含银/铜, 但免费公开端点只有黄金。"""
    r = requests.get("https://api.goldprice.dev/v1/carat", params={"currency": "USD"}, timeout=15)
    r.raise_for_status()
    d = r.json()
    p24 = d.get("price_gram_24k")
    if not p24:
        return []
    oz = round(float(p24) * 31.1034768, 2)
    text = (f"金价 USD: 现货约 {oz}/盎司 | 每克 24K {p24} / 22K {d.get('price_gram_22k')}"
            f" / 18K {d.get('price_gram_18k')}")
    return [{"time": datetime.datetime.now(_BJ).strftime("%Y-%m-%d %H:%M"),
             "text": text, "source": "goldprice.dev"}]


_FRED_SERIES = (("CPIAUCSL", "CPI指数"), ("UNRATE", "失业率%"),
                ("FEDFUNDS", "联邦基金利率%"), ("DGS10", "10Y国债收益率%"))


def fetch_fred_macro() -> list:
    """FRED 美联储宏观数据(备用): CPI/失业率/联邦基金利率/10Y国债 最新观测值快照。
    key 免费申请即得: FRED_API_KEY 或 secret.local.json 的 fred_api_key。"""
    key = _secret("fred_api_key")
    if not key:
        raise RuntimeError("fred_api_key 未配置(secret.local.json 或 FRED_API_KEY)")
    out = []
    for sid, name in _FRED_SERIES:
        r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                         params={"series_id": sid, "api_key": key, "file_type": "json",
                                 "sort_order": "desc", "limit": 1},
                         headers={"User-Agent": UA}, timeout=15)
        r.raise_for_status()
        obs = [o for o in (r.json().get("observations") or []) if o.get("value") not in (None, ".")]
        if obs:
            out.append({"time": obs[0].get("date", ""),
                        "text": f"{name}({sid}) 最新值 {obs[0]['value']}", "source": "FRED"})
    return out
