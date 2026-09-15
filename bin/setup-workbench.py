"""同事一键配好工作台（2026-09-15 分发口径）：克隆仓库后只跑这一个脚本。

做什么（全部幂等可重跑）：
  1. Python 版本检查（需 >= 3.10，推荐 3.11）
  2. pip install 工作台依赖（fastapi/uvicorn/pyyaml/requests）
  3. 可选增强包 pandas/yfinance/mplfinance（成稿 K 线图用，装不上只警告）
  4. Node.js 检查（>= 20；缺了不影响资讯/图文浏览，视频配音/出片需要它）
  5. npm install（ai-workflow/video，视频功能依赖；缺 Node 或目录不在则跳过并说明）
  6. python cli.py doctor 环境体检
  7. 打印下一步（启动工作台 + 设置页配 key）

用法：双击 bin/setup-workbench.cmd，或 python bin/setup-workbench.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VIDEO_DIR = REPO / "ai-workflow" / "video"
CORE_REQ = REPO / "workbench" / "requirements.txt"


def run(cmd: list, cwd: Path | None = None, timeout: int = 1200) -> int:
    print(f"  > {' '.join(str(c) for c in cmd)}" + (f"   (cwd={cwd.name})" if cwd else ""))
    try:
        return subprocess.run(cmd, cwd=str(cwd) if cwd else None, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        print(f"  ! 超时（>{timeout}s）中断，可重跑本脚本续装")
        return 1
    except OSError as e:
        print(f"  ! 启动失败: {e}")
        return 1


def main() -> int:
    print("=" * 62)
    print("ai-auto-gen 工作台一键配置（重复运行安全，失败可重跑）")
    print("=" * 62)

    # 1. Python 版本
    print("\n[1/6] Python 检查")
    ver = sys.version_info
    print(f"  当前解释器: {sys.executable}")
    print(f"  Python 版本: {ver.major}.{ver.minor}.{ver.micro}")
    if ver < (3, 10):
        print("  ✗ 需要 Python >= 3.10（推荐 3.11）。到 python.org/downloads 安装后重跑。")
        return 3
    print("  ✓ 版本满足")

    # 2. 核心依赖（失败即退出——没有它们工作台起不来）
    print("\n[2/6] 安装工作台核心依赖（fastapi/uvicorn/pyyaml/requests）")
    code = run([sys.executable, "-m", "pip", "install", "-r", str(CORE_REQ)])
    if code != 0:
        print("  ✗ 核心依赖安装失败（多为网络问题）。可换国内镜像后重跑：")
        print('    python -m pip install -r workbench/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple')
        return 3
    print("  ✓ 核心依赖就绪")

    # 3. 可选增强（只警告）
    print("\n[3/6] 安装可选增强包（pandas/yfinance/mplfinance，成稿 K 线图用）")
    if run([sys.executable, "-m", "pip", "install", "pandas", "yfinance", "mplfinance"]) != 0:
        print("  ! 增强包未装上——不影响工作台启动，成稿 K 线图暂不可用，之后可随时补装")

    # 4. Node 检查
    print("\n[4/6] Node.js 检查（视频配音/出片/封面需要；纯浏览不需要）")
    node = shutil.which("node")
    if not node:
        print("  ! 未检测到 Node.js——资讯/图文/翻译/追踪功能不受影响；")
        print("    视频配音与出片不可用。要用视频功能: 到 https://nodejs.org 装 LTS 版后重跑本脚本。")
    else:
        try:
            v = subprocess.run(["node", "--version"], capture_output=True, text=True,
                               timeout=15).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            v = ""
        print(f"  ✓ Node {v or '(版本探测失败, 不影响)'}")

    # 5. npm install（视频板块依赖：msedge-tts 音色包 + ffprobe）
    print("\n[5/6] 视频板块 npm 依赖（首次约几分钟）")
    if not node:
        print("  - 跳过（无 Node）；装好 Node 后重跑本脚本即可补上")
    elif not VIDEO_DIR.is_dir():
        print("  ! 未找到 ai-workflow/video 目录——本仓库疑似只拷了部分目录。")
        print("    请完整克隆 ai-gen-article-publish 仓库后重跑（视频功能依赖板块二）。")
    else:
        nm_msedge = VIDEO_DIR / "node_modules" / "msedge-tts"
        compositor = any((VIDEO_DIR / "node_modules").glob("@remotion/compositor-*"))
        if nm_msedge.is_dir() and compositor:
            print("  ✓ npm 依赖已就绪（跳过安装）")
        elif run(["npm", "install"], cwd=VIDEO_DIR) == 0:
            print("  ✓ npm 依赖安装完成")
        else:
            print("  ! npm install 失败。国内网络可先执行下面两条再重跑：")
            print("    npm config set registry https://registry.npmmirror.com")
            print("    (然后重跑 bin/setup-workbench.cmd)")

    # 6. doctor 体检
    print("\n[6/6] 环境体检 doctor")
    run([sys.executable, str(REPO / "cli.py"), "doctor"], timeout=180)

    print("\n" + "=" * 62)
    print("配置完成。下一步：")
    print("  1. 启动工作台:  python cli.py workbench serve --open")
    print("     (浏览器自动打开 http://127.0.0.1:8788)")
    print("  2. 进「设置」页逐项配 key（每项都有注册来源引导）:")
    print("     信息源连接(数据站地址+Key) / 翻译模型 / 成稿模型 / TTS 语音")
    print("  3. 日常使用只需第 1 条命令；配 key 全部在网页设置页完成")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
