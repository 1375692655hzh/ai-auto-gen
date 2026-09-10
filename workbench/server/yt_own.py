"""YTB 自有频道追踪(独立系统, 2026-09-11 用户拍板): 追踪用户自己的 YouTube 频道。

与视频页【账号管理】(他人频道, 热点采集源, yt_channels.json)完全独立:
- 独立存储 data/workbench/yt_own_channels.json(行结构与 yt_channels 同款)
- 采集件复用 yt_track(同一 Data API 通道); 视频统计写共享内容库 yt_videos.json
  (内容数据, 非账号清单 —— 热点榜按共享频道的 enabled 集合过滤, 自频道不入榜)
- 外呼只在 CLI 进程(cli.py workbench refresh-yt-track 捎带本 sweep; 端点零外呼)
"""

import json
import time
from datetime import datetime

from . import config, yt_track

DISCOVER_TAKE = 20          # 每频道发现最新视频数(自有频道量小, 与主链 50 不同档)
MAX_PER_CHANNEL = 200


def _rows() -> list:
    return config.load_yt_own_channels()


def _save(rows: list) -> list:
    return config.save_yt_own_channels(rows)


def list_view() -> dict:
    """频道列表 + 六项统计(零外呼读缓存; 自频道行 stats 挂在 channel_id 上)。"""
    rows = _rows()
    stats = own_channel_stats()
    for r in rows:
        r["stats"] = stats.get(r.get("channel_id") or "") or {}
    return {"channels": rows,
            "meta": {"configured": bool(yt_track.api_key()),
                     "enabled": sum(1 for c in rows if c.get("enabled", True)),
                     "pending": sum(1 for c in rows if c.get("resolve_status") == "pending"),
                     "failed": sum(1 for c in rows if c.get("resolve_status") == "failed")}}


def own_channel_stats() -> dict:
    """channel_stats 的自频道版: 视频统计全库现成, subs/subs_delta 用自频道行。"""
    base = yt_track.channel_stats()
    now = time.time()
    for c in _rows():
        cid = c.get("channel_id")
        if not cid:
            continue
        st = base.setdefault(cid, {"updates_1d": None, "latest_views": None,
                                   "latest_title": "", "views_7d": None,
                                   "views_7d_delta": None})
        st["subs"] = c.get("subs")
        d, _ = yt_track._delta(sorted(c.get("subs_series") or [], key=lambda p: p["ts"]),
                               now, 24 * 3600, 8 * 3600)
        st["subs_delta_1d"] = d
    return base


def series(cid: str, days: int = 30) -> dict | None:
    row = next((c for c in _rows() if c.get("channel_id") == cid), None)
    if not row:
        return None
    return yt_track.channel_series(cid, days=days, row=row)


def set_enabled(cid: str, on: bool) -> dict | None:
    rows = _rows()
    for r in rows:
        if r.get("id") == cid:
            r["enabled"] = bool(on)
            _save(rows)
            return r
    return None


def remove(cid: str) -> list:
    """删除自有频道; 已采视频/快照保留为孤儿数据(防误删丢历史)。"""
    return _save([r for r in _rows() if r.get("id") != cid])


def add(inp: str, note: str = "", enabled: bool = True) -> tuple[dict | None, dict | None]:
    """自有频道入库(纯本地解析, 零外呼; 解析留待下一轮采集)。"""
    parsed = yt_track.parse_channel_input(inp)
    if not parsed:
        return None, {"error": "无法识别的 YouTube 账号格式",
                      "hint": "支持 @handle 或 youtube.com/@handle、/channel/UC… 链接"}
    rows = _rows()
    val = parsed["value"]
    for c in rows:
        if c.get("value") == val or c.get("input", "").strip() == inp.strip():
            return None, {"error": "该频道已在自有追踪列表",
                          "hint": c.get("title") or c.get("input") or ""}
    row = {"id": "yo" + time.strftime("%m%d%H%M%S"),
           "input": inp.strip(), "kind": parsed["kind"], "value": val,
           "handle": val if parsed["kind"] == "handle" else "",
           "channel_id": val if parsed["kind"] == "channel_id" else "",
           "title": "", "note": note or "", "enabled": bool(enabled),
           "resolve_status": "pending", "resolve_error": "",
           "subs": None, "uploads_pid": "",
           "added_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    rows.append(row)
    _save(rows)
    return row, None


# ── 采集 sweep(仅 CLI 进程调用; 镜像 yt_track.collect 的四步, 作用于自频道行) ──
def _resolve_row(row: dict, key: str, report: dict) -> None:
    """解析 pending 行(镜像 yt_track.collect 的解析分支; 停一版改主链时同步)。"""
    kind, val = row.get("kind"), row.get("value") or ""
    if kind == "channel_id":
        d = yt_track._yt_get("/channels", {"part": "snippet,statistics,contentDetails",
                                           "id": val}, key)
        items = d.get("items") or []
        if not items:
            row["resolve_status"] = "failed"; row["resolve_error"] = "频道不存在"
            report["resolve_failed"] += 1
            return
        yt_track._fill_channel_row(row, items[0])
        row["resolve_status"] = "resolved"; row["resolve_error"] = ""
        report["resolved"] += 1
        return
    if kind == "name":
        d = yt_track._yt_get("/search", {"part": "snippet", "type": "channel",
                                         "q": val, "maxResults": 1}, key)
        report["quota_units_est"] = report.get("quota_units_est", 0) + 100
        hits = d.get("items") or []
        cid0 = ((hits[0].get("snippet") or {}).get("channelId")) if hits else ""
        if not cid0:
            row["resolve_status"] = "failed"; row["resolve_error"] = "搜索不到该频道名"
            report["resolve_failed"] += 1
            return
        row["channel_id"] = cid0; row["resolved_via"] = "name_search"
        row["resolve_status"] = "resolved"; report["resolved"] += 1
        return
    handle = val if val.startswith("@") else "@" + val
    d = yt_track._yt_get("/channels", {"part": "snippet,statistics,contentDetails",
                                       "forHandle": handle}, key)
    items = d.get("items") or []
    if not items:                                   # 遗留 /c/ /user/ 兜底
        d = yt_track._yt_get("/channels", {"part": "snippet,statistics,contentDetails",
                                           "forUsername": handle.lstrip("@")}, key)
        items = d.get("items") or []
    if not items:                                   # 纯 ASCII 名误判 handle 时兜底搜频道名
        d = yt_track._yt_get("/search", {"part": "snippet", "type": "channel",
                                         "q": handle.lstrip("@"), "maxResults": 1}, key)
        report["quota_units_est"] = report.get("quota_units_est", 0) + 100
        hits = d.get("items") or []
        if hits:
            cid0 = (hits[0].get("snippet") or {}).get("channelId") or ""
            if cid0:
                row["channel_id"] = cid0; row["resolved_via"] = "name_search"
                row["resolve_status"] = "resolved"; report["resolved"] += 1
                return
    if not items:
        row["resolve_status"] = "failed"; row["resolve_error"] = "未找到该 handle 的频道"
        report["resolve_failed"] += 1
        return
    yt_track._fill_channel_row(row, items[0])
    row["resolve_status"] = "resolved"; row["resolve_error"] = ""
    report["resolved"] += 1


def _merge_enabled(rows: list) -> list:
    """lost-update 防护(同主链): 采集窗口内用户切开关不被整存覆盖。"""
    fresh = {c.get("id"): c.get("enabled", True) for c in _rows()}
    for c in rows:
        if c.get("id") in fresh:
            c["enabled"] = fresh[c["id"]]
    return rows


def collect(force: bool = False) -> tuple[dict, int]:
    """自有频道 sweep: 解析 pending → 批量刷元数据+订阅快照 → 发现新视频 → 统计追加快照。
    返回 (report, exit_code): 0 正常/无频道跳过, 3 配额熔断, 4 无 key。
    视频统计写共享内容库(与主链同库, 由各自 collect 负责; 无主链状态锁, 自频道独立跑)。"""
    rows = _rows()
    if not rows:
        rep = {"skipped": "no_own_channels"}
        return rep, 0
    key = yt_track.api_key()
    if not key:
        rep = {"error": "no_api_key",
               "hint": "设置页配置 youtube.api_key(或环境变量 YOUTUBE_API_KEY)后再采集"}
        print(json.dumps(rep, ensure_ascii=False))
        return rep, 4
    now_s = time.strftime("%Y-%m-%d %H:%M:%S")
    now = time.time()
    store = yt_track.load_store()
    report = {"own_total": len(rows), "resolved": 0, "resolve_failed": 0,
              "channels_ok": 0, "new_videos": 0, "snapshotted": 0,
              "quota_units_est": 0, "circuit_break": False}
    circuit = False
    try:
        for row in rows:
            if row.get("resolve_status") == "resolved":
                continue
            try:
                _resolve_row(row, key, report)
            except yt_track._QuotaExceeded:
                circuit = True
                break
            except Exception as e:
                row["resolve_status"] = "failed"
                row["resolve_error"] = type(e).__name__
                report["resolve_failed"] += 1
        _save(_merge_enabled(rows))
        if circuit:
            raise yt_track._QuotaExceeded()

        enabled = [c for c in rows if c.get("enabled", True)
                   and c.get("resolve_status") == "resolved" and c.get("channel_id")]
        report["channels_ok"] = len(enabled)
        en_ids = {c["channel_id"] for c in enabled}

        for batch in yt_track._chunks(enabled, 50):
            try:
                d = yt_track._yt_get("/channels",
                                     {"part": "snippet,statistics,contentDetails",
                                      "id": ",".join(c["channel_id"] for c in batch)}, key)
                report["quota_units_est"] += 1
                got = {it.get("id"): it for it in d.get("items") or []}
                for c in batch:
                    it = got.get(c["channel_id"])
                    if it:
                        yt_track._fill_channel_row(c, it)
                        yt_track._snap_subs(c, now, now_s)
                        c["last_ok_at"] = now_s
                        c["last_error"] = ""
                    else:
                        c["last_error"] = "channel_not_found"
            except yt_track._QuotaExceeded:
                circuit = True
                break
            except Exception:
                for c in batch:
                    c["last_error"] = "http_error"
        _save(_merge_enabled(rows))
        if circuit:
            raise yt_track._QuotaExceeded()

        for c in enabled:
            pid = c.get("uploads_pid")
            if not pid:
                continue
            try:
                d = yt_track._yt_get("/playlistItems",
                                     {"part": "snippet,contentDetails", "playlistId": pid,
                                      "maxResults": DISCOVER_TAKE}, key)
                report["quota_units_est"] += 1
            except yt_track._QuotaExceeded:
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
                    "title": sn.get("title") or "", "published": yt_track._iso_ts(sn.get("publishedAt")),
                    "duration_s": None, "is_short": None,
                    "tags": [], "thumb": yt_track._thumb(sn),
                    "first_seen": now, "first_seen_views": None,
                    "last_stats": None, "status": "ok", "series": []}
                have += 1
                report["new_videos"] += 1
        if circuit:
            raise yt_track._QuotaExceeded()

        refresh = [vid for vid, v in store["videos"].items()
                   if v.get("status") != "unavailable" and v.get("channel_id") in en_ids
                   and (v.get("last_stats") is None
                        or now - v["last_stats"] >= 3600)]   # 自频道一律 1h 刷新窗(量小)
        for batch in yt_track._chunks(sorted(refresh), 50):
            try:
                d = yt_track._yt_get("/videos", {"part": "snippet,statistics,contentDetails",
                                                 "id": ",".join(batch)}, key)
                report["quota_units_est"] += 1
            except yt_track._QuotaExceeded:
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
                if not it:
                    v["status"] = "unavailable"
                    continue
                sn = it.get("snippet") or {}
                st = it.get("statistics") or {}
                v["title"] = sn.get("title") or v.get("title") or ""
                v["duration_s"] = yt_track._iso8601_s((it.get("contentDetails") or {}).get("duration"))
                v["is_short"] = (v["duration_s"] or 0) <= 60 if v["duration_s"] else v.get("is_short")
                v["tags"] = (sn.get("tags") or [])[:12]
                views = yt_track._int(st.get("viewCount"))
                if v.get("first_seen_views") is None:
                    v["first_seen_views"] = views
                v["series"].append({"ts": int(now), "v": views,
                                    "l": yt_track._int(st.get("likeCount")),
                                    "c": yt_track._int(st.get("commentCount"))})
                v["last_stats"] = now
                report["snapshotted"] += 1
        yt_track.save_store(store)
    except yt_track._QuotaExceeded:
        circuit = True
        report["circuit_break"] = True
        report["msg"] = "YouTube 配额熔断(quotaExceeded), 已保留旧快照"
    print(json.dumps(report, ensure_ascii=False))
    return report, (3 if circuit else 0)
