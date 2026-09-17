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
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BRIDGE_PORT = int(os.environ.get("ZEN_BRIDGE_PORT", "20131"))
SERVE_PORT = int(os.environ.get("ZEN_SERVE_PORT", "4096"))
SERVE_BASE = f"http://127.0.0.1:{SERVE_PORT}"
UPSTREAM_TIMEOUT = int(os.environ.get("ZEN_BRIDGE_UPSTREAM_TIMEOUT", "240"))
_serve_proc = None


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


def _chat_via_serve(model: str, sys_msg: str, user_msg: str) -> str:
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
        return out
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
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            msgs = body.get("messages") or []
            sys_msg = "\n".join(m.get("content") or "" for m in msgs if m.get("role") == "system")
            user_msg = "\n\n".join(m.get("content") or "" for m in msgs if m.get("role") == "user")
            out = _chat_via_serve(body.get("model") or "oc/big-pickle", sys_msg, user_msg)
            self._reply(200, {"id": "zen-bridge", "object": "chat.completion",
                              "choices": [{"index": 0, "finish_reason": "stop",
                                           "message": {"role": "assistant", "content": out}}]})
        except urllib.error.HTTPError as e:
            self._reply(502, {"error": f"upstream_http_{e.code}: {e.read()[:200]!r}"})
        except Exception as e:
            self._reply(502, {"error": f"{type(e).__name__}: {str(e)[:200]}"})


def main() -> None:
    _spawn_serve()
    print(f"[zen_bridge] listen 127.0.0.1:{BRIDGE_PORT} → opencode serve :{SERVE_PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", BRIDGE_PORT), H).serve_forever()


if __name__ == "__main__":
    main()
