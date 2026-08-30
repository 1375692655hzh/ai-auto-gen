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


# ---------- 扩展源(2026-08-30 晚: a-stock-data/global-stock-data 目录项目移植 + 前两轮遗漏补收) ----------
# 收录标准(用户定): 在范围内市场(美/A/港/日/韩/台/土/外汇/大宗) + 能给内容, 即收。

import hashlib as _hashlib
import uuid as _uuid


def fetch_cls_telegraph(page_size: int = 50) -> list:
    """财联社电报(A股最快全市场快讯): v1 API + 本地签名零 key(2026-07 复活, 08-30 实测 errno=0)。
    与财联社专栏早报不同源面; 与东财全球资讯互备(不同风控面)。"""
    params = {"appName": "CailianpressWeb", "os": "web", "sv": "7.7.5",
              "last_time": "", "refresh_type": "1", "rn": str(int(page_size))}
    qs = "&".join(f"{k}={params[k]}" for k in sorted(params))
    sign = _hashlib.md5(_hashlib.sha1(qs.encode()).hexdigest().encode()).hexdigest()
    r = requests.get(f"https://www.cls.cn/v1/roll/get_roll_list?{qs}&sign={sign}",
                     headers={"User-Agent": UA, "Referer": "https://www.cls.cn/"}, timeout=10)
    r.raise_for_status()
    d = r.json()
    out = []
    for it in (d.get("data") or {}).get("roll_data") or []:
        text = _strip_html(it.get("title") or it.get("content") or it.get("brief") or "")[:200]
        ts = it.get("ctime")
        t = datetime.datetime.fromtimestamp(int(ts), _BJ).strftime("%Y-%m-%d %H:%M") if ts else ""
        if text and t:
            out.append({"time": t, "text": text, "source": "财联社电报"})
    return out


def fetch_eastmoney_global(page_size: int = 50) -> list:
    """东财全球财经资讯(7×24 滚动): np-weblist 直连零鉴权。与财联社电报互备。"""
    r = requests.get("https://np-weblist.eastmoney.com/comm/web/getFastNewsList",
                     params={"client": "web", "biz": "web_724", "fastColumn": "102",
                             "sortEnd": "", "pageSize": str(int(page_size)),
                             "req_trace": str(_uuid.uuid4())},
                     headers={"User-Agent": UA, "Referer": "https://kuaixun.eastmoney.com/"},
                     timeout=10)
    r.raise_for_status()
    d = r.json()
    out = []
    for it in (d.get("data") or {}).get("fastNewsList") or []:
        title = (it.get("title") or "").strip()
        summ = _strip_html(it.get("summary") or "")[:120]
        t = (it.get("showTime") or "").strip()[:16]
        text = title + (f" {summ}" if summ and summ not in title else "")
        if text.strip() and t:
            out.append({"time": t, "text": text.strip(), "source": "东财全球资讯"})
    return out


def fetch_cninfo_latest(page_size: int = 30) -> list:
    """巨潮资讯全市场最新公告(沪深北, 官方全量): 公告标题+类型+时刻。财联社公告是编辑筛选版, 这是官方全量。"""
    r = requests.post("https://www.cninfo.com.cn/new/hisAnnouncement/query",
                      data={"tabName": "fulltext", "pageSize": str(int(page_size)), "pageNum": "1",
                            "column": "", "category": "", "plate": "", "seDate": "",
                            "searchkey": "", "secid": "", "sortName": "", "sortType": "",
                            "isHLtitle": "true"},
                      headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded",
                               "Referer": "https://www.cninfo.com.cn/new/disclosure",
                               "Origin": "https://www.cninfo.com.cn"}, timeout=15)
    r.raise_for_status()
    out = []
    for it in (r.json().get("announcements") or []):
        title = re.sub(r"<[^>]+>", "", it.get("announcementTitle") or "").strip()
        ts = it.get("announcementTime")                      # 毫秒时间戳
        t = (datetime.datetime.fromtimestamp(int(ts) / 1000, _BJ).strftime("%Y-%m-%d %H:%M")
             if ts else "")
        typ = it.get("announcementTypeName") or ""
        name = it.get("secName") or ""
        if title:
            out.append({"time": t, "text": f"{name}: {title}" + (f" [{typ}]" if typ else ""),
                        "source": "巨潮资讯"})
    return out


_NBS_INDEX = "https://www.stats.gov.cn/sj/zxfb/"


def _macro_text(url: str, timeout: int = 30) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def fetch_nbs_pmi() -> list:
    """国家统计局 PMI(月度, 月末发布): 制造业/非制造业/综合 + 大中小型企业分档。官方零鉴权。
    主指标解析失败=统计局措辞改版, fail-fast 报错不静默(移植自 a-stock-data §11.2)。
    发现层: 首页只放最近两周发布, 月频 PMI 会滚出首页(2026-08-30 实测), 逐页翻 index_N.html 兜底。"""
    from urllib.parse import urljoin
    hit = None
    for page in ("", "index_1.html", "index_2.html", "index_3.html"):
        idx = _macro_text(urljoin(_NBS_INDEX, page))
        links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>\s*([^<]{6,80}?)\s*</a>', idx)
        hit = next(((u, t) for u, t in links if "采购经理指数" in t), None)
        if hit:
            break
    if not hit:
        raise RuntimeError("国家统计局最新发布前 4 页均未找到「采购经理指数」条目")
    href, title = hit
    url = urljoin(_NBS_INDEX, href)
    text = _macro_text(url)
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", text, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[\s　 ]+", "", text)      # 全角括号内带空格, 空白必须整个删掉

    def grab(pat):
        m = re.search(pat, text)
        return m.group(1) if m else None

    ym = re.search(r"(\d{4})年(\d{1,2})月", title)
    period = f"{ym.group(1)}-{int(ym.group(2)):02d}" if ym else ""
    manu = grab(r"(?<!非)制造业采购经理指数（PMI）为([\d.]+)%")
    nonm = grab(r"非制造业商务活动指数为([\d.]+)%")
    comp = grab(r"综合PMI产出指数为([\d.]+)%")
    if not all([manu, nonm, comp]):
        raise RuntimeError(f"PMI 正文措辞可能已变更, 请核对: {url}")
    seg = ""
    comb = re.search(r"大、中、小型企业PMI分别为([\d.]+)%、([\d.]+)%和([\d.]+)%", text)
    if comb:
        seg = f" (大型{comb.group(1)}/中型{comb.group(2)}/小型{comb.group(3)})"
    return [{"time": f"{period}-01 09:30" if period else "",
             "text": f"统计局 {period} PMI: 制造业 {manu} | 非制造业 {nonm} | 综合 {comp}{seg}",
             "source": "国家统计局"}]


def fetch_pboc_social_financing() -> list:
    """人民银行社融增量(月度, 次月中旬发布): 最新月总额+人民币贷款/政府债/企业债。官方零鉴权。
    三级跳(索引→年份页→专题页→xlsx附件), 依赖 openpyxl; 支持 2021 年起(移植自 a-stock-data §11.1)。"""
    import io
    import openpyxl
    base = "https://www.pbc.gov.cn"
    idx = _macro_text(f"{base}/diaochatongjisi/116219/116319/index.html")
    years = re.findall(r'href=["\']([^"\']+)["\'][^>]*>\s*(\d{4})年统计数据\s*</a>', idx)
    if not years:
        raise RuntimeError("人民银行索引页未找到「XXXX年统计数据」链接, 页面结构可能已变更")
    table = {int(y): h for h, y in years}
    target = max(table)
    ypage = _macro_text(table[target] if table[target].startswith("http") else base + table[target])
    topics = re.findall(r'href=["\']([^"\']+)["\'][^>]*>\s*(社会融资规模)\s*</a>', ypage)
    if not topics:
        raise RuntimeError(f"{target} 年页未找到「社会融资规模」专题链接")
    tpage = _macro_text(topics[0][0] if topics[0][0].startswith("http") else base + topics[0][0])
    books = re.findall(r'href=["\']([^"\']+\.xlsx?)["\']', tpage)
    if not books:
        raise RuntimeError(f"{target} 年社融专题页未找到 xls/xlsx 附件")
    content = requests.get(books[0] if books[0].startswith("http") else base + books[0],
                           headers={"User-Agent": UA}, timeout=60).content
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    rows = [[c.value for c in row] for row in wb.active.iter_rows(max_row=40, max_col=12)]
    wb.close()
    start = next((i for i, r in enumerate(rows) if str(r[0]).strip() == "月份"), None)
    if start is None:
        raise RuntimeError("社融表没有独立「月份」表头, 版式不支持(仅 2021 年起新版式)")
    data = [r for r in rows[start + 3:]
            if r and r[0] is not None and re.match(r"^\d{4}\.\d{1,2}$", str(r[0]))]
    if not data:
        raise RuntimeError("社融表数据行为空")
    last = data[-1]
    s = str(last[0])                                   # Excel 吃掉尾零: 2026.01 vs 2026.1(=10月)
    frac = s.split(".")[1]
    label = f"{s.split('.')[0]}-{int(frac) if len(frac) == 2 else int(frac) * 10:02d}"

    def _n(v):
        try:
            return f"{float(v):,.0f}"
        except (TypeError, ValueError):
            return str(v)
    return [{"time": label,
             "text": f"社融增量 {label}: 总规模 {_n(last[1])}亿 (人民币贷款 {_n(last[2])}"
                     f" / 企业债 {_n(last[7])} / 政府债 {_n(last[8])} / 股票融资 {_n(last[9])})",
             "source": "人民银行"}]


def fetch_treasury_yield_curve() -> list:
    """美债收益率曲线(每日, 1M~30Y, 官方 S 级零鉴权): 最新日关键期限 + 10Y-2Y 利差。"""
    import csv
    import io
    year = datetime.datetime.now(_BJ).year
    url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
           f"daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
           f"&field_tdr_date_value={year}&page&_format=csv")
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(r.text)))
    if not rows:
        return []

    def _g(row, name):                                 # 列名年份间有大小写漂移, 防御式匹配
        for k in row:
            if k and k.strip().lower() == name and (row[k] or "").strip():
                return row[k].strip()
        return ""

    latest = rows[0]
    date, y2, y10 = latest.get("Date", ""), _g(latest, "2 yr"), _g(latest, "10 yr")
    parts = [f"{lbl} {_g(latest, key)}" for lbl, key in
             (("3M", "3 mo"), ("2Y", "2 yr"), ("10Y", "10 yr"), ("30Y", "30 yr")) if _g(latest, key)]
    spread = ""
    try:
        spread = f" | 10Y-2Y {float(y10) - float(y2):+.2f}"
    except ValueError:
        pass
    return [{"time": date, "text": f"美债收益率({date}): " + " | ".join(parts) + spread,
             "source": "US Treasury"}]


_COT_FOCUS = re.compile(r"GOLD|SILVER|COPPER|PLATINUM|PALLADIUM|CRUDE|BRENT|NATURAL GAS|"
                        r"WHEAT|CORN|SOYBEAN|COFFEE|SUGAR|COCOA|COTTON|"
                        r"EURO|YEN|POUND|FRANC|DOLLAR|YUAN|PESO", re.I)


def fetch_cftc_cot(page_size: int = 10) -> list:
    """CFTC COT 持仓报告(周度, 周五发布周二数据, 官方 S 级零鉴权): 大宗/外汇品种投机净多。
    覆盖黄金/铜/原油/农产品/主要货币对, 贴大宗与外汇资产类别。"""
    r = requests.get("https://publicreporting.cftc.gov/resource/6dca-aqww.json",
                     params={"$limit": 300, "$order": "report_date_as_yyyy_mm_dd DESC"},
                     headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    out, seen = [], set()
    for it in r.json():
        name = (it.get("contract_market_name") or "").strip()
        if not name or name in seen or not _COT_FOCUS.search(name):
            continue
        seen.add(name)
        date = (it.get("report_date_as_yyyy_mm_dd") or "")[:10]
        lo, sh = it.get("noncomm_positions_long_all"), it.get("noncomm_positions_short_all")
        net = ""
        try:
            net = f" 投机净多 {int(float(lo)) - int(float(sh)):,}"
        except (TypeError, ValueError):
            pass
        out.append({"time": date, "text": f"COT {name}:{net}".rstrip(":")
                    if not net else f"COT {name}:{net}", "source": "CFTC"})
        if len(out) >= int(page_size):
            break
    return out


def fetch_nasdaq_earnings() -> list:
    """Nasdaq 财报日历(每日): 当日发财报的公司(代码/盘前盘后/EPS 预期)。C 级条款未核实, 个人研究用。"""
    today = datetime.datetime.now(_BJ).strftime("%Y-%m-%d")
    r = requests.get("https://api.nasdaq.com/api/calendar/earnings",
                     params={"date": today},
                     headers={"User-Agent": UA, "Accept": "application/json"}, timeout=15)
    r.raise_for_status()
    rows = ((r.json().get("data") or {}).get("rows")) or []
    if not rows:
        return []
    picks = []
    for x in rows[:12]:
        eps = x.get("epsForecast") or ""
        picks.append(f"{x.get('symbol')}({x.get('time') or ''}{', 预期' + eps if eps else ''})")
    return [{"time": today,
             "text": f"今日美股财报 {len(rows)} 家: " + "、".join(picks),
             "source": "Nasdaq"}]
