"""板块四·前端工作台 后端(FastAPI)。

职责四件: ①托管 web/ 静态 SPA ②/wb-api/v1/* 代理数据源 ③本地产物/账本只读视图
④设置与追踪账号读写(仅写 data/workbench/ 自有文件)。
默认绑 127.0.0.1:8788; 对外须显式 --bind(与 sources serve 同一网络红线)。

启动: python cli.py workbench serve [--bind 0.0.0.0] [--port 8788] [--open]
"""

import json
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, ops, proxy, stats, views, xaccounts, x_profile_enricher, x_surge, yt_track

WEB = Path(__file__).resolve().parent.parent / "web"


def create_app() -> FastAPI:
    app = FastAPI(title="aag-workbench", version="0.1", docs_url=None, redoc_url=None)

    # ── 数据源代理(前端唯一取数口) ──────────────────────────────────────────
    @app.get("/wb-api/v1/{path:path}")
    def v1_proxy(path: str, request: Request):
        return proxy.forward(request, path)

    # ── 统计聚合(资讯页右栏 + 来源详情子页, 服务端聚合成品直供) ──────────────
    @app.get("/wb-api/stats")
    def stats_agg():
        try:
            return stats.aggregate()
        except proxy.UpstreamError as e:
            return JSONResponse({"error": str(e)}, status_code=e.code or 502)

    # ── 聚合健康(顶栏健康灯) ────────────────────────────────────────────────
    @app.get("/wb-api/health")
    def health():
        src = {"ok": False}
        t0 = time.time()
        try:
            cfg = config.load()["source"]
            url = cfg["base_url"].rstrip("/") + "/v1/health"
            headers = {"Authorization": f"Bearer {cfg['api_key']}"} if cfg.get("api_key") else {}
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                        timeout=5) as r:
                src = {"ok": True, "ms": int((time.time() - t0) * 1000),
                       **json.loads(r.read())}
        except Exception as e:
            src = {"ok": False, "error": type(e).__name__}
        return {"workbench": "ok", "source": src}

    # ── 设置(唯一写口: data/workbench/settings.json) ─────────────────────────
    @app.get("/wb-api/settings")
    def get_settings():
        return config.public_view(config.load())

    @app.put("/wb-api/settings")
    async def put_settings(request: Request):
        body = await request.json()
        return config.public_view(config.apply_patch(body))

    # ── 只读视图(三板块文件契约) ────────────────────────────────────────────
    @app.get("/wb-api/selfcheck")
    def selfcheck():
        return views.selfcheck()

    @app.get("/wb-api/flows")
    def flows():
        return {"flows": views.flows_list()}

    @app.get("/wb-api/runs")
    def runs():
        return {"runs": views.runs_list()}

    @app.get("/wb-api/artifacts")
    def artifacts():
        return views.artifacts()

    @app.get("/wb-api/artifacts/file")
    def artifact_file(path: str):
        p = views.artifact_file(path)
        if not p:
            return JSONResponse({"error": "文件不存在或越界"}, status_code=404)
        return FileResponse(str(p))

    @app.get("/wb-api/ledger")
    def ledger():
        return views.ledger_rows()

    @app.get("/wb-api/videos")
    def videos():
        return {"videos": views.videos()}

    @app.get("/wb-api/videos/{vid}/file/{name}")
    def video_file(vid: str, name: str):
        p = views.video_file(vid, name)
        if not p:
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(str(p))

    # ── X 账号池(只读): 池源条目按账号展示的档案供给 ─────────────────────────
    @app.get("/wb-api/x-accounts")
    def x_accounts():
        return xaccounts.payload()

    @app.get("/wb-api/x-profiles")
    def x_profiles():
        c = x_profile_enricher.load_cache()
        return {"profiles": c["profiles"], "enriched_at": c.get("enriched_at"),
                "count": len(c["profiles"])}

    # ── 账号管理(图文页子页): 全池只读 + 本地偏好(唯一写口 x_account_prefs.json) ──
    @app.get("/wb-api/x-accounts-manage")
    def x_accounts_manage():
        return xaccounts.manage_payload()

    @app.post("/wb-api/x-account-pref")
    async def x_account_pref(request: Request):
        body = await request.json()
        handle = str(body.get("handle") or "").strip().lstrip("@").lower()
        if not handle:
            return JSONResponse({"error": "缺少 handle"}, status_code=400)
        if handle not in xaccounts.pool_handles():
            return JSONResponse({"error": f"池内无此账号: {handle}"}, status_code=404)
        prefs = config.load_x_prefs()
        p = prefs.setdefault(handle, {})
        if "follow" in body:
            p["follow"] = bool(body["follow"])
        if "note" in body:
            p["note"] = str(body["note"])[:200]
        p["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        config.save_x_prefs(prefs)
        return {"handle": handle, "follow": p.get("follow", False),
                "note": p.get("note", "")}

    # ── 追踪账号(本板块自有数据, 真实增删; 指标采集留桩) ─────────────────────
    @app.get("/wb-api/track/accounts")
    def track_list():
        return {"accounts": config.load_accounts()}

    @app.post("/wb-api/track/accounts")
    async def track_add(request: Request):
        body = await request.json()
        rows = config.load_accounts()
        rows.append({"platform": body.get("platform", ""), "account": body.get("account", ""),
                     "note": body.get("note", ""),
                     "added_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        return {"accounts": config.save_accounts(rows)}

    @app.delete("/wb-api/track/accounts/{idx}")
    def track_del(idx: int):
        rows = config.load_accounts()
        if 0 <= idx < len(rows):
            rows.pop(idx)
        return {"accounts": config.save_accounts(rows)}

    # ── 关注来源(本板块自有数据: followed_sources.json) ─────────────────────
    @app.get("/wb-api/followed-sources")
    def followed_list():
        rows = config.load_followed()
        return {"rows": rows, "ids": [r["id"] for r in rows]}

    @app.post("/wb-api/followed-sources")
    async def followed_toggle(request: Request):
        body = await request.json()
        sid = str(body.get("id") or "")
        if not sid:
            return JSONResponse({"error": "缺少来源 id"}, status_code=400)
        rows = config.load_followed()
        if body.get("on"):
            if not any(r["id"] == sid for r in rows):
                rows.append({"id": sid, "added_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        else:
            rows = [r for r in rows if r["id"] != sid]
        config.save_followed(rows)
        return {"id": sid, "on": bool(body.get("on")),
                "ids": [r["id"] for r in rows]}

    # ── 来源启停(红线7: 触发类动作只经 subprocess 调 cli.py, 不直写板块一) ────
    @app.post("/wb-api/sources/{sid}/enabled")
    async def source_enabled(sid: str, request: Request):
        body = await request.json()
        on = bool(body.get("on"))
        import subprocess
        cli = Path(__file__).resolve().parents[2] / "cli.py"
        try:
            p = subprocess.run(
                ["py", "-3.11", str(cli), "sources", "enable", sid, "on" if on else "off", "--json"],
                capture_output=True, text=True, encoding="utf-8", timeout=30)
        except subprocess.TimeoutExpired:
            return JSONResponse({"error": "cli 调用超时"}, status_code=504)
        try:
            out = json.loads((p.stdout or "").strip().splitlines()[-1])
        except Exception:
            out = {"raw": (p.stdout or p.stderr or "").strip()[:300]}
        if p.returncode != 0 or not out.get("ok"):
            return JSONResponse({"error": out.get("error") or out.get("raw") or f"exit {p.returncode}"},
                                status_code=500)
        stats.invalidate()                  # 60s 统计缓存立即作废, 注册表状态即时生效
        return {"id": sid, "enabled": out.get("enabled")}

    # ── 图文页【推荐信息】数据面: 全 X 条目 + 互动快照五选排序 ────────────────
    @app.get("/wb-api/x-surge")
    def x_surge_view(range: str = "24h", golden: int = 0, market: str = "",
                     sector: str = "", min_followers: int = 0, finance: int = 0,
                     sort: str = "time", limit: int = 100):
        try:
            return x_surge.build_view(range_h=int(range.rstrip("h")) if range.endswith("h") else 24,
                                      golden=bool(golden), market=market, sector=sector,
                                      min_followers=min_followers, finance=bool(finance),
                                      sort=sort, limit=limit)
        except proxy.UpstreamError as e:
            return JSONResponse({"error": str(e)}, status_code=e.code or 502)

    # ── 图文页【蹭蹭流量】数据面: SoPilot 热帖 RSS(唯一来源, 读缓存零外呼) ─────
    @app.get("/wb-api/x-surge-rss")
    def x_surge_rss_view(sort: str = "prob", limit: int = 100):
        return x_surge.rss_view(sort=sort, limit=limit)

    # ── 视频页【热点追踪/追踪账号】: YouTube 账号库+快照增量榜(读缓存零外呼;
    #    外呼只在 /yt/collect spawn 的 CLI 进程, 同 x_surge 架构) ────────────────
    @app.get("/wb-api/yt/hot")
    def yt_hot(range: str = "24h", sort: str = "views", kind: str = "all",
               channel: str = "", q: str = "", limit: int = 100):
        return yt_track.build_view(range=range, sort=sort, kind=kind,
                                   channel=channel, q=q, limit=limit)

    @app.get("/wb-api/yt/status")
    def yt_status():
        return yt_track.status_payload()

    @app.get("/wb-api/yt/channels")
    def yt_channels_list():
        rows = config.load_yt_channels()
        return {"channels": rows,
                "meta": {"configured": bool(yt_track.api_key()),
                         "enabled": sum(1 for c in rows if c.get("enabled", True)),
                         "pending": sum(1 for c in rows if c.get("resolve_status") == "pending"),
                         "failed": sum(1 for c in rows if c.get("resolve_status") == "failed")}}

    @app.post("/wb-api/yt/channels")
    async def yt_channels_add(request: Request):
        body = await request.json()
        row, err = yt_track.add_channel(str(body.get("input") or ""),
                                        str(body.get("note") or ""),
                                        bool(body.get("enabled", True)))
        if err:
            dup = "已在追踪列表" in err["error"]
            return JSONResponse(err, status_code=409 if dup else 400)
        return {"added": row, "channels": config.load_yt_channels()}

    @app.post("/wb-api/yt/channels/{cid}/enabled")
    async def yt_channel_enabled(cid: str, request: Request):
        body = await request.json()
        rows = config.load_yt_channels()
        for r in rows:
            if r.get("id") == cid:
                r["enabled"] = bool(body.get("on"))
                config.save_yt_channels(rows)
                return {"id": cid, "enabled": r["enabled"]}
        return JSONResponse({"error": "频道不存在"}, status_code=404)

    @app.delete("/wb-api/yt/channels/{cid}")
    def yt_channel_del(cid: str):
        rows = [r for r in config.load_yt_channels() if r.get("id") != cid]
        return {"removed": 1, "channels": config.save_yt_channels(rows)}
        # 已采视频/快照保留为孤儿数据(防误删丢历史), 榜单按启用频道过滤自然隐去

    @app.post("/wb-api/yt/channels/import")
    async def yt_channels_import():
        """从追踪主页 tracked_accounts.json 导入 platform=YouTube 的行(只复制不删源)。"""
        imported, skipped = [], []
        rows = config.load_yt_channels()
        seen = {c.get("value") for c in rows}
        for a in config.load_accounts():
            if (a.get("platform") or "").lower() != "youtube":
                continue
            parsed = yt_track.parse_channel_input(a.get("account") or "")
            if not parsed or parsed["value"] in seen:
                skipped.append(a.get("account"))
                continue
            rows.append({"id": "y" + time.strftime("%m%d%H%M%S"),
                         "input": a.get("account"), "kind": parsed["kind"],
                         "value": parsed["value"],
                         "handle": parsed["value"] if parsed["kind"] == "handle" else "",
                         "channel_id": parsed["value"] if parsed["kind"] == "channel_id" else "",
                         "title": "", "note": a.get("note") or "", "enabled": True,
                         "resolve_status": "pending", "resolve_error": "",
                         "subs": None, "uploads_pid": "",
                         "added_at": time.strftime("%Y-%m-%d %H:%M:%S")})
            seen.add(parsed["value"])
            imported.append(a.get("account"))
        if imported:
            config.save_yt_channels(rows)
        return {"imported": imported, "skipped": [s for s in skipped if s],
                "channels": rows}

    @app.post("/wb-api/yt/collect")
    def yt_collect():
        """立即采集: 异步 spawn CLI(一轮 30–120s, 同步会卡死浏览器请求);
        进度/结果经 GET /yt/status 轮询(状态落 yt_videos.json last_collect)。"""
        import subprocess
        st = yt_track.status_payload()
        if not st["configured"]:
            return JSONResponse({"error": "未配置 YouTube Data API Key",
                                 "hint": "到 设置 → YouTube 热点追踪 填写"}, status_code=400)
        if st["running"]:
            return JSONResponse({"error": "采集进行中", "started_at": st["started_at"]},
                                status_code=409)
        cli = Path(__file__).resolve().parents[2] / "cli.py"
        try:
            subprocess.Popen(
                ["py", "-3.11", str(cli), "workbench", "refresh-yt-track", "--json"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:
            return JSONResponse({"error": f"采集进程启动失败: {e}"}, status_code=500)
        return {"started": True}


    # ── 图文页: 草稿真实 CRUD(data/workbench/drafts.json) ────────────────────
    @app.get("/wb-api/drafts")
    def drafts_list():
        rows = config.load_drafts()
        rows.sort(key=lambda r: r.get("updated_at", ""), reverse=True)
        return {"drafts": rows}

    @app.post("/wb-api/drafts")
    async def drafts_save(request: Request):
        body = await request.json()
        rows = config.load_drafts()
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        did = body.get("id")
        if did:                                       # 有 id = 更新
            for r in rows:
                if r.get("id") == did:
                    r.update({k: body[k] for k in
                              ("title", "content", "items", "modules", "template", "publish")
                              if k in body})
                    r["updated_at"] = now
                    break
            else:
                return JSONResponse({"error": f"草稿不存在: {did}"}, status_code=404)
        else:                                         # 无 id = 新建
            did = "d" + time.strftime("%m%d%H%M%S")
            rows.append({"id": did, "title": body.get("title") or "未命名草稿",
                         "content": body.get("content", ""),
                         "items": body.get("items") or [],
                         "modules": body.get("modules") or [],
                         "template": body.get("template", ""),
                         "publish": body.get("publish") or {},
                         "created_at": now, "updated_at": now})
        return {"drafts": config.save_drafts(rows), "id": did}

    @app.delete("/wb-api/drafts/{did}")
    def drafts_del(did: str):
        rows = [r for r in config.load_drafts() if r.get("id") != did]
        return {"drafts": config.save_drafts(rows)}

    # ── 图文页: 自动化任务真实 CRUD(data/workbench/automation.json, 调度留桩) ──
    @app.get("/wb-api/automation")
    def automation_list():
        return {"tasks": config.load_automation()}

    @app.post("/wb-api/automation")
    async def automation_add(request: Request):
        body = await request.json()
        rows = config.load_automation()
        rows.append({"id": "a" + time.strftime("%m%d%H%M%S"),
                     "name": body.get("name") or "未命名任务",
                     "note": body.get("note", ""),
                     "template": body.get("template", ""),
                     "modules": body.get("modules") or [],
                     "schedule": body.get("schedule") or {"kind": "daily", "time": "08:00"},
                     "publish": body.get("publish") or {"target": "draft"},
                     "enabled": bool(body.get("enabled", True)),
                     "created_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        return {"tasks": config.save_automation(rows)}

    @app.delete("/wb-api/automation/{tid}")
    def automation_del(tid: str):
        rows = [r for r in config.load_automation() if r.get("id") != tid]
        return {"tasks": config.save_automation(rows)}

    # ── 运维页: 常驻进程/开机任务/刷新轮/存储状态 + 白名单动作(subprocess) ────
    @app.get("/wb-api/ops/status")
    def ops_status():
        return ops.status_payload()

    @app.post("/wb-api/ops/action")
    async def ops_action(request: Request):
        body = await request.json()
        return ops.action(str(body.get("target") or ""), str(body.get("op") or ""))

    # ── 云端同步预留桩(本期一律 501) ─────────────────────────────────────────
    @app.post("/wb-api/cloud/{action}")
    def cloud_stub(action: str):
        return JSONResponse({"error": "云端同步将在后续版本开放",
                             "hint": "本期为纯本地版; 该接口形状已定型(见 docs/第四板块-前端工作台方案.md)"},
                            status_code=501)

    # ── 静态 SPA(放最后, 兜底所有非 /wb-api 路径到 index.html) ───────────────
    # SPA 静态资源禁启发式缓存: 迭代期旧 JS/CSS 被 webview 缓存会导致新旧混载
    @app.middleware("http")
    async def no_cache_static(request: Request, call_next):
        resp = await call_next(request)
        if not request.url.path.startswith("/wb-api"):
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
    return app


def run(host: str = "127.0.0.1", port: int = 8788, open_browser: bool = False) -> int:
    import uvicorn
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"⚠ 对外绑定 {host}——确认走内网/隧道, 禁裸开公网(与 sources serve 同一红线)")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
    print(f"工作台已启动: http://127.0.0.1:{port}/  (数据站: 请先 python cli.py sources serve)")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
    return 0
