#!/usr/bin/env python3
"""一键发四平台编排器

对 articles/ 里每篇【未发全】的文章, 依次发 老虎→东财→雪球→知乎(照常弹窗):
  - 失败跳过, 继续下一个平台
  - 每个平台抓真实文章链接(链接=真成功的证据; 抓不到标"待核实")
  - 全平台都成功后, 文章自动归档到 _done/
  - 最后输出每篇四平台的链接清单(可推微信)

用法:
  python3 publish_all.py                 # 发所有未发全的文章
  python3 publish_all.py --file xxx.docx # 只发指定文件
"""

import sys
import asyncio
import logging
import argparse
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import content as content_mod
from state import State
from publishers import get_publisher

# 平台发布顺序(老虎最稳→知乎)
ORDER = ["laohu", "eastmoney", "xueqiu", "zhihu"]
STOP_ON_FAIL = False    # --stop-on-fail 时为 True: 失败立即停不重试


def setup_logging():
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(),
                  logging.FileHandler(log_dir / "publish_all.log", encoding="utf-8")],
    )
    return logging.getLogger("publish-all")


def load_config():
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_articles(articles_dir, only_file=None):
    arts = []
    files = sorted(list(articles_dir.glob("*.md")) + list(articles_dir.glob("*.docx")))
    for f in files:
        if f.name.startswith("~$"):
            continue
        if only_file and f.name != only_file:
            continue
        try:
            arts.append(content_mod.load_article(f))
        except Exception as e:
            print(f"跳过 {f.name}: {e}", file=sys.stderr)
    return arts


async def publish_one_platform(plat, article, config, state, logger, throttle):
    """单平台发一篇, 返回 result dict。已发过(state)则跳过。"""
    if state.is_published(article["id"], plat):
        existing = state.get(article["id"], plat)
        return {"ok": True, "skipped": True, "url": existing.get("url", ""),
                "note": "已发过(跳过)"}
    plat_cfg = (config.get("platforms", {}) or {}).get(plat, {})
    pub = get_publisher(plat, plat_cfg, state, logger)
    try:
        await pub.run([article], draft=False,
                      min_interval_seconds=int(throttle.get("min_interval_seconds", 60)),
                      max_consecutive_failures=1)
    except Exception as e:
        logger.error(f"[{plat}] run 异常: {e}")
    # run() 内部已 state.mark, 读回结果
    st = state.get(article["id"], plat)
    return {"ok": st.get("status") == "published", "skipped": False,
            "url": st.get("url", ""), "note": st.get("note", "")}


async def main():
    parser = argparse.ArgumentParser(description="一键发四平台")
    parser.add_argument("--file", help="只发指定文件名")
    parser.add_argument("--platforms",
                        help="本次只发这些平台(逗号分隔,如 laohu,xueqiu);"
                             "不填则发 config 里 enabled=true 的全部")
    parser.add_argument("--stop-on-fail", action="store_true",
                        help="任何平台失败立即停止(验证模式; 不加则失败跳过继续)")
    args = parser.parse_args()
    global STOP_ON_FAIL
    STOP_ON_FAIL = args.stop_on_fail

    logger = setup_logging()
    config = load_config()
    state = State(ROOT / "state.json")
    throttle = config.get("throttle", {})
    articles_dir = ROOT / config.get("articles_dir", "articles")

    if args.platforms:
        # 网页勾选/命令行指定: 只发这些(仍按 ORDER 排序,且必须是已注册平台)
        picked = {p.strip() for p in args.platforms.split(",") if p.strip()}
        enabled = [p for p in ORDER if p in picked]
    else:
        enabled = [p for p in ORDER
                   if (config.get("platforms", {}) or {}).get(p, {}).get("enabled")]
    logger.info(f"启用平台(按序): {enabled}")
    if not enabled:
        logger.error("没有选中任何平台")
        return

    arts = load_articles(articles_dir, only_file=args.file)
    # 只处理"还没发全"的文章
    todo = [a for a in arts if not all(state.is_published(a["id"], p) for p in enabled)]
    if not todo:
        logger.info("没有待发文章(都已全平台发完或目录为空)")
        return
    logger.info(f"待发 {len(todo)} 篇: {[a['id'][:20] for a in todo]}")

    report = {}    # {article_id: {plat: {ok, url, note}}}
    for art in todo:
        logger.info(f"===== 开始发: {art['id']} =====")
        report[art["id"]] = {}
        for plat in enabled:
            logger.info(f"--- [{art['id'][:16]}] → {plat} ---")
            r = await publish_one_platform(plat, art, config, state, logger, throttle)
            report[art["id"]][plat] = r
            tag = "跳过(已发)" if r.get("skipped") else ("✅" if r["ok"] else "❌")
            logger.info(f"--- {plat}: {tag} {r.get('url','')} {r.get('note','')[:30]} ---")
            # 验证模式: 任何平台失败 → 立即停, 不继续不重试
            if not r["ok"] and not r.get("skipped") and STOP_ON_FAIL:
                logger.error(f"!!! {plat} 失败, 按要求立即停止(不重试不继续): {r.get('note','')}")
                summary = build_summary(report, enabled)
                (ROOT / "logs" / "last_publish_summary.txt").write_text(summary, encoding="utf-8")
                print("\n" + summary)
                print(f"\n[STOPPED] {plat} 失败: {r.get('note','')}")
                return
        # 全平台成功 → 归档
        if all(report[art["id"]][p]["ok"] for p in enabled):
            await archive(articles_dir, art["id"], logger)

    # 输出链接清单
    summary = build_summary(report, enabled)
    logger.info("\n" + summary)
    (ROOT / "logs" / "last_publish_summary.txt").write_text(summary, encoding="utf-8")
    print("\n" + summary)


async def archive(articles_dir, article_id, logger):
    import shutil
    done = articles_dir / "_done"
    done.mkdir(exist_ok=True)
    src = articles_dir / article_id
    if src.exists():
        try:
            shutil.move(str(src), str(done / article_id))
            logger.info(f"已归档(全平台发完): {article_id} → _done/")
        except Exception as e:
            logger.warning(f"归档失败 {article_id}: {e}")


PLAT_NAME = {"laohu": "老虎", "eastmoney": "东财", "xueqiu": "雪球", "zhihu": "知乎"}


def build_summary(report, enabled):
    lines = ["📋 发布结果清单"]
    for aid, plats in report.items():
        lines.append(f"\n📄 {aid}")
        for p in enabled:
            r = plats.get(p, {})
            mark = "✅" if r.get("ok") else "❌"
            url = r.get("url", "")
            note = r.get("note", "")
            extra = ""
            if r.get("ok") and (not url or "待核实" in note):
                extra = " ⚠️链接待核实"
            lines.append(f"· {PLAT_NAME.get(p,p)} {mark} {url}{extra}")
    return "\n".join(lines)


if __name__ == "__main__":
    asyncio.run(main())
