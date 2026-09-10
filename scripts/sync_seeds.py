#!/usr/bin/env py -3.11
"""把本机权威清单同步进仓内 seed/(分发用户首跑播种源)。

背景: 分发用户(含纯工作台稀疏检出)首次打开时, 账号管理/追踪账号两处清单空白、
档案增强(粉丝数/认证)缺失——因为池 yaml 在板块一目录(稀疏检出没有)、
yt_channels/x_profiles 是 gitignored 运行时数据。播种契约(见 config.seed_if_missing):
- 只在用户自有文件缺失时复制一次; 此后启停/开关全归用户自己的文件, 永不回写覆盖。
- 「跟开发者看齐」= 开发者改了清单后跑本脚本并提交 seed/。

用法: py -3.11 scripts/sync_seeds.py   (改完账号清单后跑一次 + git commit workbench/server/seed/)
"""

import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SEED = REPO / "workbench" / "server" / "seed"

JOBS = [
    # (源, 目标名, 说明)
    (REPO / "global-news-sources" / "config" / "twitter_pool.yaml", "twitter_pool.yaml",
     "X 账号池(图文页-账号管理清单源; 稀疏检出的池文件兜底)"),
    (REPO / "data" / "workbench" / "yt_channels.json", "yt_channels.json",
     "YouTube 追踪账号库(视频页-追踪账号)"),
    (REPO / "data" / "workbench" / "x_profiles.json", "x_profiles.json",
     "X 档案增强缓存(粉丝数/认证/bio 展示信息)"),
]


def main() -> int:
    SEED.mkdir(parents=True, exist_ok=True)
    rc = 0
    for src, name, note in JOBS:
        dst = SEED / name
        if not src.is_file():
            print(f"[skip] {name}: 源不存在 {src}")
            continue
        d = None
        if src.suffix == ".json":                        # 校验 JSON 合法再入库
            try:
                d = json.loads(src.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[fail] {name}: JSON 损坏 {e}")
                rc = 3
                continue
        shutil.copyfile(src, dst)
        n = len(d) if isinstance(d, list) else len(d.get("profiles", {})) if isinstance(d, dict) else "-"
        print(f"[ok] {name} ← {src.name}  ({n} 条)  # {note}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
