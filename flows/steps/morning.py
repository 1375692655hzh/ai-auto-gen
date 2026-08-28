"""早报汇总步骤:抓四源早报 → LLM 汇总分类(素材) → 按产出形式渲染(文章等)。"""

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
    """LLM 汇总分类, 产出「知识素材」(带来源标注的完整底稿, 存 run_dir 不进发布队列)。
    提示词: 包内 prompts/morning_synth.md。产出 material_path。"""
    import daily
    from common import llm_complete
    date, reports = wf.date, ctx.get("reports", [])
    per = int(params.get("per_report_chars", 4000))

    feed = "\n\n".join(
        f"【{r.get('source') or r.get('media', '?')}】《{r.get('title', '')}》"
        f"({r.get('time', '')})\n{(r.get('text') or '')[:per]}"
        for r in reports)

    tpl = daily.load_prompt("morning_synth")
    if not tpl:
        tpl = _DEFAULT_SYNTH
    user = tpl.replace("<<DATE>>", date).replace("<<REPORTS>>", feed)
    system = daily.load_prompt(
        "morning_synth_system", "你是资深财经早报编辑,只输出 Markdown 正文,不加解释。")

    print(f"汇总素材: {len(reports)} 份早报 / 送模型 {len(user)} 字 ...")
    material = llm_complete(user, system=system, max_tokens=6000, temperature=0.3)
    if len(material) < 300:
        sys.exit(f"汇总输出过短({len(material)}字), 疑似异常:\n{material[:300]}")
    path = wf.run_dir / f"material-{date}.md"
    path.write_text(material.rstrip() + "\n", encoding="utf-8")
    print(f"知识素材: {path} ({len(material)}字)")
    return {"material_path": str(path), "material_chars": len(material)}


@step("render_morning_article")
def render_morning_article(ctx, wf, params):
    """素材 → 早报文章(面向读者的成品): 每条精炼控字数、去来源标注, 进待发队列。
    提示词: 包内 prompts/morning_article.md。产出 article_path。"""
    import daily
    from common import llm_complete, out_dir, save_text
    date = wf.date
    material = ctx.get("material_path")
    if not material or not Path(material).exists():
        sys.exit("缺少素材(先跑 synth 步骤)")
    content = Path(material).read_text(encoding="utf-8")

    tpl = daily.load_prompt("morning_article")
    if not tpl:
        tpl = _DEFAULT_ARTICLE
    user = tpl.replace("<<DATE>>", date).replace("<<MATERIAL>>", content)
    system = daily.load_prompt(
        "morning_article_system", "你是资深财经早报编辑,只输出 Markdown 正文,不加解释。")

    print(f"渲染文章: 素材 {len(content)} 字 → 精炼改写 ...")
    md = llm_complete(user, system=system, max_tokens=5000, temperature=0.3)
    if len(md) < 300:
        sys.exit(f"文章输出过短({len(md)}字), 疑似异常:\n{md[:300]}")
    path = save_text(out_dir("articles_dir") / f"早报文章-{date}.md", md)
    print(f"早报文章: {path} ({len(md)}字)")
    return {"article_path": str(path), "article_chars": len(md)}


_DEFAULT_SYNTH = (
    "今天是 <<DATE>>。以下是四份同行早报的全文,请汇总合成一份带来源标注的知识素材底稿。\n\n"
    "<<REPORTS>>\n\n"
    "要求:合并同事件多源报道并标注来源;按 宏观政策/公司动态/行业产业/海外市场/大宗商品/公司公告(最后) "
    "六类组织;每条 **标题**+要点(保留数字)+行尾来源标注;开头「今日焦点」3 件;结尾免责声明。"
)

_DEFAULT_ARTICLE = (
    "今天是 <<DATE>>。以下是一份带来源标注的早报知识素材,请把它改写成面向读者的早报文章。\n\n"
    "<<MATERIAL>>\n\n"
    "要求:删除所有来源标注;每条信息优化内容与字数——**一句话标题**+最多2句要点,"
    "每条总长控制在 60-100 字,只保留最有信息量的数字;分类顺序与素材一致"
    "(公司公告仍放最后);保留「今日焦点」3 件;标题 # AI财经早报 | <<DATE>>;"
    "结尾一句免责声明。风格干净利落,禁止买卖建议。"
)
