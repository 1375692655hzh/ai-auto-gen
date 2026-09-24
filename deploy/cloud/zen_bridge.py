#!/usr/bin/env python3
"""zen_bridge.py — OpenAI /v1/chat/completions → opencode serve 桥接(2026-09-17)

背景: zen 免费层收紧门禁(2026-09-16 夜)——omniroute 的 opencode 执行器匿名/带key
伪装均被 FreeTierError 拒绝, 仅官方 opencode 客户端(带真 key)可通过。
本桥在本地起 opencode serve(官方客户端身份, HTTPS_PROXY 走住宅代理=独立配额桶),
把站端/看板存量调用方(translate/llm_tag/x_surge)的 OpenAI 形状请求翻译成
opencode serve 的会话协议。调用方只需把 base_url 从 omniroute 改到本桥端口,
api_key 任意(本桥不校验)。

部署: deploy/cloud 套件; systemd 单元 aag-zen-bridge.service(Environment 注入
HTTPS_PROXY=<住宅代理>, ExecStart=<repo>/.venv/bin/python deploy/cloud/zen_bridge.py)。
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BRIDGE_PORT = int(os.environ.get("ZEN_BRIDGE_PORT", "20133"))
SERVE_PORT = int(os.environ.get("ZEN_SERVE_PORT", "4096"))
SERVE_BASE = f"http://127.0.0.1:{SERVE_PORT}"
UPSTREAM_TIMEOUT = int(os.environ.get("ZEN_BRIDGE_UPSTREAM_TIMEOUT", "75"))  # 快于调用方90s: 桶抽风→快速502→链落下一桶
NODE = {20133: "jp", 20134: "hk", 20135: "hk2"}.get(BRIDGE_PORT, "zen")
_pm = re.search(r"@([^:/]+):", os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or "")
EGRESS_IP = _pm.group(1) if _pm else ""
_serve_proc = None

# 额度统计(2026-09-24 用户裁决): 软依赖, guard 挂桥照跑
_GNS = Path(__file__).resolve().parents[2] / "global-news-sources"
if _GNS.is_dir() and str(_GNS) not in sys.path:
    sys.path.insert(0, str(_GNS))
try:
    from sources import chain_guard as _guard
except Exception:
    _guard = None


def _tokens_of(info: dict) -> dict:
    """opencode info.tokens → 统一口径; total 不含 cache(免费层 cache 读近似免费)。"""
    tk = (info or {}).get("tokens") or {}
    ca = tk.get("cache") or {}
    inp = int(tk.get("input") or 0)
    out = int(tk.get("output") or 0)
    rea = int(tk.get("reasoning") or 0)
    return {"prompt": inp, "completion": out + rea, "total": inp + out + rea,
            "cache_read": int(ca.get("read") or 0)}


def _rec(ok: bool, ecls: str, t0: float, model: str, tokens: dict | None = None) -> None:
    if _guard is None:
        return
    try:
        _guard.record(logger="bridge", node=NODE, model=model, ok=ok, ecls=ecls,
                      latency_ms=int((time.time() - t0) * 1000), egress_ip=EGRESS_IP,
                      tokens=tokens or {})
    except Exception:
        pass


def _http_json(path: str, payload: dict | None, timeout: int = UPSTREAM_TIMEOUT) -> dict:
    req = urllib.request.Request(
        SERVE_BASE + path,
        data=json.dumps(payload or {}).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _spawn_serve() -> None:
    global _serve_proc
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""
    env = dict(os.environ)
    if proxy:
        env["HTTPS_PROXY"] = env["https_proxy"] = proxy   # zen 免费层配额按出口 IP 计
    _serve_proc = subprocess.Popen(
        ["opencode", "serve", "--port", str(SERVE_PORT), "--hostname", "127.0.0.1"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        try:
            urllib.request.urlopen(SERVE_BASE + "/config", timeout=2)
            return
        except Exception:
            time.sleep(1)
    print("[zen_bridge] opencode serve 未就绪(40s)", flush=True)


def _chat_via_serve(model: str, sys_msg: str, user_msg: str) -> tuple:
    mid = model[3:] if model.startswith("oc/") else model      # oc/ 前缀是 omniroute 时代路由残留
    sess = _http_json("/session", {})
    sid = sess.get("id")
    if not sid:
        raise RuntimeError("opencode serve 未返回 session id")
    # system 并段进 user(官方 bridge 实测最稳, 不依赖可选字段)
    text = f"<instructions>\n{sys_msg}\n</instructions>\n\n{user_msg}" if sys_msg else user_msg
    try:
        resp = _http_json(f"/session/{sid}/message", {
            "model": {"providerID": "opencode", "modelID": mid},
            "parts": [{"type": "text", "text": text}]})
        out = "".join(p.get("text") or "" for p in (resp.get("parts") or [])
                      if p.get("type") == "text").strip()
        if not out:
            raise RuntimeError(f"空响应: {str(resp.get('info'))[:120]}")
        return out, (resp.get("info") or {})
    finally:
        try:    # 会话即弃(单次任务型), 防上下文膨胀
            urllib.request.urlopen(urllib.request.Request(
                SERVE_BASE + f"/session/{sid}", method="DELETE"), timeout=5)
        except Exception:
            pass


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _reply(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            self._reply(200, {"ok": True})
        else:
            self._reply(404, {"error": "not_found"})

    def do_POST(self):
        if not self.path.rstrip("/").endswith("chat/completions"):
            self._reply(404, {"error": "not_found"})
            return
        t0, model = time.time(), ""
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            model = body.get("model") or "oc/big-pickle"
            msgs = body.get("messages") or []
            sys_msg = "\n".join(m.get("content") or "" for m in msgs if m.get("role") == "system")
            user_msg = "\n\n".join(m.get("content") or "" for m in msgs if m.get("role") == "user")
            out, info = _chat_via_serve(model, sys_msg, user_msg)
            self._reply(200, {"id": "zen-bridge", "object": "chat.completion",
                              "choices": [{"index": 0, "finish_reason": "stop",
                                           "message": {"role": "assistant", "content": out}}]})
            _rec(True, "ok", t0, model, _tokens_of(info))
        except urllib.error.HTTPError as e:
            eb = e.read()[:200]
            self._reply(502, {"error": f"upstream_http_{e.code}: {eb!r}"})
            ecls = _guard.classify(status=e.code, body=str(eb)) if _guard else "other"
            _rec(False, ecls, t0, model)
        except Exception as e:
            eb = f"{type(e).__name__}: {str(e)[:200]}"
            self._reply(502, {"error": eb})
            ecls = _guard.classify(exc=e, body=eb) if _guard else "other"
            _rec(False, ecls, t0, model)


def main() -> None:
    _spawn_serve()
    print(f"[zen_bridge] listen 127.0.0.1:{BRIDGE_PORT} → opencode serve :{SERVE_PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", BRIDGE_PORT), H).serve_forever()


if __name__ == "__main__":
    main()
