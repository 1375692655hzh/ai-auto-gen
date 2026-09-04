"""YouTube 热点追踪 —— 账号库 + 视频统计快照 + 播放增量榜数据面(视频页【热点追踪】【追踪账号】)。

方案: docs/workbench-moa/16/17/18-codex/kimi/gemini-yttrack.md(MoA 三家合成裁决 2026-09-05)。
- 账号库 data/workbench/yt_channels.json(config.load_rows 通用存取), 与追踪主页面的
  tracked_accounts.json 物理隔离——后者按数组下标删改且本期禁改(track.js), 共库会被
  采集器收尾回写覆盖; 导入走 POST /wb-api/yt/channels/import 只复制不删源。
- 视频库 data/workbench/yt_videos.json: video_id 为键, 元数据 + series 时序快照合并
  单文件(一次原子落盘, 免跨文件事务); Δviews=快照差分, None 一律沉底。
- 采集(CLI 才外呼, 服务器零外呼, 同 x_surge.py 架构): YouTube Data API v3 纯 REST
  (urllib, 不引 SDK); 解析 channels.list forHandle(1单位) → 发现 playlistItems
  uploads 第1页(1单位/频道) → 统计 videos.list 50个/批(1单位) → 追加快照。
  403 quotaExceeded 全局熔断保旧数据(exit 3); 无 key exit 4(AGENTS.md 配置缺失契约)。
- 口径: YouTube 2026-08-24 起播放按「开始播放即计」, 本库快照全部始于新口径, 内部
  自洽; 跨口径/与外部工具历史斜率不可比(caliber 字段透出)。订阅数为公开取整口径,
  仅展示禁用于净增计算。

架构红线: 对板块一只读; 本模块外呼仅发生在 CLI 进程, app.py 端点只读缓存。
"""

import json
import hashlib
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path

from . import config

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "workbench"
VIDEOS_FILE = DATA_DIR / "yt_videos.json"

_YT_API = "https://www.googleapis.com/youtube/v3"
HTTP_TIMEOUT = 15

SNAPSHOT_RETAIN_D = 28        # 快照保留天数(覆盖 Δ7d 口径 + 4 倍容差)
MAX_POINTS = 200              # 单视频快照点上限(超出丢最旧)
MAX_VIDEOS = 5000             # 全库视频硬顶(按最近统计时间淘汰最旧)
MAX_PER_CHANNEL = 40          # 发现阶段单频道库存上限(28d 窗够用)
DISCOVER_TAKE = 50            # 每频道发现条数(playlistItems 第 1 页)
SHORT_S = 180                 # Shorts 判别口径(2024-10 起上限 3 分钟)
CALIBER = "count-on-start-2026-08-24"   # 播放计数口径代次(口径再变时 bump)
COOLDOWN_MIN = 5              # 采集冷却(防前端按钮与计划任务双跑; --force 穿透)
RUNNING_STALE_MIN = 30        # 重入锁过期(视为僵尸, 允许接管)
DESC_HEAD = 300               # 简介开头截存长度(轻量解读输入)
INSIGHT_TOP = 20              # 解读候选池: 近7天播放 Top20
INSIGHT_TAKE = 10             # 解读展示条数(热榜页最前)
INSIGHT_PER_ROUND = 5         # 每轮采集最多补几条解读(防首轮集中打 LLM)

_UC_RE = re.compile(r"UC[\w-]{22}")
_URL_RE = re.compile(
    r"youtube\.com/(?:channel/(UC[\w-]{22})|@([A-Za-z0-9._-]{3,30})|c/([A-Za-z0-9._-]{3,30})|user/([A-Za-z0-9._-]{3,30}))",
    re.I)
_DUR_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_SORTS = ("views", "delta24h", "delta7d", "rate", "newest")
_RANGES = {"24h": 24, "48h": 48, "7d": 24 * 7, "28d": 24 * 28}


# ── 输入解析(纯函数, 离线可测) ───────────────────────────────────────────────
def parse_channel_input(raw: str) -> dict | None:
    """频道输入归一化: /channel/UC… 或裸 UC… → channel_id; @handle / /@h → handle;
    /c/Name、/user/Name(遗留形态) → handle 猜测(resolve 时先 forHandle 后 forUsername)。
    识别不出返回 None(端点回 400)。"""
    s = (raw or "").strip()
    if not s:
        return None
    m = _URL_RE.search(s)
    if m:
        if m.group(1):
            return {"kind": "channel_id", "value": m.group(1)}
        name = m.group(2) or m.group(3) or m.group(4)
        return {"kind": "handle", "value": "@" + name}
    m = _UC_RE.fullmatch(s)
    if m:
        return {"kind": "channel_id", "value": m.group(0)}
    if s.startswith("@"):
        s = s[1:]
    if "youtube.com/watch" in s or "youtu.be/" in s:   # 是视频不是频道, 明确拒掉防误入 name 分支
        return None
    # YouTube handle 只可能是 ASCII(\w 默认吃 CJK, 中文频道名须落到 name 分支)
    if re.fullmatch(r"[A-Za-z0-9._-]{3,30}", s):
        return {"kind": "handle", "value": "@" + s}
    # 频道名搜索解析(100 单位/个, 一次性): 须含 CJK 字符, 或纯字母+空格组合
    # (防"not a channel!!"之类垃圾输入被当频道名搜出张冠李戴的结果)
    if 2 <= len(s) <= 60 and (_CJK_RE.search(s) or re.fullmatch(r"[A-Za-z ]{2,60}", s)):
        return {"kind": "name", "value": s}
    return None


# ── 视频库读写(合并单文件, 原子写, 损坏当空库重来) ───────────────────────────
def _empty_store() -> dict:
    return {"version": 1, "updated_at": None, "caliber": CALIBER,
            "last_collect": {}, "videos": {}}


def load_store() -> dict:
    if not VIDEOS_FILE.is_file():
        return _empty_store()
    try:
        d = json.loads(VIDEOS_FILE.read_text(encoding="utf-8"))
        d.setdefault("videos", {})
        d.setdefault("last_collect", {})
        d.setdefault("caliber", CALIBER)
        return d
    except Exception:
        return _empty_store()


def save_store(store: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, VIDEOS_FILE)


def _prune(store: dict) -> None:
    """28d 保留 + 单视频 200 点 + 5000 视频硬顶(最久无统计的先淘汰)。"""
    now = time.time()
    for vid in list(store["videos"]):
        v = store["videos"][vid]
        v["series"] = [p for p in v.get("series", []) if p["ts"] >= now - SNAPSHOT_RETAIN_D * 86400]
        stale = v.get("last_stats") or v.get("first_seen") or 0
        if (not v["series"] and now - stale > 45 * 86400) \
                or (v.get("status") == "unavailable" and not v["series"]):
            del store["videos"][vid]
    if len(store["videos"]) > MAX_VIDEOS:
        ranked = sorted(store["videos"].items(),
                        key=lambda kv: kv[1].get("last_stats") or 0, reverse=True)
        store["videos"] = dict(ranked[:MAX_VIDEOS])


# ── Data API v3(仅 CLI 进程调用) ─────────────────────────────────────────────
class _QuotaExceeded(Exception):
    pass


def _yt_get(path: str, params: dict, key: str) -> dict:
    import urllib.error
    import urllib.parse
    import urllib.request
    params = dict(params)
    params["key"] = key
    req = urllib.request.Request(_YT_API + path + "?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": "aag-workbench/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        if e.code == 403 and "quotaExceeded" in body:
            raise _QuotaExceeded()
        if e.code == 404:
            return {}                                # 上层按"缺失"处理
        raise


def _int(x) -> int | None:
    try:
        return int(x)
    except Exception:
        return None


def _iso_ts(s: str) -> float | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z").timestamp()   # %z 吃 Z
    except Exception:
        return None


def _iso8601_s(s: str) -> int | None:
    if not s:
        return None
    m = _DUR_RE.match(s)
    if not m:
        return None
    h, mi, sec = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + sec


def _thumb(sn: dict) -> str:
    th = sn.get("thumbnails") or {}
    return ((th.get("medium") or th.get("default") or {}).get("url")) or ""


def _fill_channel_row(row: dict, it: dict) -> None:
    row["channel_id"] = it.get("id") or row.get("channel_id") or ""
    sn = it.get("snippet") or {}
    row["title"] = sn.get("title") or row.get("title") or ""
    row["handle"] = sn.get("customUrl") or row.get("handle") or ""
    row["subs"] = _int((it.get("statistics") or {}).get("subscriberCount"))
    row["uploads_pid"] = ((it.get("contentDetails") or {}).get("relatedPlaylists") or {}) \
        .get("uploads") or ("UU" + row["channel_id"][2:] if row["channel_id"].startswith("UC")
                            else row.get("uploads_pid") or "")


def api_key() -> str:
    return (config.load().get("youtube") or {}).get("api_key") \
        or os.environ.get("YOUTUBE_API_KEY", "")


def _chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


# ── 轻量解读(近7天播放 Top20 的前10条, translate 链 LLM 生成简介+标签) ────────
def _insight_hot_vids(store: dict, en_ids: set, now: float) -> list:
    """解读候选口径(与展示同源): 启用频道近7天发布的视频按最新播放降序前 20。"""
    cands = []
    for vid, v in store["videos"].items():
        pub = v.get("published")
        if not pub or v.get("channel_id") not in en_ids or now - pub > 7 * 86400:
            continue
        series = v.get("series") or []
        views = series[-1].get("v") if series else None
        cands.append((views if views is not None else -1, vid))
    cands.sort(reverse=True)
    return [vid for _, vid in cands[:INSIGHT_TOP]]


def _call_insight(base: str, key: str, model: str, title: str, kind: str,
                  tags: list, desc: str) -> str | None:
    """OpenAI 兼容 /chat/completions(复用 settings.translate 段), 返回模型原文。"""
    import urllib.request
    body = json.dumps({
        "model": model, "temperature": 0.3, "max_tokens": 300,
        "messages": [
            {"role": "system",
             "content": "你是财经视频编辑。根据标题/标签/简介开头, 用一句中文概括该视频讲什么。"
                        "只输出 JSON: {\"summary\":\"≤40字\",\"tags\":[\"≤8字主题词\"]}, "
                        "tags 给2-4个, 不要解释。"},
            {"role": "user",
             "content": f"标题: {title}\n类型: {kind}\n标签: {', '.join(tags[:8]) or '无'}\n"
                        f"简介开头: {desc or '无'}"}],
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


def _parse_insight(text: str) -> dict | None:
    """模型输出 → {summary≤40字, tags≤4个各≤8字}; 围栏/杂质容错, 解析失败返回 None。"""
    if not text:
        return None
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I).strip()
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        d = json.loads(s[i:j + 1])
    except Exception:
        return None
    summary = str(d.get("summary") or "").strip()
    if not summary:
        return None
    tags = []
    for t in (d.get("tags") or [])[:4]:
        t = str(t).strip()[:8]
        if t:
            tags.append(t)
    return {"summary": summary[:40], "tags": tags}


def _fill_insights(store: dict, report: dict) -> None:
    """采集收尾补解读: 7天Top20取前10中缺 insight 或输入(title+desc)已变者,
    每轮最多 INSIGHT_PER_ROUND 条, 0.5s 间隔; 未配置 translate 静默跳过;
    任何异常只记 report 不影响采集主流程(与 exit code 无关)。"""
    try:
        cfg = config.load().get("translate") or {}
        base, key, model = cfg.get("base_url"), cfg.get("api_key"), cfg.get("model")
        if not (base and key and model):
            report["insight_skipped"] = "translate 未配置"
            return
        channels = config.load_yt_channels()
        en_ids = {c["channel_id"] for c in channels
                  if c.get("enabled", True) and c.get("resolve_status") == "resolved"
                  and c.get("channel_id")}
        todo = []
        for vid in _insight_hot_vids(store, en_ids, time.time())[:INSIGHT_TAKE]:
            v = store["videos"].get(vid) or {}
            h = hashlib.sha1(((v.get("title") or "") + "\n" + (v.get("description_head") or ""))
                             .encode("utf-8")).hexdigest()[:16]
            ins = v.get("insight")
            if ins and ins.get("input_hash") == h:
                continue
            todo.append((vid, v, h))
        done = fail = 0
        for i, (vid, v, h) in enumerate(todo[:INSIGHT_PER_ROUND]):
            if i:
                time.sleep(0.5)
            text = _call_insight(base, key, model, v.get("title") or "",
                                 "Shorts" if v.get("is_short") else "长视频",
                                 v.get("tags") or [], v.get("description_head") or "")
            parsed = _parse_insight(text)
            if not parsed:
                fail += 1
                continue
            parsed.update({"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                           "model": model, "input_hash": h})
            v["insight"] = parsed
            done += 1
        report["insight_done"] = done
        if fail:
            report["insight_failed"] = fail
        if todo:
            report["insight_pending"] = max(len(todo) - INSIGHT_PER_ROUND, 0)
    except Exception as e:
        report["insight_error"] = type(e).__name__


# ── 采集一轮(CLI 进程) ───────────────────────────────────────────────────────
def collect(force: bool = False) -> tuple[dict, int]:
    """解析 pending 账号 → 刷频道元数据 → 发现新视频 → 批量刷新统计追加快照。
    返回 (report, exit_code): 0 正常/跳过, 3 配额熔断, 4 无 key。"""
    now_s = time.strftime("%Y-%m-%d %H:%M:%S")
    now = time.time()
    store = load_store()
    lc = store.get("last_collect") or {}

    # 重入锁: running 且未过期 → 跳过(防前端按钮与计划任务/双开重叠)
    if not force and lc.get("running") and lc.get("started_at"):
        try:
            st = time.mktime(time.strptime(lc["started_at"], "%Y-%m-%d %H:%M:%S"))
            if now - st < RUNNING_STALE_MIN * 60:
                rep = {"skipped": "already_running", "started_at": lc["started_at"]}
                print(json.dumps(rep, ensure_ascii=False))
                return rep, 0
        except Exception:
            pass
    # 冷却
    if not force and lc.get("finished_at"):
        try:
            ft = time.mktime(time.strptime(lc["finished_at"], "%Y-%m-%d %H:%M:%S"))
            if now - ft < COOLDOWN_MIN * 60:
                rep = {"skipped": "cooldown", "finished_at": lc["finished_at"]}
                print(json.dumps(rep, ensure_ascii=False))
                return rep, 0
        except Exception:
            pass

    key = api_key()
    if not key:
        rep = {"error": "no_api_key",
               "hint": "设置页配置 youtube.api_key(或环境变量 YOUTUBE_API_KEY)后再采集"}
        print(json.dumps(rep, ensure_ascii=False))
        return rep, 4

    channels = config.load_yt_channels()
    lc = {"running": True, "started_at": now_s}
    store["last_collect"] = lc
    save_store(store)                                # 先占锁再外呼

    report = {"channels_total": len(channels), "resolved": 0, "resolve_failed": 0,
              "channels_ok": 0, "new_videos": 0, "snapshotted": 0,
              "quota_units_est": 0, "circuit_break": False}
    units = 0
    circuit = False
    try:
        # 1) 解析 pending(每行 1 单位, 停用行也解析让账号页尽出标题;
        #    /c/、/user/ 遗留形态先 forHandle 后 forUsername)
        for row in channels:
            if row.get("resolve_status") == "resolved":
                continue
            kind, val = row.get("kind"), row.get("value") or ""
            try:
                if kind == "channel_id":
                    d = _yt_get("/channels", {"part": "snippet,statistics,contentDetails",
                                              "id": val}, key)
                    items = d.get("items") or []
                    if not items:
                        row["resolve_status"] = "failed"
                        row["resolve_error"] = "频道不存在"
                        report["resolve_failed"] += 1
                    else:
                        _fill_channel_row(row, items[0])
                        row["resolve_status"] = "resolved"
                        row["resolve_error"] = ""
                        report["resolved"] += 1
                else:
                    if kind == "name":
                        # 频道名搜索解析(100 单位, 一次性): 取首个命中 → channel_id,
                        # title/subs 由步骤 2 的批量 channels.list 回填
                        d = _yt_get("/search", {"part": "snippet", "type": "channel",
                                                "q": val, "maxResults": 1}, key)
                        units += 100
                        hits = d.get("items") or []
                        cid0 = ((hits[0].get("snippet") or {}).get("channelId")) if hits else ""
                        if not cid0:
                            row["resolve_status"] = "failed"
                            row["resolve_error"] = "搜索不到该频道名"
                            report["resolve_failed"] += 1
                            continue
                        row["channel_id"] = cid0
                        row["resolved_via"] = "name_search"
                        row["resolve_status"] = "resolved"   # title/subs 由批量刷新回填
                        report["resolved"] += 1
                        continue
                    handle = val if val.startswith("@") else "@" + val
                    d = _yt_get("/channels", {"part": "snippet,statistics,contentDetails",
                                              "forHandle": handle}, key)
                    items = d.get("items") or []
                    if not items:                    # 遗留 /c/ /user/ 兜底
                        d = _yt_get("/channels", {"part": "snippet,statistics,contentDetails",
                                                  "forUsername": handle.lstrip("@")}, key)
                        items = d.get("items") or []
                    if not items:                    # 终极兜底: 当频道名搜索(纯 ASCII 名误判 handle 时救命)
                        d = _yt_get("/search", {"part": "snippet", "type": "channel",
                                                "q": handle.lstrip("@"), "maxResults": 1}, key)
                        units += 100
                        hits = d.get("items") or []
                        if hits:
                            cid0 = (hits[0].get("snippet") or {}).get("channelId") or ""
                            if cid0:
                                row["channel_id"] = cid0
                                row["resolved_via"] = "name_search"
                                row["resolve_status"] = "resolved"
                                report["resolved"] += 1
                                continue
                    if not items:
                        row["resolve_status"] = "failed"
                        row["resolve_error"] = "未找到该 handle 的频道"
                        report["resolve_failed"] += 1
                    else:
                        _fill_channel_row(row, items[0])
                        row["resolve_status"] = "resolved"
                        row["resolve_error"] = ""
                        report["resolved"] += 1
                units += 1 if items else 2
            except _QuotaExceeded:
                circuit = True
                break
            except Exception as e:
                row["resolve_status"] = "failed"
                row["resolve_error"] = type(e).__name__
                report["resolve_failed"] += 1
        config.save_yt_channels(channels)
        if circuit:
            raise _QuotaExceeded()

        enabled = [c for c in channels
                   if c.get("enabled", True) and c.get("resolve_status") == "resolved"
                   and c.get("channel_id")]
        report["channels_ok"] = len(enabled)
        en_ids = {c["channel_id"] for c in enabled}

        # 2) 频道元数据批量刷新(50/批, 1 单位/批; 订阅数取整仅展示)
        for batch in _chunks(enabled, 50):
            try:
                d = _yt_get("/channels", {"part": "snippet,statistics,contentDetails",
                                          "id": ",".join(c["channel_id"] for c in batch)}, key)
                units += 1
                got = {it.get("id"): it for it in d.get("items") or []}
                for c in batch:
                    it = got.get(c["channel_id"])
                    if it:
                        _fill_channel_row(c, it)
                        c["last_ok_at"] = now_s
                        c["last_error"] = ""
                    else:
                        c["last_error"] = "channel_not_found"
            except _QuotaExceeded:
                circuit = True
                break
            except Exception:
                for c in batch:
                    c["last_error"] = "http_error"
        config.save_yt_channels(channels)
        if circuit:
            raise _QuotaExceeded()

        # 3) 发现新视频: uploads 播放列表第 1 页(1 单位/频道)
        for c in enabled:
            pid = c.get("uploads_pid")
            if not pid:
                continue
            try:
                d = _yt_get("/playlistItems",
                            {"part": "snippet,contentDetails", "playlistId": pid,
                             "maxResults": DISCOVER_TAKE}, key)
                units += 1
            except _QuotaExceeded:
                circuit = True
                break
            except Exception:
                c["last_error"] = "discover_failed"
                continue
            have = sum(1 for v in store["videos"].values()
                       if v.get("channel_id") == c["channel_id"])
            for it in d.get("items") or []:
                vid = ((it.get("contentDetails") or {}).get("videoId")) or ""
                if not vid or vid in store["videos"]:
                    continue
                if have >= MAX_PER_CHANNEL:
                    break
                sn = it.get("snippet") or {}
                store["videos"][vid] = {
                    "video_id": vid, "channel_id": c["channel_id"],
                    "title": sn.get("title") or "", "published": _iso_ts(sn.get("publishedAt")),
                    "duration_s": None, "is_short": None,
                    "tags": [], "thumb": _thumb(sn),
                    "first_seen": now, "first_seen_views": None,
                    "last_stats": None, "status": "ok", "series": []}
                have += 1
                report["new_videos"] += 1
        if circuit:
            raise _QuotaExceeded()

        # 4) 统计刷新候选集: 新视频 + 分层冷却到期的老视频
        #    (≤48h→1h, ≤7d→6h, ≤28d→24h; 更老不主动刷, >28d 快照也已被 prune)
        refresh = set()
        for vid, v in store["videos"].items():
            if v.get("status") == "unavailable" or v.get("channel_id") not in en_ids:
                continue
            if v.get("last_stats") is None:          # 新发现未取到统计的
                refresh.add(vid)
                continue
            pub = v.get("published") or now
            age_h = (now - pub) / 3600
            need = 3600 if age_h <= 48 else 6 * 3600 if age_h <= 24 * 7 \
                else 24 * 3600 if age_h <= 28 * 24 else None
            if need is not None and now - v["last_stats"] >= need:
                refresh.add(vid)
        report["refresh_candidates"] = len(refresh)

        # 5) 批量刷新统计(50/批, 1 单位/批) → 追加快照
        for batch in _chunks(sorted(refresh), 50):
            try:
                d = _yt_get("/videos", {"part": "snippet,statistics,contentDetails",
                                        "id": ",".join(batch)}, key)
                units += 1
            except _QuotaExceeded:
                circuit = True
                break
            except Exception:
                continue
            got = {it.get("id"): it for it in d.get("items") or []}
            for vid in batch:
                v = store["videos"].get(vid)
                if not v:
                    continue
                it = got.get(vid)
                if not it:                           # 删除/转私享: 保留快照不再刷新
                    v["status"] = "unavailable"
                    continue
                sn = it.get("snippet") or {}
                st = it.get("statistics") or {}
                v["title"] = sn.get("title") or v.get("title") or ""
                v["duration_s"] = _iso8601_s((it.get("contentDetails") or {}).get("duration"))
                v["is_short"] = (v["duration_s"] or 0) <= SHORT_S if v["duration_s"] else v.get("is_short")
                v["tags"] = (sn.get("tags") or [])[:12]
                v["description_head"] = (sn.get("description") or "").strip()[:DESC_HEAD]
                if not v.get("thumb"):
                    v["thumb"] = _thumb(sn)
                views = _int(st.get("viewCount"))
                if v.get("first_seen_views") is None:
                    v["first_seen_views"] = views
                v["series"].append({"ts": int(now), "v": views,
                                    "l": _int(st.get("likeCount")),
                                    "c": _int(st.get("commentCount"))})
                v["last_stats"] = now
                report["snapshotted"] += 1
    except _QuotaExceeded:
        circuit = True
        report["circuit_break"] = True
        report["msg"] = "YouTube 配额熔断(quotaExceeded), 已保留旧快照"
    finally:
        _fill_insights(store, report)            # LLM 解读不吃 YT 配额, 熔断也照跑
        _prune(store)
        store["updated_at"] = now_s
        report["quota_units_est"] = units
        exit_code = 3 if circuit else 0
        store["last_collect"] = {"running": False, "started_at": lc.get("started_at"),
                                 "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                 "exit": exit_code, "report": report}
        save_store(store)
    print(json.dumps(report, ensure_ascii=False))
    return report, (3 if circuit else 0)


# ── 指标与榜单(读缓存, 无外呼; app.py 端点用) ────────────────────────────────
def _delta(series: list, now: float, win_s: int, tol_s: int) -> tuple[int | None, bool]:
    """窗口增量: 锚点=≤now−win 的最近一点; 锚点过老(>win+tol)或跨度<1h → 不可信。"""
    if len(series) < 2:
        return None, False
    anchor = None
    for p in series:
        if p["ts"] <= now - win_s:
            anchor = p
        else:
            break
    if anchor is None:
        return None, False
    span = now - anchor["ts"]
    if span > win_s + tol_s or span < 3600:
        return None, False
    last = series[-1]
    if last.get("v") is None or anchor.get("v") is None:
        return None, False
    return last["v"] - anchor["v"], True


def build_view(range: str = "24h", sort: str = "views", kind: str = "all",
               channel: str = "", q: str = "", limit: int = 100) -> dict:
    """热点榜主表=启用频道的窗口内视频, 快照差分派生增量; 绝不外呼。
    sort: views(累计播放, 默认=用户主视角) | delta24h | delta7d | rate(折合日速) | newest。
    增量 None/不可信一律沉底; 新视频用首见基线(basis=first_seen, 前端标 *)。"""
    range = range if range in _RANGES else "24h"
    sort = sort if sort in _SORTS else "views"
    now = time.time()
    store = load_store()
    channels = [c for c in config.load_yt_channels()
                if c.get("enabled", True) and c.get("resolve_status") == "resolved"]
    ch_map = {c["channel_id"]: c for c in channels}
    en_ids = set(ch_map)

    lc = store.get("last_collect") or {}
    data_age_min = None
    if lc.get("finished_at"):
        try:
            data_age_min = int((now - time.mktime(
                time.strptime(lc["finished_at"], "%Y-%m-%d %H:%M:%S"))) / 60)
        except Exception:
            pass

    rows = []
    for vid, v in store["videos"].items():
        cid = v.get("channel_id")
        if cid not in en_ids:
            continue
        pub = v.get("published")
        if pub is None:
            continue
        range_h = _RANGES[range]
        if range_h and now - pub > range_h * 3600:
            continue
        series = sorted(v.get("series", []), key=lambda p: p["ts"])
        last = series[-1] if series else None
        views = last.get("v") if last else None
        likes = last.get("l") if last else None
        comments = last.get("c") if last else None
        age_h = max((now - pub) / 3600, 0)

        d24, cred24 = _delta(series, now, 24 * 3600, 8 * 3600)
        basis24 = "snapshot" if d24 is not None else None
        if d24 is None and age_h <= 24 and views is not None \
                and v.get("first_seen_views") is not None:
            d24, cred24, basis24 = views - v["first_seen_views"], False, "first_seen"
        d7, cred7 = _delta(series, now, 7 * 86400, 24 * 3600)

        rate = None                                   # 折合日速(最近两点, ≥30min 防抖)
        if len(series) >= 2:
            s1, s2 = series[-2], series[-1]
            span_d = (s2["ts"] - s1["ts"]) / 86400
            if span_d >= 0.5 / 24 and s1.get("v") is not None and s2.get("v") is not None:
                rate = (s2["v"] - s1["v"]) / span_d

        first24 = None                                # 发布后 24h 表现(首点须在 6h 内纳管)
        if series and views is not None and age_h >= 24 and series[0]["ts"] <= pub + 6 * 3600 \
                and series[0].get("v") is not None:
            p24 = next((p for p in series if p["ts"] >= pub + 24 * 3600
                        and p.get("v") is not None), None)
            if p24:
                first24 = p24["v"] - series[0]["v"]

        title = v.get("title") or ""
        if q and q.lower() not in title.lower():
            continue
        if kind == "short" and not v.get("is_short"):
            continue
        if kind == "long" and v.get("is_short") is not False:
            continue
        if channel and cid != channel:
            continue
        rows.append({
            "video_id": vid, "channel_id": cid,
            "channel_title": (ch_map.get(cid) or {}).get("title") or "",
            "title": title,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "thumb": v.get("thumb") or "",
            "published_at": time.strftime("%m-%d %H:%M", time.localtime(pub)),
            "age_h": round(age_h, 1),
            "duration_s": v.get("duration_s"), "is_short": bool(v.get("is_short")),
            "views": views, "likes": likes, "comments": comments,
            "delta_24h": d24, "delta_24h_credible": cred24, "delta_24h_basis": basis24,
            "delta_7d": d7 if cred7 else None,
            "rate_per_day": round(rate) if rate is not None else None,
            "first24_views": first24,
            "snap_n": len(series), "cold": len(series) < 2,
        })

    # 分层负数制: 可信 0 > 首见基线 -1 > 不可信/缺 -2, 配合 reverse=True 保证可信在前、None 沉底
    def sort_key(r):
        vv = r["views"] or 0
        if sort == "newest":
            return (r["published_at"] or "", vv)
        if sort == "delta24h":
            tier = 0 if r["delta_24h_credible"] else (-1 if r["delta_24h"] is not None else -2)
            return (tier, r["delta_24h"] if r["delta_24h"] is not None else -1, vv)
        if sort == "delta7d":
            return (0 if r["delta_7d"] is not None else -1,
                    r["delta_7d"] if r["delta_7d"] is not None else -1, vv)
        if sort == "rate":
            return (0 if r["rate_per_day"] is not None else -1,
                    r["rate_per_day"] if r["rate_per_day"] is not None else -1, vv)
        return (0 if views is not None else -1, views if views is not None else -1, vv)

    rows.sort(key=sort_key, reverse=True)
    total = len(rows)
    rows = rows[:limit]
    cold_start = bool(rows) and all(r["cold"] for r in rows)

    # 热门视频解读(页面最前块): 近7天播放 Top20 固定取前10, 不随大榜筛选联动
    insights = []
    for vid in _insight_hot_vids(store, en_ids, now)[:INSIGHT_TAKE]:
        v = store["videos"].get(vid) or {}
        pub = v.get("published")
        if not pub:
            continue
        series = sorted(v.get("series") or [], key=lambda p: p["ts"])
        last = series[-1] if series else {}
        d24, cred24 = _delta(series, now, 24 * 3600, 8 * 3600)
        if d24 is None and (now - pub) / 3600 <= 24 and last.get("v") is not None \
                and v.get("first_seen_views") is not None:
            d24 = last["v"] - v["first_seen_views"]
        d7, cred7 = _delta(series, now, 7 * 86400, 24 * 3600)
        rate = None
        if len(series) >= 2:
            s1, s2 = series[-2], series[-1]
            span_d = (s2["ts"] - s1["ts"]) / 86400
            if span_d >= 0.5 / 24 and s1.get("v") is not None and s2.get("v") is not None:
                rate = (s2["v"] - s1["v"]) / span_d
        ins = v.get("insight") or {}
        insights.append({
            "video_id": vid, "title": v.get("title") or "",
            "url": f"https://www.youtube.com/watch?v={vid}",
            "channel_title": (ch_map.get(v.get("channel_id")) or {}).get("title") or "",
            "is_short": bool(v.get("is_short")),
            "published_at": time.strftime("%m-%d %H:%M", time.localtime(pub)),
            "views": last.get("v"), "likes": last.get("l"), "comments": last.get("c"),
            "summary": ins.get("summary"), "tags": ins.get("tags") or [],
            "delta_24h": d24, "delta_24h_credible": cred24,
            "delta_7d": d7 if cred7 else None,
            "rate_per_day": round(rate) if rate is not None else None,
        })
    tcfg = config.load().get("translate") or {}
    return {"items": rows, "total": total, "insights": insights,
            "meta": {"range": range, "sort": sort, "kind": kind, "channel": channel,
                     "configured": bool(api_key()),
                     "insight_configured": bool(tcfg.get("base_url") and tcfg.get("api_key")
                                                and tcfg.get("model")),
                     "enabled_channels": len(en_ids),
                     "updated_at": store.get("updated_at"),
                     "last_collect_at": lc.get("finished_at"),
                     "data_age_min": data_age_min,
                     "cold_start": cold_start,
                     "caliber": store.get("caliber"),
                     "rule": "Δviews=本地快照差分; 无快照/不可信一律沉底; 带*为新视频首见基线(偏小); "
                             "Shorts=时长≤3分钟; 播放口径 2026-08-24 起=开始播放即计, 跨口径不可比斜率; "
                             "订阅数为公开取整仅展示"}}


def status_payload() -> dict:
    """页顶状态条 + 采集按钮轮询用。零外呼。"""
    store = load_store()
    channels = config.load_yt_channels()
    lc = store.get("last_collect") or {}
    running = False
    if lc.get("running") and lc.get("started_at"):
        try:
            running = time.time() - time.mktime(
                time.strptime(lc["started_at"], "%Y-%m-%d %H:%M:%S")) < RUNNING_STALE_MIN * 60
        except Exception:
            pass
    data_age_min = None
    if lc.get("finished_at"):
        try:
            data_age_min = int((time.time() - time.mktime(
                time.strptime(lc["finished_at"], "%Y-%m-%d %H:%M:%S"))) / 60)
        except Exception:
            pass
    return {"configured": bool(api_key()),
            "running": running, "started_at": lc.get("started_at"),
            "finished_at": lc.get("finished_at"), "last_exit": lc.get("exit"),
            "last_report": lc.get("report") or {},
            "data_age_min": data_age_min,
            "channels": {"total": len(channels),
                         "enabled": sum(1 for c in channels if c.get("enabled", True)),
                         "pending": sum(1 for c in channels if c.get("resolve_status") == "pending"),
                         "failed": sum(1 for c in channels if c.get("resolve_status") == "failed")},
            "videos_tracked": len(store.get("videos") or {})}


def add_channel(inp: str, note: str = "", enabled: bool = True) -> tuple[dict | None, dict | None]:
    """账号入库(纯本地解析, 零外呼; 解析留待下一轮采集)。返回 (row, err)。"""
    parsed = parse_channel_input(inp)
    if not parsed:
        return None, {"error": "无法识别的 YouTube 账号格式",
                      "hint": "支持 @handle 或 youtube.com/@handle、/channel/UC… 链接"}
    channels = config.load_yt_channels()
    val = parsed["value"]
    for c in channels:
        if c.get("value") == val or c.get("input", "").strip() == inp.strip():
            return None, {"error": "该频道已在追踪列表",
                          "hint": c.get("title") or c.get("input") or ""}
    row = {"id": "y" + time.strftime("%m%d%H%M%S"),
           "input": inp.strip(), "kind": parsed["kind"], "value": val,
           "handle": val if parsed["kind"] == "handle" else "",
           "channel_id": val if parsed["kind"] == "channel_id" else "",
           "title": "", "note": note or "", "enabled": bool(enabled),
           "resolve_status": "pending", "resolve_error": "",
           "subs": None, "uploads_pid": "",
           "added_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    channels.append(row)
    config.save_yt_channels(channels)
    return row, None
