"""数据站侧运维管理前端，与数据站同机、随站部署。

控制台负责展示常驻进程、任务计划、最近刷新轮和存储状态，并通过白名单动作
拉起或停止数据站任务。工作台是用户端，只通过数据站地址与 Key 接入。

启动: python cli.py sources console [--bind 0.0.0.0] [--port 8786]
"""

import json
import re
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

# 常驻进程清单: key → (显示名, 端口, 说明)
PROCS = {
    "serve":   ("数据站 sources serve", 8787, "板块一读侧供数( Bearer 鉴权 )"),
    "console": ("本控制台", 8786, "能打开本页=在跑"),
}

# 开机/计划任务清单
TASKS = ["aag-sources-refresh", "aag-xsurge-refresh", "aag-serve", "aag-console"]

LOG_FILES = ["refresh_task.log", "xsurge_task.log", "serve_task.log",
             "console_task.log", r"serve\access.log"]


def _run(cmd: list, timeout: int = 15) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
        out = (p.stdout or b"").decode("mbcs", errors="ignore") + \
              (p.stderr or b"").decode("mbcs", errors="ignore")
        return p.returncode, out.strip()
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"


def _port_pid(port: int) -> int:
    """netstat -ano 找 LISTENING 占用 PID(0=未监听)。"""
    rc, out = _run(["netstat", "-ano"], timeout=10)
    for line in out.splitlines():
        if f":{port}" in line and "LISTENING" in line.upper():
            parts = line.split()
            if parts and parts[-1].isdigit():
                return int(parts[-1])
    return 0


def _proc_status() -> list:
    rows = []
    for key, (name, port, note) in PROCS.items():
        if key == "console":
            rows.append({"key": key, "name": name, "port": port, "note": note,
                         "up": True, "pid": None})
            continue
        pid = _port_pid(port)
        rows.append({"key": key, "name": name, "port": port, "note": note,
                     "up": pid > 0, "pid": pid})
    return rows


def _task_status() -> list:
    rows = []
    for name in TASKS:
        rc, out = _run(["schtasks", "/query", "/tn", name, "/fo", "csv", "/nh"])
        if rc != 0 or '"' not in out:
            rows.append({"name": name, "registered": False})
            continue
        parts = [c.strip().strip('"') for c in out.splitlines()[0].split('","')]
        row = {"name": name, "registered": True,
               "next_run": parts[1] if len(parts) > 1 else "",
               "state": parts[2] if len(parts) > 2 else ""}
        rc2, xml = _run(["schtasks", "/query", "/tn", name, "/xml"])
        m = re.search(r"<Interval>PT(\d+)M</Interval>", xml or "")
        if m:
            row["interval_min"] = int(m.group(1))
        rows.append(row)
    return rows


def _last_round() -> dict:
    out = {"sources": None, "xsurge": None}
    try:
        d = json.loads((DATA / "serve" / "refresh.json").read_text(encoding="utf-8"))
        srcs = d.get("sources") or {}
        ok = sum(1 for s in srcs.values() if s.get("status") == "ok")
        fail = sum(1 for s in srcs.values() if s.get("status") not in ("ok", "empty"))
        out["sources"] = {"started": d.get("round_started_at"),
                          "finished": d.get("round_finished_at"),
                          "ok": ok, "fail": fail, "new": sum(int(s.get("new") or 0)
                                                             for s in srcs.values()
                                                             if isinstance(s, dict))}
    except Exception:
        pass
    try:                                                    # xsurge 日志末行是 JSON
        lines = (DATA / "xsurge_task.log").read_text(encoding="utf-8",
                                                     errors="ignore").strip().splitlines()
        for ln in reversed(lines[-20:]):
            ln = ln.strip()
            if ln.startswith("{"):
                j = json.loads(ln)
                out["xsurge"] = {k: j.get(k) for k in
                                 ("ok", "failed", "todo", "tracked",
                                  "translated", "translate_failed") if k in j}
                break
    except Exception:
        pass
    return out


def _storage() -> dict:
    files = []
    for rel in LOG_FILES:
        p = DATA / rel
        files.append({"name": rel.replace("\\", "/"),
                      "mb": round(p.stat().st_size / 1048576, 2) if p.exists() else None})
    db = DATA / "serve" / "items.db"
    du = shutil.disk_usage(DATA.anchor)
    return {"items_db_mb": round(db.stat().st_size / 1048576, 1) if db.exists() else None,
            "logs": files, "disk_free_gb": round(du.free / 1073741824, 1)}


def status_payload() -> dict:
    return {"procs": _proc_status(), "tasks": _task_status(),
            "last_round": _last_round(), "storage": _storage(),
            "at": time.strftime("%Y-%m-%d %H:%M:%S")}


# ── 动作(白名单) ─────────────────────────────────────────────────────────────

def _spawn(cli_args: list, log: str) -> tuple[bool, str]:
    """后台拉起 cli.py 子命令(脱离本进程, 关窗口, 日志落 data\\<log>)。"""
    DATA.mkdir(exist_ok=True)
    f = open(DATA / log, "a", encoding="utf-8")
    f.write(f"\n===== {time.strftime('%F %T')} console 拉起: {' '.join(cli_args)} =====\n")
    f.flush()
    subprocess.Popen(["py", "-3.11", str(ROOT / "cli.py")] + cli_args,
                     cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return True, f"已后台启动(cli.py {' '.join(cli_args)})"


def action(target: str, op: str) -> dict:
    try:
        return _action_inner(target, op)
    except Exception as e:
        return {"ok": False, "output": f"{type(e).__name__}: {e}"}


def _action_inner(target: str, op: str) -> dict:
    if target == "serve":
        if op == "start":
            if _port_pid(8787):
                return {"ok": True, "output": "8787 已在监听, 无需启动"}
            return dict(zip(("ok", "output"), _spawn(["sources", "serve"], "serve_task.log")))
        if op == "stop":
            pid = _port_pid(8787)
            if not pid:
                return {"ok": True, "output": "8787 本就没在跑"}
            rc, out = _run(["taskkill", "/F", "/PID", str(pid)])
            return {"ok": rc == 0, "output": out or f"taskkill pid={pid} rc={rc}"}
    elif target == "refresh":
        if op == "start":                                # 立即刷一轮(幂等, 与任务计划并存)
            return dict(zip(("ok", "output"),
                            _spawn(["sources", "refresh"], "refresh_task.log")))
    elif target == "xsurge":
        if op == "start":
            return dict(zip(("ok", "output"),
                            _spawn(["workbench", "refresh-x-surge"], "xsurge_task.log")))
    return {"ok": False, "output": f"不支持的动作: {target}/{op}"}


# ── HTTP 路由 ────────────────────────────────────────────────────────────────

def create_app(host: str = "127.0.0.1"):
    from fastapi import FastAPI, Request
    from fastapi.responses import FileResponse, JSONResponse
    from sources.serve import _load_keys

    app = FastAPI(title="aag-sources-console", version="1.0",
                  docs_url=None, redoc_url=None)
    need_auth = host not in ("127.0.0.1", "localhost", "::1")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if need_auth and request.url.path.startswith("/admin/api"):
            auth = request.headers.get("Authorization", "")
            m = re.match(r"Bearer\s+(\S+)", auth)
            if not m or m.group(1) not in _load_keys():
                return JSONResponse({"error": "需要有效的 API Key"}, status_code=401)
        return await call_next(request)

    @app.get("/admin/api/status")
    def admin_status():
        return status_payload()

    @app.post("/admin/api/action")
    async def admin_action(request: Request):
        body = await request.json()
        return action(str(body.get("target") or ""), str(body.get("op") or ""))

    @app.get("/")
    def index():
        page = Path(__file__).resolve().parents[1] / "web" / "console.html"
        return FileResponse(str(page))

    return app


def run(host: str = "127.0.0.1", port: int = 8786) -> int:
    import uvicorn
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"⚠ 对外绑定 {host}——控制台含启停动作, 务必配好 api_keys.local.json")
    uvicorn.run(create_app(host), host=host, port=port, log_level="warning")
    return 0
