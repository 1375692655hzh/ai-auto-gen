# -*- coding: utf-8 -*-
"""次幂数据 公众号抓取(2026-10-19 接入)。

通道: api.cimidata.com REST(余额计费; 2026-10-19 实测: 当天列表 4/次、正文 v3 1/篇、
搜号后余额 490 起步)。AppID 是 10 位且含前导零(0933535266)——控制台复制极易丢首位,
报 4102「appid无效或过期」先数位数; YAML 里必须加引号否则前导零被吞。token 7 天有效,
缓存 data/cache/cimi_token.json, 余量不足 1 天自动换新。

账号清单走 config.local.yaml sources.cimi_wx.accounts, 每项:
  wxid:        gh_ 开头原始 id(优先; nickname 首查约 30s 内会错一次)
  nickname:    展示名(条目 media 字段)
  daily_stop:  true=当日已成功拉到过文章即停拉(日更早报号省余额), 默认 true
  window:      该账号的抓取时段 "HH:MM-HH:MM"(北京时间), 默认 06:00-08:30
  title_match: 只入库标题含该子串的文章(如 投研日报), 缺省=全收
防重复: seen 文件按 content_url 记账 14 天; 正文失败不标 seen, 窗口内下轮重试。
列表 4/次是主要成本, 无账号时零调用直接返回(源空转不花钱)。
"""
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

_BJ = ZoneInfo("Asia/Shanghai")
_BASE = "https://api.cimidata.com"
_CACHE = Path(__file__).resolve().parents[2] / "data" / "cache"
_TOKEN_PATH = _CACHE / "cimi_token.json"
_SEEN_PATH = _CACHE / "cimi_seen.json"
_DEFAULT_WINDOW = "06:00-08:30"


def _in_window(spec: str) -> bool:
    now = datetime.now(_BJ)
    cur = now.hour * 60 + now.minute
    for win in str(spec or "").split(","):
        m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$", win)
        if not m:
            continue
        a = int(m.group(1)) * 60 + int(m.group(2))
        b = int(m.group(3)) * 60 + int(m.group(4))
        if a <= b:
            if a <= cur < b:
                return True
        elif cur >= a or cur < b:
            return True
    return False


def _load_json(p: Path, default):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def _save_json(p: Path, d) -> None:
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(p) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, p)
    except OSError:
        pass


def _token(app_id: str, app_secret: str) -> str:
    d = _load_json(_TOKEN_PATH, {})
    tok, ts = d.get("token", ""), d.get("ts", 0)
    if tok and time.time() - ts < 6 * 86400:            # 7 天有效, 留 1 天余量换新
        return tok
    r = requests.post(f"{_BASE}/api/v2/token",
                      json={"app_id": app_id, "app_secret": app_secret},
                      headers={"Content-Type": "application/json"}, timeout=20)
    j = r.json()
    tok = (j.get("data") or {}).get("access_token") or ""
    if j.get("code") != 200 or not tok:
        raise RuntimeError(f"次幂数据 token 失败({j.get('code')}): {j.get('msg')} "
                           "(4102=先数 AppID 位数, 前导零易丢)")
    _save_json(_TOKEN_PATH, {"token": tok, "ts": int(time.time())})
    return tok


def _call(path: str, body: dict, app_id: str, app_secret: str) -> dict:
    tok = _token(app_id, app_secret)
    r = requests.post(f"{_BASE}{path}", params={"access_token": tok},
                      json=body, headers={"Content-Type": "application/json"}, timeout=40)
    j = r.json()
    if j.get("code") != 200 and "token" in str(j.get("msg", "")).lower():
        _save_json(_TOKEN_PATH, {})                    # token 失效, 强制换新重试一次
        tok = _token(app_id, app_secret)
        r = requests.post(f"{_BASE}{path}", params={"access_token": tok},
                          json=body, headers={"Content-Type": "application/json"}, timeout=40)
        j = r.json()
    if j.get("code") != 200:
        raise RuntimeError(f"次幂数据 {path} 失败({j.get('code')}): {j.get('msg')}")
    if isinstance(j.get("balance"), (int, float)):     # 每次响应都带余额, 落盘供低额熔断
        _save_json(_CACHE / "cimi_state.json", {"balance": j["balance"], "ts": int(time.time())})
    return j


def _detail_plain(url: str, app_id: str, app_secret: str) -> str:
    j = _call("/api/v3/articles/detail", {"url": url, "need_text": True}, app_id, app_secret)
    return ((j.get("data") or {}).get("plain_text") or "").strip()


def fetch_cimi_wx(conf: dict) -> list:
    app_id = str(conf.get("app_id", ""))
    app_secret = str(conf.get("app_secret", ""))
    accounts = conf.get("accounts") or []
    if not accounts:
        return []                                       # 无账号=零成本空转
    if not app_id or not app_secret:
        raise RuntimeError("cimi_wx 需要 app_id/app_secret: config.local.yaml sources.cimi_wx 段")
    st = _load_json(_CACHE / "cimi_state.json", {})
    if st.get("balance", 10 ** 9) < int(conf.get("min_balance", 15)):
        raise RuntimeError(f"次幂数据余额不足({st.get('balance')}), 充值后再跑")

    seen = _load_json(_SEEN_PATH, {})
    seen = {k: v for k, v in seen.items()
            if not k.startswith("_") and v > time.time() - 14 * 86400}
    daily = seen.get("_daily") or {}
    today = datetime.now(_BJ).strftime("%Y-%m-%d")
    items, errors = [], []
    for acc in accounts:
        wxid, nick = str(acc.get("wxid", "")), str(acc.get("nickname") or wxid)
        if not wxid:
            continue
        if (acc.get("daily_stop", True)) and daily.get(wxid) == today:
            continue                                    # 早报号当日已拉到, 免列表费
        if not _in_window(acc.get("window") or _DEFAULT_WINDOW):
            continue
        try:
            j = _call("/api/v2/articles/current", {"wxid": wxid}, app_id, app_secret)
        except Exception as ex:
            errors.append(f"{nick}: {ex}")
            continue
        match = str(acc.get("title_match") or "").strip()
        for a in j.get("data") or []:
            url, title = a.get("content_url") or "", (a.get("title") or "").strip()
            if not url or url in seen or (match and match not in title):
                continue
            try:
                text = _detail_plain(url, app_id, app_secret)
            except Exception:
                continue                                # 正文失败不标 seen, 下轮重试
            if not text:
                continue
            seen[url] = int(time.time())
            daily[wxid] = today
            pt = (a.get("published_at") or "")[:16]
            items.append({
                "time": pt if re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", pt)
                        else datetime.now(_BJ).strftime("%Y-%m-%d %H:%M"),
                "title": title, "text": text, "url": url,
                "media": nick, "source": f"公众号·{nick}",
            })
    seen["_daily"] = daily
    _save_json(_SEEN_PATH, seen)
    if errors and not items:
        raise RuntimeError("; ".join(errors)[:200])
    return items
