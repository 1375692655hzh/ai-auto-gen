"""比特浏览器(BitBrowser)本地 API 封装

比特浏览器客户端在本机开启 HTTP 服务(默认 http://127.0.0.1:54345),
可按窗口 ID 打开/关闭指纹浏览器窗口, 返回调试端口, Playwright 用
connect_over_cdp 接管即可 —— 指纹/代理/IP 隔离全部由比特浏览器负责。

配置见 config.yaml:
  bitbrowser:
    api: http://127.0.0.1:54345
    windows:            # 平台名 -> 比特浏览器窗口 ID(客户端"浏览器窗口"列表里复制)
      xueqiu: "xxxx..."
      zhihu:  "yyyy..."

用法(publishers/base.py 已自动接入):
  平台 config 里出现 bitbrowser.window_id 时, run() 走 connect_over_cdp。
"""

import json
import urllib.request

DEFAULT_API = "http://127.0.0.1:54345"


def _post(api: str, path: str, payload: dict, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        api.rstrip("/") + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def available(api: str = DEFAULT_API) -> bool:
    """比特浏览器客户端是否在运行(本地 API 可达)。"""
    try:
        _post(api, "/browser/list", {"page": 0, "pageSize": 1}, timeout=5)
        return True
    except Exception:
        return False


def list_windows(api: str = DEFAULT_API) -> list:
    """列出全部窗口环境 [{id, name, remark, ...}]。"""
    out, page = [], 0
    while True:
        r = _post(api, "/browser/list", {"page": page, "pageSize": 100})
        data = r.get("data") or {}
        batch = data.get("list") or []
        out.extend(batch)
        if len(out) >= int(data.get("totalNum", 0)) or not batch:
            break
        page += 1
    return out


def open_window(window_id: str, api: str = DEFAULT_API) -> dict:
    """打开窗口, 返回 {ws, http}(调试地址)。失败抛 RuntimeError。"""
    r = _post(api, "/browser/open", {"id": window_id})
    if not r.get("success"):
        raise RuntimeError(f"比特浏览器打开窗口失败: {r.get('msg') or r}")
    d = r.get("data") or {}
    if not d.get("ws") and not d.get("http"):
        raise RuntimeError(f"比特浏览器未返回调试地址(窗口可能已在别处打开): {r}")
    return d


def close_window(window_id: str, api: str = DEFAULT_API) -> None:
    """关闭窗口(不删环境; 登录态保留在窗口环境里)。失败仅忽略。"""
    try:
        _post(api, "/browser/close", {"id": window_id})
    except Exception:
        pass


def find_window_by_name(name: str, api: str = DEFAULT_API) -> str:
    """按窗口名称/备注模糊找窗口 ID, 找不到返回 ""。"""
    for w in list_windows(api):
        if name in (w.get("name") or "") or name in (w.get("remark") or ""):
            return w["id"]
    return ""
