"""视频发布入口 —— B站 / 抖音

用法:
  py publish_video.py --video ..\\video\\videos\\daily-xxx\\out\\final.mp4 \
      --title "AI财经早报 8-28" --platforms bilibili,douyin
  可选: --desc "简介" --tags 财经,早报 --draft(存草稿不真发)

平台实现: publishers/bilibili.py / publishers/douyin.py
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from publish_all import load_config, setup_logging      # noqa: E402
from state import State                                  # noqa: E402
from publishers import get_publisher                     # noqa: E402


async def main():
    ap = argparse.ArgumentParser(description="视频发布(B站/抖音)")
    ap.add_argument("--video", required=True, help="视频文件路径(.mp4)")
    ap.add_argument("--title", required=True, help="标题")
    ap.add_argument("--desc", default="", help="简介(默认用标题)")
    ap.add_argument("--tags", default="财经,早报", help="标签/话题(逗号分隔)")
    ap.add_argument("--platforms", default="bilibili,douyin", help="平台(逗号分隔)")
    ap.add_argument("--draft", action="store_true", help="存草稿, 不真发")
    ap.add_argument("--cover", default="", help="封面图(默认自动用视频同目录 out/cover.png)")
    args = ap.parse_args()

    logger = setup_logging()
    config = load_config()
    state = State(Path(__file__).resolve().parent / "state.json")
    art = {
        "id": Path(args.video).stem,
        "title": args.title,
        "body": args.desc or args.title,
        "blocks": [],
        "video": str(Path(args.video).resolve()),
        "tags": [t.strip() for t in args.tags.split(",") if t.strip()],
        "cover": args.cover or str(Path(args.video).resolve().parent / "cover.png"),
    }
    for plat in [p.strip() for p in args.platforms.split(",") if p.strip()]:
        logger.info(f"===== [{plat}] 视频发布 =====")
        try:
            pub = get_publisher(plat, (config.get("platforms") or {}).get(plat, {}),
                                state, logger)
            await pub.run([art], draft=args.draft, min_interval_seconds=10)
        except Exception as e:
            logger.error(f"[{plat}] 异常: {e}")


if __name__ == "__main__":
    asyncio.run(main())
