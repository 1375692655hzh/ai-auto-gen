"""OmniRoute 本地翻译网关一键管理(2026-09-09): 分发用户开箱即用免费翻译。

出厂翻译链预置了 OmniRoute 免费位(127.0.0.1:20128 + muse 免费模型), 但它是个
npm 全局包, 分发包里不带二进制——没装的机器上免费位是死的, 翻译静默失败。
本模块把「检测 → 安装 → 启动」做成工作台内置一键动作(设置页按钮触发):
- status(): 20128 在听? / 已安装? / 有 Node? 三态探测
- setup(): 幂等——已运行直接成功; 已装未跑只启动; 未装走 npm i -g omniroute 再启动
- 全部 subprocess 列表参数(无 shell 注入面), 仅装 omniroute 一个包, 仅回环绑定
"""

import shutil
import socket
import subprocess
import time

HOST, PORT = "127.0.0.1", 20128


def _listening() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=1.5):
            return True
    except OSError:
        return False


def _installed() -> bool:
    return shutil.which("omniroute") is not None


def _node_ok() -> bool:
    return shutil.which("node") is not None or shutil.which("npm") is not None


def status() -> dict:
    """三态探测: running(20128在听) / installed(装了没跑) / missing(没装) / no_node(无Node环境)。"""
    if _listening():
        return {"state": "running", "port": PORT}
    if not _node_ok():
        return {"state": "no_node", "port": PORT,
                "hint": "未检测到 Node.js — 先到 https://nodejs.org 安装 LTS 版(一路下一步), 再回来点一键安装"}
    if not _installed():
        return {"state": "missing", "port": PORT}
    return {"state": "installed", "port": PORT}


def setup(timeout_s: int = 300) -> dict:
    """幂等安装并启动。返回最终状态; npm 输出尾部回显供前端展示。"""
    st = status()
    if st["state"] == "running":
        return {**st, "ok": True, "msg": "OmniRoute 已在运行, 免费翻译已生效"}
    log_tail = ""
    if st["state"] == "missing":
        npm = shutil.which("npm")
        if not npm:
            return {**st, "ok": False, "msg": st.get("hint") or "未找到 npm"}
        try:
            p = subprocess.run([npm, "i", "-g", "omniroute"],
                               capture_output=True, text=True, timeout=timeout_s)
            log_tail = ((p.stdout or "") + (p.stderr or ""))[-500:]
            if p.returncode != 0 or not _installed():
                return {"state": "missing", "ok": False,
                        "msg": f"npm 安装失败(退出码 {p.returncode})", "log": log_tail}
        except subprocess.TimeoutExpired:
            return {"state": "missing", "ok": False, "msg": f"npm 安装超时({timeout_s}s)", "log": log_tail}
    exe = shutil.which("omniroute")
    if not exe:
        return {"state": "missing", "ok": False, "msg": "安装后仍未找到 omniroute 命令"}
    import os
    env = dict(os.environ, OMNIROUTE_SERVER_HOST=HOST)          # 仅回环绑定(安全红线)
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen([exe, "serve", "--daemon", "--no-open"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, env=env, creationflags=flags,
                         close_fds=True)
    except OSError as e:
        return {"state": "installed", "ok": False, "msg": f"启动失败: {e}"}
    for _ in range(20):                                          # 最多等 20s 起监听
        if _listening():
            return {"state": "running", "ok": True,
                    "msg": "OmniRoute 已启动, 免费翻译生效(链位: 127.0.0.1:20128 muse)", "log": log_tail}
        time.sleep(1)
    return {"state": "installed", "ok": False, "msg": "已拉起但 20s 内未见 20128 监听, 稍后再试或看 data/omniroute_task.log"}
