"""运维页数据面(板块四·运维): 常驻进程/开机任务/刷新轮/存储四块状态 + 白名单动作。

红线适配: 全程只读取证(端口/netstat/schtasks/文件体积), 动作一律 subprocess
(启动=拉起 cli.py/omniroute, 停止=taskkill 端口占用 PID), 不直写三板块文件;
唯一落盘是 bat 侧自己的 data\\*_task.log。工作台自身只读展示(你在看页面=它在跑)。
"""

import json
import re
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # 仓库根
DATA = ROOT / "data"

# 常驻进程清单: key → (显示名, 端口, 说明)
PROCS = {
    "serve":     ("数据站 sources serve", 8787, "板块一读侧供数( Bearer 鉴权 )"),
    "workbench": ("工作台 workbench", 8788, "板块四本页面所在进程"),
    "omniroute": ("OmniRoute 翻译网关", 20128, "翻译链免费位(muse/mimo)所在"),
}

# 开机/计划任务清单(刷新型=已有; 自启型=本次新增)
TASKS = ["aag-sources-refresh", "aag-xsurge-refresh",
         "aag-serve", "aag-workbench", "aag-omniroute"]

LOG_FILES = ["refresh_task.log", "xsurge_task.log", "serve_task.log",
             "workbench_task.log", "omniroute_task.log", r"serve\access.log"]


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
    f.write(f"\n===== {time.strftime('%F %T')} ops 拉起: {' '.join(cli_args)} =====\n")
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
    elif target == "omniroute":
        # npm 装的 omniroute 是 .cmd shim, CreateProcess 不能直接执行, 必须经 cmd /c
        if op == "start":
            if _port_pid(20128):
                return {"ok": True, "output": "20128 已在监听, 无需启动"}
            import os
            env = dict(os.environ, OMNIROUTE_SERVER_HOST="127.0.0.1")
            p = subprocess.run(["cmd", "/c", "omniroute", "serve", "--daemon", "--no-open"],
                               capture_output=True, timeout=60, env=env)
            out = ((p.stdout or b"") + (p.stderr or b"")).decode("utf-8", errors="ignore")
            return {"ok": p.returncode == 0, "output": out[-400:]}
        if op == "stop":
            p = subprocess.run(["cmd", "/c", "omniroute", "stop"],
                               capture_output=True, timeout=30)
            out = ((p.stdout or b"") + (p.stderr or b"")).decode("utf-8", errors="ignore")
            return {"ok": p.returncode == 0, "output": out[-300:]}
    elif target == "refresh":
        if op == "start":                                # 立即刷一轮(幂等, 与任务计划并存)
            return dict(zip(("ok", "output"), _spawn(["sources", "refresh"], "refresh_task.log")))
    elif target == "xsurge":
        if op == "start":
            return dict(zip(("ok", "output"),
                            _spawn(["workbench", "refresh-x-surge"], "xsurge_task.log")))
    return {"ok": False, "output": f"不支持的动作: {target}/{op}"}
