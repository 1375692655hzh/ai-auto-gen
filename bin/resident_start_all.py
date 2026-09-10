"""常驻服务一键自愈(替代 resident_watchdog.bat 的 wscript 链)。

背景: 原 watchdog 经 wscript/silent_run 链调四个 bat, 实测父链退出会连带杀死
刚拉起的子进程; 且 bat 每 15min 弹黑窗打扰桌面。本脚本用 pyw 无窗执行,
复用 run_detached 的 DETACHED 拉起与端口幂等, 四个服务逐个兜底。

用法: pyw -3.11 bin/resident_start_all.py   (schtasks 每 15min 触发)
退出码恒 0(单服务失败不阻塞其余兜底, 错误落在 data/resident_start_all.log)。
"""
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_detached

REPO = run_detached.REPO
LOG = REPO / "data" / "resident_start_all.log"


def _log(msg: str) -> None:
    from datetime import datetime
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")


def start_cli(*args: str) -> None:
    """幂等拉起 cli.py 子命令(workbench serve / sources serve / sources console)。"""
    port = run_detached.PORTS.get(tuple(args[:2]))
    if port and run_detached._port_busy(port):
        _log(f"{args}: port {port} 在听/退让, skip")
        return
    log_dir = REPO / "data"
    log_dir.mkdir(exist_ok=True)
    log = open(log_dir / f"{args[0]}_task.log", "a", encoding="utf-8")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    DETACHED = 0x00000008 | 0x00000200
    subprocess.Popen([sys.executable, "-u", str(REPO / "cli.py"), *args],
                     cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT,
                     env=env, creationflags=DETACHED, close_fds=True)
    _log(f"{args}: detached-launched")


def start_omniroute() -> None:
    """幂等拉起 OmniRoute 网关(--daemon 自我守护, 只恢复免费翻译层)。"""
    if run_detached._port_busy(20128):
        _log("omniroute: port 20128 在听/退让, skip")
        return
    shim = shutil.which("omniroute")
    if not shim:
        _log("omniroute: PATH 中找不到 omniroute, skip(翻译链自动落付费位)")
        return
    (REPO / "data").mkdir(exist_ok=True)
    log = open(REPO / "data" / "omniroute_task.log", "a", encoding="utf-8")
    env = dict(os.environ, OMNIROUTE_SERVER_HOST="127.0.0.1")
    if shim.lower().endswith(".cmd"):        # npm shim 必须经 cmd 执行
        cmd = ["cmd", "/c", shim, "serve", "--daemon", "--no-open"]
    else:
        cmd = [shim, "serve", "--daemon", "--no-open"]
    DETACHED = 0x00000008 | 0x00000200
    subprocess.Popen(cmd, cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT,
                     env=env, creationflags=DETACHED, close_fds=True)
    _log("omniroute: detached-launched")


def main() -> int:
    steps = [("workbench serve", lambda: start_cli("workbench", "serve")),
             ("sources serve", lambda: start_cli("sources", "serve")),
             ("sources console", lambda: start_cli("sources", "console")),
             ("omniroute", start_omniroute)]
    for name, fn in steps:
        try:
            fn()
        except Exception:
            _log(f"{name}: 拉起失败\n{traceback.format_exc()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
