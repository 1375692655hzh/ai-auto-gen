"""一周财经前瞻 + 财报日历 —— 自包含抓取模块(供外部项目复制, 单文件零配置)。

依赖: pip install requests   (仅此一个三方包, 无需任何 API Key)
口径: 全部北京时间; 条目统一 {"time": "YYYY-MM-DD HH:MM", "text": 中文可读句, "source": 来源名}

四个函数(可按需只用其中几个):
  calendar_week()      一周财经前瞻: 明天起 7 天经济事件(中文, importance>=2, 含预期/前值)
                       —— 华尔街见闻经济日历, 与"今日"口径的日历互补
  earnings_week()      本周美股财报前瞻: 明天起 5 个交易日逐日聚合(家数/代码/盘前盘后/EPS预期)
  earnings_today()     今日美股财报(单条聚合, 与上面的周口径互补)
  ff_calendar_week()   ForexFactory 本周全球经济日历(英文事件名+中文国家, Medium/High 级)
                       —— 注意: 数据域限频很紧, 调用方自行低频(建议 >=4h 一次), 失败属正常

用法(复制本文件后):
    from week_ahead_export import calendar_week, earnings_week
    for it in calendar_week() + earnings_week():
        print(it["time"], it["text"])

直接运行本文件可看演示输出:  python week_ahead_export.py
"""

import datetime
import time as _time

import requests

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_BJ = datetime.timezone(datetime.timedelta(hours=8))


# ── 1. 一周财经前瞻(中文, 明天起 7 天) ──────────────────────────────────────

def calendar_week(page_size: int = 150) -> list:
    """华尔街见闻经济日历·明天起 7 天。importance>=2(2=重要 3=重磅), 中文事件名,
    附预期值; 事件时间官方秒级。失败抛异常(网络类), 调用方自行容错。"""
    now = datetime.datetime.now()
    start = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0)
    r = requests.get(
        "https://api-one-wscn.awtmt.com/apiv1/finance/macrodatas",
        headers={"User-Agent": _UA, "Referer": "https://wallstreetcn.com/calendar"},
        params={"start": int(start.timestamp()), "end": int(start.timestamp()) + 7 * 86400 - 1},
        timeout=15)
    r.raise_for_status()
    items = (r.json().get("data") or {}).get("items") or []
    out = []
    for i in items:
        ts = i.get("public_date") or 0
        imp = int(i.get("importance") or 0)
        event = (i.get("title") or i.get("event") or "").strip()
        if not ts or imp < 2 or not event:
            continue
        head = "【重磅】" if imp >= 3 else ""
        tail = []
        if i.get("forecast"):
            tail.append(f"预期 {i['forecast']}")
        if i.get("actual"):
            tail.append(f"前值 {i['actual']}")
        out.append({"time": datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M"),
                    "text": f"{head}{i.get('country', '')} {event}"
                            + ("：" + " / ".join(tail) if tail else ""),
                    "source": "一周前瞻"})
    out.sort(key=lambda x: x["time"])
    return out[:int(page_size)]


# ── 2/3. 美股财报(纳斯达克官方日历 API, 零鉴权) ─────────────────────────────

def _nasdaq_earnings_date(d: str) -> list:
    r = requests.get("https://api.nasdaq.com/api/calendar/earnings",
                     params={"date": d},
                     headers={"User-Agent": _UA, "Accept": "application/json"}, timeout=15)
    r.raise_for_status()
    return ((r.json().get("data") or {}).get("rows")) or []


def _fmt_rows(rows: list, cap: int = 12) -> str:
    picks = []
    for x in rows[:cap]:
        eps = x.get("epsForecast") or ""
        picks.append(f"{x.get('symbol')}({x.get('time') or ''}"
                     f"{', 预期' + eps if eps else ''})")
    return "、".join(picks)


def earnings_week(max_days: int = 5) -> list:
    """明天起 max_days 个交易日的美股财报, 每天一条聚合(周末/假期空日自动跳过)。
    注意: 内部对 nasdaq API 连发带 0.5s 间隔, 整体耗时约 3-5 秒。"""
    out = []
    day = datetime.datetime.now(_BJ).date() + datetime.timedelta(days=1)
    while len(out) < int(max_days):
        if day.weekday() < 5:                          # 跳过周末
            d = day.strftime("%Y-%m-%d")
            rows = _nasdaq_earnings_date(d)
            if rows:
                wk = "一二三四五六日"[day.weekday()]
                out.append({"time": d,
                            "text": f"周{wk}美股财报 {len(rows)} 家: " + _fmt_rows(rows),
                            "source": "Nasdaq"})
            _time.sleep(0.5)
        day += datetime.timedelta(days=1)
    return out


def earnings_today() -> list:
    """今日美股财报(单条聚合; 非交易日返回空列表)。"""
    today = datetime.datetime.now(_BJ).strftime("%Y-%m-%d")
    rows = _nasdaq_earnings_date(today)
    if not rows:
        return []
    return [{"time": today,
             "text": f"今日美股财报 {len(rows)} 家: " + _fmt_rows(rows),
             "source": "Nasdaq"}]


# ── 4. ForexFactory 本周全球日历(备用, 限频紧) ──────────────────────────────

_FF_COUNTRY = {"USD": "美国", "EUR": "欧元区", "GBP": "英国", "JPY": "日本",
               "AUD": "澳大利亚", "CAD": "加拿大", "CHF": "瑞士", "NZD": "新西兰",
               "CNY": "中国", "SGD": "新加坡", "MXN": "墨西哥", "ALL": "全球"}
_FF_IMPACT = {"High": "重磅", "Medium": "重要", "Holiday": "休市"}


def ff_calendar_week() -> list:
    """ForexFactory 本周经济日历(英文事件名, Medium/High/休市, Low 噪声丢弃)。
    数据域 nfs.faireconomy.media 限频很紧(连抓即 429), 请 >=4h 一次; 429 捕获后
    隔几小时重试即可, 周历本身一周才更新一次, 实时性要求低。"""
    r = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                     headers={"User-Agent": _UA, "Referer": "https://www.forexfactory.com/"},
                     timeout=15)
    r.raise_for_status()
    out = []
    for it in r.json():
        imp = (it.get("impact") or "").strip()
        title = (it.get("title") or "").strip()
        if imp not in _FF_IMPACT or not title:
            continue
        try:
            t = datetime.datetime.fromisoformat(it["date"]).astimezone(_BJ)
        except (KeyError, ValueError):
            continue
        parts = [_FF_COUNTRY.get(it.get("country", ""), it.get("country", "")), title]
        if it.get("forecast"):
            parts.append(f"预期 {it['forecast']}")
        if it.get("previous"):
            parts.append(f"前值 {it['previous']}")
        out.append({"time": t.strftime("%Y-%m-%d %H:%M"),
                    "text": " ".join(p for p in parts if p) + f"（{_FF_IMPACT[imp]}）",
                    "source": "ForexFactory"})
    return out


if __name__ == "__main__":
    print("== 一周财经前瞻(前 8 条) ==")
    for it in calendar_week()[:8]:
        print(f"  {it['time']}  {it['text'][:66]}")
    print("== 本周美股财报 ==")
    for it in earnings_week():
        print(f"  {it['time']}  {it['text'][:90]}")
