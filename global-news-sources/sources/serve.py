"""只读为主 HTTP 供数服务(单机数据站读侧, 拍板 2026-09-01)。

- 全 GET 读端点 + 唯一写端点 POST /v1/sources/{sid}/enabled(源启停——管理员远程运维
  通道, 权限 = key 定义含 "admin": true 或本机(loopback); 工作台(客户级)不走此端点,
  其「来源详情」开关是本机视图过滤, 2026-09-18 用户裁决)——刷新仍只由任务计划/管理员发起
- 默认绑 127.0.0.1; 对外须显式 --bind 0.0.0.0(跨网走 Tailscale/隧道, 不裸开公网)
- 鉴权: Bearer Key(config/api_keys.local.json, gitignored); localhost 可免密
- 配额: 每键 RPM/日条数; 快照接口单独按次限流; 超限 429 + Retry-After
- 访问日志: data/serve/access.log(键名前缀/路由/条数/耗时, 不记正文不记全 key)

启动: python cli.py sources serve [--bind 0.0.0.0] [--port 8787]
"""

import datetime as _dt
import json
import os
import re
import time
from pathlib import Path

from sources import list_sources, IMPORT_ERRORS
from sources import health as _health
from sources import store as _store


# ── 档位/窗口辅助(/v1/alloc 全量清单用, 模块级供单测) ────────────────────────

def _norm_hours(schedule: list) -> list:
    """锚点小时归一: 0 归 24(午夜锚点, 同推送 _anchor_hour 语义), 升序去重。"""
    return sorted({24 if int(h) == 0 else int(h) for h in schedule})


def _anchor_dt(d, h: int):
    """锚点时刻: h=24 → 次日零点。"""
    return _dt.datetime(d.year, d.month, d.day) + _dt.timedelta(hours=h)


def _latest_anchor(hours: list, now):
    """最近一个已到来的锚点 → (date, hour); 无 schedule/全天未到 → None。"""
    best = None                                  # (锚点时刻, date, hour)
    for back in (0, 1):
        d = (now - _dt.timedelta(days=back)).date()
        for h in sorted(hours, reverse=True):
            dt = _anchor_dt(d, h)
            if dt <= now and (best is None or dt > best[0]):
                best = (dt, d, h)
    return (best[1], best[2]) if best else None


def _parse_slot(slot: str):
    """'YYYY-M-D-H'(小时可补零; 0 归 24) → (date, hour); 非法值抛 ValueError。"""
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})-(\d{1,2})$", slot.strip())
    if not m:
        raise ValueError("档位格式应为 YYYY-MM-DD-H, 如 2026-10-14-8")
    y, mo, dy, h = (int(x) for x in m.groups())
    if h == 0:
        h = 24                                    # 锚点语义: 午夜归 24(同推送侧)
    return _dt.date(y, mo, dy), h


def _slot_window(d, h: int, hours: list):
    """档位窗口 = [上一锚点, 本锚点)。当天最早档 ← 昨日最末锚点(覆盖 overnight)。"""
    until = _anchor_dt(d, h)
    prevs = [a for a in hours if a < h]
    if prevs:
        pd, ph = d, max(prevs)
    else:
        pd, ph = d - _dt.timedelta(days=1), hours[-1]
    return _anchor_dt(pd, ph), until


# ── 鉴权与配额 ──────────────────────────────────────────────────────────────

def _keys_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config" / "api_keys.local.json"


def _load_keys() -> dict:
    try:
        d = json.loads(_keys_path().read_text(encoding="utf-8"))
        return {k["key"]: k for k in d.get("keys", []) if k.get("enabled", True)}
    except Exception:
        return {}


_rpm_bucket: dict[str, list] = {}         # key -> [epoch, ...] 进程内滑动窗
_daily_count: dict[str, list] = {}        # key -> [date_str, count]


def _check_quota(kdef: dict, cost_items: int = 0, snap: bool = False) -> str:
    """返回 ""=放行, 否则为 429 原因。"""
    key = kdef["key"]
    now = time.time()
    rpm = int(kdef.get("rpm", 60))
    win = [t for t in _rpm_bucket.get(key, []) if now - t < 60]
    if len(win) >= rpm:
        return f"rate limit: {rpm}/min"
    win.append(now)
    _rpm_bucket[key] = win
    if cost_items:
        today = time.strftime("%Y-%m-%d")
        dc = _daily_count.get(key) or [today, 0]
        if dc[0] != today:
            dc = [today, 0]
        limit = int(kdef.get("daily_snapshot", 10)) if snap else int(kdef.get("daily_items", 200000))
        dc[1] += (1 if snap else cost_items)
        _daily_count[key] = dc
        if dc[1] > limit:
            return f"daily quota exceeded ({'snapshot' if snap else 'items'})"
    return ""


def _auth_scope(request, kdef: dict | None) -> tuple[dict | None, object | None]:
    """返回 (key定义, None) 或 (None, 401响应)。localhost 且未配置任何 key 时免密。"""
    from fastapi.responses import JSONResponse
    host = request.client.host if request.client else ""
    keys = _load_keys()
    if not keys and host in ("127.0.0.1", "::1"):
        return {"key": "local-anonymous", "name": "localhost", "rpm": 600,
                "daily_items": 10**9, "daily_snapshot": 10**6}, None
    auth = request.headers.get("Authorization", "")
    m = re.match(r"Bearer\s+(\S+)", auth)
    token = m.group(1) if m else request.headers.get("X-API-Key", "")
    kdef = keys.get(token)
    if not kdef:
        return None, JSONResponse({"error": "unauthorized"}, status_code=401)
    return kdef, None


def _access_log(kdef: dict, path: str, n: int, ms: int, status: int = 200) -> None:
    try:
        line = json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                           "key": (kdef.get("name") or kdef.get("key", "")[:8]),
                           "path": path, "items": n, "ms": ms, "status": status},
                          ensure_ascii=False)
        p = _store._serve_dir() / "access.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── 路由 ────────────────────────────────────────────────────────────────────

def create_app():
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, FileResponse
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="aag-sources", version="1.0", docs_url=None, redoc_url=None)
    # 同事的工作台若是浏览器页面直连, 需要 CORS 放行(只读 API + Key 鉴权, 内网场景)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"],
                       allow_headers=["Authorization", "X-API-Key"])

    @app.middleware("http")
    async def guard(request: Request, call_next):
        t0 = time.time()
        kdef, deny = _auth_scope(request, None)
        if deny is not None:
            _access_log({"name": "anon-denied"}, request.url.path, 0,
                        int((time.time() - t0) * 1000), 401)
            return deny
        request.state.kdef = kdef
        resp = await call_next(request)
        _access_log(kdef, request.url.path, getattr(request.state, "n_items", 0),
                    int((time.time() - t0) * 1000), resp.status_code)
        return resp

    @app.get("/v1/health")
    def health(request: Request):
        snap = {}
        try:
            snap = json.loads((_store._serve_dir().parent / "dist" / "manifest.json")
                              .read_text(encoding="utf-8"))
        except Exception:
            pass
        return {"status": "ok", "store": _store.stats(), "snapshot": snap,
                "registry_import_errors": IMPORT_ERRORS}

    @app.get("/v1/sources")
    def sources(request: Request, markets: str = "", channels: str = "",
                positionings: str = "", forms: str = "", kinds: str = ""):
        csv = lambda v: [s.strip() for s in v.split(",") if s.strip()] or None
        out = list_sources(markets=csv(markets), channels=csv(channels),
                           positionings=csv(positionings),
                           forms=csv(forms), kinds=csv(kinds))
        request.state.n_items = len(out)
        return {"total": len(out), "sources": out}

    @app.get("/v1/sources/{sid}")
    def source_detail(sid: str, request: Request):
        for m in list_sources():
            if m["id"] == sid:
                m["health_detail"] = _health.get(sid)
                return m
        return JSONResponse({"error": f"unknown source: {sid}"}, status_code=404)

    @app.get("/v1/items")
    def items(request: Request, markets: str = "", kinds: str = "",
              info_types: str = "", channels: str = "", forms: str = "",
              item_types: str = "", positionings: str = "",
              sources: str = "", tickers: str = "", sentiments: str = "",
              event_types: str = "", sectors: str = "", q: str = "",
              since: str = "", limit: int = 200, cursor: str = "",
              dedup: int = 1, display: int = 1):
        csv = lambda v: [s.strip() for s in v.split(",") if s.strip()] or None
        out, nxt = _store.query(markets=csv(markets), kinds=csv(kinds),
                                info_types=csv(info_types), channels=csv(channels),
                                item_types=csv(item_types),
                                positionings=csv(positionings),
                                forms=csv(forms), source_ids=csv(sources),
                                tickers=csv(tickers), sentiments=csv(sentiments),
                                event_types=csv(event_types), sectors=csv(sectors),
                                q=q, since=since, limit=limit, cursor=cursor,
                                dedup=bool(dedup))
        if display:                               # 中文用户默认: text/title 换成译文
            for d in out:
                if d.get("text_display") and d["text_display"] != d.get("text"):
                    d["text_src"], d["text"] = d["text"], d["text_display"]
                if d.get("title_display") and d["title_display"] != d.get("title"):
                    d["title_src"], d["title"] = d["title"], d["title_display"]
        why = _check_quota(request.state.kdef, cost_items=len(out))
        if why:
            return JSONResponse({"error": why}, status_code=429,
                                headers={"Retry-After": "60"})
        request.state.n_items = len(out)
        return {"total": len(out), "next_cursor": nxt, "items": out}

    @app.get("/v1/snapshot/latest")
    def snapshot(request: Request):
        why = _check_quota(request.state.kdef, cost_items=1, snap=True)
        if why:
            return JSONResponse({"error": why}, status_code=429,
                                headers={"Retry-After": "3600"})
        f = _store._serve_dir().parent / "dist" / "latest.json.gz"
        if not f.exists():
            return JSONResponse({"error": "快照未生成(先跑 sources refresh)"}, status_code=404)
        return FileResponse(str(f), media_type="application/gzip",
                            filename="latest.json.gz")

    @app.get("/v1/status")
    def status(request: Request):
        try:
            ledger = json.loads((_store._serve_dir() / "refresh.json")
                                .read_text(encoding="utf-8"))
        except Exception:
            ledger = {}
        return {"refresh": ledger, "store": _store.stats(),
                "health_dead": [k for k, v in _health.report().items()
                                if v.get("status") == "dead"]}

    # ── 唯一写端点: 源启停(2026-09-11)。数据站是源配置的所有者, 工作台本地/局域网/
    #    云端三接入形态统一经此启停(旧工作台 spawn 本机 cli 只对"数据站在本机"成立)。
    #    权限: key 定义含 "admin": true, 或本机(loopback)调用; 普通分发 key 403。──
    # ── 账号选题全量清单(2026-10-14 用户裁决: alloc 不做限量分配, 直接回全量命中,
    #    与飞书表格子页同口径)。档=推送锚点; 档位键 "YYYY-M-D-H" 小时不补零(与推送侧
    #    f"{date}-{hour}" 一致), 午夜锚点=24; 查询侧兼容补零输入, 未知档位显式 404
    #    不静默回落(修 1014 "查 08 档静默回最新档"坑, 与 28b849c 同族)。
    #    档位/窗口辅助函数在模块级(_norm_hours/_parse_slot/_slot_window/...)供单测。──

    @app.get("/v1/alloc")
    def alloc_index(request: Request):
        """全量清单索引: 账号列表 + 各自最新档位(档=推送锚点, 详情与飞书表格同口径)。"""
        from . import feishu
        ap = feishu._push_conf(feishu._conf())
        hours = _norm_hours(ap["schedule"])
        latest = ""
        la = _latest_anchor(hours, _dt.datetime.now()) if hours else None
        if la:
            latest = f"{la[0]:%Y-%m-%d}-{la[1]}"
        accs = {str(a.get("name") or "?"):
                {"latest_slot": latest, "owner": str(a.get("owner") or "?")}
                for a in ap["accounts"]}
        why = _check_quota(request.state.kdef, cost_items=len(accs))
        if why:
            return JSONResponse({"error": why}, status_code=429,
                                headers={"Retry-After": "60"})
        request.state.n_items = len(accs)
        return {"accounts": accs, "schedule": hours,
                "note": "详情: GET /v1/alloc/{账号名}?slot={档位,缺省最新;"
                        " 返回该账号窗口内全量命中清单(与飞书表格同口径, 无限量分配)}"}

    @app.get("/v1/alloc/{account}")
    def alloc_account(request: Request, account: str, slot: str = ""):
        """账号 × 档位的全量命中清单: 窗口内该账号主题命中的全部 X 帖(与飞书表格
        子页同口径, 2026-10-14 起不做限量分配)。查询=推送同款(fetched_at 窗口 +
        '%twitter%' 源 + LIMIT 400 + URL 去重 + 剥 @作者: 前缀); 排序=主题(mix 降序)
        →观点在前→时间降序; 一帖一行(表格中多主题帖会在多个主题段重复, 此处不重复,
        themes 列出全部命中主题)。"""
        from . import feishu
        ap = feishu._push_conf(feishu._conf())
        acc = next((a for a in ap["accounts"]
                    if str(a.get("name") or "") == account), None)
        if acc is None:
            return JSONResponse(
                {"error": f"unknown account '{account}'",
                 "accounts": [str(a.get("name")) for a in ap["accounts"]]},
                status_code=404)
        hours = _norm_hours(ap["schedule"])
        if not hours:
            return JSONResponse(
                {"error": "account_push.schedule 未配置, 无法定位档位窗口"},
                status_code=400)
        now = _dt.datetime.now()
        if slot:
            try:
                d, h = _parse_slot(slot)
            except ValueError as ex:
                return JSONResponse({"error": str(ex)}, status_code=400)
        else:
            la = _latest_anchor(hours, now)
            if la is None:
                return JSONResponse({"error": "今日锚点尚未到来"}, status_code=404)
            d, h = la
        if h not in hours:
            return JSONResponse(
                {"error": f"档位 {h} 不在 schedule 中",
                 "schedule": hours,
                 "valid_slots_of_day": [f"{d:%Y-%m-%d}-{a}" for a in hours]},
                status_code=404)
        since, until = _slot_window(d, h, hours)
        if until > now:
            return JSONResponse({"error": f"档位 {d:%Y-%m-%d}-{h} 尚未到来"
                                          f"(锚点时刻 {until:%Y-%m-%d %H:%M})"},
                                status_code=404)
        mix = {str(k): float(v) for k, v in (acc.get("mix") or {}).items()
               if str(k) in feishu.TOPICS and float(v) > 0}
        if not mix:
            return JSONResponse({"error": f"账号 '{account}' mix 无效"}, status_code=400)
        rows = []
        conn = _store._connect()
        try:
            rows = conn.execute(
                "SELECT time, text, text_zh, url, author_handle, sectors, markets, "
                "item_type, author_role, tickers, event_type, dup_count, positioning "
                "FROM items WHERE fetched_at>=? AND fetched_at<? "
                "AND source_id LIKE '%twitter%' ORDER BY time DESC LIMIT 400",
                (since.strftime("%Y-%m-%d %H:%M:%S"),
                 until.strftime("%Y-%m-%d %H:%M:%S"))).fetchall()
        finally:
            conn.close()
        seen, items = set(), []
        for r in rows:
            u = str(r[3] or "")
            if u:
                if u in seen:                        # flash/views 双源同帖去重(同推送)
                    continue
                seen.add(u)
            items.append({"text": re.sub(r"^@\w+:\s*", "", str(r[1] or "")),
                          "text_zh": r[2], "url": u, "time": r[0],
                          "author_handle": r[4], "sectors": r[5], "markets": r[6],
                          "item_type": r[7], "author_role": r[8], "tickers": r[9],
                          "event_type": r[10], "dup_count": r[11],
                          "positioning": r[12]})
        try:
            a_topics = feishu._author_topics()
        except Exception:
            a_topics = {}
        theme_order = sorted(mix, key=lambda t: -mix[t])
        buckets: dict[str, list] = {t: [] for t in theme_order}
        for it in items:
            tp = feishu._item_topics(it["sectors"], it["markets"],
                                     it["author_handle"], a_topics, it["text"])
            hit = [t for t in theme_order if t in tp]
            if not hit:
                continue
            it["_themes"] = sorted(hit)
            buckets[hit[0]].append(it)               # 归属 mix 最高的命中主题
        out = []
        for t in theme_order:
            its = sorted(buckets[t], key=lambda x: str(x.get("time") or ""),
                         reverse=True)
            its = sorted(its, key=lambda x: 0 if feishu._is_opinion(x) else 1)
            for it in its:
                out.append({"theme": t, "themes": it["_themes"],
                            "type": "观点" if feishu._is_opinion(it) else "资讯",
                            "fv": feishu._fv_item_score(it, now),
                            "url": it["url"], "time": it["time"],
                            "author": it["author_handle"],
                            "text": it["text"], "text_zh": it["text_zh"],
                            "sectors": it["sectors"], "markets": it["markets"],
                            "tickers": it["tickers"],
                            "event_type": it["event_type"],
                            "item_type": it["item_type"],
                            "positioning": it["positioning"],
                            "dup_count": it["dup_count"]})
        why = _check_quota(request.state.kdef, cost_items=len(out))
        if why:
            return JSONResponse({"error": why}, status_code=429,
                                headers={"Retry-After": "60"})
        request.state.n_items = len(out)
        return {"account": account, "owner": str(acc.get("owner") or "?"),
                "mix": mix, "slot": f"{d:%Y-%m-%d}-{h}",
                "window": {"since": since.strftime("%Y-%m-%d %H:%M"),
                           "until": until.strftime("%Y-%m-%d %H:%M")},
                "total": len(out),
                "themes": [{"theme": t, "count": len(buckets[t])}
                           for t in theme_order if buckets[t]],
                "items": out,
                "note": "全量命中清单, 与飞书表格同口径(一帖一行; 表格中多主题帖"
                        "会在多个主题段重复, 此处归入 mix 最高主题, themes 列全量)"}

    @app.post("/v1/sources/{sid}/enabled")
    async def source_enabled(sid: str, request: Request):
        from sources import ctl
        kdef = request.state.kdef
        host = request.client.host if request.client else ""
        if not (kdef.get("admin") or host in ("127.0.0.1", "::1")):
            return JSONResponse({"error": "forbidden: 源启停需 admin key 或在数据站本机操作",
                                 "hint": "数据站 config/api_keys.local.json 的 key 定义加 \"admin\": true"},
                                status_code=403)
        try:
            body = await request.json()
        except Exception:
            body = {}
        on = body.get("on")                 # 缺省 = 翻转(对齐 cli sources enable)
        try:
            return ctl.set_enabled(sid, on)
        except KeyError:
            return JSONResponse({"error": f"unknown source: {sid}"}, status_code=404)

    return app


def run(host: str = "127.0.0.1", port: int = 8787) -> int:
    import uvicorn
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"⚠ 对外绑定 {host}——确认走内网/隧道, 且已配置 api_keys.local.json")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
    return 0
