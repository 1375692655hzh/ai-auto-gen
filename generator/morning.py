"""早报生成:A股早报 + 港美股早报,各产出「文章」和「口播稿」。

素材来自 sources.gather(),按市场分类这件事交给模型做
(关键词预筛容易漏宏观联动消息,模型筛选更稳)。
"""

import sys

from common import load_cfg, out_dir, today, now_str, save_text, llm_complete
import sources

MARKETS = {
    "a": {
        "name": "A股早报",
        "pick": "A股及国内宏观相关(沪深北交易所、证监会/央行政策、国内经济数据、行业板块、A股公司公告、影响A股的资金面消息)",
        "exclude": "纯美股个股行情、港股个股、与A股无关的海外新闻",
    },
    "us": {
        "name": "港美股早报",
        "pick": "港股与美股相关(美联储、美国经济数据、美股三大指数与明星个股、中概股、港股与港交所、影响港美股的宏观地缘消息)",
        "exclude": "只影响A股的国内政策与个股消息",
    },
}

SYS_ARTICLE = (
    "你是资深财经编辑,为散户投资者写盘前早报。文风:客观、信息密度高、不喊单。"
    "输出纯 Markdown,第一行是一级标题。不要编造快讯里没有的事实,不确定的信息宁可不写。"
)

SYS_SCRIPT = (
    "你是财经短视频口播撰稿人。口语化、有节奏、短句为主,像主播说话,不念文件。"
    "开头3秒必须抛出当天最抓眼的钩子,结尾一句自然引导关注。只输出口播正文,不要小标题和 Markdown 记号。"
)


def build_market(market: str, items: list, quiet: bool = False) -> dict:
    m = MARKETS[market]
    cfg = load_cfg().get("morning", {})
    secs = int(cfg.get("script_seconds", 90))
    words = round(secs / 60 * 260)
    feed = sources.render_items(items)

    article = llm_complete(
        f"今天是 {today()},现在 {now_str()}。以下是最新的财经快讯素材:\n\n{feed}\n\n"
        f"请从中只筛选「{m['pick']}」的条目,排除「{m['exclude']}」,写一篇{m['name']}文章。\n"
        f"要求:{cfg.get('article_hint', '800-1200字,分板块,每条要闻带时间')}。\n"
        "结构建议:第一行一级标题(含「今日A股早报」或「今日港美股早报」字样和日期);"
        "然后按主题分二级标题板块(如 宏观与政策 / 行业与公司 / 今日关注),"
        "每条要闻用列表项并保留原始时间;结尾一小段「今日看点」收束。"
        "信息少的板块可以合并,不要为了凑板块注水。",
        system=SYS_ARTICLE,
    )

    script = llm_complete(
        f"以下是今天{m['name']}的成稿:\n\n{article}\n\n"
        f"请把它改写成约 {words} 字(对应约 {secs} 秒)的口播稿。",
        system=SYS_SCRIPT,
        max_tokens=1500,
    )

    stem = f"{m['name']}-{today()}"
    a_path = save_text(out_dir("articles_dir") / f"{stem}.md", article)
    s_path = save_text(out_dir("scripts_dir") / f"{stem}-口播.md",
                       f"# {stem} 口播稿(约{secs}秒)\n\n{script}\n")
    return {"article": a_path, "script": s_path}


def run(markets: str = "both") -> list:
    from common import llm_require_config
    llm_require_config()  # 先确认模型可用,再抓素材
    cfg = load_cfg()
    max_items = int(cfg.get("morning", {}).get("max_items", 60))
    items, failed = sources.gather(limit=max_items)
    if failed:
        print(f"⚠ 部分信息源不可用: {', '.join(failed)}")
    if not items:
        sys.exit("没有抓到任何快讯素材,请检查网络或信息源配置")
    print(f"已抓取 {len(items)} 条快讯(取最新 {max_items} 条)")

    todo = list(MARKETS) if markets == "both" else [markets]
    results = []
    for mk in todo:
        print(f"\n===== 生成 {MARKETS[mk]['name']} =====")
        r = build_market(mk, items)
        print(f"文章: {r['article']}")
        print(f"口播: {r['script']}")
        results.append(r)
    print("\n提示:文章已直接放入 autopub 待发目录,可用 `python autopub/publish_all.py --limit 1` 试发;口播稿在 generator/output/ 下,不进发布链路。")
    return results
