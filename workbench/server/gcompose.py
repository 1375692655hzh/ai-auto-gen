"""内容生成·成稿编排(一期) —— 素材→检索补全→行情快照→技术位→观点聚合→LLM成稿。

架构同 vstudio: 服务器端点零外呼(仅 begin_job + spawn CLI + 轮询);
外网行情(yfinance)/LLM(chat_completions 走设置页翻译链配置)全在 CLI 子进程。
红线7: 板块一只读(retrieve 复用 proxy GET /v1/items + importlib tagger);
产物只写 data/workbench/gen_jobs.json + gen_posts/<id>.json + gen_assets/<id>/*.png。

字数闸: X 计权规则(CJK 每字计 2, 其余计 1), 免费 280 / 付费 25000;
一期自实现加权计数(离线零依赖), 后续若引入 twitter-text 官方库可整体替换。
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import config, proxy, retrieve, vstudio

DATA_DIR = config.DATA_DIR
JOBS_FILE = DATA_DIR / "gen_jobs.json"
POSTS_DIR = DATA_DIR / "gen_posts"
ASSETS_DIR = DATA_DIR / "gen_assets"

MODULES = ("retrieve", "snapshot", "tech", "aggregate")
PLATFORMS = ("x",)
LANGS = {"en": "English", "zh-CN": "简体中文", "zh-TW": "繁體中文",
         "ja": "日本語", "yue": "粵語(香港財經媒體書面語)"}
TEMPLATES = ("catalyst-take", "earnings-print", "macro-print", "policy-call",
             "tape-recap", "thesis-note", "risk-flag", "thread-post",
             "news-flash", "fact-sheet", "week-ahead", "earnings-watch", "funding-trail")
TPL_DEFAULT = "catalyst-take"
_TPL_LEGACY = {"short": "catalyst-take", "morning": "tape-recap", "digest": "thesis-note"}
# 零观点信息披露类(2026-09-07 codex+grok 综合): 骨架内嵌禁观点约束, 后端再硬剔观点标记行
ZERO_OPINION_TEMPLATES = ("news-flash", "fact-sheet", "week-ahead",
                          "earnings-watch", "funding-trail")
TIER_LIMIT = {"free": 280, "paid": 25000}
CHART_CAP = 2                # 单次最多出几张行情图
OPINION_CAP = 8              # 聚合分析每组观点条数上限

_X_STYLE = """你是 X(Twitter) 平台财经写手。铁律:
- 首行 hook = 结论 + $代码(或最有冲击力的数字), 单独成行——时间线约 280 字符处折叠, 折叠前必须能停滑
- 短句短段, 每段不超过两句, 多用换行; 数字+方向先于形容词
- 标的首次出现写成 $CASHTAG 内联在句中(如 $NVDA), 可点可进图表页; 已内联的 cashtag 禁止再在末尾堆叠(2026-09-07 grok 调研定稿: X 无独立标签字段, 正文是唯一载体)
- hashtag 默认不带(X 算法不加分, Elon 公开称系统不需要), 最多 1 个放末尾; 禁用 #stocks 类宽泛标签
- 成稿是作者自己的内容: 正文不放任何链接——素材里的来源链接/t.co 短链仅供你理解上下文, 一律禁止带进成稿(2026-09-06 用户拍板)
- 不用"重磅/速看"式营销词; 禁止编造输入里不存在的数据、引语或来源; 事实与观点分行陈述; 涉及预测必须标注不确定性
- 观点标记用 X 财经圈惯用的 "My take:" 或 "Bottom line:"(二选一), 禁用 "View:" 这类终端机风格标记
- 同一关键词(如 CPI/$NVDA/yields)每帖出现不超过 2 次, hook 与正文避免同词重复
- 模板骨架里的局部约束(如零观点模板的禁观点标记)优先于上述通用规则"""

# 成稿模板 = 信息结构(2026-09-07 grok 定稿, 7 模板定位不重叠: 突发单票/财报/数据打印/
# 官方决策/盘面/论点/风险); 长短由免费·付费档位决定——免费档只留 Hook+1 块事实,
# 付费档骨架全开; 缺料的节一律省略, 禁止编造。每项 = (中文名, 免费档骨架, 付费档骨架)。
_TPL_SCAFFOLD = {
    "thread-post": ("串推",
        "3-5 条串推: 1/ 钩子+最强数字前置(主$cashtag) → 每条一个节拍(自带主语和数字, 禁回指词) → 末条 Bottom line 结论+互动钩子",
        "5-8 条串推: 1/ 钩子+最强数字前置 → 事实/机制/反方各成条(每条自带主语和数字, 禁回指词) → 末条 Bottom line 结论+风险+互动钩子"),
    "catalyst-take": ("事件快评",
        "Hook(结论+主$cashtag) → 事件详情(谁/何时/关键数字, ≤2句) → 有行情加半句即时定价 → 一句观点(含不确定性)",
        "Hook(结论+主$cashtag) → 事件详情(谁/何时/关键数字) → 即时定价(涨跌/量, 缺行情省) → 机制(为何这样定价) → 市场共识/分歧(缺观点省, 最多2条对立转述) → 技术参考(支撑/阻力, 缺省) → 下一催化(标不确定性)"),
    "earnings-print": ("业绩拆解",
        "Hook(beat/miss+指引方向+主$cashtag) → 1个最超预期数字(vs预期) → 一句定价含义",
        "Hook(beat/miss+指引方向+主$cashtag) → 核心数字(营收/EPS/利润率 vs 预期, 并列短行) → 指引与口径(无则省) → 盘后/盘中反应(缺行情省) → 卖侧/大V拆解(缺观点省) → 关键位(缺省) → 下季观察(标不确定性)"),
    "macro-print": ("数据读数",
        "Hook(读数vs预期+利率含义) → 1个核心分项 → 一句观点(含不确定性)",
        "Hook(读数vs预期+利率含义) → 分项与修订 → 股债汇金即时反应(缺行情省) → 机制(政策路径/实际利率) → 共识漂移(缺观点省) → 下一数据/会议(标不确定性)"),
    "policy-call": ("政策纪要",
        "Hook(决定+措辞/点阵偏移) → 1条最关键措辞变化 → 一句含义(含不确定性)",
        "Hook(决定+措辞/点阵偏移) → 要点(票委/工具/关键词) → 与预期差 → 跨资产反应(缺行情省) → 路径情景(分档, 标不确定性) → 指数关键位(缺省)"),
    "tape-recap": ("盘面综述",
        "Hook(今日主线+1-2个主$cashtag) → 指数一句 → 1个领涨/领跌 → 一句观点",
        "Hook(今日主线+主$cashtag) → 指数/广度/成交 → 板块领涨跌(可分节【宏观】【板块】【个股】) → 异动个股各1句事实 → 市场共识(缺观点省) → 明日关注"),
    "thesis-note": ("深度观点",
        "Hook(论点一句+主$cashtag) → 1个事实底座 → 1句机制 → 反方半句",
        "Hook(论点一句+主$cashtag) → 事实底座 → 正方机制 → 反方/证伪条件(必须有) → 价与位(缺行情/技术省) → 时间与仓位表达(标不确定性)"),
    "risk-flag": ("风险提示",
        "Hook(风险是什么+主$cashtag) → 触发事实(≤2句) → 一句失效条件。禁止写成买入论点",
        "Hook(风险是什么+主$cashtag) → 触发事实 → 暴露/拥挤度(缺观点省) → 已定价程度(缺行情省) → 失效条件(标不确定性)。禁止展开正方机制, 禁止写成买入论点"),
    "news-flash": ("资讯速递",
        "【零观点: 禁止 View/My take/我认为/利好利空等评价词, 只陈述已发生事实】首行=什么事+主$cashtag(无评价词) → 关键数字/引语(≤2行) → 来源+时间",
        "【零观点: 禁止观点标记与评价词; 引述他人观点须署名来源】首行=什么事+主$cashtag → 关键数字/引语 → 客观背景1行 → 事件时间线(缺料省) → 各方反应(须署名, 缺观点省) → 后续待披露节点"),
    "fact-sheet": ("披露卡",
        "【零观点: 禁止观点标记/利好利空措辞】首行=$T 披露了什么 → 要点清单≤3条(数字优先, 一行一条)",
        "【零观点: 禁止观点标记/利好利空措辞】首行=$T 披露了什么 → 要点清单3-5条(数字优先, 一行一条) → 同比/环比对照(缺行情省) → 后续时间节点(电话会/生效日, 缺料省)"),
    "week-ahead": ("一周日历",
        "【零观点】首行=下周N个关注点 → 按日分组一行一条: `9/8 Mon 美CPI est 2.9%`(≤8条, 同日按重要性降序; 英文行≤30字符, CJK行≤14字)",
        "【零观点】首行=下周N个关注点 → 按日分节, 一行一条含 时间/事件/预期/前值/关注理由(理由=中性事实非观点) → 可按资产分节"),
    "earnings-watch": ("财报前瞻",
        "【零观点】首行=本周N家发财报 → 按日分组一行一票: `9/9 $ORCL 盘后·EPS est 1.48`(≤6家, 按市值/关注度降序)",
        "【零观点; 关注点=中性检索事实】首行=本周N家发财报 → 按日分节一行一票: 时间/$T/盘中盘后/EPS与营收预期/关注点 → 各家共识分歧摘要(须标注来源, 缺观点省)"),
    "funding-trail": ("融资脉络",
        "【零观点】首行=$T 融资全记录 → 按轮次时间序一行一轮: `2021 B轮 $2亿·红杉领投`(≤5轮)",
        "【零观点】首行=$T 融资全记录 → 按轮次时间序一行一轮(期次/时间/金额/领投方/用途) → 估值变化(缺料省) → 累计融资汇总行"),
}


# ── X 计权字数(grok 2026-09 核实: 拉丁=1/CJK=2/emoji=2/URL 恒=23(t.co);
#    一期不含 NFC 规范化, meta 注明; 后续可整体换 twitter-text v3 权重表) ─────
_URL_RE = re.compile(r"https?://\S+")


def weighted_len(text: str) -> int:
    text = text or ""
    urls = _URL_RE.findall(text)
    n = 23 * len(urls)
    for ch in _URL_RE.sub("", text):
        o = ord(ch)
        if (0x2E80 <= o <= 0x9FFF) or (0xF900 <= o <= 0xFAFF) \
                or (0x3000 <= o <= 0x303F) or (0xFE30 <= o <= 0xFE4F) \
                or (0xFF00 <= o <= 0xFFEF) or o >= 0x1F000:
            n += 2
        else:
            n += 1
    return n


# ── job 状态(仿 vstudio, 单 kind=compose, 同时只允许一个生成任务) ────────────
def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _empty_job() -> dict:
    return {"running": False, "started_at": None, "finished_at": None, "exit": None,
            "progress": {"stage": "idle", "pct": 0, "message": ""}, "request": {},
            "result": "", "error": "", "hint": ""}


def load_jobs() -> dict:
    try:
        data = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("bad jobs")
    except Exception:
        data = {}
    base = _empty_job()
    raw = data.get("compose") if isinstance(data.get("compose"), dict) else {}
    base.update(raw)
    prog = raw.get("progress") if isinstance(raw.get("progress"), dict) else {}
    base["progress"] = {**_empty_job()["progress"], **prog}
    return {"compose": base}


def _save_jobs(jobs: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
    with open(fd, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=1)
    import os
    os.replace(tmp, JOBS_FILE)


def begin_job(request: dict) -> None:
    with config.file_lock("gen_jobs"):
        job = _empty_job()
        job.update({"running": True, "started_at": _now(), "request": dict(request or {})})
        _save_jobs({"compose": job})


def try_begin_job(request: dict) -> bool:
    """检查+占位同一临界区(2026-09-11 三岗复审修复): 防并发 POST 双开两个生成 CLI。"""
    with config.file_lock("gen_jobs"):
        if job_running():
            return False
        job = _empty_job()
        job.update({"running": True, "started_at": _now(), "request": dict(request or {})})
        _save_jobs({"compose": job})
        return True


def tick(stage: str, pct: int, msg: str) -> None:
    with config.file_lock("gen_jobs"):
        jobs = load_jobs()
        jobs["compose"]["progress"] = {"stage": stage, "pct": pct, "message": msg}
        _save_jobs(jobs)


def finish_job(code: int, error: str, hint: str = "", result: str = "") -> None:
    with config.file_lock("gen_jobs"):
        jobs = load_jobs()
        jobs["compose"].update({"running": False, "finished_at": _now(), "exit": code,
                                "error": error or "", "hint": hint or ""})
        if result:
            jobs["compose"]["result"] = result
        if code == 0:
            jobs["compose"]["progress"] = {"stage": "done", "pct": 100, "message": "完成"}
        _save_jobs(jobs)


def job_running() -> bool:
    j = load_jobs()["compose"]
    if not j["running"]:
        return False
    try:                                   # 进程崩了没来得及收尾 → 超 10 分钟自动判死
        from datetime import datetime
        age = time.time() - datetime.strptime(j["started_at"], "%Y-%m-%d %H:%M:%S").timestamp()
        return age < 600
    except Exception:
        return False


def status_payload() -> dict:
    j = load_jobs()["compose"]
    return {"compose": {k: j.get(k) for k in
                        ("running", "started_at", "finished_at", "exit",
                         "progress", "result", "error", "hint")}}


# ── 产物读取(端点用) ────────────────────────────────────────────────────────
def post_get(pid: str) -> dict | None:
    if not re.fullmatch(r"p\d{10,12}", pid or ""):
        return None
    f = POSTS_DIR / f"{pid}.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def post_list() -> list:
    rows = []
    for f in POSTS_DIR.glob("p*.json"):
        post = post_get(f.stem)
        if not isinstance(post, dict):
            continue
        params = post.get("params") or {}
        lines = str(post.get("text") or "").splitlines()
        rows.append({"id": f.stem, "created_at": str(post.get("created_at") or ""),
                     "params": {"template": params.get("template"), "tier": params.get("tier")},
                     "weighted_len": post.get("weighted_len", 0), "tags": post.get("tags") or [],
                     "summary": (lines[0] if lines else "")[:60],
                     "image_count": len(post.get("images") or [])})
    return sorted(rows, key=lambda p: (p["created_at"], p["id"]), reverse=True)


def post_delete(pid: str) -> bool:
    if not re.fullmatch(r"p\d{10,12}", pid or ""):
        return False
    post = POSTS_DIR / f"{pid}.json"
    assets = ASSETS_DIR / pid
    # Resolve before recursive deletion; reject junctions outside the asset root.
    if post.resolve().parent != POSTS_DIR.resolve() or assets.resolve().parent != ASSETS_DIR.resolve():
        return False
    existed = post.is_file()
    if assets.exists():
        shutil.rmtree(assets)
    post.unlink(missing_ok=True)
    return existed


def asset_file(pid: str, name: str) -> Path | None:
    if not re.fullmatch(r"p\d{10,12}", pid or "") \
            or not re.fullmatch(r"[A-Za-z0-9_.\-]{1,64}\.png", name or ""):
        return None
    f = ASSETS_DIR / pid / name
    return f if f.is_file() else None


# ── 行情: yfinance(Yahoo, 免 key, 本机 2026-09-06 实测通) 主力,
#    东财 push2his 裸接口(免 key, 美105./港116./A股1./0.) 降级——
#    grok 云端实测东财三通, 但本机直连被 TLS 掐断(curl/urllib 同现), 故主备互换;
#    两路均只读外网, 仅 CLI 子进程调用 ─────────────────────────────────────────
def _em_secid(ticker: str) -> str:
    t = ticker.upper()
    if t.endswith(".SH"):
        return "1." + t[:-3]
    if t.endswith(".SZ"):
        return "0." + t[:-3]
    if t.endswith(".HK"):
        return "116." + t[:-3].zfill(5)
    return "105." + t


def _fetch_ohlcv_em(ticker: str, lmt: int = 120):
    """东财日线(前复权)。返回 (df, err); f51日期 f52开 f53收 f54高 f55低 f56量。"""
    import urllib.request
    import pandas as pd
    url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?secid="
           + _em_secid(ticker) + "&fields1=f1,f2,f3,f4,f5,f6"
           + "&fields2=f51,f52,f53,f54,f55,f56,f57&klt=101&fqt=1&beg=0&end=20500101&lmt="
           + str(lmt))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = json.loads(urllib.request.urlopen(req, timeout=15).read())
        klines = ((data or {}).get("data") or {}).get("klines") or []
        rows = [k.split(",") for k in klines]
        df = pd.DataFrame({
            "Open": [float(r[1]) for r in rows], "Close": [float(r[2]) for r in rows],
            "High": [float(r[3]) for r in rows], "Low": [float(r[4]) for r in rows],
            "Volume": [float(r[5]) for r in rows]},
            index=pd.to_datetime([r[0] for r in rows]))
        df.index.name = "Date"
        return (df[["Open", "High", "Low", "Close", "Volume"]].dropna(), "") if len(df) \
            else (None, f"{ticker} 东财无数据")
    except Exception as e:
        return None, f"{ticker} 东财接口失败: {e}"


_YF_SUFFIX = {".SH": ".SS"}      # 板块一词典后缀 → Yahoo 后缀


def _yf_symbol(ticker: str) -> str:
    for src, dst in _YF_SUFFIX.items():
        if ticker.upper().endswith(src):
            return ticker.upper()[:-len(src)] + dst
    return ticker.upper()


def _fetch_ohlcv_yf(ticker: str, period: str = "3mo"):
    import pandas as pd
    import yfinance as yf
    try:
        df = yf.download(_yf_symbol(ticker), period=period, interval="1d",
                         progress=False, auto_adjust=True)
    except Exception as e:
        return None, f"{ticker} yfinance 拉取失败: {e}"
    if df is None or not len(df):
        return None, f"{ticker} 无行情数据(Yahoo 未覆盖或停牌)"
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    return df, ""


def _fetch_ohlcv(ticker: str, period: str = "3mo", pref: str = "auto"):
    """按偏好依次尝试行情源; 返回 (df, err, via)。未知偏好沿用 auto。"""
    sources = ("eastmoney", "yfinance") if pref == "em_first" else ("yfinance", "eastmoney")
    if pref == "yf_only":
        sources = ("yfinance",)
    errors = []
    for via in sources:
        df, err = (_fetch_ohlcv_yf(ticker, period) if via == "yfinance"
                   else _fetch_ohlcv_em(ticker))
        if df is not None:
            return df, "", via
        errors.append(err)
    return None, "; ".join(errors), ""


# ── 投行分析师观点(可选增强): settings.json 配 finnhub.api_key 即启用,
#    免费档 /stock/recommendation + /stock/price-target, 仅覆盖美股 ────────────
def _finnhub_view(ticker: str, key: str) -> str:
    if not key or not ticker or "." in ticker:
        return ""
    import urllib.request
    base = "https://finnhub.io/api/v1"
    hdr = {"User-Agent": "Mozilla/5.0"}

    def get(path):
        try:
            req = urllib.request.Request(base + path + "&token=" + key, headers=hdr)
            return json.loads(urllib.request.urlopen(req, timeout=12).read())
        except Exception:
            return None

    out = []
    rec = get(f"/stock/recommendation?symbol={ticker}")
    if rec and isinstance(rec, list) and rec:
        r = rec[0]
        out.append(f"分析师评级({r.get('period', '')}): 强买{r.get('strongBuy', 0)} "
                   f"买{r.get('buy', 0)} 持有{r.get('hold', 0)} 卖{r.get('sell', 0)} "
                   f"强卖{r.get('strongSell', 0)}")
    pt = get(f"/stock/price-target?symbol={ticker}")
    if pt and isinstance(pt, dict) and pt.get("targetMean"):
        out.append(f"目标价: 均值{pt.get('targetMean')} (中位{pt.get('targetMedian')}, "
                   f"区间{pt.get('targetLow')}-{pt.get('targetHigh')})")
    return "Finnhub: " + "; ".join(out) if out else ""


def _sr_levels(df, k: int = 5, band_pct: float = 0.015, lookback: int = 60) -> dict:
    """摆动高低点聚类(近 lookback 根, 窗口 k 根局部极值; ±band_pct 价位带归并,
    触碰次数>距离排序) + 窗口极值与昨日枢轴 R1/S1 兜底——趋势行情里近端摆点
    可能全在同侧(如创新高时上方无摆动阻力), 裸跑摆点会给空集。"""
    d = df.tail(lookback)
    highs, lows = list(d["High"]), list(d["Low"])
    last = float(d["Close"].iloc[-1])
    band = last * band_pct
    h, l = float(d["High"].iloc[-1]), float(d["Low"].iloc[-1])
    p = (h + l + last) / 3
    pivot = {"P": round(p, 2), "R1": round(2 * p - l, 2), "S1": round(2 * p - h, 2),
             "R2": round(p + (h - l), 2), "S2": round(p - (h - l), 2)}
    swing_h = [highs[i] for i in range(k, len(d) - k)
               if highs[i] == max(highs[i - k:i + k + 1])]
    swing_l = [lows[i] for i in range(k, len(d) - k)
               if lows[i] == min(lows[i - k:i + k + 1])]
    res_pool = swing_h + [max(highs), pivot["R1"], pivot["R2"]]
    sup_pool = swing_l + [min(lows), pivot["S1"], pivot["S2"]]

    def cluster(pts):
        out = []
        for p2 in sorted(pts, reverse=True):
            for c in out:
                if abs(p2 - c["lvl"]) <= band:
                    c["lvl"] = (c["lvl"] * c["n"] + p2) / (c["n"] + 1)
                    c["n"] += 1
                    break
            else:
                out.append({"lvl": p2, "n": 1})
        return out

    def pick(pool, above: bool):
        cand = [c for c in cluster(pool) if (c["lvl"] > last) == above
                and abs(c["lvl"] - last) / last > 0.003]        # 贴着现价的带无意义
        cand.sort(key=lambda c: (-c["n"], abs(c["lvl"] - last)))
        return [{"price": round(c["lvl"], 2), "touches": c["n"]} for c in cand[:2]]

    return {"ticker_close": round(last, 2),
            "supports": pick(sup_pool, False), "resistances": pick(res_pool, True),
            "pivot": pivot}


def _render_chart(ticker: str, df, sr: dict | None, out: Path) -> str:
    """mplfinance 蜡烛图+成交量+支撑阻力水平线; 返回 err(空串=成功)。"""
    import matplotlib
    matplotlib.use("Agg")
    import mplfinance as mpf
    out.parent.mkdir(parents=True, exist_ok=True)
    levels, colors = [], []
    if sr:
        levels += [s["price"] for s in sr.get("supports", [])]
        colors += ["#2e7d32"] * len(sr.get("supports", []))
        levels += [r["price"] for r in sr.get("resistances", [])]
        colors += ["#c62828"] * len(sr.get("resistances", []))
    kw = {}
    if levels:
        kw["hlines"] = dict(hlines=levels, colors=colors, linestyle="--", linewidths=1.0)
    try:
        mpf.plot(df, type="candle", volume=True, style="yahoo",
                 title=f"\n{ticker} daily (3M)", ylabel="", datetime_format="%m-%d",
                 xrotation=0, figratio=(16, 9), figscale=1.1,
                 savefig=dict(fname=str(out), dpi=110, bbox_inches="tight",
                              facecolor="white"), **kw)
        return ""
    except Exception as e:
        return f"{ticker} 画图失败: {e}"


# ── 聚合分析: 站内观点池(X大V / 机构官方快讯) → LLM 归并共识与分歧 ────────────
def _items(params: dict) -> list:
    import urllib.parse
    try:
        return proxy.fetch_json("items?" + urllib.parse.urlencode(params)).get("items") or []
    except Exception:
        return []


def _opinion_pool(tickers: list, extra: list) -> tuple[list, list]:
    """近48h 同标的条目 + 检索补充, 按 positioning 分两组, 按时间倒序截断。"""
    pool = list(extra)
    if tickers:
        since = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 48 * 3600))
        pool += _items({"tickers": ",".join(tickers[:6]), "since": since,
                        "limit": 60, "dedup": 1})
    seen, rows = set(), []
    for it in pool:
        key = it.get("id") or it.get("url") or (it.get("source"), it.get("time"))
        if key in seen:
            continue
        seen.add(key)
        rows.append(it)
    rows.sort(key=lambda x: x.get("time") or "", reverse=True)
    bigv = [r for r in rows if r.get("positioning") == "大V"][:OPINION_CAP]
    inst = [r for r in rows if r.get("positioning") in ("机构", "官方", "快讯源", "新闻源")][:OPINION_CAP]
    return bigv, inst


_AGG_SYS = "你在整理财经事件的市场观点。只依据输入材料, 禁止编造。输出严格 JSON。"
_AGG_USER = """事件相关条目分两组:

[X 大V 帖]
{bigv}

[机构/官方/快讯报道]
{inst}

输出 JSON(不要输出任何其它文字):
{{"bigv": "X大V观点要点(2-4条, 注明分歧, 用中文)",
  "inst": "机构/分析师视角要点(1-3条, 用中文)",
  "consensus": "一句话共识(无则空串)",
  "divergence": "一句话分歧(无则空串)"}}"""


def _fmt_rows(rows: list, n: int) -> str:
    out = []
    for r in rows[:n]:
        text = (r.get("text") or "")[:160].replace("\n", " ")
        out.append(f"- [{r.get('source')} {r.get('time')}] {text}")
    return "\n".join(out) or "(无)"


def _llm(cfg3, system: str, user: str, max_tokens: int | None = None,
         timeout: int = 120) -> str | None:
    base, key, model = cfg3[:3]
    extra = cfg3[3] if len(cfg3) > 3 else None     # 厂商私有参数(如推理模型关思考)
    return vstudio.chat_completions(base, key, model,
                                    [{"role": "system", "content": system},
                                     {"role": "user", "content": user}],
                                    0.4, max_tokens, timeout, extra=extra)


def _llm_chain(chain: list, system: str, user: str, max_tokens: int | None = None,
               timeout: int = 120) -> tuple[str | None, dict | None]:
    """成稿模型链调用(2026-09-10 多元化): 按优先级依次尝试, 前一失败自动落下一。
    max_tokens 默认 None=请求体不带该字段, 走各厂商自己的输出上限(2026-09-11 全档放宽:
    推理模型 reasoning 计入 max_tokens, 显式小额会被思考烧光返回空; 写死大数又会撞
    低上限厂商的 400, 唯有"不传"天然适配所有厂商)。超长输出由 TIER_LIMIT 压缩修复兜底。
    → (内容|None, 实际命中的链位|None)。"""
    for m in chain:
        raw = _llm((m["base_url"], m["api_key"], m["model"], m.get("extra_body")),
                   system, user, max_tokens, timeout)
        if raw:
            return raw, m
    return None, None


def _parse_json(raw: str) -> dict | None:
    decoder = json.JSONDecoder()
    for m in re.finditer(r"\{", raw or ""):
        try:
            value, _ = decoder.raw_decode(raw[m.start():])
            return value
        except ValueError:
            continue
    return None


# ── 终稿组装 ────────────────────────────────────────────────────────────────
def _compose_prompt(params: dict, materials: list, contexts: list,
                    tech_facts: str, opinions: dict, tickers: list) -> tuple[str, str]:
    lang = LANGS.get(params["lang"], "English")
    limit = TIER_LIMIT[params["tier"]]
    tpl = _TPL_SCAFFOLD[params["template"]]
    scaffold = "模板「" + tpl[0] + "」: " + (tpl[2] if params["tier"] == "paid" else tpl[1])
    mat = "\n\n".join(f"【素材{i + 1}·{m.get('source')} {m.get('time')}】\n{m.get('text')}"
                      for i, m in enumerate(materials))
    sup = "\n".join(contexts) if contexts else "(无)"
    agg = ""
    if opinions:
        agg = ("\n[市场观点聚合]\nX大V: " + (opinions.get("bigv") or "无")
               + "\n机构/分析师: " + (opinions.get("inst") or "无")
               + ("\n投行分析师: " + opinions["analyst"] if opinions.get("analyst") else "")
               + ("\n共识: " + opinions["consensus"] if opinions.get("consensus") else "")
               + ("\n分歧: " + opinions["divergence"] if opinions.get("divergence") else ""))
    tech = ("\n[技术面事实]\n" + tech_facts) if tech_facts else ""
    cashtags = " ".join("$" + t.split(".")[0] for t in tickers[:6])
    manual_hint = ("\n注: 标注「手动录入」的素材由用户本人提供, 事实性由用户担保, "
                   "正常采用但不得虚构出处。\n"
                   if any(str(m.get("id") or "").startswith("manual-") for m in materials) else "")
    user = f"""语言: 全文用{lang}写(素材是其它语言也要写成{lang})。
结构模板: {scaffold}
字数: X 计权长度不超过 {limit} (CJK 字符每个计 2, 其余计 1)。

[素材原文]
{mat}
{manual_hint}
[检索补充]
{sup}{tech}{agg}

[可用 cashtag] {cashtags or "(无)"}

只输出 JSON(不要任何其它文字): {{"text": "成稿正文(含行间换行)"}}
text 标签规则: 每个标的首次出现写成 $TICKER 内联在句中(不要移到末尾堆叠); hashtag 默认 0 个、最多 1 个放末尾。"""
    if params["template"] == "thread-post":
        user = user[:user.index("只输出 JSON")]
        user += (f'只输出 JSON: {{"tweets": ["1/ ...", "2/ ...", "3/ ..."]}}。'
                 f'输出 3-8 条(免费档 3-5 条, 付费档 5-8 条, 本契约优先于骨架条数)。'
                 f'每条以连续 N/ 前缀开头(只写 N/, 不要写 N/M, 后端统一补 M)。'
                 f'每条独立成帖——单独出现也必须读得懂: 禁用回指词(the beat/also/this/above/as mentioned/it/they 指代上条), '
                 f'每个数字带主语与单位; 中段每条至多一次 $TICKER 锚点; '
                 f'首条=钩子+最强数字前置+主 $cashtag; 末条=My take:/Bottom line: 结论+互动钩子(提问或展望)。'
                 f'含前缀的每条 X 计权长度 ≤{limit}, 不是整串合计上限。')
    return _X_STYLE, user


def _tech_text(ta: dict) -> str:
    lines = []
    for t, s in ta.items():
        sup = "/".join(str(x["price"]) for x in s.get("supports", [])) or "—"
        res = "/".join(str(x["price"]) for x in s.get("resistances", [])) or "—"
        pv = s.get("pivot") or {}
        lines.append(f"{t} 现价 {s.get('ticker_close')}; 阻力位 {res}; 支撑位 {sup}; "
                     f"昨日枢轴 P={pv.get('P')} R1={pv.get('R1')} S1={pv.get('S1')}"
                     f"(近60交易日摆动点聚类, 仅供参考)")
    return "\n".join(lines)


def _strip_urls(text: str) -> str:
    """成稿强制无链接(用户拍板: 自己产出的内容不指向别人)——prompt 规则之外的
    硬保证; 剥离后合并空行, 防 LLM 把链接单独留成行时出现大段空白。"""
    if not _URL_RE.search(text or ""):
        return text
    t = _URL_RE.sub("", text or "")
    out, blank = [], False
    for ln in t.splitlines():
        ln = ln.rstrip()
        if ln.strip():
            out.append(ln)
            blank = False
        elif not blank and out:
            out.append("")
            blank = True
    return "\n".join(out).strip()


def _extract_tags(text: str) -> list:
    """从正文抽取实际出现的 $cashtag/#hashtag(出现顺序, 大小写不敏感去重)——
    X 无独立标签字段, 徽章只展示正文真实携带的标签。cashtag 要求字母开头,
    天然排除 $230 这类价格误配。"""
    tags, seen = [], set()
    for m in re.finditer(r"\$([A-Za-z]{1,6}(?:\.[A-Za-z]{1,2})?)|#(\w{1,30})",
                         text or ""):
        tok = "$" + m.group(1).upper() if m.group(1) else "#" + m.group(2)
        if tok.lower() not in seen:
            seen.add(tok.lower())
            tags.append(tok)
    return tags[:8]


def _ensure_cashtags(text: str, tickers: list, limit: int):
    """cashtag 保底直写正文(tags 侧路在 X 上无效)。已内联(大小写不敏感)跳过;
    正文有全大写裸提 → 首个出现处升级为 $TICKER(真内联, 大小写敏感防 ON/A 类
    常用词误伤); 完全没提 → 文末补齐(受字数上限约束)。只处理字母代码——
    数字代码(2330.TW 等)在 X 无功能 cashtag, 且易与价格混淆, 跳过。"""
    heads = []
    for t in tickers[:3]:
        head = (t or "").split(".")[0].upper()
        if re.fullmatch(r"[A-Z]{1,6}", head or ""):
            heads.append(head)
    missing, skipped = [], []
    for h in heads:
        if re.search(r"\$" + re.escape(h) + r"\b", text, re.I):
            continue
        m = re.search(r"(?<![\w$])" + re.escape(h) + r"\b", text) if len(h) >= 2 else None
        if m:
            cand = text[:m.start()] + "$" + h + text[m.end():]
            if weighted_len(cand) <= limit:
                text = cand
            else:
                skipped.append(h)
        else:
            missing.append(h)
    if missing:
        cand = text.rstrip() + "\n\n" + " ".join("$" + h for h in missing)
        if weighted_len(cand) <= limit:
            text = cand
        else:
            skipped.extend(missing)
    note = ("cashtag " + " ".join("$" + h for h in skipped) + " 因字数上限未补入") if skipped else ""
    return text, note


_OPINION_LINE_RE = re.compile(
    r"^(?:view|my take|bottom line|takeaway|my view)[:：]"
    r"|^(?:我认为|我的观点|个人观点|我看|笔者认為)", re.I)


def _strip_opinion_lines(text: str) -> tuple[str, bool]:
    """零观点模板的硬保证(对应链接硬剥离): 剔除行首观点标记行, 合并空行。
    保守口径——只认行首标记, 正文里引述的'利好/利空'措辞不动(那是事实引述)。
    剔空时放弃(防 LLM 整帖一句话还带标记被剔成空白)。"""
    lines = (text or "").splitlines()
    kept = [ln for ln in lines if not _OPINION_LINE_RE.match(ln.strip())]
    if len(kept) == len(lines):
        return text, False
    out, blank = [], False
    for ln in kept:
        if ln.strip():
            out.append(ln.rstrip())
            blank = False
        elif not blank and out:
            out.append("")
            blank = True
    stripped = "\n".join(out).strip()
    return (stripped, True) if stripped else (text, False)


def _hard_truncate(text: str, limit: int) -> str:
    """超限时在句读边界内硬截(保底, 正常路径由 LLM 修复)。"""
    while text and weighted_len(text) > limit:
        cut = max(text.rfind(p) for p in ("。", "\n", ".", "！", "!", "？", "?"))
        if cut <= 0:
            break
        text = text[:cut].rstrip()
    while text and weighted_len(text) > limit:   # 仍超 → 逐字尾删
        text = text[:-1]
    return text


_TWEET_NUM_RE = re.compile(r"^(\d{1,2})\s*/\s*(?:(\d{1,2})\s*/?\s*)?")
_TWEET_BACKREF_RE = re.compile(
    r"^(the beat|also|this|above|as mentioned|it |they |同上|承上|如前所述|接上文)")


def _normalize_tweet(raw: str, i: int, n: int, limit: int, notes: list):
    """串推单条规范化: 剥链接 → 吞掉 LLM 自带编号(N/、N/M、N/M/ 都吞, 防双重编号;
    仅当首号等于位置 i 或形如 N/n 才吞, 避免误吞 "9/8 CPI" 这类日期开头)
    → 确定性重编号 i/n → 超限硬截断。空帖返回 None(调用方报 llm_failed)。
    中段软警告(疑似回指词开头 / 缺 $cashtag 与数字锚点)只进 notes, 不硬失败。"""
    if _URL_RE.search(raw or ""):
        notes.append(f"串推第{i}条: 已剥离外部链接")
    clean = _strip_urls(raw).strip()
    mnum = _TWEET_NUM_RE.match(clean)
    if mnum:
        a, b = int(mnum.group(1)), int(mnum.group(2) or 0)
        if a == i or (b == n and a <= 8):
            clean = clean[mnum.end():].strip()
    if not clean:
        return None
    text = f"{i}/{n} {clean}"
    if weighted_len(text) > limit:
        text = _hard_truncate(text, limit)
        notes.append(f"串推第{i}条: 超字数上限, 已硬截断")
    if i > 1:
        if _TWEET_BACKREF_RE.match(clean[:24].lower()):
            notes.append(f"串推第{i}条: 疑似回指词开头, 单独出现可能读不懂")
        elif "$" not in clean and not re.search(r"\d", clean):
            notes.append(f"串推第{i}条: 缺 $cashtag/数字锚点, 单独出现可能读不懂")
    return text


# ── CLI 主流程(仅子进程调用; 端点侧只 spawn) ────────────────────────────────
def run_compose(request: dict) -> tuple[dict, int]:
    items = [m for m in (request.get("items") or []) if isinstance(m, dict)][:8]
    if not items:
        return {"error": "no_items", "hint": "先勾选参与生成的素材"}, 4
    modules = [m for m in (request.get("modules") or []) if m in MODULES]
    tpl_req = _TPL_LEGACY.get(request.get("template"), request.get("template"))
    params = {"platform": request.get("platform") if request.get("platform") in PLATFORMS else "x",
              "lang": request.get("lang") if request.get("lang") in LANGS else "en",
              "tier": request.get("tier") if request.get("tier") in TIER_LIMIT else "free",
              "template": tpl_req if tpl_req in TEMPLATES else TPL_DEFAULT}
    pid = "p" + time.strftime("%m%d%H%M%S")
    cfg = config.load()
    source_pref = (cfg.get("market") or {}).get("source_pref", "auto")
    chain = config.compose_chain(cfg)              # 成稿模型链(2026-09-10 多元化:
    if not chain:                                  #  列表序=优先级, 失败自动落下一; 不回落翻译链)
        return {"error": "no_llm_config",
                "hint": "到设置页配置「成稿模型」(内容生成专用, 独立于翻译链, 可配多条按优先级兜底)"}, 4

    notes, contexts, images, ta = [], [], [], {}
    tick("retrieve", 5, "素材识别与信息补全")
    mats = []
    groups = []
    if "retrieve" in modules:
        try:
            groups = retrieve.run({"items": items, "window_h": 24}).get("groups") or []
        except Exception as e:
            notes.append(f"信息检索不可用: {e}")
    gmap = {g.get("seed_id"): g for g in groups}
    tickers = []
    for m in items:
        g = gmap.get(m.get("id")) or {}
        hy = g.get("hydrated") or {}
        text = hy.get("full") or m.get("body") or m.get("text") or ""
        mats.append({**m, "text": text})
        for t2 in ((g.get("tags") or {}).get("tickers") or []):
            if t2 not in tickers:
                tickers.append(t2)
        for h in (g.get("related") or [])[:3]:
            contexts.append(f"- [{h.get('source')} {h.get('time')}] "
                            f"{(h.get('title') or h.get('text') or '')[:140]}"
                            f"({'/'.join(h.get('why') or [])})")
    if not tickers:                                  # 检索没跑/没命中 → 直接对原文打标
        for m in items:
            for t2 in retrieve._enrich((m.get("body") or m.get("text") or "") + " " + (m.get("title") or ""))["tickers"]:
                if t2 not in tickers:
                    tickers.append(t2)

    if "snapshot" in modules or "tech" in modules:
        tick("market", 25, "拉取行情数据")
        for t2 in tickers[:CHART_CAP]:
            df, err, via = _fetch_ohlcv(t2, pref=source_pref)
            if err:
                notes.append(err)
                continue
            sr = _sr_levels(df) if "tech" in modules else None
            if sr:
                ta[t2] = sr
            if "snapshot" in modules:
                tick("market", 35, f"渲染 {t2} 行情图")
                err = _render_chart(t2, df, sr, ASSETS_DIR / pid / f"{t2}.png")
                if err:
                    notes.append(err)
                else:
                    images.append({"ticker": t2, "file": f"{t2}.png", "via": via,
                                   "url": f"/wb-api/gen-assets/{pid}/{t2}.png"})
        if not tickers:
            notes.append("素材未识别到标的, 快照抓取/技术分析跳过")

    opinions = None
    if "aggregate" in modules:
        tick("aggregate", 55, "聚合 X 大V 与机构观点")
        bigv, inst = _opinion_pool(tickers, [])
        analyst = _finnhub_view(tickers[0], str((cfg.get("finnhub") or {}).get("api_key") or "")) \
            if tickers else ""
        if bigv or inst:
            raw, _used = _llm_chain(chain, _AGG_SYS,
                                    _AGG_USER.format(bigv=_fmt_rows(bigv, OPINION_CAP),
                                                     inst=_fmt_rows(inst, OPINION_CAP)))
            opinions = _parse_json(raw or "")
            if not opinions:
                notes.append("观点聚合 LLM 未返回有效 JSON, 已跳过")
        if analyst:
            opinions = opinions or {}
            opinions["analyst"] = analyst
        if opinions is None:
            notes.append("近48h 未检到大V/机构同标的观点, 聚合分析跳过"
                         + ("" if tickers else "(素材无标的)"))

    tick("compose", 75, "LLM 成稿中")
    system, user = _compose_prompt(params, mats, contexts[:10],
                                   _tech_text(ta), opinions, tickers)
    limit = TIER_LIMIT[params["tier"]]
    raw, used = _llm_chain(chain, system, user,
                           None)   # 全档不传 max_tokens, 厂商默认上限(2026-09-11)
    if used and chain and used["id"] != chain[0]["id"]:
        notes.append(f"成稿模型链头未命中, 实际用「{used['name']}」({used['model']})")
    draft = _parse_json(raw or "")
    thread = []
    if params["template"] == "thread-post":
        tweets = draft.get("tweets") if isinstance(draft, dict) else None
        if (not isinstance(tweets, list) or not 3 <= len(tweets) <= 8
                or any(not isinstance(t, str) or not t.strip() for t in tweets)):
            return {"error": "llm_failed", "hint": "串推模型须返回 tweets 数组(3-8 条非空文字)"}, 3
        n = len(tweets)
        for i, tweet in enumerate(tweets, 1):
            text = _normalize_tweet(tweet, i, n, limit, notes)
            if text is None:
                return {"error": "llm_failed", "hint": "串推剥离链接后存在空帖, 请重试"}, 3
            if i == 1:
                text, tag_note = _ensure_cashtags(text, tickers, limit)
                if tag_note:
                    notes.append(tag_note)
            thread.append(text)
        text = "\n\n".join(thread)
    else:
        if not draft or not (draft.get("text") or "").strip():
            return {"error": "llm_failed", "hint": "成稿模型未返回有效 JSON, 请重试"}, 3
        text = str(draft["text"]).strip()
        if _URL_RE.search(text):                     # 硬保证: 成稿不指向他人内容
            text = _strip_urls(text)
            notes.append("已剥离素材带入的外部链接(成稿不带链接, 出处以文字注明)")
        if weighted_len(text) > limit:                 # 修复调用限时 60s(免费池可能滴流挂起),
            tick("compose", 88, "字数超限, 压缩修复")      # 失败即放弃修复 → 句读硬截断保底
            fix, _ = _llm_chain(chain, _X_STYLE,
                                f"把下面的帖子压缩到 X 计权 {limit} 以内(CJK 每字计 2), 保留核心事实与观点, "
                                f"保留内联 $cashtag, 语言与风格不变, 不带任何链接, 只输出压缩后的正文:\n\n{text}",
                                None, 60)
            fix = _strip_urls((fix or "").strip().strip('"'))
            if fix and weighted_len(fix) <= limit:
                text = fix
            elif weighted_len(text) > limit:
                text = _hard_truncate(text, limit)
                notes.append("成稿超字数上限, 已按句读硬截断")
        if params["template"] in ZERO_OPINION_TEMPLATES:     # 零观点披露类: 硬剔观点标记行
            text, dropped = _strip_opinion_lines(text)
            if dropped:
                notes.append("零观点模板: 已剔除观点标记行")
        text, tag_note = _ensure_cashtags(text, tickers, limit)  # 保底直写正文(X 无 tags 字段)
        if tag_note:
            notes.append(tag_note)
    tags = _extract_tags(text)                               # 徽章 = 正文实际携带的标签

    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    result = {"id": pid, "text": text, "tags": tags, "images": images,
              "params": params, "modules": modules, "tickers": tickers,
              "weighted_len": max(map(weighted_len, thread)) if thread else weighted_len(text), "limit": limit,
              "notes": notes, "created_at": _now()}
    if used:
        result["model"] = used["model"]
        result["model_name"] = used["name"]
    if thread:
        result["thread"] = thread
    (POSTS_DIR / f"{pid}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    for old in post_list()[50:]:
        post_delete(old["id"])
    return result, 0


def run_compose_cli(args) -> int:
    """CLI 子进程入口: 读 gen_jobs.json 里的 request, 跑编排, 写产物并收尾。"""
    request = load_jobs()["compose"].get("request") or {}
    try:
        result, code = run_compose(request)
    except Exception as e:
        finish_job(3, f"compose_crash: {e}")
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 3
    if code == 0:
        finish_job(0, "", result=result["id"])
    else:
        finish_job(code, result.get("error", ""), result.get("hint", ""))
    if getattr(args, "json", False):
        slim = {k: result.get(k) for k in ("id", "error", "hint", "weighted_len", "limit")}
        print(json.dumps(slim, ensure_ascii=False))
    return code


def spawn_cli() -> None:
    """端点侧: 静默拉起 CLI 子进程(同 vstudio 先例; 前缀自适应 Python 版本 config.py_cmd)。"""
    cli = Path(__file__).resolve().parents[2] / "cli.py"
    subprocess.Popen([*config.py_cmd(), str(cli), "workbench", "gen-post", "--json"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
