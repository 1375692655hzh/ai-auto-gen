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
from publishers import get_publisher, REGISTRY

# 平台发布优先级(仅排序用;实际清单 = 这里列出的 ∩ config enabled,未列出的注册平台排最后)
ORDER = ["eastmoney", "xueqiu", "weibo", "futu", "changqiao",
         "laohu", "zhihu", "bilibili", "douyin", "tonghuashun", "xiaohongshu"]
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


async def publish_one_platform(plat, article, config, state, logger, throttle,
                               draft=False):
    """单平台发一篇, 返回 result dict。已发过/结果未确认(state)则跳过。"""
    if state.is_skip(article["id"], plat):
        existing = state.get(article["id"], plat)
        if existing.get("status") == "uncertain":
            return {"ok": False, "skipped": True, "url": existing.get("url", ""),
                    "note": "上次结果未确认(uncertain),需人工核实,已跳过"}
        return {"ok": True, "skipped": True, "url": existing.get("url", ""),
                "note": "已发过(跳过)"}
    plat_cfg = (config.get("platforms", {}) or {}).get(plat, {})
    pub = get_publisher(plat, plat_cfg, state, logger)
    try:
        await pub.run([article], draft=draft,
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
    parser.add_argument("--draft", action="store_true",
                        help="草稿模式(只填充+截图,不真发);不加默认真发")
    parser.add_argument("--force", action="store_true",
                        help="跳过失败冷却强制重试(默认同篇同平台失败后30分钟内不重试,防限流)")
    args = parser.parse_args()
    global STOP_ON_FAIL
    STOP_ON_FAIL = args.stop_on_fail

    logger = setup_logging()
    config = load_config()
    state = State(ROOT / "state.json")
    throttle = config.get("throttle", {})
    articles_dir = ROOT / config.get("articles_dir", "articles")

    all_known = [p for p in ORDER if p in REGISTRY] + \
                [p for p in REGISTRY if p not in ORDER]
    if args.platforms:
        # 网页勾选/命令行指定: 只发这些(必须是已注册平台,拼错直接报错)
        picked = {p.strip() for p in args.platforms.split(",") if p.strip()}
        unknown = picked - set(REGISTRY)
        if unknown:
            logger.error(f"未知平台: {sorted(unknown)} (已注册: {list(REGISTRY)})")
            return
        enabled = [p for p in all_known if p in picked]
    else:
        enabled = [p for p in all_known
                   if (config.get("platforms", {}) or {}).get(p, {}).get("enabled")]
    logger.info(f"启用平台(按序): {enabled}" + (" [草稿模式]" if args.draft else ""))
    if not enabled:
        logger.error("没有选中任何平台")
        return

    arts = load_articles(articles_dir, only_file=args.file)
    # 只处理"还没发全"的文章(uncertain 也算未完成,但会在单平台层被跳过并提示人工核实)
    todo = [a for a in arts if not all(state.is_published(a["id"], p) for p in enabled)]
    if not todo:
        logger.info("没有待发文章(都已全平台发完或目录为空)")
        return
    logger.info(f"待发 {len(todo)} 篇: {[a['id'][:20] for a in todo]}")

    # 发布前登录态预检: 失效平台直接剔除并记账(带原因),
    # 不再发文中途卡 240s 等登录; failed 不算已发, 重登后重跑自动补发
    if config.get("precheck_login", True) and not args.draft:
        logger.info("登录态预检中(每平台约10s)...")
        import health
        for r in await health.check_logins_async(enabled):
            p = r["platform"]
            if r.get("logged_in") is False:
                logger.error(f"[{p}] 预检: {r['why']} —— 本次跳过, 扫码重登后重跑即自动补发")
                for art in todo:
                    state.mark(art["id"], p, "failed", note=f"预检跳过: {r['why']}")
                enabled = [x for x in enabled if x != p]
            elif r.get("logged_in") is None:
                logger.warning(f"[{p}] 预检不确定: {r['why']} (照常尝试)")
        if not enabled:
            logger.error("预检后没有可用平台(都需重新登录)")
            return

    report = {}    # {article_id: {plat: {ok, url, note}}}
    for art in todo:
        logger.info(f"===== 开始发: {art['id']} =====")
        report[art["id"]] = {}
        for plat in enabled:
            logger.info(f"--- [{art['id'][:16]}] → {plat} ---")
            # 防限流冷却: 同篇×同平台失败后 N 分钟内不再重试(高频重试会触发平台风控,
            # 2026-09-03 微博限流的教训)。--force 可跳过。
            cooldown = int(throttle.get("retry_cooldown_minutes", 30))
            if not args.force and cooldown > 0 and not args.draft:
                prev = state.get(art["id"], plat)
                if prev.get("status") in ("failed", "uncertain"):
                    try:
                        from datetime import datetime as _dt
                        mins = (_dt.now() - _dt.strptime(prev["time"],
                                "%Y-%m-%d %H:%M:%S")).total_seconds() / 60
                        if 0 <= mins < cooldown:
                            r = {"ok": False, "skipped": True, "url": "",
                                 "note": f"冷却中: 上次{prev['status']}于{int(mins)}分钟前,"
                                         f"{cooldown}分钟后才可重试(--force 可强制)"}
                            report[art["id"]][plat] = r
                            logger.warning(f"--- {plat}: ⏸️ {r['note']} ---")
                            continue
                    except Exception:
                        pass
            r = await publish_one_platform(plat, art, config, state, logger, throttle,
                                           draft=args.draft)
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


PLAT_NAME = {"laohu": "老虎", "eastmoney": "东财", "xueqiu": "雪球", "zhihu": "知乎",
             "weibo": "微博", "futu": "富途", "changqiao": "长桥",
             "bilibili": "B站", "douyin": "抖音", "tonghuashun": "同花顺"}


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
