# -*- coding: utf-8 -*-
"""finance-all 通道移植(2026-10-15, 原型 E:\\finance-all\\scraper.py 10-14 实测验证)。

11 个新通道接入数据站; 与既有源不重叠:
  富途五栏目(前瞻/午评/收评/盘前/收盘, 全文) / 财联社港股早报+科创板早报(全文) /
  财联社热门榜(全文) / 见闻最热榜(全文, 早餐除外) / 海豚投研(全文) /
  长桥资讯(全文) / 智通财经美股频道(全文) / 金十·市场参考(摘要, NUXT+node) /
  老虎资讯流(摘要) / 富途资讯流(摘要)

正文抓取只对"未见过的条目"做(seen 缓存 7d, data/cache/finance_all_seen.json),
避免每 15min 刷新轮重复抓详情; 列表仍全量返回, 重复入库由 store 去重兜底。
"""
import html as html_mod
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

_BJ = ZoneInfo("Asia/Shanghai")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
_SEEN_PATH = Path(__file__).resolve().parents[2] / "data" / "cache" / "finance_all_seen.json"
_SEEN_TTL = 7 * 86400
_RETAIN_HOURS = 72          # 列表条目时间窗: 超过的不返回(与上游滚动策略一致)

FUTU_COLUMNS = {              # 早报除外——既有源 futu_morning 已覆盖
    "一周前瞻": "富途一周前瞻",
    "港股午评": "富途港股午评",
    "港市速睇": "富途港股收评",
    "美股前瞻": "富途美股盘前",
    "美股收盘": "富途美股收盘",
}
LB_CHANNEL = "WHAB0001"
LB_OP_FILTER = re.compile(r"交易展示会|抽奖|任务币|每日市场热议|活动|CLI 上新")


def _get(url, referer=None, timeout=20):
    headers = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
    if referer:
        headers["Referer"] = referer
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.text


def _get_json(url, referer=None, timeout=20):
    return json.loads(_get(url, referer, timeout))


def _fmt_ts(ts):
    if not ts:
        return datetime.now(_BJ).strftime("%Y-%m-%d %H:%M")
    return datetime.fromtimestamp(int(ts), _BJ).strftime("%Y-%m-%d %H:%M")


def _within_window(ts):
    return not ts or int(ts) >= time.time() - _RETAIN_HOURS * 3600


# ---------- seen 缓存(详情抓取防重) ----------

_seen = None


def _load_seen():
    global _seen
    if _seen is None:
        try:
            _seen = json.load(open(_SEEN_PATH, encoding="utf-8"))
        except Exception:
            _seen = {}
    cutoff = time.time() - _SEEN_TTL
    stale = [k for k, v in _seen.items() if v < cutoff]
    for k in stale:
        _seen.pop(k, None)
    return _seen


def _mark_seen(external_id):
    s = _load_seen()
    s[external_id] = int(time.time())
    try:
        _SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(_SEEN_PATH) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False)
        os.replace(tmp, _SEEN_PATH)
    except OSError:
        pass


def _is_new(external_id):
    return external_id not in _load_seen()


# ---------- HTML 正文提取(上游验证口径) ----------

def _p_texts(fragment):
    out = []
    for p in re.findall(r"<p[^>]*>(.*?)</p>", fragment, flags=re.S):
        t = re.sub(r"<[^>]+>", "", p)
        t = html_mod.unescape(t)
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) >= 15:
            out.append(t)
    return out


def _paragraphs_from_html(html_text):
    """整页 HTML -> 正文段落: 砍 script/style -> h1 截取 -> 砍评论区 -> 取 <p>。"""
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html_text, flags=re.S)
    m = re.search(r"<h1[^>]*>", body)
    if m:
        body = body[m.end():]
    for stop in ['id="comment', 'class="comment', "相关推荐", "猜你喜欢"]:
        mm = re.search(stop, body)
        if mm:
            body = body[:mm.start()]
    return _p_texts(body)


def _next_data(html_text):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html_text, flags=re.S)
    return json.loads(m.group(1)) if m else None


def _item(title, text, url, ts, source, external_id=None):
    return {"time": _fmt_ts(ts), "title": (title or "").strip(),
            "text": (text or "").strip(), "media": source, "source": source,
            "url": (url or "").split("?")[0] or None}


# ---------- 1. 富途五栏目(周期报告, 全文) ----------

def fetch_futu_columns(pages: int = 4) -> list:
    items, seq = [], None
    for _ in range(int(pages)):
        url = "https://news.futunn.com/news-site-api/main/get-market-list?limit=24"
        if seq:
            url += "&seqMark=" + seq
        d = _get_json(url)["data"]
        items += d["list"]
        seq = d.get("seqMark")
        if not d.get("hasMore"):
            break
    out = []
    for i in items:
        if i.get("source") == "快讯":
            continue
        title = (i.get("title") or "").strip()
        prefix = re.split(r"[|｜]", title, 1)[0].strip()
        col = FUTU_COLUMNS.get(prefix)
        if not col:
            continue                      # 非五栏目 → 交给 futu_newsflow 源
        eid = str(i["newsId"])
        ts = int(i["timestamp"]) if i.get("timestamp") else None
        if not _within_window(ts):
            continue
        text = (i.get("abstract") or "").strip()
        if _is_new(eid):
            detail = _futu_detail(eid, url=i.get("url") or "", fallback=text)
            if detail:
                text = detail
                _mark_seen(eid)        # 只有拿到正文才标记, 失败下轮重试
        if not text:
            continue
        out.append(_item(title, text, i.get("url"), ts, "富途资讯"))
    return out


def _futu_detail(eid, url, fallback=""):
    """富途详情: post 页 SSR 全文优先(有限流), 降级 API 摘要。"""
    text = ""
    try:
        time.sleep(0.8)
        text = "\n\n".join(_paragraphs_from_html(_get(url)))
    except Exception:
        pass
    if len(text) < 200:
        try:
            d = _get_json("https://news.futunn.com/news-site-api/detail/get-post-info?id=" + eid)
            ab = ((d.get("data") or {}).get("info") or {}).get("abstract") or ""
            if ab.strip():
                text = ab.strip()
        except Exception:
            pass
    return text or fallback


# ---------- 2/3. 财联社早报专题(8705 港股 / 2012 科创板, 全文) ----------

CLS_SUBJECTS = {"8705": "财联社港股早报", "2012": "财联社科创板早报"}


def fetch_cls_morning_series(subject_id: str) -> list:
    series = CLS_SUBJECTS[subject_id]
    d = _next_data(_get(f"https://www.cls.cn/subject/{subject_id}"))
    arts = d["props"]["pageProps"]["data"]["articles"]
    out = []
    for a in arts[:6]:
        eid = str(a["article_id"])
        ts = int(a["article_time"]) if a.get("article_time") else None
        if not _within_window(ts):
            continue
        text = ""
        if _is_new(eid):
            text = _cls_detail(f"https://www.cls.cn/detail/{eid}")
            if text:
                _mark_seen(eid)
        if not text:
            continue
        out.append(_item(a["article_title"], text,
                         f"https://www.cls.cn/detail/{eid}", ts, series))
    return out


def _cls_detail(url):
    d = _next_data(_get(url))
    return "\n\n".join(_p_texts(d["props"]["pageProps"]["articleDetail"].get("content") or ""))


# ---------- 4. 财联社热门文章榜(全文) ----------

def fetch_cls_hot(page_size: int = 12) -> list:
    html_text = _get("https://www.cls.cn/")
    i = html_text.find("热门文章排行榜")
    seg = html_text[i:i + 15000] if i >= 0 else ""
    out = []
    for url, title in re.findall(r'href="(/detail/\d+)"[^>]*>([^<]{8,80})</a>', seg):
        eid = url.split("/")[-1]
        if _is_new(eid):
            time.sleep(0.3)
            text = _cls_detail("https://www.cls.cn" + url)
            if text:
                _mark_seen(eid)
        else:
            text = ""
        if text:
            out.append(_item(title.strip(), text, "https://www.cls.cn" + url, None, "财联社"))
        if len(out) >= int(page_size):
            break
    return out


# ---------- 5. 见闻最热榜(全文, 早餐除外——wscn_breakfast 已覆盖) ----------

def _wscn_detail(aid):
    d = _get_json(f"https://api-one.wallstcn.com/apiv1/content/articles/{aid}?extract=0")["data"]
    text = "\n\n".join(_p_texts(d.get("content") or ""))
    return text, bool(d.get("is_need_pay") or d.get("is_priced"))


def fetch_wscn_hot(page_size: int = 10) -> list:
    d = _get_json("https://api-one.wallstcn.com/apiv1/content/articles/hot?period=day")["data"]
    out = []
    for a in d.get("day_items", [])[:int(page_size)]:
        title = (a.get("title") or "").strip()
        if not title or "华尔街见闻早餐" in title:
            continue
        eid = str(a["id"])
        ts = int(a["display_time"]) if a.get("display_time") else None
        text = ""
        if _is_new(eid):
            text, _pay = _wscn_detail(eid)
            if text:
                _mark_seen(eid)
        if text:
            out.append(_item(title, text, a.get("uri") or
                             f"https://wallstreetcn.com/articles/{eid}", ts, "华尔街见闻"))
    return out


# ---------- 6. 海豚投研(全文) / 7. 长桥资讯(全文) ----------

def _lb_pair(html_text, link_pat):
    pairs = []
    for m in re.finditer(link_pat + r'[^>]*>.{0,200}?"title":"([^"]{6,90})"', html_text, flags=re.S):
        pairs.append((m.group(1), m.group(2)))
    if not pairs:
        ids = re.findall(link_pat, html_text)
        titles = re.findall(r'"title":"([^"]{6,90})"', html_text)
        for k in range(min(len(ids), len(titles))):
            pairs.append((ids[k], titles[k]))
    return pairs


def _lb_list(path, source, prefix, page_size):
    html_text = _get(f"https://longbridge.com/zh-CN/{path}?channel={LB_CHANNEL}")
    out = []
    for pid, title in _lb_pair(html_text, rf'href="/zh-CN/{prefix}/(\d+)')[:int(page_size)]:
        url = f"https://longbridge.com/zh-CN/{prefix}/{pid}?channel={LB_CHANNEL}"
        eid = f"{prefix}_{pid}"
        text = ""
        if _is_new(eid):
            time.sleep(0.3)
            text = "\n\n".join(_paragraphs_from_html(_get(url)))
            if text:
                _mark_seen(eid)
        if text:
            out.append(_item(title.strip(), text, url, None, source))
    return out


def fetch_lb_dolphin(page_size: int = 10) -> list:
    return _lb_list("dolphin", "海豚投研", "dolphin/post", page_size)


def fetch_lb_news(page_size: int = 15) -> list:
    return _lb_list("news", "长桥资讯", "news", page_size)


# ---------- 8. 智通财经美股频道(全文) ----------

def _detail_safe(fn, *args):
    """详情抓取逐条容错: 失败返回空串(下轮重试), 不炸整源。"""
    try:
        time.sleep(0.3)
        return fn(*args)
    except Exception:
        return ""


def fetch_zhitong_us(pages: int = 2, page_size: int = 30) -> list:
    out, seen_ids = [], set()
    for page in range(1, int(pages) + 1):
        html_text = _get(f"https://www.zhitongcaijing.com/?index=meigu&page={page}",
                         referer="https://www.zhitongcaijing.com/")
        for m in re.finditer(r'<a\s[^>]*href="/content/detail/(\d+)\.html"[^>]*>(.*?)</a>',
                             html_text, flags=re.S):
            pid, inner = m.group(1), m.group(2)
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            title = html_mod.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner))).strip()
            if len(title) < 10:
                continue
            url = f"https://www.zhitongcaijing.com/content/detail/{pid}.html"
            text = ""
            if _is_new(pid):
                text = _detail_safe(lambda: "\n\n".join(
                    _paragraphs_from_html(_get(url, referer="https://www.zhitongcaijing.com/"))))
                if text:
                    _mark_seen(pid)
            if text:
                out.append(_item(title, text, url, None, "智通财经"))
            if len(out) >= int(page_size):
                return out
    return out


# ---------- 9. 金十·市场参考(NUXT + node 求值, 摘要) ----------

_J10_EVAL_JS = (
    "const fs=require('fs');const s=fs.readFileSync(process.argv[1],'utf8');"
    "const i0=s.indexOf('__NUXT__=');const st=s.indexOf('(',i0);"
    "let d=0,en;for(let i=st;i<s.length;i++){if(s[i]==='(')d++;"
    "else if(s[i]===')'){d--;if(d===0){en=i+1;break;}}}"
    "console.log(JSON.stringify(eval(s.slice(st,en))));"
)


def fetch_jin10_market(page_size: int = 20) -> list:
    html_text = _get("https://xnews.jin10.com/53", referer="https://www.jin10.com/")
    i0 = html_text.find("__NUXT__=")
    if i0 < 0:
        raise RuntimeError("no __NUXT__ in xnews page")
    fd, tmp = tempfile.mkstemp(suffix=".html")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(html_text)
        r = subprocess.run(["node", "-e", _J10_EVAL_JS, tmp],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(f"node eval fail: {r.stderr[:200]}")
        nuxt = json.loads(r.stdout)
    finally:
        os.remove(tmp)
    lst = (nuxt.get("data") or [{}])[1].get("list", [])
    out = []
    for x in lst[:int(page_size)]:
        url = x.get("detail_url") or ""
        m = re.search(r"id=(\d+)", url)
        if not m:
            continue
        ts = None
        try:
            ts = int(datetime.strptime(x["display_datetime"], "%Y-%m-%d %H:%M:%S")
                     .replace(tzinfo=_BJ).timestamp())
        except (KeyError, ValueError):
            pass
        out.append(_item(x.get("title") or "", x.get("introduction") or "",
                         url, ts, "金十市场参考"))
    return out


# ---------- 10. 老虎资讯流(摘要) ----------

def fetch_laohu_news(pages: int = 2, page_size: int = 30) -> list:
    base = ("https://stock-news.laohu8.com/v2/highlight/list?pageCount={page}"
            "&lang=zh_CN&lang_content=all&region=CHN&appVer=4.50.1&appName=laohu8"
            "&vendor=web&platform=web&edition=full")
    out = []
    for page in range(1, int(pages) + 1):
        try:
            d = _get_json(base.format(page=page), referer="https://www.laohu8.com/")
        except Exception as e:
            if "91000000" in str(e):
                time.sleep(3)
                d = _get_json(base.format(page=page), referer="https://www.laohu8.com/")
            else:
                raise
        for i in d.get("items", []):
            ts = i.get("pubTimestamp")
            if not _within_window(ts):
                continue
            out.append(_item(i.get("title") or "", i.get("summary") or "",
                             i.get("url"), ts, i.get("media") or "老虎资讯"))
        if len(out) >= int(page_size):
            break
    return out[:int(page_size)]


# ---------- 11. 富途资讯流(标题级快讯; 列表API对文章不带摘要, 全文由重叠的上游源覆盖) ----------

def fetch_futu_newsflow(page_size: int = 24) -> list:
    items, seq = [], None
    for _ in range(4):
        url = "https://news.futunn.com/news-site-api/main/get-market-list?limit=24"
        if seq:
            url += "&seqMark=" + seq
        d = _get_json(url)["data"]
        items += d["list"]
        seq = d.get("seqMark")
        if not d.get("hasMore") or len(items) >= int(page_size):
            break
    out = []
    for i in items:
        if i.get("source") == "快讯":
            continue
        title = (i.get("title") or "").strip()
        prefix = re.split(r"[|｜]", title, 1)[0].strip()
        if prefix in FUTU_COLUMNS:
            continue                     # 栏目类 → futu_columns 源
        ts = int(i["timestamp"]) if i.get("timestamp") else None
        if not _within_window(ts):
            continue
        if title:
            out.append(_item(title, title, i.get("url"), ts, i.get("source") or "富途资讯"))
        if len(out) >= int(page_size):
            break
    return out
