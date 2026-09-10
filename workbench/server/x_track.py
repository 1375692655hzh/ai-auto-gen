"""X 账号追踪 —— 自选账号粉丝/增粉/更新/流量日快照数据面(图文页【账号追踪】子页)。

与 yt_track 同构(2026-09-10): 库单文件原子写 + 采集只在 CLI 进程外呼 + app.py 端点零外呼。
- 账号库 data/workbench/x_track.json: accounts 以 handle 为键, 每账号 days 按日快照
  (粉丝/更新次数/流量), 日粒度满足「观察每日粉丝量」; 同日多轮采集按单调合并
  (counters 取 max 防时间线窗口截断回退, followers 恒取最新真值)。
- 数据通路: api.fxtwitter.com 免登录 v2 两只 —— /2/profile/<h>(followers/累计推数)
  + /2/profile/<h>/statuses?with_replies=true(每帖 views/replies/created_timestamp),
  与 fetchers/basic.py 池抓取同源同限速纪律(2026-09-01 实测零限流; 429 全局熔断)。
- 口径: 增粉=当日粉丝-前一日粉丝; 更新次数=当日本人发帖+回复(转推不计, 线程逐帖计);
  流量=当日新帖(帖+回复)浏览量之和(采集时刻口径, 旧日随重采缓涨属正常)。
- 采集入口: CLI `workbench refresh-x-track`(按钮/计划任务拉起); 日界为北京时间。

架构红线: 对板块一只读(导入关注列表只读 x_account_prefs/twitter_pool); 本模块外呼
仅发生在 CLI 进程, app.py 端点只读缓存或 spawn CLI。
"""

import json
import os
import re
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "workbench"
TRACK_FILE = DATA_DIR / "x_track.json"
REPO = Path(__file__).resolve().parents[2]
TASK_NAME = "aag-xtrack-refresh"

_FX = "https://api.fxtwitter.com"
HTTP_TIMEOUT = 15
WORKERS = 3                        # FxTwitter 友好(池抓取同款纪律), 3 并发足够
COUNT_PER_PAGE = 100               # v2 单页条数上限实测 100
MAX_PAGES = 2                      # 最多翻 2 页(200 帖, 覆盖日更百帖账号两天窗)
DAY_RETAIN = 120                   # 单账号日快照保留天数
MAX_ACCOUNTS = 300                 # 全库账号硬顶
COOLDOWN_MIN = 5                   # 采集冷却(防按钮/计划任务双跑; --force 穿透)
RUNNING_STALE_MIN = 30             # 重入锁过期(僵尸接管)
PAGE_DELAY_S = 0.5                 # 同账号翻页间隔

_BJ = timezone(timedelta(hours=8))
_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_URL_RE = re.compile(r"(?:x|twitter)\.com/@?([A-Za-z0-9_]{1,15})", re.I)


# ── 输入解析(纯函数, 离线可测) ───────────────────────────────────────────────
def parse_handle(raw: str) -> str | None:
    """@handle / 裸 handle / x.com 链接 → 归一 handle(小写); 识别不出 None。"""
    s = (raw or "").strip()
    if not s:
        return None
    m = _URL_RE.search(s)
    if m:
        s = m.group(1)
    else:
        s = s.lstrip("@")
    if not _HANDLE_RE.fullmatch(s):
        return None
    return s.lower()


# ── 库读写(单文件原子写, 损坏当空库重来) ─────────────────────────────────────
def _empty_store() -> dict:
    return {"version": 1, "updated_at": None, "last_collect": {}, "accounts": {}}


def load_store() -> dict:
    if not TRACK_FILE.is_file():
        return _empty_store()
    try:
        d = json.loads(TRACK_FILE.read_text(encoding="utf-8"))
        d.setdefault("accounts", {})
        d.setdefault("last_collect", {})
        d.setdefault("version", 1)
        return d
    except Exception:
        return _empty_store()


def save_store(store: dict) -> None:
    store["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, TRACK_FILE)


def _prune(acc: dict) -> None:
    days = acc.get("days") or {}
    if len(days) > DAY_RETAIN:
        keep = sorted(days)[-DAY_RETAIN:]
        acc["days"] = {k: days[k] for k in keep}


# ── 账号增删改(端点侧, 零外呼) ───────────────────────────────────────────────
def add_account(inp: str, note: str = "", enabled: bool = True) -> tuple[dict | None, dict | None]:
    handle = parse_handle(inp)
    if not handle:
        return None, {"error": "无法识别的 X 账号格式",
                      "hint": "支持 @handle、裸 handle 或 x.com/<handle> 链接"}
    store = load_store()
    accounts = store["accounts"]
    if handle in accounts:
        return None, {"error": "该账号已在追踪列表", "hint": "@" + handle}
    if len(accounts) >= MAX_ACCOUNTS:
        return None, {"error": f"追踪账号已达上限({MAX_ACCOUNTS}), 请先删减"}
    row = {"handle": handle, "name": "", "avatar": "", "verified": False,
           "bio": "", "note": note or "", "enabled": bool(enabled),
           "error": "", "error_at": "",
           "added_at": time.strftime("%Y-%m-%d %H:%M:%S"), "days": {}}
    accounts[handle] = row
    save_store(store)
    return row, None


def remove_account(handle: str) -> int:
    store = load_store()
    h = (handle or "").strip().lstrip("@").lower()
    if h in store["accounts"]:
        del store["accounts"][h]
        save_store(store)
        return 1
    return 0


def set_enabled(handle: str, on: bool) -> bool:
    store = load_store()
    h = (handle or "").strip().lstrip("@").lower()
    acc = store["accounts"].get(h)
    if acc is None:
        return False
    acc["enabled"] = bool(on)
    save_store(store)
    return True


def set_note(handle: str, note: str) -> bool:
    store = load_store()
    h = (handle or "").strip().lstrip("@").lower()
    acc = store["accounts"].get(h)
    if acc is None:
        return False
    acc["note"] = (note or "")[:200]
    save_store(store)
    return True


def import_followed() -> dict:
    """从账号管理页的关注列表(x_account_prefs follow=True ∩ 池)导入, 只复制不删源。"""
    from . import xaccounts
    prefs = config.load_x_prefs()
    pool = xaccounts.load_accounts()
    store = load_store()
    imported, skipped = [], []
    for key, pref in prefs.items():
        if not (isinstance(pref, dict) and pref.get("follow")):
            continue
        h = str(key).lower().lstrip("@")
        if h not in pool or h in store["accounts"]:
            skipped.append(h)
            continue
        src = pool[h]
        store["accounts"][h] = {
            "handle": h, "name": src.get("name") or "", "avatar": "",
            "verified": False, "bio": "", "note": "导入自关注列表",
            "enabled": True, "error": "", "error_at": "",
            "added_at": time.strftime("%Y-%m-%d %H:%M:%S"), "days": {}}
        imported.append(h)
    if imported:
        save_store(store)
    return {"imported": imported, "skipped": skipped}


# ── 采集(CLI 进程) ───────────────────────────────────────────────────────────
class _RateLimited(Exception):
    pass


def _get_json(url: str, params: dict | None = None) -> dict:
    import urllib.error
    import urllib.parse
    import urllib.request
    full = _FX + url
    if params:
        full += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": "aag-workbench/0.1",
                                                "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise _RateLimited()
        raise RuntimeError(f"http_{e.code}")


def _fetch_profile(handle: str) -> dict:
    """→ {followers, statuses_total, name, bio, avatar, verified}; 404/不存在抛 KeyError。"""
    d = _get_json(f"/2/profile/{handle}")
    if d.get("code") != 200 or not d.get("user"):
        raise KeyError(d.get("message") or f"code={d.get('code')}")
    u = d["user"]
    return {"followers": int(u.get("followers") or 0),
            "statuses_total": int(u.get("statuses") or 0),
            "name": str(u.get("name") or ""),
            "bio": str(u.get("description") or "")[:200],
            "avatar": str(u.get("avatar_url") or ""),
            "verified": bool(((u.get("verification") or {}).get("verified"))
                             or u.get("verification", {}).get("verified_at"))}


def _fetch_statuses(handle: str) -> list:
    """时间线一页起步, 最旧帖仍在 26h 内则翻页(最多 2 页); 非本人帖/转推剔除同 basic.py。"""
    out, cursor, pages = [], None, 0
    while pages < MAX_PAGES:
        params = {"count": COUNT_PER_PAGE, "groupthreads": "true", "with_replies": "true"}
        if cursor:
            params["cursor"] = cursor
        d = _get_json(f"/2/profile/{handle}/statuses", params)
        if d.get("code") != 200:
            raise RuntimeError(f"code={d.get('code')}")
        res = d.get("results") or []
        out.extend(res)
        oldest_ts = None
        for it in res:
            for s in _own_statuses(it, handle):
                ts = s.get("created_timestamp")
                oldest_ts = ts if isinstance(ts, (int, float)) and (
                    oldest_ts is None or ts < oldest_ts) else oldest_ts
        cursor = (d.get("cursor") or {}).get("bottom") or None
        pages += 1
        if not cursor or not res:
            break
        fresh = oldest_ts is not None and oldest_ts > time.time() - 26 * 3600
        if not fresh and pages >= 1:
            break                                    # 已覆盖超过一天窗, 不必再翻
        time.sleep(PAGE_DELAY_S)
    return out


def _own_statuses(item: dict, handle: str) -> list:
    """条目 → 本人帖列表(线程展开, 转推/他人帖剔除; 与 fetchers/basic.py 同规则)。"""
    posts = item.get("statuses") or [] if item.get("type") == "thread" else [item]
    own = []
    for s in posts:
        if not isinstance(s, dict):
            continue
        au = s.get("author") or {}
        if str(au.get("screen_name", "")).lower() != handle:
            continue
        if s.get("reposted_by"):
            continue
        own.append(s)
    return own


def _bucket_days(statuses: list, handle: str) -> dict:
    """本人帖按北京时区日界分桶 → {date: {updates, posts, replies, views, likes, rts}}。"""
    days: dict[str, dict] = {}
    for it in statuses:
        for s in _own_statuses(it, handle):
            ts = s.get("created_timestamp")
            if not isinstance(ts, (int, float)):
                continue
            d = datetime.fromtimestamp(ts, _BJ).strftime("%Y-%m-%d")
            bucket = days.setdefault(d, {"updates": 0, "posts": 0, "replies": 0,
                                         "views": 0, "likes": 0, "rts": 0})
            bucket["updates"] += 1
            bucket["replies" if s.get("replying_to") else "posts"] += 1
            bucket["views"] += int(s.get("views") or 0)
            bucket["likes"] += int(s.get("likes") or 0)
            bucket["rts"] += int(s.get("reposts") or 0)
    return days


_MERGE_KEYS = ("updates", "posts", "replies", "views", "likes", "rts")


def _collect_one(handle: str) -> tuple[dict, dict, str]:
    """单账号一轮: 档案 + 时间线 → 档案行 + 日快照桶。返回 (profile, days, err)。"""
    try:
        prof = _fetch_profile(handle)
    except KeyError as e:
        return None, None, f"账号不存在({e})"
    except _RateLimited:
        raise
    except Exception as e:
        return None, None, f"{type(e).__name__}: {str(e)[:60]}"
    try:
        days = _bucket_days(_fetch_statuses(handle), handle)
    except _RateLimited:
        raise
    except Exception as e:
        days, err = {}, f"timeline {type(e).__name__}: {str(e)[:50]}"
    else:
        err = ""
    now_s = time.strftime("%Y-%m-%d %H:%M:%S")
    today = datetime.now(_BJ).strftime("%Y-%m-%d")
    row = {"followers": prof["followers"], "statuses_total": prof["statuses_total"],
           "sampled_at": now_s}
    days = dict(days)
    days[today] = {**(days.get(today) or {}), **row}   # 档案日快照(即使时间线挂了粉丝也照记)
    return prof, days, err


def collect(force: bool = False, handles: list | None = None) -> tuple[dict, int]:
    """一轮采集(仅 CLI 进程调用): 占锁→并发拉→单调合并→落盘。返回 (report, exit_code)。"""
    store = load_store()
    lc = store.get("last_collect") or {}
    now = time.time()

    def _ts(v):
        try:
            return time.mktime(time.strptime(v, "%Y-%m-%d %H:%M:%S"))
        except Exception:
            return None

    if not force:
        if lc.get("running") and lc.get("started_at"):
            st = _ts(lc["started_at"])
            if st is not None and now - st < RUNNING_STALE_MIN * 60:
                return {"skipped": "already_running", "started_at": lc["started_at"]}, 0
        if lc.get("finished_at"):
            ft = _ts(lc["finished_at"])
            if ft is not None and now - ft < COOLDOWN_MIN * 60:
                return {"skipped": "cooldown", "finished_at": lc["finished_at"]}, 0

    accounts = store["accounts"]
    todo = [h for h, a in accounts.items()
            if a.get("enabled", True) and (not handles or h in handles)]
    if not todo:
        return {"msg": "无启用的追踪账号", "total": 0}, 0

    started_s = store["last_collect"].get("started_at")
    save_store(store)                                # 先占锁再外呼

    report = {"total": len(todo), "ok": 0, "fail": 0, "circuit_break": False,
              "failures": {}}
    lock = threading.Lock()
    circuit = False
    results: dict[str, dict] = {}                    # handle → {days, followers, statuses_total}

    def work(h: str):
        nonlocal circuit
        if circuit:
            return
        try:
            prof, days, err = _collect_one(h)
        except _RateLimited:
            with lock:
                circuit = True                       # 全局熔断: 本轮到此为止, 保旧数据
            return
        with lock:
            if err:
                report["fail"] += 1
                report["failures"][h] = err
            else:
                report["ok"] += 1
            if days and prof:
                results[h] = {"days": days, "followers": prof["followers"],
                              "statuses_total": prof["statuses_total"]}

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(work, todo))

    # 重读库再合并: 采集窗口(分钟级)内用户增删/开关经服务端落盘, 整存旧快照会
    # 复活已删账号(lost-update); 结果只并进仍存在的账号, 已删的自然丢弃。
    store = load_store()
    accounts = store["accounts"]
    now_s = time.strftime("%Y-%m-%d %H:%M:%S")
    for h, got in results.items():
        acc = accounts.get(h)
        if acc is None:
            continue
        merged = acc.get("days") or {}
        for d, row in got["days"].items():
            old = merged.get(d) or {}
            new = dict(old)
            for k in _MERGE_KEYS:
                new[k] = max(int(old.get(k) or 0), int(row.get(k) or 0))
            new.update({k: row[k] for k in ("followers", "statuses_total", "sampled_at")
                        if k in row})
            merged[d] = new
        # 冷启动回填: 本轮覆盖到的天缺粉丝记录(纯时间线天)时, 用当前档案值补基线
        # —— 增粉曲线从追踪起点平铺起步, 首轮 delta 不会误算成全量粉丝数。
        for d, row in merged.items():
            if "followers" not in row:
                row["followers"] = got["followers"]
                row["statuses_total"] = got["statuses_total"]
                row["sampled_at"] = now_s
        acc["days"] = merged
        _prune(acc)
    for h, acc in accounts.items():
        if report["failures"].get(h):
            acc["error"] = report["failures"][h][:120]
            acc["error_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        elif h in results:
            acc["error"] = ""
            acc["error_at"] = ""
    store["last_collect"] = {
        "running": False, "started_at": started_s,
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "exit": 0, "report": dict(report)}
    save_store(store)
    report["elapsed_s"] = int(time.time() - t0)
    if circuit:
        report["not_run"] = report["total"] - report["ok"] - report["fail"]
    return report, (3 if circuit else 0)


# ── 视图(端点侧, 零外呼) ─────────────────────────────────────────────────────
def _delta(series: list, i: int):
    """第 i 天相对前一可见日的粉丝差; 无前日 None。series=[(d, row)] 升序。"""
    if i <= 0:
        return None
    a, b = series[i - 1][1].get("followers"), series[i][1].get("followers")
    if a is None or b is None:
        return None
    return int(b) - int(a)


def _sum_range(days: dict, dates: list, keys: tuple) -> dict:
    out = {k: 0 for k in keys}
    for d in dates:
        row = days.get(d) or {}
        for k in keys:
            out[k] += int(row.get(k) or 0)
    return out


def _acc_row(handle: str, acc: dict) -> dict:
    days = acc.get("days") or {}
    dates = sorted(days)
    today = datetime.now(_BJ).strftime("%Y-%m-%d")
    last7 = [d for d in dates if d >= (datetime.now(_BJ) - timedelta(days=6)).strftime("%Y-%m-%d")]
    followers = int((days[dates[-1]].get("followers")) or 0) if dates else 0
    prev_f = int((days[dates[-2]].get("followers")) or 0) if len(dates) >= 2 else None
    d7 = _sum_range(days, last7, ("updates", "views"))
    base7 = int((days[last7[0]].get("followers")) or 0) if len(last7) >= 2 else None
    spark = [int((days[d].get("followers")) or 0) for d in dates[-30:]]
    return {"handle": handle, "name": acc.get("name") or "", "avatar": acc.get("avatar") or "",
            "verified": bool(acc.get("verified")), "bio": acc.get("bio") or "",
            "note": acc.get("note") or "", "enabled": acc.get("enabled", True),
            "error": acc.get("error") or "", "error_at": acc.get("error_at") or "",
            "added_at": acc.get("added_at") or "",
            "followers": followers,
            "delta_1d": (followers - prev_f) if prev_f is not None else None,
            "delta_7d": (followers - base7) if base7 is not None else None,
            "updates_1d": int(((days.get(today) or {}).get("updates")) or 0),
            "replies_1d": int(((days.get(today) or {}).get("replies")) or 0),
            "views_1d": int(((days.get(today) or {}).get("views")) or 0),
            "updates_7d": d7["updates"], "views_7d": d7["views"],
            "days_n": len(dates), "last_day": dates[-1] if dates else "",
            "sampled_at": (days[dates[-1]].get("sampled_at") or "") if dates else "",
            "spark": spark}


def overview_payload() -> dict:
    store = load_store()
    accounts = store["accounts"]
    rows = [_acc_row(h, a) for h, a in accounts.items()]
    rows.sort(key=lambda r: (not r["enabled"], -r["followers"], r["handle"]))
    st = status_payload()
    return {"accounts": rows, "count": len(rows),
            "enabled_n": sum(1 for r in rows if r["enabled"]),
            "status": st,
            "loaded_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def account_series(handle: str, days: int = 30) -> dict:
    h = (handle or "").strip().lstrip("@").lower()
    acc = load_store()["accounts"].get(h)
    if acc is None:
        return {}
    all_days = acc.get("days") or {}
    dates = sorted(all_days)[-max(1, min(int(days or 30), DAY_RETAIN)):]
    series = []
    for i, d in enumerate(dates):
        row = all_days[d]
        series.append({
            "date": d, "followers": int(row.get("followers") or 0),
            "delta": None,   # 下面补(相对全史前一可见日, 不受截窗影响)
            "updates": int(row.get("updates") or 0),
            "posts": int(row.get("posts") or 0),
            "replies": int(row.get("replies") or 0),
            "views": int(row.get("views") or 0),
            "likes": int(row.get("likes") or 0)})
    full = sorted(all_days)
    for i, d in enumerate(dates):
        j = full.index(d)
        series[i]["delta"] = _delta([(x, all_days[x]) for x in full], j)
    return {"account": _acc_row(h, acc), "series": series}


def status_payload() -> dict:
    """页顶状态条 + 采集按钮轮询用。零外呼。"""
    store = load_store()
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
    accounts = store.get("accounts") or {}
    return {"running": running, "started_at": lc.get("started_at"),
            "finished_at": lc.get("finished_at"), "last_report": lc.get("report") or {},
            "data_age_min": data_age_min,
            "total": len(accounts),
            "enabled": sum(1 for a in accounts.values() if a.get("enabled", True)),
            "scheduled": _task_scheduled()}


# ── 计划任务(对齐 xsurge_ctl 一键范式; 每小时 :11 错相) ──────────────────────
def _task_bat() -> Path:
    return REPO / "bin" / "xtrack_task.bat"


def _task_scheduled() -> bool:
    import shutil
    if os.name != "nt" or not shutil.which("schtasks"):
        return False
    try:
        p = subprocess.run(["schtasks", "/query", "/tn", TASK_NAME],
                           capture_output=True, text=True, timeout=15)
        return p.returncode == 0
    except Exception:
        return False


def schedule(on: bool = True) -> dict:
    """登记/移除每小时自动采集(Windows 任务计划, 与 :00/:07/:15 相位错开)。幂等。"""
    import shutil
    if os.name != "nt" or not shutil.which("schtasks"):
        return {"ok": False, "scheduled": False, "msg": "仅 Windows 支持任务计划; 手动点「立即采集」即可"}
    if not on:
        subprocess.run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
                       capture_output=True, text=True, timeout=30)
        return {"ok": True, "scheduled": False, "msg": "已停止定时采集"}
    if _task_scheduled():
        return {"ok": True, "scheduled": True, "msg": "定时采集已开启, 每小时自动跑一轮"}
    bat = _task_bat()
    if not bat.is_file():
        return {"ok": False, "scheduled": False,
                "msg": f"缺少 {bat}, 请重新拉取仓库"}
    vbs = REPO / "bin" / "silent_run.vbs"
    tr = f'wscript.exe "{vbs}" "{bat}"'
    cmd = ["schtasks", "/create", "/tn", TASK_NAME, "/tr", tr,
           "/sc", "hourly", "/st", "00:11", "/f"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception as e:
        return {"ok": False, "scheduled": False, "msg": f"登记失败: {e}"}
    if p.returncode == 0:
        return {"ok": True, "scheduled": True,
                "msg": "已开启每小时自动采集(数据以日快照落库)"}
    return {"ok": False, "scheduled": False,
            "msg": "任务计划登记失败(可能无权限)。可手动运行: schtasks /create " +
                   f'/tn "{TASK_NAME}" /tr "{tr}" /sc hourly /st 00:11 /f'}


# ── CLI 入口 ────────────────────────────────────────────────────────────────
def run_cli(args) -> int:
    handles = None
    if getattr(args, "handles", ""):
        handles = {parse_handle(x) for x in str(args.handles).split(",")}
        handles.discard(None)
        handles = list(handles) or None
    rep, code = collect(force=bool(getattr(args, "force", False)), handles=handles)
    print(json.dumps(rep, ensure_ascii=False))
    return code
