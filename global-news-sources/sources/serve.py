"""只读 HTTP 供数服务(单机数据站读侧, 拍板 2026-09-01)。

- 全 GET、零写端点、零触发抓取端点——刷新只由任务计划/管理员发起
- 默认绑 127.0.0.1; 对外须显式 --bind 0.0.0.0(跨网走 Tailscale/隧道, 不裸开公网)
- 鉴权: Bearer Key(config/api_keys.local.json, gitignored); localhost 可免密
- 配额: 每键 RPM/日条数; 快照接口单独按次限流; 超限 429 + Retry-After
- 访问日志: data/serve/access.log(键名前缀/路由/条数/耗时, 不记正文不记全 key)

启动: python cli.py sources serve [--bind 0.0.0.0] [--port 8787]
"""

import json
import os
import re
import time
from pathlib import Path

from sources import list_sources, IMPORT_ERRORS
from sources import health as _health
from sources import store as _store


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
                forms: str = "", kinds: str = ""):
        csv = lambda v: [s.strip() for s in v.split(",") if s.strip()] or None
        out = list_sources(markets=csv(markets), channels=csv(channels),
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
              sources: str = "", tickers: str = "", sentiments: str = "",
              event_types: str = "", q: str = "",
              since: str = "", limit: int = 200, cursor: str = "",
              dedup: int = 1):
        csv = lambda v: [s.strip() for s in v.split(",") if s.strip()] or None
        out, nxt = _store.query(markets=csv(markets), kinds=csv(kinds),
                                info_types=csv(info_types), channels=csv(channels),
                                forms=csv(forms), source_ids=csv(sources),
                                tickers=csv(tickers), sentiments=csv(sentiments),
                                event_types=csv(event_types),
                                q=q, since=since, limit=limit, cursor=cursor,
                                dedup=bool(dedup))
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

    return app


def run(host: str = "127.0.0.1", port: int = 8787) -> int:
    import uvicorn
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"⚠ 对外绑定 {host}——确认走内网/隧道, 且已配置 api_keys.local.json")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
    return 0
