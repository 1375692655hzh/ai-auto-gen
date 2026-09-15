"""只看看板(board)——工作台的轻量只读对外视图, 部署在数据站同机对外。

四个固定数据面(与工作台对应页面同一数据源同一算法, 只砍交互):
  资讯总览 = 资讯页·信息筛选(/v1/* 透传 + stats 赛道48h聚合)
  X推荐    = 图文页·推荐信息(x_surge.build_view, FV 六维规则分)
  X热门帖  = 图文页·蹭蹭流量(x_surge.rss_view, SoPilot 热帖 RSS)
  YTB追踪  = 视频页·热点追踪(yt_track.build_view, YouTube 快照)

安全模型:
  - 全 GET 零写端点, 唯一例外 POST /vb-api/translate(浏览层按需翻译, 同工作台
    /wb-api/translate: 免费模型链+哈希缓存, 写面仅 data/workbench/translate_ondemand.json);
  - 访问口令 = data/workbench/viewer_access.key(管理员直写文件, 空/缺省=不设防),
    /vb-api/* 要求 X-View-Key 头或 ?k= 查询参数, 静态页首次输入存 localStorage;
  - 数据站 Key 沿用 proxy 契约: 仅存服务端 settings.json, 永不下发浏览器。

启动: python cli.py viewer serve [--host 0.0.0.0] [--port 8790]
"""

import threading

from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from . import ondemand_translate, proxy, stats, x_surge, yt_track, config

WEB = Path(__file__).resolve().parents[1] / "web"
_KEY_CACHE = {"at": 0.0, "val": "", "lock": threading.Lock()}


def _access_key() -> str:
    """读访问口令(60s 缓存): data/workbench/viewer_access.key, 空/缺=公开。"""
    with _KEY_CACHE["lock"]:
        import time as _t
        now = _t.time()
        if now - _KEY_CACHE["at"] > 60:
            try:
                _KEY_CACHE["val"] = (config.DATA_DIR / "viewer_access.key") \
                    .read_text(encoding="utf-8").strip()
            except Exception:
                _KEY_CACHE["val"] = ""
            _KEY_CACHE["at"] = now
        return _KEY_CACHE["val"]


def _authorized(request: Request) -> bool:
    key = _access_key()
    if not key:
        return True
    if request.headers.get("X-View-Key", "") == key:
        return True
    if request.query_params.get("k", "") == key:
        return True
    return False


def create_app() -> FastAPI:
    app = FastAPI(title="aag-board", version="1.0", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def gate(request: Request, call_next):
        if request.url.path.startswith("/vb-api") \
                and request.url.path != "/vb-api/gate" \
                and not _authorized(request):
            return JSONResponse({"error": "view_key_required",
                                 "hint": "首次访问请输入访问口令"}, status_code=401)
        return await call_next(request)

    @app.get("/vb-api/gate")
    def vb_gate():
        return {"need": bool(_access_key())}

    # 资讯总览: 数据站 /v1/* 全透传(带 Key 注入, 同工作台 proxy 通道)
    @app.get("/vb-api/v1/{path:path}")
    def vb_v1(request: Request, path: str):
        return proxy.forward(request, path)

    @app.get("/vb-api/stats")
    def vb_stats():
        return stats.aggregate()

    # X推荐(图文页·推荐信息同款)
    @app.get("/vb-api/x-surge")
    def vb_x_surge(range: str = "24h", golden: int = 0, market: str = "",
                   sector: str = "", min_followers: int = 0, finance: int = 0,
                   sort: str = "time", limit: int = 100):
        try:
            return x_surge.build_view(
                range_h=int(range.rstrip("h")) if range.endswith("h") else 24,
                golden=bool(golden), market=market, sector=sector,
                min_followers=min_followers, finance=bool(finance),
                sort=sort, limit=limit)
        except proxy.UpstreamError as e:
            return JSONResponse({"error": str(e)}, status_code=e.code or 502)

    # X热门帖(图文页·蹭蹭流量同款, SoPilot RSS 缓存)
    @app.get("/vb-api/x-surge-rss")
    def vb_x_surge_rss(sort: str = "prob", limit: int = 100):
        return x_surge.rss_view(sort=sort, limit=limit)

    # YTB追踪(视频页·热点追踪同款)
    @app.get("/vb-api/yt/hot")
    def vb_yt_hot(range: str = "24h", sort: str = "views", kind: str = "all",
                  channel: str = "", q: str = "", limit: int = 100):
        return yt_track.build_view(range=range, sort=sort, kind=kind,
                                   channel=channel, q=q, limit=limit)

    @app.get("/vb-api/yt/status")
    def vb_yt_status():
        return yt_track.status_payload()

    @app.get("/vb-api/yt/channels")
    def vb_yt_channels():
        rows = [{"channel_id": r.get("channel_id"), "title": r.get("title"),
                 "enabled": r.get("enabled", True)}
                for r in config.load_yt_channels()]
        return {"channels": rows,
                "meta": {"configured": bool(yt_track.api_key()),
                         "enabled": sum(1 for r in rows if r["enabled"])}}

    # 浏览层按需翻译(同工作台 /wb-api/translate: 视口内缺译文卡片批量翻,
    # 免费链+服务端哈希缓存; 同事场景唯一读英文出口, 翻译在看板侧接住)
    @app.post("/vb-api/translate")
    def vb_translate(body: dict = Body(default=None)):
        try:
            return ondemand_translate.translate_batch((body or {}).get("items") or [])
        except Exception as e:
            return JSONResponse({"error": f"translate_failed: {e}"}, status_code=500)

    @app.get("/")
    def index():
        return FileResponse(str(WEB / "viewer.html"))

    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
    return app


def run(host: str = "127.0.0.1", port: int = 8790) -> int:
    import uvicorn
    if _access_key():
        print("🔒 访问口令已启用(data/workbench/viewer_access.key)")
    else:
        print("⚠ 未设访问口令 —— 公开可看; 要上锁: 写 data/workbench/viewer_access.key")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
    return 0
