"""X 起爆帖(蹭蹭流量)——互动采集 + 增速/起爆概率计算 + 两页统一数据面。

复刻 SoPilot「评论卡位」闭环的数据侧(方案: docs/workbench-moa/14/15, 裁决合成):
- 采集(CLI 才外呼, 服务器零外呼): 从数据站拉近窗 X 条目 → 提 (handle,status_id) →
  批量调 FxTwitter API 拿 likes/retweets/replies/views 四件套 → 追加时序快照
  data/workbench/x_engagement.json(status_id 为键, 72h 保留, 单帖 96 点, 4000 帖硬顶)。
- 采样(2026-09-04 修复"先截断后跳冷却"的饥饿缺陷): 先按分层冷却(帖龄≤6h→20min,
  ≤24h→60min, 更老→180min)过滤, 再截断 limit——老帖冷却到期后能补采, 覆盖深度
  不再卡在最新 250 条。
- build_view(读缓存+数据站, 无外呼): **主表=窗口内全 X 条目**(author_handle 非空,
  不限池), 快照为可选 join——未采集的新条目照常出现(互动字段为 null), 六选排序
  (fv/time/surge/growth/pred/exposure)对 null 一律沉底。赛道(L1)筛选严格匹配,
  未打标数经 meta.sector_unlabeled_n 透明化。
- 金融价值 FV(2026-09-05 MoA 四家合成定稿, calc_fv 纯规则查表): 六维加总封顶 100
  (事件28+主体22+信源15+影响12+意外10+印证×时效13), 推荐页默认 sort=fv 按
  P0/P1/P2/P3 分组呈现; LLM 不打总分, M1 意外度恒取缺省中性 5。

架构红线: 对板块一只读(经 proxy); 本模块外呼仅发生在 CLI 进程, app.py 端点只读缓存。
"""

import json
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import proxy, x_profile_enricher

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "workbench"
ENGAGE_FILE = DATA_DIR / "x_engagement.json"
TEXTS_FILE = DATA_DIR / "x_surge_texts.json"     # 推文译文缓存 {status_id: {zh, ts}}
RSS_FILE = DATA_DIR / "x_surge_rss.json"         # SoPilot 热帖 RSS 缓存(蹭蹭流量页唯一数据源)
RSS_URL = "https://sopilot.net/rss/hottweets"
RSS_RETAIN_H = 48

RETAIN_H = 72                 # 快照保留窗口
MAX_POINTS = 96               # 单帖快照点上限(超出丢最旧)
MAX_STATUSES = 4000           # 帖子数硬顶(超出按最后快照时间淘汰最旧; 全X化后扩容)
WORKERS = 4                   # FxTwitter 并发
HTTP_TIMEOUT = 8
GOLDEN_H = 2.0                # 黄金窗口: 发布后 2h
_URL_RE = re.compile(r"(?:x|twitter)\.com/(\w+)/status/(\d+)")
_MONTH = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
          "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
_SORTS = ("time", "surge", "growth", "pred", "exposure", "fv")


# ── 缓存读写 ─────────────────────────────────────────────────────────────────
def load_engage() -> dict:
    if not ENGAGE_FILE.is_file():
        return {"version": 1, "updated_at": None, "statuses": {}}
    try:
        d = json.loads(ENGAGE_FILE.read_text(encoding="utf-8"))
        d.setdefault("statuses", {})
        return d
    except Exception:                              # 损坏不炸, 当空库重来
        return {"version": 1, "updated_at": None, "statuses": {}}


def _save_engage(eng: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(eng, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, ENGAGE_FILE)


def load_texts() -> dict:
    if not TEXTS_FILE.is_file():
        return {}
    try:
        return json.loads(TEXTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_texts(t: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(t, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, TEXTS_FILE)


def _prune(eng: dict) -> None:
    """72h 保留 + 单帖 96 点 + 4000 帖硬顶(最久未更新的先淘汰)。"""
    cutoff = time.time() - RETAIN_H * 3600
    for sid in list(eng["statuses"]):
        s = eng["statuses"][sid]
        s["series"] = [p for p in s["series"] if p["ts"] >= cutoff][-MAX_POINTS:]
        if not s["series"]:
            del eng["statuses"][sid]
    if len(eng["statuses"]) > MAX_STATUSES:
        ranked = sorted(eng["statuses"].items(),
                        key=lambda kv: kv[1]["series"][-1]["ts"], reverse=True)
        eng["statuses"] = dict(ranked[:MAX_STATUSES])


# ── 窗口条目(主表数据源; 60s 进程内缓存防筛选切换反复回源) ────────────────────
_win_cache = {"key": None, "at": 0.0, "items": []}
_WIN_TTL = 300.0                           # 5min: 窗口拉一次 ≈ 3000-5000 条计入数据站日配额, 别频繁回源


def _fetch_window(range_h: int, max_pages: int = 5) -> list:
    """拉窗口内全量条目(cursor 翻页)。单页会被并发刷新的非 X 源挤占(实测), 须翻到见底。"""
    import urllib.parse
    key = range_h
    if _win_cache["key"] == key and time.time() - _win_cache["at"] < _WIN_TTL:
        return _win_cache["items"]
    since = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - range_h * 3600))
    items, cursor = [], ""
    for _ in range(max_pages):
        qs = {"limit": 1000, "dedup": 1, "display": 1, "since": since}
        if cursor:
            qs["cursor"] = cursor
        d = proxy.fetch_json("items?" + urllib.parse.urlencode(qs))
        items.extend(d.get("items") or [])
        cursor = d.get("next_cursor") or ""
        if not cursor:
            break
    _win_cache.update({"key": key, "at": time.time(), "items": items})
    return items


def _x_cands(items: list) -> list:
    """条目 → X 候选(handle/status_id/time/url/text), 去重。"""
    seen, cands = set(), []
    for it in items:
        m = _URL_RE.search(it.get("url") or "")
        if not m or not it.get("author_handle"):
            continue
        sid = m.group(2)
        if sid in seen:
            continue
        seen.add(sid)
        cands.append({"handle": m.group(1).lower(), "status_id": sid,
                      "time": it.get("time") or "", "url": it.get("url"),
                      "text": (it.get("text_display") or it.get("text") or "")[:400]})
    cands.sort(key=lambda c: c["time"], reverse=True)
    return cands


# ── 采集(CLI 进程) ───────────────────────────────────────────────────────────
def _age_h_of(c: dict) -> float:
    """候选帖龄(小时), 用条目时间粗算(供分层冷却)。"""
    try:
        t = datetime.strptime(c["time"], "%Y-%m-%d %H:%M").astimezone()
        return max((time.time() - t.timestamp()) / 3600, 0)
    except Exception:
        return 24.0


def _cooldown_s(age_h: float) -> int:
    """分层冷却: 新帖采得勤(增速窗口在头部), 老帖降频(省预算提覆盖)。"""
    if age_h <= 6:
        return 20 * 60
    if age_h <= 24:
        return 60 * 60
    return 180 * 60


def _fetch_one(handle: str, status_id: str) -> dict | None:
    """单帖互动四件套; 失败返回 None(不炸轮)。429 抛 _RateLimited。"""
    url = f"https://api.fxtwitter.com/{handle}/status/{status_id}"
    import urllib.error
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "aag-workbench/0.1"})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            t = json.loads(r.read())["tweet"]
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise _RateLimited()
        return None
    except Exception:
        return None

    def num(d, k):
        v = (d.get(k) or {})
        return v.get("count") if isinstance(v, dict) else v
    return {"l": num(t, "likes"), "r": num(t, "retweets"),
            "p": num(t, "replies"), "v": num(t, "views"),   # views 可能缺失→None
            "created_at": t.get("created_at") or ""}


class _RateLimited(Exception):
    pass


def collect(range_h: int = 24, limit: int = 300, force: bool = False) -> dict:
    """一轮采集: 全量候选→先跳冷却→再截断→并发拉→追加快照→原子落盘→顺带补翻译。"""
    eng = load_engage()
    now = time.time()
    cands = _x_cands(_fetch_window(range_h))
    todo, skip_cd = [], 0
    for c in cands:                                # 先跳冷却, 后截断(修采样饥饿)
        s = eng["statuses"].get(c["status_id"])
        if not force and s and s["series"] and \
                now - s["series"][-1]["ts"] < _cooldown_s(_age_h_of(c)):
            skip_cd += 1
            continue
        todo.append(c)
    todo = todo[:limit]

    ok = fail = 0
    circuit = False
    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(_fetch_one, c["handle"], c["status_id"]): c for c in todo}
            for fu, c in futs.items():
                try:
                    got = fu.result()
                except _RateLimited:
                    circuit = True          # 全局熔断: 剩余任务取消, 本轮到此为止
                    break
                except Exception:
                    got = None
                if got is None:
                    fail += 1
                    continue
                s = eng["statuses"].setdefault(
                    c["status_id"], {"handle": c["handle"], "url": c["url"], "series": []})
                s["handle"] = c["handle"]   # local 池可能改名, 以最新为准
                s["url"] = c["url"]
                s["series"].append({"ts": now, **got})
                ok += 1
    except Exception:
        pass

    if ok == 0 and fail == 0 and circuit:
        rep = {"todo": len(todo), "ok": 0, "failed": 0, "skip_cooldown": skip_cd,
               "circuit_break": True, "msg": "FxTwitter 429 熔断, 保留旧快照"}
        print(json.dumps(rep, ensure_ascii=False))
        return rep
    if ok or not circuit:                       # 有增量或非熔断(纯失败也记时间戳)才落盘
        eng["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _prune(eng)
        _save_engage(eng)
    rep = {"candidates": len(cands), "todo": len(todo), "ok": ok, "failed": fail,
           "skip_cooldown": skip_cd, "circuit_break": circuit,
           "tracked": len(eng["statuses"]), "cache": str(ENGAGE_FILE)}
    rep.update(translate_pending(cands))        # 采集完顺带补翻译(配置了才生效)
    print(json.dumps(rep, ensure_ascii=False))
    return rep


# ── 翻译(设置页可配 OpenAI 兼容端点; 缓存 data/workbench/x_surge_texts.json) ──
_ZH_RE = re.compile(r"[\u4e00-\u9fff]")


def _is_zh(s: str) -> bool:
    """粗判已是中文: 每 30 字里有一个汉字就算(标题夹英文缩写不算外文)。"""
    s = s or ""
    return bool(s) and len(_ZH_RE.findall(s)) * 30 >= len(s)


def _call_translate(base: str, key: str, model: str, text: str) -> str | None:
    import urllib.error
    import urllib.request
    body = json.dumps({
        "model": model, "temperature": 0.2, "max_tokens": 600,
        "messages": [
            {"role": "system",
             "content": "你是专业财经翻译。把推文翻译成简体中文: 保留专有名词/股票代码/"
                        "链接/数字原样, 语气从简, 只输出译文, 不要任何解释。"},
            {"role": "user", "content": text}],
    }).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read())
        return (d["choices"][0]["message"]["content"] or "").strip() or None
    except Exception:
        return None


def translate_pending(cands: list, limit: int = 60) -> dict:
    """给候选里没译文的补翻译; 已是中文的直接记原生; 未配置则静默跳过。"""
    from . import config as wb_config
    cfg = wb_config.load().get("translate") or {}
    base, key, model = cfg.get("base_url"), cfg.get("api_key"), cfg.get("model")
    cache = load_texts()
    now_s = time.strftime("%Y-%m-%d %H:%M:%S")
    zh_native = 0
    todo = []
    for c in cands:
        if c["status_id"] in cache:
            continue
        if _is_zh(c["text"]):
            cache[c["status_id"]] = {"zh": c["text"], "ts": now_s}
            zh_native += 1
        else:
            todo.append(c)
    if not (base and key and model):
        if zh_native:
            _save_texts(cache)
        return {"translated": 0, "translate_failed": 0, "zh_native": zh_native,
                "pending": len(todo), "skipped": "translate 未配置, 跳过"}
    todo = [c for c in todo if len((c["text"] or "").strip()) >= 8][-limit:]  # 空文本不送翻
    ok = fail = 0
    for i, c in enumerate(todo):
        if i:                                        # 轻微间隔, 防 API 限流
            time.sleep(0.25)
        zh = _call_translate(base, key, model, c["text"])
        if zh:
            cache[c["status_id"]] = {"zh": zh, "ts": now_s}
            ok += 1
        else:
            fail += 1
    if ok or zh_native:
        _save_texts(cache)
    return {"translated": ok, "translate_failed": fail, "zh_native": zh_native,
            "pending": max(len(todo) - ok - fail, 0)}


# ── 指标(读缓存+数据站, 无外呼; app.py 端点用) ────────────────────────────────
def _parse_created(s: str) -> float | None:
    """FxTwitter created_at → epoch; 两路都挂返回 None。"""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y").timestamp()
    except Exception:
        pass
    try:                                        # Windows locale 兜底: 手写月名
        p = s.split()
        dt = datetime(int(p[5]), _MONTH[p[1]], int(p[2]),
                      *(int(x) for x in p[3].split(":")), tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def _tiers(v, table) -> int:
    for th, score in table:
        if v is not None and v >= th:
            return score
    return table[-1][1]


_T1 = [(2.0, 40), (1.0, 32), (0.5, 24), (0.2, 16), (0.05, 8), (1e-9, 3), (0, 0)]
_T2 = [(3.0, 30), (1.5, 24), (0.8, 18), (0.3, 12), (0.1, 6), (1e-9, 5), (0, 0)]
_T3 = [(1.0, 20), (2.0, 16), (4.0, 10), (8.0, 6), (16.0, 3), (24.0, 1), (1e9, 0)]
_T4 = [(100_000, 10), (30_000, 7), (10_000, 4), (2_000, 2), (500, 1), (0, 0)]


# ── 金融价值 FV(M1 纯规则查表; MoA grok+codex+kimi+gemini 合成裁决 2026-09-05) ─
# 六维加总封顶 100: 事件28 + 主体22 + 信源15 + 影响12 + 意外10 + 印证×时效13。
# LLM 不打总分(红线): 意外度 M3 接打标前恒取缺省中性 5; 阈值首周 75/60/40, M4 校准。
_FV_EVENT = {"macro": 28, "policy": 26, "legal": 24,             # 央行/政策/制裁地缘级
             "guidance": 20, "mna": 20, "earnings": 16,          # 指引/并购/财报
             "contract": 13, "product": 13, "fda": 12, "offering": 10,
             "dividend": 6, "rating": 6, "personnel": 5}         # 点评级
_FV_MACRO_RE = re.compile(
    r"FOMC|美联储|联邦储备|ECB|日本央行|央行|非农|关税|出口管制|实体清单|制裁|地缘|空袭|停火", re.I)
_FV_REVISION_RE = re.compile(r"修订|修正|终值|revised|revision", re.I)
_FV_T1_TICKERS = {"NVDA", "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "TSLA",
                  "TSM", "ASML", "AVGO", "AMD", "MU", "000660"}   # mega-cap+卡点(M2 外置)
_FV_T1_TEXT_RE = re.compile(
    r"美联储|FOMC|ECB|日本央行|央行|财政部|白宫|台积电|TSMC|ASML|阿斯麦|英伟达|海力士|"
    r"美光|博通|CoWoS|HBM|EUV|CPO|硅光|光模块", re.I)
_FV_HOT_L2 = ("HBM", "CPO", "EUV", "CoWoS", "光模块", "硅光", "先进制程")
_FV_SOURCE = {"官方": 15, "机构": 12, "快讯源": 8, "新闻源": 6, "大V": 5}
_FV_TIERS = ((75, "P0"), (60, "P1"), (40, "P2"))                 # 首周临时, 校准后 80/65/45


def calc_fv(it: dict, age_h: float) -> dict:
    """金融价值分(纯规则, 缺字段走中性/保守档, 全程可复盘): {score, tier, parts}。"""
    text = it.get("text_display") or it.get("text") or ""
    sectors = it.get("sectors") or []
    tickers = it.get("tickers") or []
    markets = it.get("markets") or []

    # D1 事件类型(28): 枚举查表 + 宏观/地缘关键词托底; 修订/终值 −6
    ev = _FV_EVENT.get(it.get("event_type") or "", 2)
    if _FV_MACRO_RE.search(text):
        ev = max(ev, 24)
    if _FV_REVISION_RE.search(text):
        ev = max(ev - 6, 2)

    # D2 主体(22): T1 词典(tickers∩ 或文本命中)=22; 热点赛道路径=12; 有 ticker=8; 无=2
    if set(tickers) & _FV_T1_TICKERS or _FV_T1_TEXT_RE.search(text):
        ent = 22
    elif any(k in str(s) for s in sectors for k in _FV_HOT_L2):
        ent = 12
    elif tickers:
        ent = 8
    else:
        ent = 2

    # D3 信源(15): 条目定位直查(X 池账号由 author_role 派生, store 已写入)
    src = _FV_SOURCE.get(it.get("positioning") or "", 3)

    # D4 影响面(12): 市场广度; 无市场有赛道给保底
    if len(markets) >= 3 or "全球" in markets:
        imp = 12
    elif len(markets) == 2:
        imp = 8
    elif len(markets) == 1:
        imp = 5
    elif sectors:
        imp = 3
    else:
        imp = 0

    sur = 5                                        # D5 意外度(10): M1 恒缺省中性
    dup = int(it.get("dup_count") or 1)
    proof = 7 if dup >= 5 else 5 if dup >= 3 else 3 if dup >= 2 else 1
    fresh = (6 if age_h <= 2 else 5 if age_h <= 6 else 3 if age_h <= 24
             else 1 if age_h <= 72 else 0)         # D6 印证×时效(13)

    score = min(ev + ent + src + imp + sur + proof + fresh, 100)
    if ev >= 24 and src >= 15:                     # 硬规则: 官方源宏观级事件保底 P0
        score = max(score, 80)
    if ev <= 6 and ent <= 2:                       # 硬规则: 低值事件且无主体封顶 P2 下
        score = min(score, 40)
    tier = next((t for th, t in _FV_TIERS if score >= th), "P3")
    return {"score": score, "tier": tier,
            "parts": {"event": ev, "entity": ent, "source": src,
                      "impact": imp, "surprise": sur, "proof": proof + fresh}}


def build_view(range_h: int = 24, golden: bool = False, market: str = "",
               sector: str = "", min_followers: int = 0, finance: bool = False,
               sort: str = "time", limit: int = 100) -> dict:
    """主表=窗口内全 X 条目, 快照可选 join → 六选排序。绝不外呼。

    sort: fv(金融价值, 推荐页默认) | time(发布时间降序) | surge(起爆概率) |
          growth(浏览增速) | pred(预测浏览) | exposure(评论曝光)。
          None 一律沉底, 平分按 views 降序。
    """
    range_h = min(max(int(range_h), 1), 48)
    sort = sort if sort in _SORTS else "time"
    eng = load_engage()
    texts = load_texts()
    now = time.time()
    data_age_min = None
    if eng.get("updated_at"):
        try:
            data_age_min = int((now - datetime.strptime(
                eng["updated_at"], "%Y-%m-%d %H:%M:%S").timestamp()) / 60)
        except Exception:
            pass

    profiles = x_profile_enricher.load_cache()["profiles"]
    rows, sector_counter = [], {}
    for it in _fetch_window(range_h):
        m = _URL_RE.search(it.get("url") or "")
        if not m or not it.get("author_handle"):
            continue                             # 非 X 条目不进这两页
        sid, handle = m.group(2), m.group(1).lower()
        s = eng["statuses"].get(sid)
        series = (s or {}).get("series") or []
        last = series[-1] if series else None
        has_engage = last is not None
        views = last.get("v") if last else None
        likes = last.get("l") if last else None
        followers = (profiles.get(handle) or {}).get("followers")   # 可能 None(非池)

        created_ts = _parse_created((last or {}).get("created_at") or "")
        if created_ts is None and it.get("time"):
            try:
                created_ts = datetime.strptime(it["time"], "%Y-%m-%d %H:%M") \
                    .astimezone().timestamp()
            except Exception:
                pass
        age_h = max((now - created_ts) / 3600, 0) if created_ts else 24.0

        # 增速: 最近两点差/时间差(≥5min 防抖)
        g_views = g_likes = None
        if len(series) >= 2:
            s1, s2 = series[-2], series[-1]
            span_h = (s2["ts"] - s1["ts"]) / 3600
            if span_h >= 5 / 60 and s1.get("v") is not None and s2.get("v") is not None:
                g_views = (s2["v"] - s1["v"]) / span_h
                g_likes = ((s2.get("l") or 0) - (s1.get("l") or 0)) / span_h \
                    if s1.get("l") is not None else None

        # 起爆四分量: 粉丝缺失→S1/S2 记 0(防千粉基数放大失真), 无快照→整体退化
        fbase = followers if followers else None
        rate_norm = (g_views * 1000 / fbase) if (g_views is not None and fbase) else None
        ratio = (views / fbase) if (views is not None and fbase) else None
        if has_engage:
            s1v = _tiers(rate_norm, _T1)
            s2v = _tiers(ratio, _T2)
            s3v = _tiers(age_h, _T3)
            s4v = _tiers(views, _T4)
            surge = min(s1v + s2v + s3v + s4v, 100)
        else:
            s1v = s2v = s3v = s4v = surge = 0
        views_pred = round(views * (1 + 3 / max(age_h, 0.5))) if views is not None else None
        if views_pred is not None:
            views_pred = min(views_pred, views * 4)

        sectors = it.get("sectors") or []
        sector_l1 = str(sectors[0]).split(">")[0] if sectors else ""
        if sector_l1:
            sector_counter[sector_l1] = sector_counter.get(sector_l1, 0) + 1
        fv = calc_fv(it, age_h)

        rows.append({
            "status_id": sid, "handle": handle,
            "name": re.sub(r"^X·", "", it.get("source") or "@" + handle),
            "followers": followers, "time": it.get("time"), "age_h": round(age_h, 1),
            "text": (it.get("text_display") or it.get("text") or "")[:200],
            "text_zh": (texts.get(sid) or {}).get("zh"),
            "finance": bool(sectors or it.get("tickers") or it.get("event_type")),
            "sector_l1": sector_l1,
            "url": s["url"] if s else it.get("url"),
            "reply_url": f"https://x.com/{handle}/status/{sid}",
            "markets": it.get("markets") or [],
            # 标签对齐资讯页(双标签制): 条目级标签原样透传, 供卡片徽章与 FV 复盘
            "positioning": it.get("positioning") or "",
            "sectors": sectors,
            "tickers": it.get("tickers") or [],
            "event_type": it.get("event_type") or "",
            "sentiment": it.get("sentiment") or "",
            "dup_count": int(it.get("dup_count") or 1),
            "likes": likes, "retweets": last.get("r") if last else None,
            "replies": last.get("p") if last else None, "views": views,
            "growth_views_h": round(g_views) if g_views is not None else None,
            "has_engage": has_engage, "golden": age_h <= GOLDEN_H,
            "surge": surge, "views_pred": views_pred,
            "reply_exposure": int(views * 0.10) if views is not None else None,
            "surge_parts": {"growth": s1v, "baseline": s2v, "decay": s3v, "abs": s4v},
            "fv_score": fv["score"], "fv_tier": fv["tier"], "fv_parts": fv["parts"],
        })

    # 排序(None 沉底, 平分按 views 降序; surge 走 has_engage 门禁防退化分参排)
    def sort_key(r):
        v = r["views"] or 0
        if sort == "fv":
            return (r["fv_score"], v)
        if sort == "time":
            return (r["time"] or "", v)
        if sort == "surge":
            return (r["surge"] if r["has_engage"] else -1, v)
        if sort == "growth":
            return (r["growth_views_h"] if r["growth_views_h"] is not None else -1, v)
        if sort == "pred":
            return (r["views_pred"] if r["views_pred"] is not None else -1, v)
        return (r["reply_exposure"] if r["reply_exposure"] is not None else -1, v)

    sectors_l1 = sorted(sector_counter.items(), key=lambda kv: -kv[1])
    total = len(rows)
    golden_n = sum(1 for r in rows if r["golden"])
    if golden:
        rows = [r for r in rows if r["golden"]]
    if market:
        wants = [x.strip() for x in market.split(",") if x.strip()]
        rows = [r for r in rows if any(w in (r["markets"] or []) for w in wants)]
    if sector:
        rows = [r for r in rows if r["sector_l1"] == sector]
    if min_followers > 0:
        rows = [r for r in rows if (r["followers"] or 0) >= min_followers]  # 未知粉丝严格排除
    if finance:
        rows = [r for r in rows if r["finance"]]
    rows.sort(key=sort_key, reverse=True)
    return {"items": rows[:limit], "total": total, "golden_n": golden_n,
            "sector_unlabeled_n": sum(1 for r in rows if not r["sector_l1"]),
            "meta": {"data_age_min": data_age_min, "tracked": len(eng["statuses"]),
                     "updated_at": eng.get("updated_at"), "sort": sort,
                     "sectors_l1": sectors_l1,
                     "rule": "FV金融价值=事件28+主体22+信源15+影响12+意外10(缺省5)+印证时效13; "
                             "首周阈值 P0≥75/P1≥60/P2≥40; 评论曝光≈views×10%; 黄金窗口=发布≤2h"}}


def run_cli(args) -> int:                        # 保留 CLI 直调入口形状(cli.py 未用, 备用)
    collect(range_h=48 if args.range == "48h" else 24,
            limit=args.limit, force=args.force)
    return 0


# ── SoPilot 热帖 RSS(蹭蹭流量页唯一数据源; 公开 RSS, 采集仅在 CLI 进程) ────────
def load_rss() -> dict:
    if not RSS_FILE.is_file():
        return {"updated_at": None, "items": {}}
    try:
        d = json.loads(RSS_FILE.read_text(encoding="utf-8"))
        d.setdefault("items", {})
        return d
    except Exception:
        return {"updated_at": None, "items": {}}


def _save_rss(d: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, RSS_FILE)


def fetch_rss() -> dict:
    """拉 SoPilot 热帖 RSS → 解析 → 合并进缓存(按 tweet_id 去重, 48h 保留)。

    RSS item 形状(实测): title='名字 (@handle)'; description=正文 + 
    '❤️ 33 🔁 0 💬 7 🔖 3 👀 16405' + '预测爆火概率:100%，预测浏览量:246000，
    预测评论浏览量:2900' + '原推链接: https://x.com/...'。解析容错: 单条坏不炸轮。
    """
    import urllib.request
    import xml.etree.ElementTree as ET
    req = urllib.request.Request(RSS_URL, headers={"User-Agent": "aag-workbench/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        xml_text = r.read().decode("utf-8", "replace")
    root = ET.fromstring(xml_text)
    now_s = time.strftime("%Y-%m-%d %H:%M:%S")
    cache = load_rss()
    ok = bad = 0
    for item in root.iter("item"):
        try:
            title = (item.findtext("title") or "").strip()
            desc = (item.findtext("description") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            link = (item.findtext("link") or "").strip()
            mh = re.search(r"\(@([A-Za-z0-9_]+)\)\s*$", title)
            mtid = re.search(r"tweetId=(\d+)", link) or re.search(r"status/(\d+)", desc)
            if not mh or not mtid:
                bad += 1
                continue
            handle, sid = mh.group(1), mtid.group(1)
            name = title[:mh.start()].strip()
            # description 分段: 正文 / 互动行 / 预测行 / 原推链接
            lines = [x.strip() for x in desc.splitlines() if x.strip()]
            text_lines, eng, pred, orig = [], None, None, ""
            for ln in lines:
                if ln.startswith("❤️"):
                    eng = ln
                elif ln.startswith("预测爆火概率"):
                    pred = ln
                elif ln.startswith("原推链接"):
                    orig = ln
                elif eng is None and pred is None:
                    text_lines.append(ln)
            me = re.search(r"❤️\s*(\d+)\s*🔁\s*(\d+)\s*💬\s*(\d+)\s*🔖\s*(\d+)\s*👀\s*(\d+)", eng or "")
            mp = re.search(r"预测爆火概率[:：]\s*(\d+)\s*%?\s*[，,]\s*预测浏览量[:：]\s*(\d+)\s*[，,]\s*预测评论浏览量[:：]\s*(\d+)", pred or "")
            mo = re.search(r"https://x\.com/\w+/status/\d+", orig)
            cache["items"][sid] = {
                "tweet_id": sid, "handle": handle.lower(), "name": name,
                "text": "\n".join(text_lines)[:400],
                "likes": int(me.group(1)) if me else None,
                "retweets": int(me.group(2)) if me else None,
                "replies": int(me.group(3)) if me else None,
                "bookmarks": int(me.group(4)) if me else None,
                "views": int(me.group(5)) if me else None,
                "prob": int(mp.group(1)) if mp else None,          # SoPilot 爆火概率
                "views_pred": int(mp.group(2)) if mp else None,
                "exposure_pred": int(mp.group(3)) if mp else None,  # 它的预测评论浏览量
                "url": mo.group(0) if mo else f"https://x.com/{handle}/status/{sid}",
                "pub": pub, "fetched_at": now_s,
            }
            ok += 1
        except Exception:
            bad += 1
    # 48h 保留(按抓取时间)
    cutoff = time.time() - RSS_RETAIN_H * 3600
    for sid in list(cache["items"]):
        try:
            if datetime.strptime(cache["items"][sid]["fetched_at"],
                                 "%Y-%m-%d %H:%M:%S").timestamp() < cutoff:
                del cache["items"][sid]
        except Exception:
            pass
    cache["updated_at"] = now_s
    _save_rss(cache)
    # 顺带补翻译(和自产榜同一套配置)
    cands = [{"status_id": sid, "text": it["text"]} for sid, it in cache["items"].items()]
    tr = translate_pending(cands, limit=40)
    rep = {"rss_items": ok, "rss_bad": bad, "tracked": len(cache["items"]), **tr}
    print(json.dumps(rep, ensure_ascii=False))
    return rep


def rss_view(sort: str = "prob", limit: int = 100) -> dict:
    """蹭蹭流量页(RSS 版): 读缓存排序, 无外呼。sort= prob|views|exposure|time。"""
    cache = load_rss()
    rows = []
    for sid, it in cache["items"].items():
        t_local = it["pub"]
        try:                                         # GMT 原文 → 本地可读
            t_local = datetime.strptime(it["pub"], "%a, %d %b %Y %H:%M:%S %Z") \
                .astimezone().strftime("%m-%d %H:%M")
        except Exception:
            pass
        rows.append({
            "status_id": sid, "handle": it["handle"], "name": it["name"],
            "text": it["text"], "text_zh": (load_texts().get(sid) or {}).get("zh"),
            "time": t_local, "url": it["url"],
            "reply_url": f"https://x.com/{it['handle']}/status/{sid}",
            "likes": it["likes"], "retweets": it["retweets"], "replies": it["replies"],
            "bookmarks": it["bookmarks"], "views": it["views"],
            "prob": it["prob"], "views_pred": it["views_pred"],
            "exposure": it["exposure_pred"],
        })

    def key(r):
        v = r["views"] or 0
        if sort == "views":
            return (r["views"] or -1, v)
        if sort == "exposure":
            return (r["exposure"] if r["exposure"] is not None else -1, v)
        if sort == "time":
            return (r["time"] or "", v)
        return (r["prob"] if r["prob"] is not None else -1, v)

    rows.sort(key=key, reverse=True)
    return {"items": rows[:limit], "total": len(rows),
            "meta": {"updated_at": cache.get("updated_at"), "source": "sopilot-rss",
                     "rule": "数据源: SoPilot 今日热帖公开 RSS; 爆火概率/预测浏览/评论曝光为其服务端口径"}}
