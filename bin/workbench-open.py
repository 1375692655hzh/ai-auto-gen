"""双击启动工作台(bin/workbench-open.cmd 的干活体, 2026-09-20 分发补丁)。

对普通用户隐藏"双进程"模型(工作台 8788 + 本机数据站 8787):
  1. 8788 已在听 → 只开浏览器, 零副作用;
  2. 否则: 若 data/workbench/settings.json 的 source.base_url 指向本机
     (127.0.0.1/localhost) 且数据站端口未听 → 顺带 detached 拉起 sources serve;
  3. 经 bin/run_detached.py detached 拉起 workbench serve(端口幂等, 日志
     data/workbench_task.log), 轮询 8788 最多 15s, 起来即开浏览器;
  4. 超时不停在静默上: 打印日志路径与排查指引, 退出码 3(.cmd 会 pause 住窗口)。

幂等可重跑; 不读不改任何密钥; 只写 run_detached.py 自身的日志文件。
"""
import json
import socket
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUN_DETACHED = Path(__file__).resolve().parent / "run_detached.py"
WB_PORT = 8788
POLL_S = 15.0

for _s in (sys.stdout, sys.stderr):          # 双击 cmd 控制台回退 GBK 时防崩(对齐 cli.py)
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _listening(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.35):
            return True
    except OSError:
        return False


def _local_station_port() -> int | None:
    """settings.json source.base_url 指向本机 → 返回其端口; 远程/读不到 → None。

    文件不存在/损坏按出厂默认 http://127.0.0.1:8787 处理(与 config.DEFAULTS 一致)。"""
    try:
        cfg = json.loads((REPO / "data" / "workbench" / "settings.json")
                         .read_text(encoding="utf-8"))
        base = str(((cfg.get("source") or {}).get("base_url")) or "")
    except Exception:
        base = ""
    if not base:
        base = "http://127.0.0.1:8787"        # 出厂默认(本机数据站)
    try:
        u = urllib.parse.urlparse(base if "//" in base else "http://" + base)
        if u.hostname not in ("127.0.0.1", "localhost", "::1"):
            return None                        # 局域网/云端数据站: 不在本机拉
        return u.port or 80 if u.scheme == "http" else (u.port or 443)
    except ValueError:
        return None


def _launch(*cli_args: str) -> None:
    """detached 拉起 cli.py 服务(run_detached.py 端口幂等, 不挂本窗口)。"""
    subprocess.run([sys.executable, "-u", str(RUN_DETACHED), *cli_args],
                   capture_output=True, timeout=60)


def main() -> int:
    url = f"http://127.0.0.1:{WB_PORT}/"
    if _listening(WB_PORT):
        print("工作台已在运行, 直接打开浏览器。")
        webbrowser.open(url)
        return 0

    st_port = _local_station_port()
    if st_port and not _listening(st_port):
        print(f"本机数据站(端口 {st_port})未启动, 正在顺带拉起 sources serve ...")
        _launch("sources", "serve")
    else:
        print("数据站无需处理(远程数据站或本机已在运行)。")

    print("正在启动工作台 serve(最多等待 15 秒)...")
    _launch("workbench", "serve")
    deadline = time.time() + POLL_S
    while time.time() < deadline:
        if _listening(WB_PORT):
            print(f"工作台已就绪: {url}")
            webbrowser.open(url)
            return 0
        time.sleep(0.5)
    print("等待超时: 工作台 15 秒内未监听 8788。请查看日志:")
    print(f"  {REPO / 'data' / 'workbench_task.log'}")
    print("或手动运行排查: python cli.py workbench serve")
    return 3


if __name__ == "__main__":
    sys.exit(main())
