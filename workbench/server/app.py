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

from . import config, proxy, reco, stats, views, xaccounts, x_profile_enricher

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

    # ── 图文页: 推荐信息打分(服务端, 规则透明) ───────────────────────────────
    @app.get("/wb-api/recommend")
    def recommend(since: str = "", markets: str = "", kinds: str = "",
                  channels: str = "", positionings: str = "",
                  item_types: str = "", limit: int = 50):
        try:
            return reco.recommend(since=since, markets=markets, kinds=kinds,
                                  channels=channels, positionings=positionings,
                                  item_types=item_types, limit=limit)
        except proxy.UpstreamError as e:
            return JSONResponse({"error": str(e)}, status_code=e.code or 502)

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
