"""早报汇总步骤:抓四源早报 → LLM 汇总分类 → 合成一篇早报文章。"""

import sys
from pathlib import Path

from flows.steps import step


@step("fetch_morning_reports")
def fetch_morning_reports(ctx, wf, params):
    """四份早报源: 富途/财联社/gangtise(元宝兜底) 走 peers 聚合 + 华尔街见闻单独。
    with: {wscn_count: 2}。产出 reports(list)/failed。"""
    import extra_sources
    import sources as gs        # generator/sources.py(fetch_wscn_breakfast 在这)
    refs, failed = extra_sources.fetch_peer_mornings()
    try:
        wscn = gs.fetch_wscn_breakfast(int(params.get("wscn_count", 2)))
        refs.extend(wscn)
        if not wscn:
            failed.append("华尔街见闻早餐(空结果)")
    except Exception as e:
        failed.append(f"华尔街见闻早餐({type(e).__name__}: {str(e)[:60]})")
    if not refs:
        sys.exit("四份早报源全部失败, 无素材可合成")
    ok_names = "、".join(r.get("source", "?") for r in refs)
    print(f"早报源就绪 {len(refs)} 份: {ok_names}"
          + (f" | 缺: {', '.join(failed)}" if failed else ""))
    return {"reports": refs, "failed": failed}


@step("synthesize_morning")
def synthesize_morning(ctx, wf, params):
    """LLM 汇总分类合成早报文章。提示词: 包内 prompts/morning_synth.md(可改)。
    with: {per_report_chars: 4000}。产出 article_path。"""
    import daily                       # load_prompt 走它的外置机制(包内注入已就绪)
    from common import llm_complete, out_dir, save_text
    date, reports = wf.date, ctx.get("reports", [])
    per = int(params.get("per_report_chars", 4000))

    feed = "\n\n".join(
        f"【{r.get('source') or r.get('media', '?')}】《{r.get('title', '')}》"
        f"({r.get('time', '')})\n{(r.get('text') or '')[:per]}"
        for r in reports)

    tpl = daily.load_prompt("morning_synth")
    if not tpl:
        tpl = _DEFAULT_PROMPT
    user = tpl.replace("<<DATE>>", date).replace("<<REPORTS>>", feed)
    system = daily.load_prompt(
        "morning_synth_system", "你是资深财经早报编辑,只输出 Markdown 正文,不加解释。")

    print(f"合成中: {len(reports)} 份早报 / 送模型 {len(user)} 字 ...")
    md = llm_complete(user, system=system, max_tokens=6000, temperature=0.3)
    if len(md) < 300:
        sys.exit(f"合成输出过短({len(md)}字), 疑似异常:\n{md[:300]}")
    path = save_text(out_dir("articles_dir") / f"早报汇总-{date}.md", md)
    print(f"早报文章: {path} ({len(md)}字)")
    return {"article_path": str(path), "article_chars": len(md)}


_DEFAULT_PROMPT = (
    "今天是 <<DATE>>。以下是四份同行早报的全文,请汇总合成一篇我们自己的早报文章。\n\n"
    "<<REPORTS>>\n\n"
    "要求:\n"
    "1. 先通读全部材料,合并同一事件的不同报道(交叉印证的数字以更权威来源为准,"
    "标注所有涉及来源,如 [财联社|见闻])。\n"
    "2. 按分类组织:宏观政策 / 公司动态 / 行业产业 / 海外市场 / 大宗商品,"
    "空分类跳过;每类下按重要性排序。\n"
    "3. 开头是「今日焦点」: 全天最重要的 3 件事, 每件一句话。\n"
    "4. 每条要闻格式: **一句话标题** + 1-3 句要点(保留关键数字/价格/涨跌幅,"
    "数字必须逐字来自材料) + 行尾来源标注。\n"
    "5. 结尾固定一句免责声明。\n"
    "6. 标题第一行: # AI财经早报 | <<DATE>>,风格简洁、信息密度高,禁止买卖建议。"
)
