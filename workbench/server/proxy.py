"""数据源代理: /wb-api/v1/* → 设置里的数据源(sources serve)。

前端永不直连 8787: Key 只存在服务端 settings.json, 由本模块注入 Authorization;
切局域网/云端 = 设置页改 base_url, 前端零改动。
只转发 GET(供数契约本身就是全 GET 零写); 错误统一翻译成 {error, hint}。
"""

import urllib.error
import urllib.parse
import urllib.request

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from . import config

# 允许透传的响应头(快照下载需要 Content-Disposition)
_PASS_HEADERS = ("content-type", "content-disposition", "retry-after")


def forward(request: Request, path: str) -> Response:
    cfg = config.load()["source"]
    base = (cfg.get("base_url") or "").rstrip("/")
    if not base:
        return JSONResponse({"error": "未配置数据源地址",
                             "hint": "到 设置 → 信息源连接 填写数据站地址"}, status_code=400)
    if cfg.get("mode") == "cloud" and (config.load()["cloud"].get("endpoint")):
        base = config.load()["cloud"]["endpoint"].rstrip("/")   # 云端演进缝: mode=cloud 换端点
    url = f"{base}/v1/{path}"
    if request.url.query:
        url += "?" + request.url.query

    headers = {}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=float(cfg.get("timeout_s") or 15)) as r:
            body = r.read()
            hs = {k: v for k, v in r.headers.items() if k.lower() in _PASS_HEADERS}
            return Response(content=body, status_code=r.status,
                            media_type=hs.pop("content-type", "application/json"), headers=hs)
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            import json
            payload = json.loads(body)
        except Exception:
            payload = {"error": body.decode("utf-8", "replace")[:300]}
        if e.code == 401:
            payload.setdefault("hint", "数据源要求鉴权: 到 设置 → 信息源连接 填 API Key")
        if e.code == 429:
            payload.setdefault("hint", "数据源限流, 请按 Retry-After 稍后再试")
        return JSONResponse(payload, status_code=e.code,
                            headers={"Retry-After": e.headers["Retry-After"]}
                            if e.headers.get("Retry-After") else None)
    except Exception as e:
        return JSONResponse({"error": f"数据源不可达: {type(e).__name__}",
                             "hint": f"确认数据站已启动({base}); 本机场景请先运行 "
                                     f"python cli.py sources serve"}, status_code=502)


class UpstreamError(Exception):
    """数据源调用失败(stats 等服务端聚合用): .code 0=不可达, 否则为 HTTP 状态码。"""

    def __init__(self, msg: str, code: int = 0):
        super().__init__(msg)
        self.code = code


def fetch_json(path_qs: str):
    """服务端内部调 /v1/{path_qs} 并返回解析后的 JSON(带 Key 注入, 与 forward 同通道)。"""
    import json

    cfg = config.load()["source"]
    base = (cfg.get("base_url") or "").rstrip("/")
    if not base:
        raise UpstreamError("未配置数据源地址: 到 设置 → 信息源连接 填写数据站地址")
    if cfg.get("mode") == "cloud" and (config.load()["cloud"].get("endpoint")):
        base = config.load()["cloud"]["endpoint"].rstrip("/")
    headers = {}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    req = urllib.request.Request(f"{base}/v1/{path_qs}", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=float(cfg.get("timeout_s") or 15)) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        hint = "数据源要求鉴权: 到 设置 → 信息源连接 填 API Key" if e.code == 401 else ""
        raise UpstreamError(f"HTTP {e.code}: {hint or e.reason}", code=e.code)
    except Exception as e:
        raise UpstreamError(f"数据源不可达({base}): {type(e).__name__} "
                            f"——确认数据站已启动: python cli.py sources serve")
