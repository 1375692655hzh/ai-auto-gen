"""扩展数据源:富途早报/财联社有声早报/gangtise镜像(同行早报证据层)
+ 财经事件日历/外围市场行情/上市公司公告(版式专用板块)。

移植自 NEWS 项目的实战实现(TypeScript → Python):
- 富途: news-site-api 列表 + 文章页正文 + WAF 破盾(futu-waf 算法)
- 财联社: 专题页 __NEXT_DATA__.pageProps(公告专题 1555/8271、有声早报专题 1151)
- 日历: 华尔街见闻 macrodatas(本周,取今日 importance>=2)
全部无需凭证,只靠 UA/Referer。
"""

import datetime
import hashlib
import html
import json
import sys
import random
import re

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}


def _get(url, referer, **kw):
    r = requests.get(url, headers={**UA, "Referer": referer}, timeout=15, **kw)
    r.raise_for_status()
    return r


# ---------- 富途早报(列表 API + WAF 破盾) ----------

def _waf_hash(jwt: str) -> str:
    MOD = 2 ** 25
    h = 0x811C9DC5
    for c in jwt:
        h = (0x83 * h + h + ord(c)) % MOD
    return format(abs(h) % MOD, "x")


def _waf_suffix() -> str:
    while True:
        n = str(random.randint(10 ** 8, 10 ** 10))
        if n[-7] == "1" and n[-3] == "1":
            return n


def fetch_futu_morning() -> dict | None:
    """富途《港美早报/富途早报》最新一篇,返回 {title,text,url,time}。

    列表按时间倒序但早报每天只有一篇,混排在要闻流里很快被顶下去——
    用 seqMark 翻页(最多 10 页)直到命中(参考 NEWS 项目 futu-topic-parse.ts)。"""
    arts, seq_mark = [], ""
    import time as _time
    for _page in range(10):
        params = {"size": 60}
        if seq_mark:
            params["seqMark"] = seq_mark
        try:
            r = _get("https://news.futunn.com/news-site-api/main/get-market-list",
                     "https://news.futunn.com/", params=params).json()
        except Exception:
            if _page == 0:
                _time.sleep(2)                 # 列表接口偶发抖动, 首页重试一次
                r = _get("https://news.futunn.com/news-site-api/main/get-market-list",
                         "https://news.futunn.com/", params=params).json()
            else:
                raise
        data = r.get("data") or {}
        lst = data.get("list") or []
        if not lst and _page == 0:             # 空列表同样视作抖动, 退避重试一次
            _time.sleep(2)
            r = _get("https://news.futunn.com/news-site-api/main/get-market-list",
                     "https://news.futunn.com/", params=params).json()
            lst = (r.get("data") or {}).get("list") or []
        arts.extend(lst)
        if any(re.search(r"港美早报|富途早报", a.get("title", "")) for a in arts):
            break                                   # 命中即停(倒序, 最新的在前)
        if not data.get("hasMore") or not data.get("seqMark") or not lst:
            break
        seq_mark = data["seqMark"]
    hits = [a for a in arts if re.search(r"港美早报|富途早报", a.get("title", ""))]
    if not hits:
        return None
    art = max(hits, key=lambda a: int(a.get("timestamp") or 0))
    url = art["url"].split("?")[0]

    s = requests.Session()
    s.headers.update({**UA, "Referer": "https://news.futunn.com/"})
    h = s.get(url, timeout=20).text
    if "wafToken" in h and "origin_content" not in h:
        m = re.search(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", h)
        if m:
            jwt = m.group(0)
            s.cookies.set("wafToken", f"{jwt}@{_waf_hash(jwt)}@{_waf_suffix()}")
            h = s.get(url, timeout=20).text
    i = h.find("origin_content")
    if i < 0:
        return None
    seg = h[i:i + 120000]
    # 跳过 origin_content 标签自身的属性残渣(如 origin_content zh-cn">)
    gt = seg.find(">")
    if 0 <= gt < 60:
        seg = seg[gt + 1:]
    for end in ('class="origin_', "免责声明", "相关阅读"):
        j = seg[6000:].find(end)
        if j > 0:
            seg = seg[:6000 + j]
    text = html.unescape(re.sub(r"<[^>]+>", "\n", seg))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return {"title": art["title"].strip(), "text": text[:8000], "url": url,
            "time": datetime.datetime.fromtimestamp(int(art.get("timestamp") or 0)).strftime("%Y-%m-%d %H:%M"),
            "media": "富途牛牛", "source": "富途早报"}


# ---------- 财联社(有声早报 1151 / 公告 1555+8271) ----------

def _cls_page_props(url: str) -> dict:
    h = _get(url, url).content.decode("utf-8", "ignore")
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.DOTALL)
    if not m:
        raise RuntimeError("页面无 __NEXT_DATA__")
    return json.loads(m.group(1))["props"]["pageProps"]


def _cls_articles(subject_id: str) -> list:
    p = _cls_page_props(f"https://www.cls.cn/subject/{subject_id}")
    return ((p.get("data") or {}).get("articles")) or []


def fetch_cls_morning() -> dict | None:
    """财联社有声早报(专栏 1151, 每天 07:00 发布): 今天那篇优先, 否则 48h 内最新一篇全文。"""
    cutoff = datetime.datetime.now() - datetime.timedelta(hours=48)
    cands = [a for a in _cls_articles("1151")
             if "早报" in (a.get("article_title") or "")
             and datetime.datetime.fromtimestamp(a.get("article_time") or 0) >= cutoff]
    if not cands:
        return None
    a = max(cands, key=lambda x: x.get("article_time") or 0)
    t = a.get("article_time") or 0
    detail = _cls_page_props(f"https://www.cls.cn/detail/{a['article_id']}")
    content = ((detail.get("articleDetail") or {}).get("content")) or ""
    text = html.unescape(re.sub(r"<[^>]+>", "\n", content))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return {"title": a["article_title"], "text": text[:8000],
            "url": f"https://www.cls.cn/detail/{a['article_id']}",
            "time": datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M"),
            "media": "财联社", "source": "财联社有声早报"}


# ---------- Anadolu Agency 英文晨报 ----------

_TR_TZ = datetime.timezone(datetime.timedelta(hours=3))
_BJ_TZ = datetime.timezone(datetime.timedelta(hours=8))
_AA_SLUG_RE = re.compile(r"morning-briefing-([a-z]+)-(\d{1,2})-(\d{4})/(\d+)", re.I)
_AA_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def _clean_html_text(raw: str) -> str:
    """统一清理 HTML / RSC 片段为纯文本。"""
    text = html.unescape(re.sub(r"<[^>]+>", "\n", raw))
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def _aa_rsc_text(page: str) -> str:
    """从 AA Next.js RSC script payload 中抽取晨报正文。"""
    blocks = []
    for raw in re.findall(r"<script[^>]*>(.*?)</script>", page, re.S | re.I):
        if "TOP STORIES" not in raw and "NEWS IN BRIEF" not in raw:
            continue
        decoded = re.sub(r"\\u([0-9a-fA-F]{4})",
                         lambda m: chr(int(m.group(1), 16)), raw)
        # 导语措辞多变("Here's/Here’s/Here is a rundown"):先宽匹配到 RSC 数组收尾,再退回段落式
        m = re.search(r"(<p>Here.{0,60}rundown[\s\S]*?)(?:\"\]\)|\"\]\])", decoded, re.I)
        if not m:
            m = re.search(r"(<p>Here.?s a rundown[\s\S]*?</p>(?:[\s\S]*?<p>[\s\S]*?</p>)*)",
                          decoded, re.I)
        if not m:
            m = re.search(r"(Here.?s a rundown[\s\S]*?)(?:\"\]\)|\"\]\])", decoded, re.I)
        if not m:
            continue
        block = m.group(1)
        for end in ('\"])', '\"]]', "US-Iran war", "LATEST NEWS"):
            pos = block.find(end)
            if pos > 1000:
                block = block[:pos]
        block = (block.replace(r'\"', '"').replace(r'\/', '/')
                      .replace(r'\n', '\n').replace(r'\t', '\t').replace(r'\\', '\\'))
        blocks.append(_clean_html_text(block))
    return max(blocks, key=len, default="")


def fetch_aa_morning() -> dict | None:
    """抓取 AA 英文晨报：土耳其今天优先，48 小时窗口内回退最新一篇。"""
    today = datetime.datetime.now(_TR_TZ).date()
    wanted = [today - datetime.timedelta(days=n) for n in range(3)]
    search_url = "https://www.aa.com.tr/en/search?s=Morning+Briefing"
    discovery = ((search_url, "https://www.aa.com.tr/en/"),
                 ("https://www.aa.com.tr/en/rss/default?cat=world", "https://www.aa.com.tr/en/world"),
                 ("https://www.aa.com.tr/en/world", "https://www.aa.com.tr/en/"))
    discovered = None
    errors = []
    fetched_any = False
    for url, referer in discovery:
        try:
            page = _get(url, referer).text
        except Exception as e:
            errors.append(e)
            continue
        fetched_any = True
        candidates = []
        for m in _AA_SLUG_RE.finditer(page):
            month = _AA_MONTHS.get(m.group(1).lower())
            if not month:
                continue
            try:
                date = datetime.date(int(m.group(3)), month, int(m.group(2)))
            except ValueError:
                continue
            if date in wanted:
                candidates.append((date, m.group(0)))
        if candidates:
            discovered = max(candidates, key=lambda x: x[0])[1]
            break
    if not discovered:
        if fetched_any:
            return None                # 请求通了但 48h 窗口内无晨报 → 未发布
        raise RuntimeError(f"AA 发现入口均请求失败: {type(errors[-1]).__name__ if errors else 'unknown'}")

    page = article_url = ""
    for section in ("world", "general"):
        candidate = f"https://www.aa.com.tr/en/{section}/{discovered}"
        try:
            response = _get(candidate, "https://www.aa.com.tr/en/")
        except Exception:
            continue
        if "Morning Briefing" in response.text:
            article_url, page = candidate, response.text
            print(f"  AA晨报发现: {article_url}")
            break
    if not page:
        raise RuntimeError("AA 晨报文章页不可用")

    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S | re.I)
    title = _clean_html_text(h1.group(1)) if h1 else "Morning Briefing"
    published = re.search(r'"datePublished"\s*:\s*"([^"]+)"', page)
    if not published:
        published = re.search(r'<meta[^>]+(?:property|name)=["\']article:published_time["\'][^>]+content=["\']([^"\']+)', page, re.I)
    if not published:
        published = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']article:published_time["\']', page, re.I)
    try:
        dt = datetime.datetime.fromisoformat(published.group(1).replace("Z", "+00:00"))
        dt = dt.replace(tzinfo=_TR_TZ) if dt.tzinfo is None else dt
        time_text = dt.astimezone(_BJ_TZ).strftime("%Y-%m-%d %H:%M")
    except Exception:
        time_text = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    text = _aa_rsc_text(page)
    if not text:                       # 兜底: main 常是 RSC 空壳, 逐个试到取到文本为止
        for pat in (r"<main[^>]*>(.*?)</main>", r"<body[^>]*>(.*?)</body>"):
            m = re.search(pat, page, re.S | re.I)
            if m:
                text = _clean_html_text(m.group(1))
                if text:
                    break
    if not text:
        raise RuntimeError("AA 晨报正文解析为空")
    return {"time": time_text, "title": title, "text": text[:12000],
            "media": "Anadolu Agency", "url": article_url, "source": "AA晨报"}


# ---------- BloombergHT 土耳其市场 ----------

_TR_MONTHS = {"ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4,
              "mayıs": 5, "mayis": 5, "haziran": 6, "temmuz": 7,
              "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9, "ekim": 10,
              "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12}


def _bht_title(raw: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", raw))).strip()


def fetch_turkey_morning() -> dict | None:
    """抓取 BloombergHT 快讯、要闻及当日可用的土耳其市场收盘综述。"""
    base = "https://www.bloomberght.com"
    session = requests.Session()
    session.headers.update({**UA, "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8"})
    response = session.get(f"{base}/borsa", timeout=15)
    response.raise_for_status()
    page = response.text
    breaking, featured = [], []
    marker = page.find("SON DAKİKA")
    if marker >= 0:
        for m in re.finditer(r'<a[^>]+href=["\'](/sondakika)["\'][^>]*>(.*?)</a>', page[marker:marker + 9000], re.S | re.I):
            title = _bht_title(m.group(2))
            if title and title not in breaking:
                breaking.append(title)
    marker = page.find("Öne Çıkan")
    if marker >= 0:
        for m in re.finditer(r'<a[^>]+href=["\'](/[^"\']+-\d+)["\'][^>]*>(.*?)</a>', page[marker:marker + 12000], re.S | re.I):
            title = _bht_title(m.group(2))
            if title and title not in {x[0] for x in featured}:
                featured.append((title, base + m.group(1)))

    summary = ""
    today = datetime.datetime.now(_TR_TZ).date()
    try:
        listing = session.get(f"{base}/tum-piyasa-haberleri", timeout=15)
        listing.raise_for_status()
        for m in re.finditer(r'href=["\']([^"\']*(?:piyasalarda-gunun-ozeti|piyasa-ozeti)[^"\']*)["\']', listing.text, re.I):
            href = html.unescape(m.group(1))
            date_match = re.search(r"(\d{1,2})-([a-zçğıöşü]+)-(\d{4})", href, re.I)
            if not date_match or _TR_MONTHS.get(date_match.group(2).lower()) is None:
                continue
            date = datetime.date(int(date_match.group(3)), _TR_MONTHS[date_match.group(2).lower()], int(date_match.group(1)))
            if date != today:
                continue
            article = session.get(href if href.startswith("http") else base + href, timeout=15)
            article.raise_for_status()
            # 正文在 <article class="...news-content..."> 里; 容器没匹配上就跳过(整页兜底全是广告脚本)
            content = re.search(r'<article[^>]*news-content[^>]*>(.*?)</article>',
                                article.text, re.S | re.I)
            summary = _clean_html_text(content.group(1)) if content else ""
            break
    except Exception:
        pass

    parts = ["[土耳其市场·机器汇总]"]
    if breaking:
        parts.extend(["", "■ SON DAKİKA 快讯"] + [f"- {x}" for x in breaking[:12]])
    if featured:
        parts.extend(["", "■ Öne Çıkan 要闻"] + [f"- {title} ({url})" for title, url in featured[:8]])
    if summary:
        parts.extend(["", "■ 收盘综述(当日如有)", summary])
    if not (breaking or featured or summary):
        return None
    text = "\n".join(parts)[:12000]
    print(f"  BloombergHT汇总: 快讯{len(breaking[:12])}条，要闻{len(featured[:8])}条")
    return {"time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "title": f"BloombergHT土耳其市场汇总 {today:%Y-%m-%d}", "text": text,
            "media": "BloombergHT", "url": f"{base}/borsa", "source": "BloombergHT土耳其"}


# ---------- CNBC 美股晨报(Daily Open) ----------

_CNBC_ARCHIVE = "https://www.cnbc.com/daily-open/"
_CNBC_URL_RE = re.compile(r"https://www\.cnbc\.com/(\d{4}/\d{2}/\d{2})/(?:cnbc-)?daily-open[a-z0-9-]*\.html")
_UTC_TZ = datetime.timezone.utc


def _cnbc_article_text(page: str) -> str:
    """CNBC 文章页 SSR 正文: ArticleBody-articleBody 容器, 内联标签保行内连续、块级换行。"""
    m = re.search(r'<div[^>]*ArticleBody-articleBody[^>]*>(.*?)(?=<div[^>]*class="[^"]*ArticleBody-googlePreferredSourceContainer)',
                  page, re.S)
    seg = m.group(1) if m else ""
    if not seg:                       # 容器标记改版时退而取 articleBody 起点后固定范围
        i = page.find("ArticleBody-articleBody")
        if i < 0:
            return ""
        seg = page[i:i + 60000]
    seg = re.sub(r"</(?:p|li|h2|h3)>|<br\s*/?>", "\n", seg)
    seg = html.unescape(re.sub(r"<[^>]+>", "", seg))
    seg = re.sub(r"[ \t\xa0]+", " ", seg)
    lines = [ln.strip() for ln in seg.split("\n")
             if ln.strip() and "Getty Images" not in ln]
    return re.sub(r"\n{2,}", "\n", "\n".join(lines)).strip()


def fetch_cnbc_morning() -> dict | None:
    """CNBC Daily Open 晨报(每工作日 APAC/EMEA 两版, 周末停更)。
    归档页 SSR 发现 48h 内最新一篇 → 文章页 SSR 全文。"""
    page = _get(_CNBC_ARCHIVE, "https://www.cnbc.com/").text
    today = datetime.datetime.now(_UTC_TZ).date()
    seen, urls = set(), []
    for m in _CNBC_URL_RE.finditer(page):
        y, mo, d = (int(x) for x in m.group(1).split("/"))
        try:
            dt = datetime.date(y, mo, d)
        except ValueError:
            continue
        if dt < today - datetime.timedelta(days=2) or m.group(0) in seen:
            continue
        seen.add(m.group(0))
        urls.append((dt, m.group(0)))
    if not urls:
        return None                   # 请求通但 48h 窗口内无晨报(周末)
    url = max(urls)[1]
    art = _get(url, _CNBC_ARCHIVE).text
    text = _cnbc_article_text(art)
    if not text:
        raise RuntimeError("CNBC 正文解析为空")
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", art, re.S)
    title = _clean_html_text(h1.group(1)) if h1 else "CNBC Daily Open"
    published = re.search(r'"datePublished"\s*:\s*"([^"]+)"', art)
    try:
        dt = datetime.datetime.strptime(published.group(1), "%Y-%m-%dT%H:%M:%S%z")
        time_text = dt.astimezone(_BJ_TZ).strftime("%Y-%m-%d %H:%M")
    except Exception:
        time_text = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"  CNBC晨报发现: {url.rsplit('/', 1)[-1][:60]}")
    return {"time": time_text, "title": title, "text": text[:12000],
            "media": "CNBC", "url": url, "source": "CNBC美股晨报"}


# ---------- Kyodo 共同社 / Yonhap 韩联社 市场精选(RSS) ----------

_JP_KW = re.compile(r"(?:Nikkei|stocks?|yen|BOJ|Bank of Japan|market|econom|trade|GDP|"
                    r"exports?|tariff|interest rate|inflation|TSE|Topix)", re.I)
_KR_KW = re.compile(r"(?:KOSPI|KOSDAQ|won\b|BOK|Bank of Korea|market|econom|trade|GDP|"
                    r"exports?|chip|semiconductor|tariff|interest rate|inflation|"
                    r"Samsung|Hyundai|SK Group|LG\b)", re.I)


def _rss_items(xml_text: str) -> list:
    """RSS 2.0 → [(title, link, pubDate_bj, lead)]; 解析失败条目跳过。"""
    out = []
    for it in re.findall(r"<item>(.*?)</item>", xml_text, re.S):
        def tag(t):
            m = re.search(rf"<{t}>(.*?)(?:</{t}>|</item>)", it, re.S)
            return re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", m.group(1), flags=re.S) if m else ""
        title, link, pub, desc = (tag("title"), tag("link"), tag("pubDate"), tag("description"))
        title = _clean_html_text(title)
        desc = _clean_html_text(re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", desc, flags=re.S))
        dt = None
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M %z"):
            try:
                dt = datetime.datetime.strptime(pub, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            iso = tag("dc:date")                    # ING Think 等用 dc:date(ISO 分钟级)
            if iso:
                try:
                    dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
                except ValueError:
                    pass
        out.append({"title": title, "link": link, "dt": dt,
                    "pub_bj": dt.astimezone(_BJ_TZ).strftime("%Y-%m-%d %H:%M") if dt else pub,
                    "lead": desc})
    return out


def _market_digest(feed_url: str, kw: re.Pattern, label: str, media: str,
                   max_items: int = 10) -> dict | None:
    """通用市场精选: 当日(北京时间)条目 × 关键词过滤 → 单篇机器汇总。"""
    xml_text = _get(feed_url, "https://www.google.com/").text
    today = datetime.datetime.now(_BJ_TZ).strftime("%Y-%m-%d")
    hits = [x for x in _rss_items(xml_text)
            if x["pub_bj"][:10] == today and kw.search(f"{x['title']} {x['lead']}")]
    if not hits:
        return None                  # 当日无市场相关条目
    parts = [f"[{label}·机器汇总]"]
    for x in hits[:max_items]:
        lead = x["lead"][:300]
        parts.append(f"- {x['title']}：{lead}" if lead else f"- {x['title']}")
    print(f"  {media}汇总: 当日市场条目 {len(hits[:max_items])} 条")
    return {"time": max(x["pub_bj"] for x in hits[:max_items]),
            "title": f"{media}{label}精选 {today}",
            "text": "\n".join(parts)[:12000], "media": media,
            "url": feed_url, "source": f"{media}{label}"}


def fetch_japan_morning() -> dict | None:
    """共同社英文 Japan Wire: 当日市场/宏观条目精选。"""
    return _market_digest("https://english.kyodonews.net/list/feed/rss4kyodonews-fzone",
                          _JP_KW, "日本市场", "共同社")


def fetch_korea_morning() -> dict | None:
    """韩联社英文 RSS: 当日市场/宏观条目精选(URGENT/LEAD 演进链按标题去重取最新)。"""
    r = _market_digest("https://en.yna.co.kr/RSS/news.xml", _KR_KW, "韩国市场", "韩联社")
    if r and r["text"]:
        lines = r["text"].split("\n")
        seen, kept = set(), [lines[0]]
        for ln in lines[1:]:
            key = re.sub(r"^(?:URGENT|LEAD|\d+(?:st|nd|rd|th) LD)[\s,:-]*", "", ln[:60])
            if key in seen:
                continue
            seen.add(key)
            kept.append(ln)
        r["text"] = "\n".join(kept)[:12000]
    return r


# ---------- 机构观点/名家分析(东财研报中心 + 新浪意见领袖) ----------

def fetch_em_research() -> dict | None:
    """东财研报中心: 当日宏观研究(qType=3)+晨会纪要(q4)+策略(q2) 列表拼"机构观点索引"篇。
    列表自带机构+研究员署名(详情页全文太重, 索引已足以告知 synth 今日机构研判方向)。"""
    import requests as rq
    today = datetime.datetime.now(_BJ_TZ).strftime("%Y-%m-%d")
    lines, seen = [], set()
    for qt, label in ((4, "晨会纪要"), (3, "宏观研究"), (2, "策略报告")):
        u = ("https://reportapi.eastmoney.com/report/jg?pageSize=50"
             f"&beginTime={today}&endTime={today}&pageNo=1&qType={qt}")
        r = rq.get(u, headers={**UA}, timeout=15)
        r.raise_for_status()
        for it in (r.json() or {}).get("data") or []:
            key = it.get("title", "")
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"【{it.get('orgSName', '')}｜{it.get('researcher', '')}】{key}")
        if len(lines) >= 30:
            break
    if not lines:
        return None                # 交易日才有, 周末 None 属预期
    print(f"  东财研报: 当日 {len(lines[:30])} 条机构观点")
    return {"time": f"{today} 08:30", "title": f"机构观点索引 {today}",
            "text": "[机构观点·机器汇总]\n" + "\n".join(lines[:30])[:12000],
            "media": "东方财富研报中心", "url": "https://data.eastmoney.com/report/",
            "source": "东财研报"}


def fetch_sina_vip() -> dict | None:
    """新浪财经意见领袖: 首席经济学家/大V当日署名观点(标题+摘要)。"""
    import requests as rq
    today = datetime.datetime.now(_BJ_TZ).strftime("%Y-%m-%d")
    lines = []
    for page in (1, 2):
        r = rq.get(f"https://interface.sina.cn/finance/api_feed.d.json?page={page}",
                   headers={**UA, "Referer": "https://finance.sina.com.cn/zl/"},
                   timeout=15)
        r.raise_for_status()
        body = r.json()
        items = body.get("data") if isinstance(body, dict) else body
        if not isinstance(items, list):
            break
        stop = False
        for it in items:
            if (it.get("publish_time") or "")[:10] != today:
                if (it.get("publish_time") or "")[:10] < today:
                    stop = True
                continue
            t = it.get("title", "")
            if t and it.get("summary"):
                lines.append(f"【{it.get('author_name', '')}】{t}：{it['summary']}")
        if stop:
            break
    if not lines:
        return None
    print(f"  新浪意见领袖: 当日 {len(lines)} 篇")
    return {"time": f"{today} {datetime.datetime.now(_BJ_TZ).strftime('%H:%M')}",
            "title": f"意见领袖观点精选 {today}",
            "text": "[名家观点·机器汇总]\n" + "\n".join(lines[:15])[:12000],
            "media": "新浪财经", "url": "https://finance.sina.com.cn/zl/",
            "source": "新浪意见领袖"}


# ---------- etnet經濟通/Newsquawk/SMM(交叉验证轮接入; ING已随欧洲线移除) ----------

_ETNET_CAT = "開市Ｇｏ"


def fetch_etnet_open() -> dict | None:
    """etnet經濟通「開市Ｇｏ」港股晨报: 工作日 08:30-08:38 HKT 一篇, meta description 即要聞盤點全文。"""
    import urllib.parse
    base = "https://www.etnet.com.hk/www/tc/news/"
    lst = _get(f"{base}special_news_list.php?category={urllib.parse.quote(_ETNET_CAT)}",
               "https://www.etnet.com.hk/").text
    today = datetime.datetime.now(_BJ_TZ).strftime("%d/%m/%Y")
    m = re.search(r'newsid=(\d+)"[^>]*>\s*<h2[^>]*>([^<]+)</h2>.*?<p class="time">'
                  + re.escape(today) + r' (\d{2}:\d{2})</p>', lst, re.S)
    day = today
    if not m:
        # 当日无(周末/未发) → 48h 窗口回退昨天
        day = (datetime.datetime.now(_BJ_TZ) - datetime.timedelta(days=1)).strftime("%d/%m/%Y")
        m = re.search(r'newsid=(\d+)"[^>]*>\s*<h2[^>]*>([^<]+)</h2>.*?<p class="time">'
                      + re.escape(day) + r' (\d{2}:\d{2})</p>', lst, re.S)
    if not m:
        return None
    newsid, title, hm = m.group(1), _clean_html_text(m.group(2)), m.group(3)
    # 精确日期归属: 用该 newsid 附近的时间串重抓一次
    tmatch = re.search(r'newsid=' + newsid + r'".*?<p class="time">(\d{2}/\d{2}/\d{4}) (\d{2}:\d{2})</p>', lst, re.S)
    dmy, hm = (tmatch.group(1), tmatch.group(2)) if tmatch else (day, hm)
    dd, mm, yy = dmy.split("/")
    art = _get(f"{base}news-article.php?section=special&category={urllib.parse.quote(_ETNET_CAT)}&newsid={newsid}",
               "https://www.etnet.com.hk/").text
    desc = re.search(r'<meta name="description" content="([^"]+)"', art)
    text = _clean_html_text(desc.group(1)) if desc else ""
    if not text:
        body = re.search(r'<article[^>]*>(.*?)</article>', art, re.S) or re.search(r'<body[^>]*>(.*?)</body>', art, re.S)
        text = _clean_html_text(body.group(1))[:6000] if body else ""
    if not text:
        return None
    print(f"  etnet開市Go发现: {title[:30]}")
    return {"time": f"{yy}-{mm}-{dd} {hm}", "title": title, "text": text[:12000],
            "media": "etnet經濟通", "url": f"{base}news-article.php?newsid={newsid}",
            "source": "etnet港股晨报"}


def fetch_newsquawk_open() -> dict | None:
    """Newsquawk EU/US Market Open: 交易日两篇(北京 14:38/18:12), 免费全文 111 段。"""
    lst = _get("https://www.newsquawk.com/daily", "https://www.newsquawk.com/").text
    links = re.findall(r'href="(/daily/\d+-[a-z-]+)"[^>]*>.*?(\d{1,2} \w{3} \d{4})', lst, re.S)
    if not links:
        return None
    art_url = "https://www.newsquawk.com" + links[0][0]
    art = _get(art_url, "https://www.newsquawk.com/daily").text
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", art, re.S)
    published = re.search(r'"datePublished"\s*:\s*"([^"]+)"', art)
    body = re.search(r"<article[^>]*>(.*?)</article>", art, re.S) \
        or re.search(r"<main[^>]*>(.*?)</main>", art, re.S)
    text = _clean_html_text(body.group(1)) if body else ""
    if not text:
        return None
    try:
        dt = datetime.datetime.strptime(published.group(1), "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=_UTC_TZ)
        time_text = dt.astimezone(_BJ_TZ).strftime("%Y-%m-%d %H:%M")
    except Exception:
        time_text = datetime.datetime.now(_BJ_TZ).strftime("%Y-%m-%d %H:%M")
    print(f"  Newsquawk发现: {(h1.group(1) if h1 else art_url)[:44]}")
    return {"time": time_text, "title": _clean_html_text(h1.group(1)) if h1 else "Market Open",
            "text": text[:12000], "media": "Newsquawk", "url": art_url, "source": "Newsquawk市场开盘"}


_SMM_SERIES = ("隔夜行情", "SMM日评", "SMM午评", "LME收盘", "收盘评论")


def fetch_smm_metals() -> dict | None:
    """SMM 上海有色网大宗商品日报: 栏目页取最新一篇系列文(【隔夜行情】优先) → 文章页全文。
    资产类别源(用户 2026-08-30 许可): 独立于七地理市场之外。"""
    lst = _get("https://news.smm.cn/l/21", "https://news.smm.cn/").text
    cards = re.findall(r'href="(/news/\d+)"[^>]*>([^<]*【([^】]+)】)', lst)
    # 栏目页混有直播/公告包装卡: 只认标题以系列名"结尾"的真文章卡
    real = [(p, t) for p, t, tag in cards
            if not re.search(r"直播|公告|发布", t) and any(t.rstrip().endswith(f"【{s}】") for s in _SMM_SERIES)]
    target = None
    for preferred in ("隔夜行情", "SMM日评", "LME收盘", "SMM午评", "收盘评论"):
        for path, full in real:
            if full.rstrip().endswith(f"【{preferred}】"):
                target = (path, _clean_html_text(full))
                break
        if target:
            break
    if not target and real:
        target = (real[0][0], _clean_html_text(real[0][1]))
    if not target:
        return None
    art = _get(f"https://news.smm.cn{target[0]}", "https://news.smm.cn/l/21").text
    # detail 容器嵌套 div 无法精确闭合, 直接取全文长 <p> 段(正文段落 30+ 字符, 短碎块自然滤掉)
    paras = [_clean_html_text(p) for p in re.findall(r"<p[^>]*>([^<]{30,})</p>", art)]
    text = "\n".join(paras)
    if not text:
        return None
    # 发布时间: 页面 time 是推荐位的不可信; 栏目页首位=最新发布, 日期用抓取时刻(聚合层只按日过滤)
    now = datetime.datetime.now(_BJ_TZ)
    tms = re.findall(r"<time[^>]*>(\d{4}-\d{2}-\d{2} \d{2}:\d{2})</time>", art)
    recent = [t for t in tms if t[:10] >= (now - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
              and t <= now.strftime("%Y-%m-%d %H:%M")]
    time_text = max(recent) if recent else now.strftime("%Y-%m-%d %H:%M")
    print(f"  SMM发现: {target[1][:36]}")
    return {"time": time_text, "title": target[1], "text": text[:12000],
            "media": "SMM上海有色网", "url": f"https://news.smm.cn{target[0]}",
            "source": "SMM大宗商品"}


def fetch_cnyes_tw() -> dict | None:
    """鉅亨网台湾市场精选: 新闻API tw_stock 分类当日条目(繁中, title+summary), 周末照常滚动。"""
    import requests as rq
    now = int(datetime.datetime.now(_BJ_TZ).timestamp())
    u = ("https://news.cnyes.com/api/v3/news/category/tw_stock"
         f"?startAt={now - 86400}&endAt={now}&limit=30")
    r = rq.get(u, headers={**UA, "Referer": "https://news.cnyes.com/"}, timeout=15)
    r.raise_for_status()
    items = (r.json().get("items") or {}).get("data") or []
    today = datetime.datetime.now(_BJ_TZ).strftime("%Y-%m-%d")
    lines = []
    for it in items:
        ts = it.get("publishAt") or 0
        bj = datetime.datetime.fromtimestamp(ts, _BJ_TZ)
        if bj.strftime("%Y-%m-%d") != today:
            continue
        lines.append((bj.strftime("%H:%M"), f"- {it.get('title', '')}：{_strip_tags(it.get('summary', ''))[:120]}"))
    if not lines:
        return None
    print(f"  鉅亨台湾: 当日 {len(lines)} 条")
    body = "\n".join(x[1] for x in sorted(lines, reverse=True))
    return {"time": f"{today} {max(x[0] for x in lines)}",
            "title": f"鉅亨台股精选 {today}",
            "text": "[台湾市场·机器汇总]\n" + body[:12000],
            "media": "鉅亨网", "url": "https://news.cnyes.com/cat/tw_stock",
            "source": "鉅亨台股"}


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _cls_article_text(article_id) -> str:
    detail = _cls_page_props(f"https://www.cls.cn/detail/{article_id}")
    content = ((detail.get("articleDetail") or {}).get("content")) or ""
    text = html.unescape(re.sub(r"<[^>]+>", "\n", content))
    return re.sub(r"\n{2,}", "\n", text)


def fetch_cls_announcements(limit: int = 15) -> list:
    """上市公司公告:财联社 1555/8271 专题,每篇即一条公告(标题【公司:内容】)。
    取昨日 15:00 以来的早报窗口(覆盖隔夜披露高峰),按时间倒序。"""
    cutoff = datetime.datetime.now().replace(hour=15, minute=0, second=0) - datetime.timedelta(days=1)
    out = []
    for sid, label in (("1555", "A股公告速递"), ("8271", "速读公告")):
        try:
            for a in _cls_articles(sid):
                t = a.get("article_time") or 0
                if datetime.datetime.fromtimestamp(t) < cutoff:
                    continue
                title = (a.get("article_title") or "").strip()
                if not title:
                    continue
                stocks = a.get("stock_list") or []
                company = (stocks[0].get("name") or "") if stocks else ""
                if not company:
                    m = re.match(r"【([^：:【】]+)[：:]", title)
                    company = m.group(1) if m else ""
                m2 = re.match(r"【([^】]+)】", title)
                if not company:
                    # 无 stock_list 且无【公司:】前缀:在标题中找"中文段+财报关键词"组合作公司名兜底
                    m3 = re.search(r"(?:^|(?<=[\s：:、】]))([\u4e00-\u9fa5]{2,6}?)(?=20\d{2}|H1|Q\d|上半年|半年度|年度|净利|营收|拟|中标|签署|回购|增持|减持|股东|董事长|实际控制人)", title)
                    company = m3.group(1) if m3 else ""
                out.append({"company": company or "—",
                            "title": (m2.group(1) if m2 else title)[:80],
                            "time": datetime.datetime.fromtimestamp(t).strftime("%m-%d %H:%M"),
                            "url": f"https://www.cls.cn/detail/{a.get('article_id')}",
                            "kind": label})
        except Exception:
            continue
    out.sort(key=lambda x: x["time"], reverse=True)
    # 同公司去重,保留最新
    seen, deduped = set(), []
    for x in out:
        if x["company"] in seen:
            continue
        seen.add(x["company"])
        deduped.append(x)
    return deduped[:limit]


# ---------- 事件日历(华尔街见闻 macrodatas) ----------

def fetch_calendar() -> list:
    """今日财经事件日历,importance>=2,按时间排序。"""
    now = datetime.datetime.now()
    mon = (now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0)
    r = _get("https://api-one-wscn.awtmt.com/apiv1/finance/macrodatas",
             "https://wallstreetcn.com/calendar",
             params={"start": int(mon.timestamp()), "end": int(mon.timestamp()) + 7 * 86400 - 1}).json()
    items = (r.get("data") or {}).get("items") or []
    out = []
    for i in items:
        ts = i.get("public_date") or 0
        if not ts or datetime.datetime.fromtimestamp(ts).date() != now.date():
            continue
        imp = int(i.get("importance") or 0)
        if imp < 2:
            continue
        out.append({"time": datetime.datetime.fromtimestamp(ts).strftime("%H:%M"),
                    "country": i.get("country", ""),
                    "event": (i.get("title") or i.get("event") or "").strip(),
                    "importance": imp,
                    "forecast": i.get("forecast") or "", "actual": i.get("actual") or ""})
    out.sort(key=lambda x: x["time"])
    return out


# ---------- 外围市场(新浪全球指数) ----------

MARKET_CODES = {  # 新浪代码 → 显示名
    "gb_dji": "道琼斯", "gb_ixic": "纳斯达克", "gb_inx": "标普500",
    "hkHSI": "恒生指数", "hkHSTECH": "恒生科技",
    "gb_n225": "日经225", "gb_dax": "德国DAX", "gb_ukx": "富时100",
}


def fetch_global_markets() -> list:
    """隔夜外围指数涨跌。gb_* 字段: [名称,现价,涨跌额,涨跌幅%...] hk_* 另行解析。"""
    codes = ",".join(MARKET_CODES)
    r = _get(f"https://hq.sinajs.cn/list={codes}", "https://finance.sina.com.cn/")
    body = r.content.decode("gbk", "ignore")
    out = []
    for m in re.finditer(r'hq_str_(\w+)="([^"]*)"', body):
        code, raw = m.group(1), m.group(2)
        if code not in MARKET_CODES or not raw:
            continue
        parts = raw.split(",")
        name, price, chg_pct = MARKET_CODES[code], None, None
        try:
            if code.startswith("gb_"):
                price = parts[1]
                chg_pct = parts[4] if len(parts) > 4 else None
            else:  # hk 指数: 字段 6=现价, 8=涨跌额... 不同源差异大,防御式取数
                nums = [p for p in parts[1:] if re.fullmatch(r"-?\d+(\.\d+)?", p or "x")]
                price = parts[6] if len(parts) > 6 else (nums[0] if nums else None)
                if len(parts) > 8 and re.fullmatch(r"-?\d+(\.\d+)?", parts[8] or ""):
                    prev = None
                    for n in nums:
                        if prev is not None and n != price:
                            break
                        prev = n
        except Exception:
            pass
        if price is None:
            continue
        out.append({"name": name, "price": price,
                    "chg_pct": (f"{float(chg_pct):+.2f}%" if chg_pct else "")})
    return out


# ---------- gangtise 公众号早报(镜像,尽力而为) ----------

_SOGOU_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}


def _today_title_patterns() -> list:
    """gangtise 命名规律: 'Gangtise投研日报 | 8月27日星期四' / '... | 2026-08-27'。"""
    import datetime
    d = datetime.date.today()
    weekdays = "一二三四五六日"
    m, day = d.month, d.day
    return [f"{m}月{day}日", d.strftime("%Y-%m-%d"), d.strftime("%Y.%m.%d"),
            f"{m}.{day}", f"{m}月{day}号"][:3] + [f"{m}月{day}日星期{weekdays[d.weekday()]}"]


def _sogou_weixin_links(session, query: str, limit: int = 6) -> list:
    """搜狗微信搜索,返回代理链接列表;被反爬拦截时返回 []。"""
    import urllib.parse
    r = session.get("https://weixin.sogou.com/weixin",
                    params={"type": 2, "query": query}, timeout=15)
    if r.status_code != 200 or "antispider" in r.url or len(r.text) < 10000:
        return []
    hrefs = []
    for m in re.finditer(r'href="(/link\?url=[^"]+)"', r.text):
        h = "https://weixin.sogou.com" + m.group(1).replace("&amp;", "&")
        if h not in hrefs:
            hrefs.append(h)
    return hrefs[:limit]


def _sogou_proxy_target(session, proxy_url: str) -> str | None:
    """代理页是 JS 拼接跳转,提取真实 mp.weixin URL。"""
    r = session.get(proxy_url, timeout=15)
    parts = re.findall(r"url \+= '([^']*)'", r.text)
    return "".join(parts) or None


def _mp_article(session, url: str) -> tuple:
    """抓公众号文章页,返回 (标题, 正文)。"""
    import html as H
    r = session.get(url, timeout=20)
    if r.status_code != 200:
        return "", ""
    t = re.search(r'<h1[^>]*id="activity-name"[^>]*>(.*?)</h1>', r.text, re.S)
    title = H.unescape(re.sub(r"<[^>]+>|\s+", "", t.group(1))).strip() if t else ""
    body = re.search(r'<div[^>]*id="js_content"[^>]*>(.*?)</div>\s*(?:<script|<div[^>]*id="js_tags)', r.text, re.S)
    text = ""
    if body:
        text = re.sub(r"<[^>]+>", "\n", body.group(1))
        text = re.sub(r"\n{2,}", "\n", H.unescape(text)).strip()
    return title, text


def fetch_gangtise() -> dict | None:
    """gangtise 每日早报。命名规律 'Gangtise投研日报 | 8月27日星期四':
    搜狗微信搜索 -> 代理页解真实 URL -> 按当天日期匹配标题 -> 抓正文。
    被反爬/当日未发布时回退豆包搜索镜像,仍无则返回 None(不硬凑)。"""
    import time as _t
    try:
        s = requests.Session()
        s.headers.update(_SOGOU_UA)
        pats = _today_title_patterns()
        for query in ("Gangtise投研日报", "gangtise 投研日报"):
            links = _sogou_weixin_links(s, query)
            for proxy in links:
                try:
                    target = _sogou_proxy_target(s, proxy)
                    if not target or "mp.weixin.qq.com" not in target:
                        continue
                    title, text = _mp_article(s, target)
                    if title and text and "gangtise" in title.lower() \
                            and any(p in title for p in pats) and len(text) > 500:
                        return {"title": title, "text": text[:12000], "url": target,
                                "time": "", "media": "Gangtise投研(公众号)",
                                "source": "gangtise公众号(搜狗微信)"}
                    _t.sleep(1.5)  # 慢速翻结果,降低反爬概率
                except Exception:
                    continue
    except Exception:
        pass
    # 回退:豆包搜索镜像(多数日期无可靠镜像)
    try:
        from search import web_search
        for w in web_search("Gangtise投研日报", count=5):
            blob = (w["title"] + w["url"] + w["text"][:300]).lower()
            if "gangtise" in blob and any(p in w["title"] for p in pats):
                return {"title": w["title"], "text": w["text"], "url": w["url"],
                        "time": w["time"], "media": w["site"], "source": f"gangtise镜像({w['site']})"}
    except Exception:
        pass
    return None


# ---------- 聚合 ----------

def fetch_peer_mornings() -> tuple:
    """十四份同行早报/观点源(富途/财联社/AA/BHT/CNBC/日韩台/研报/意见领袖/etnet/Newsquawk/SMM/gangtise)，单个失败不影响其余。
    市场范围: 美/A/港/日/韩/台/土耳其; SMM为大宗资产类别源(用户 2026-08-30 许可, 独立于地理市场之外)。"""
    refs, failed = [], []
    for name, fn in (("富途早报", fetch_futu_morning),
                     ("财联社有声早报", fetch_cls_morning),
                     ("AA英文晨报", fetch_aa_morning),
                     ("BloombergHT土耳其", fetch_turkey_morning),
                     ("CNBC美股晨报", fetch_cnbc_morning),
                     ("共同社日本市场", fetch_japan_morning),
                     ("韩联社韩国市场", fetch_korea_morning),
                     ("东财研报", fetch_em_research),
                     ("新浪意见领袖", fetch_sina_vip),
                     ("etnet港股", fetch_etnet_open),
                     ("鉅亨台股", fetch_cnyes_tw),
                     ("Newsquawk欧美", fetch_newsquawk_open),
                     ("SMM大宗商品", fetch_smm_metals),
                     ("gangtise", fetch_gangtise)):
        try:
            r = fn()
            if r and r.get("text"):
                refs.append(r)
                print(f"  同行早报 ✓ {name}:《{r['title'][:30]}》{len(r['text'])}字")
            else:
                failed.append(f"{name}(今日未发布或未命中)")
        except Exception as e:
            failed.append(f"{name}({type(e).__name__}: {str(e)[:60]})")
    # gangtise 没拿到 → 元宝镜像兜底(Playwright 登录态, 更稳)
    if not any("gangtise" in (r.get("source") or "") or "元宝" in (r.get("source") or "")
               for r in refs):
        try:
            r = fetch_yuanbao_gangtise()
            if r and r.get("text"):
                refs.append(r)
                print(f"  同行早报 ✓ 元宝·gangtise镜像:《{r['title'][:30]}》{len(r['text'])}字")
        except Exception as e:
            failed.append(f"元宝镜像({type(e).__name__}: {str(e)[:60]})")
    return refs, failed


def fetch_yuanbao_gangtise() -> dict | None:
    """元宝网页版(持久化登录态)问当日 gangtise 日报全文; 未登录返回 None 不阻断。"""
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parent / "yuanbao_fetch.py"
    spec = importlib.util.spec_from_file_location("yuanbao_fetch_mod", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["yuanbao_fetch_mod"] = mod
    spec.loader.exec_module(mod)
    r = mod.run()
    if not r.get("ok") or not r.get("text"):
        return None
    return {"title": f"Gangtise投研日报(元宝镜像)", "text": r["text"][:12000],
            "url": r.get("article_url") or "", "time": r.get("date", ""),
            "media": "元宝/Gangtise", "source": "元宝·Gangtise"}


def fetch_extras() -> dict:
    """版式专用板块数据:事件日历/外围市场/上市公司公告。"""
    extras = {"calendar": [], "markets": [], "announcements": []}
    for key, fn in (("calendar", fetch_calendar),
                    ("markets", fetch_global_markets),
                    ("announcements", fetch_cls_announcements)):
        try:
            extras[key] = fn()
            print(f"  版式数据 ✓ {key}: {len(extras[key])} 条")
        except Exception as e:
            print(f"  ⚠ {key} 获取失败({type(e).__name__}: {str(e)[:60]})")
    return extras


if __name__ == "__main__":
    print("== 同行早报 ==")
    refs, failed = fetch_peer_mornings()
    print("failed:", failed)
    print("== 版式数据 ==")
    print(json.dumps(fetch_extras(), ensure_ascii=False, indent=1)[:1500])
