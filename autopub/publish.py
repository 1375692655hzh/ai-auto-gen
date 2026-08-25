#!/usr/bin/env python3
"""auto-publisher 主入口

读 articles_dir 里的 .md → 发到指定平台(跳过账本里已发过的)。

  python publish.py --platform laohu              # 真发
  python publish.py --platform laohu --draft      # 校准:填内容+截图,不真发
  python publish.py --platform laohu --limit 3
  python publish.py --status                       # 看各篇在各平台状态
"""

import sys
import asyncio
import logging
import argparse
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import content as content_mod
from state import State
from publishers import get_publisher, REGISTRY


def setup_logging():
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "publish.log", encoding="utf-8"),
        ],
    )
    return logging.getLogger("auto-publisher")


def load_config():
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_articles(articles_dir: Path) -> list:
    arts = []
    files = sorted(list(articles_dir.glob("*.md")) + list(articles_dir.glob("*.docx")))
    for f in files:
        if f.name.startswith("~$"):       # 跳过 Word 临时锁文件
            continue
        try:
            arts.append(content_mod.load_article(f))
        except Exception as e:
            print(f"跳过 {f.name}: 读取失败 {e}", file=sys.stderr)
    return arts


def cmd_status(config, state, logger):
    articles_dir = (ROOT / config.get("articles_dir", "articles"))
    arts = load_articles(articles_dir)
    print(f"\n文章目录: {articles_dir}  共 {len(arts)} 篇\n")
    platforms = list(REGISTRY)
    for a in arts:
        print(f"● {a['id']}  「{a['title'][:30]}」")
        for plat in platforms:
            st = state.get(a["id"], plat)
            mark = {"published": "✅", "failed": "❌"}.get(st.get("status"), "·")
            note = f"  {st.get('note','')}" if st.get("note") else ""
            print(f"    {mark} {plat:<12} {st.get('status','未发'):<10}{note}")
        print()


def main():
    parser = argparse.ArgumentParser(description="auto-publisher 多平台自动发文")
    parser.add_argument("--platform", help=f"平台,可选: {list(REGISTRY)}")
    parser.add_argument("--draft", action="store_true", help="校准模式:填内容+截图,不真发")
    parser.add_argument("--limit", type=int, default=None, help="本次最多发几篇")
    parser.add_argument("--status", action="store_true", help="只看状态,不发")
    args = parser.parse_args()

    logger = setup_logging()
    config = load_config()
    state = State(ROOT / "state.json")

    if args.status:
        cmd_status(config, state, logger)
        return

    if not args.platform:
        parser.error("需要 --platform(或用 --status 看状态)")

    plat = args.platform
    plat_cfg = (config.get("platforms", {}) or {}).get(plat, {})
    if not plat_cfg.get("enabled", False) and not args.draft:
        logger.warning(f"平台 {plat} 在 config 里 enabled=false;草稿模式可加 --draft 强行校准")
        if not args.draft:
            return

    articles_dir = ROOT / config.get("articles_dir", "articles")
    all_arts = load_articles(articles_dir)
    # 过滤掉账本里已发过的(草稿模式不过滤,方便反复校准)
    if args.draft:
        todo = all_arts
    else:
        todo = [a for a in all_arts if not state.is_published(a["id"], plat)]
    if args.limit:
        todo = todo[: args.limit]

    if not todo:
        logger.info(f"[{plat}] 没有待发文章(共 {len(all_arts)} 篇,均已发过或目录为空)")
        return
    logger.info(f"[{plat}] 待发 {len(todo)}/{len(all_arts)} 篇{'(草稿校准)' if args.draft else ''}")

    pub = get_publisher(plat, plat_cfg, state, logger)
    throttle = config.get("throttle", {})
    asyncio.run(pub.run(
        todo,
        draft=args.draft,
        min_interval_seconds=int(throttle.get("min_interval_seconds", 60)),
        max_consecutive_failures=int(throttle.get("max_consecutive_failures", 3)),
    ))

    # 发完后归档: 在所有 enabled 平台都发成功的文章, 移到 articles/_done/
    if not args.draft:
        archive_done(articles_dir, config, state, logger)


def archive_done(articles_dir, config, state, logger):
    """把'所有 enabled 平台都已 published'的文章移到 _done/(articles/ 只留待发)。"""
    import shutil
    enabled = [p for p, c in (config.get("platforms", {}) or {}).items()
               if (c or {}).get("enabled")]
    if not enabled:
        return
    done_dir = articles_dir / "_done"
    done_dir.mkdir(exist_ok=True)
    for f in list(articles_dir.glob("*.md")) + list(articles_dir.glob("*.docx")):
        if f.name.startswith("~$"):
            continue
        aid = f.name
        if all(state.is_published(aid, p) for p in enabled):
            try:
                shutil.move(str(f), str(done_dir / f.name))
                logger.info(f"已归档(全平台发完): {f.name} → _done/")
            except Exception as e:
                logger.warning(f"归档失败 {f.name}: {e}")


if __name__ == "__main__":
    main()
