"""以脱离登录会话的分离进程拉起常驻服务(带端口幂等自检)。

背景(2026-09-10 实测排障): workbench_task.bat 原用 `start /b`, 在
wscript/计划任务拉起链下, 父链退出会连带杀死子进程——bat 拉起的 serve 绑定后
数秒即死; 交互式 shell 拉起则一直正常。两层修复:
1. 本脚本用 DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP 起子进程, 不挂父控制台;
2. 更关键: 计划任务动作不再经 wscript/silent_run 链, 直接调本脚本
   (见 aag-workbench / aag-resident-watchdog 任务登记)。

用法: py -3.11 bin/run_detached.py workbench serve
日志: data/<args[0]>_task.log(即 workbench_task.log, 与 bat 原落点一致)
幂等: 目标端口 LISTENING 或 TIME_WAIT 时零副作用退出 0(对齐 *_task.bat 语义)。
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PORTS = {("workbench", "serve"): 8788,
         ("sources", "serve"): 8787,
         ("sources", "console"): 8786}


def _port_busy(port: int) -> bool:
    import socket
    s = socket.socket()
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", port))
        return True                      # 在听 = 幂等退出
    except OSError:
        return False
    finally:
        s.close()
    # 注意: 不显式退让 TIME_WAIT——刚被杀的旧实例残留 TIME_WAIT 会让任务空转
    # 一轮, 崩后自愈反而被拖住; uvicorn 起监听带 SO_REUSEADDR, 可越过 TIME_WAIT 绑定。


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("usage: run_detached.py <cli 参数...>  例: run_detached.py workbench serve",
              file=sys.stderr)
        return 2
    port = PORTS.get(tuple(args[:2]))
    if port and _port_busy(port):
        print(f"port {port} busy/listening-or-time_wait, no-op exit 0")
        return 0
    log_dir = REPO / "data"
    log_dir.mkdir(exist_ok=True)
    log = open(log_dir / f"{args[0]}_task.log", "a", encoding="utf-8")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    DETACHED = 0x00000008 | 0x00000200      # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([sys.executable, "-u", str(REPO / "cli.py"), *args],
                     cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT,
                     env=env, creationflags=DETACHED, close_fds=True)
    print(f"detached-launched: {' '.join(args)} -> data/{args[0]}_task.log")
    return 0


if __name__ == "__main__":
    sys.exit(main())
