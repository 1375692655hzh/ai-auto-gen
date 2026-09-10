"""X 起爆帖采集一键管理(2026-09-10): 分发用户开箱即采, 不用碰命令行。

问题: 纯工作台部署(稀疏检出)没有 Windows 计划任务, refresh-x-surge 从不跑,
推荐信息/蹭蹭流量两页空态文案只会叫用户去敲 CLI。
本模块把工作台变成采集入口(对齐 omniroute_ctl 的一键范式):
- status(): 采集是否在跑(psutil 按命令行匹配, 含任务计划拉起的那轮)
          + 两缓存新鲜度(RSS / 互动快照) + 定时任务是否已登记
- collect(): 幂等触发一轮采集——在跑则直接返回, 否则 Popen 拉起
          `cli.py workbench refresh-x-surge`(沿用 xsurge_task.bat 同款命令)。
          x_surge.collect 自带单实例锁, 双保险。
- schedule(): 登记 aag-xsurge-refresh 计划任务(复用 bin/xsurge_task.bat + silent_run.vbs,
          与主仓 every-15min 错相 7 分钟)。仅 Windows; 失败给可复制的登记命令。
全部 subprocess 列表参数(无 shell 注入面)。
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import config, x_surge

REPO = Path(__file__).resolve().parents[2]
TASK_BAT = REPO / "bin" / "xsurge_task.bat"
SILENT_VBS = REPO / "bin" / "silent_run.vbs"
LOG = REPO / "data" / "xsurge_collect.log"
TASK_NAME = "aag-xsurge-refresh"

_spawned: dict = {}   # pid -> Popen, 本进程触发过的采集轮(任务计划拉起的靠 psutil 探测)


def _python_exe() -> tuple[str, list]:
    """CLI 启动前缀走 config.py_cmd 自适应(探 py -3.11, 缺失退本体解释器)。"""
    cmd = config.py_cmd()
    return cmd[0], cmd[1:]


def _collect_running() -> bool:
    """有进程在跑 refresh-x-surge 吗(含任务计划/手跑的其它终端)。"""
    try:
        import psutil
    except ImportError:
        return any(p.poll() is None for p in _spawned.values())
    for p in _spawned.values():                 # 先看自己拉起的, 快路径
        if p.poll() is None:
            return True
    for p in psutil.process_iter(["cmdline", "pid"]):
        try:
            cmd = p.info.get("cmdline") or []
            flat = " ".join(str(c) for c in cmd)
            if "refresh-x-surge" in flat and "cli.py" in flat:
                if p.pid != os.getpid():
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def _task_scheduled() -> bool:
    """计划任务 aag-xsurge-refresh 是否已登记(非 Windows 一律 False)。"""
    if os.name != "nt" or not shutil.which("schtasks"):
        return False
    try:
        p = subprocess.run(["schtasks", "/query", "/tn", TASK_NAME],
                           capture_output=True, text=True, timeout=15)
        return p.returncode == 0
    except Exception:
        return False


def status() -> dict:
    rss = x_surge.load_rss()
    eng = x_surge.load_engage()
    return {"collecting": _collect_running(),
            "rss_updated_at": rss.get("updated_at"),
            "rss_total": len(rss.get("items") or {}),
            "eng_updated_at": eng.get("updated_at"),
            "eng_tracked": len(eng.get("statuses") or {}),
            "scheduled": _task_scheduled()}


def collect() -> dict:
    """幂等拉一轮采集。在跑→直接报告; 否则 detached 拉起, 日志落 data/xsurge_collect.log。"""
    if _collect_running():
        return {"ok": True, "note": "采集已在进行中, 稍候片刻自动出数", "collecting": True}
    py, pre = _python_exe()
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    LOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        log = open(LOG, "a", encoding="utf-8")
        proc = subprocess.Popen([py, *pre, str(REPO / "cli.py"), "workbench",
                                 "refresh-x-surge", "--force"],
                                cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    except OSError as e:
        return {"ok": False, "msg": f"拉起失败: {e}", "collecting": False}
    _spawned[proc.pid] = proc
    for pid in [k for k, p in _spawned.items() if p.poll() is not None]:
        del _spawned[pid]                        # 顺手清理已结束的
    return {"ok": True, "note": "采集已启动(X 热帖 + SoPilot RSS, 约 2-5 分钟), 完成后页面自动刷新",
            "collecting": True, "pid": proc.pid}


def schedule() -> dict:
    """登记每 15 分钟自动采集(Windows 任务计划)。幂等: 已登记直接成功。"""
    if os.name != "nt":
        return {"ok": False, "msg": "仅 Windows 支持任务计划; 手动点「立即采集」即可",
                "scheduled": False}
    if _task_scheduled():
        return {"ok": True, "msg": "定时采集已登记, 每 15 分钟自动跑一轮", "scheduled": True}
    tr = f'wscript.exe "{SILENT_VBS}" "{TASK_BAT}"'
    cmd = ["schtasks", "/create", "/tn", TASK_NAME, "/tr", tr,
           "/sc", "minute", "/mo", "15", "/st", "00:07", "/f"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception as e:
        return {"ok": False, "msg": f"登记失败: {e}", "scheduled": False}
    if p.returncode == 0:
        return {"ok": True, "msg": "已开启每 15 分钟自动采集(与数据站刷新错相 7 分钟)",
                "scheduled": True}
    return {"ok": False, "scheduled": False,
            "msg": "任务计划登记失败(可能无权限)。可手动运行: schtasks /create " +
                   f'/tn "{TASK_NAME}" /tr "{tr}" /sc minute /mo 15 /st 00:07 /f'}
