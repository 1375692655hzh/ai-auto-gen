"""早报汇总步骤:抓四源早报(当日校验) → LLM 汇总分类(素材) → 按产出形式渲染(文章等)。"""

import re
import sys
from pathlib import Path

from flows.steps import step


@step("fetch_morning_reports")
def fetch_morning_reports(ctx, wf, params):
    """四份早报源: 富途/财联社/gangtise(元宝兜底) 走 peers 聚合 + 华尔街见闻单独。
    只保留「今天」发布的早报(防昨日早报被当今日素材误发), 非当日源计入 failed。
    with: {wscn_count: 2, allow_stale: false}。产出 reports(list)/failed。"""
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

    if not params.get("allow_stale"):
        fresh, stale = [], []
        for r in refs:
            t = (r.get("time") or "").strip()[:10]
            (fresh if t == wf.date else stale).append(r)
        for r in stale:
            failed.append(f"{r.get('source')}({t and '非当日' or '无时间'}: {t or '?'}, "
                          f"预计发布时间未到或源异常)")
        if not fresh:
            sys.exit(f"没有当日({wf.date})早报, 拒绝用旧素材合成(强跑加 --set allow_stale=true)。"
                     f"缺: {', '.join(failed)}")
        refs = fresh

    ok_names = "、".join(r.get("source", "?") for r in refs)
    print(f"当日早报源就绪 {len(refs)} 份: {ok_names}"
          + (f" | 缺: {', '.join(failed)}" if failed else ""))
    return {"reports": refs, "failed": failed}


@step("synthesize_morning")
def synthesize_morning(ctx, wf, params):
    """LLM 汇总分类, 产出「知识素材」(带来源标注的完整底稿, 存 run_dir 不进发布队列)。
    提示词: 包内 prompts/morning_synth.md(必须存在, 缺失即报错——防格式静默降级)。"""
    import daily
    from common import llm_complete
    date, reports = wf.date, ctx.get("reports", [])
    per = int(params.get("per_report_chars", 6000))

    feed = "\n\n".join(
        f"【{r.get('source') or r.get('media', '?')}】《{r.get('title', '')}》"
        f"({r.get('time', '')})\n{(r.get('text') or '')[:per]}"
        for r in reports)

    tpl = daily.load_prompt("morning_synth")
    if not tpl:
        sys.exit("缺少提示词 morning_synth(包内 prompts/ 或全局 flows/prompts/ 必须提供)")
    user = tpl.replace("<<DATE>>", date).replace("<<REPORTS>>", feed)
    system = daily.load_prompt(
        "morning_synth_system", "你是资深财经早报编辑,只输出 Markdown 正文,不加解释。")

    print(f"汇总素材: {len(reports)} 份早报 / 送模型 {len(user)} 字 ...")
    material = llm_complete(user, system=system, max_tokens=8000, temperature=0.3)
    _check_complete(material, "素材")
    path = wf.run_dir / f"material-{date}.md"
    path.write_text(material.rstrip() + "\n", encoding="utf-8")
    print(f"知识素材: {path} ({len(material)}字)")
    return {"material_path": str(path), "material_chars": len(material)}


@step("render_morning_article")
def render_morning_article(ctx, wf, params):
    """素材 → 早报文章(面向读者的成品): 每条「标签:详情」精炼格式、去来源标注, 进待发队列。
    提示词: 包内 prompts/morning_article.md(必须存在)。产出 article_path。"""
    import daily
    from common import llm_complete, out_dir, save_text
    date = wf.date
    material = ctx.get("material_path")
    if not material or not Path(material).exists():
        sys.exit("缺少素材(先跑 synth 步骤)")
    content = Path(material).read_text(encoding="utf-8")

    tpl = daily.load_prompt("morning_article")
    if not tpl:
        sys.exit("缺少提示词 morning_article(包内 prompts/ 必须提供)")
    user = tpl.replace("<<DATE>>", date).replace("<<MATERIAL>>", content)
    system = daily.load_prompt(
        "morning_article_system", "你是资深财经早报编辑,只输出 Markdown 正文,不加解释。")

    print(f"渲染文章: 素材 {len(content)} 字 → 精炼改写 ...")
    md = llm_complete(user, system=system, max_tokens=6500, temperature=0.3)
    _check_complete(md, "文章")
    report = _lint_article(md)
    path = save_text(out_dir("articles_dir") / f"早报文章-{date}.md", md)
    print(f"早报文章: {path} ({len(md)}字)")
    if report["fail"]:
        sys.exit(f"文章机检未过: {report['fail']} (产物已存 {path}, 修提示词后 --from article 重跑)")
    return {"article_path": str(path), "article_chars": len(md),
            "lint": {"items": report["items"], "short": report["short"],
                     "bad_tags": report["bad_tags"]}}


# ---------- 校验与机检 ----------

def _check_complete(text: str, what: str) -> None:
    """完整性: 长度下限 + 必须以免责声明收尾(截断会让结尾消失)。"""
    if len(text) < 300:
        sys.exit(f"{what}输出过短({len(text)}字), 疑似异常:\n{text[:300]}")
    if "投资建议" not in text[-120:]:
        sys.exit(f"{what}结尾缺少免责声明——疑似 LLM 输出被截断, "
                 "检查 max_tokens 或素材长度后重跑")


TAGS = ["注意", "地缘", "政策", "数据", "公司", "概念", "行情", "事件"]


def _lint_article(md: str) -> dict:
    """成品机检: 标签白名单/全角冒号/来源残留/字数分布。fail 列表非空=阻断。"""
    items = re.findall(r"^- \*\*([^*]+)\*\*([：:])(.*)$", md, re.M)
    bare = len(re.findall(r"^\*\*[^*]+\*\*[：:]", md, re.M))   # 丢了「- 」前缀的条目
    bad_tags = [t for t, _, _ in items if t not in TAGS]
    half_colon = [t for t, c, _ in items if c != "："]
    src_leak = len(re.findall(r"\[(?:财联社|富途|见闻|Gangtise)", md))
    lens = [len(t) + 1 + len(b.strip()) for t, _, b in items]
    short = sum(1 for n in lens if n < 40)          # 下限放宽到 40(公告一行题可短)
    over = sum(1 for n in lens if n > 110)
    fail = []
    if bare:
        pass                       # bare 已在上面收集, 统一在此入 fail
    if bare:
        fail.append(f"条目缺少「- 」列表前缀: {bare} 条")
    if bad_tags:
        fail.append(f"标签白名单外: {bad_tags[:5]}")
    if half_colon:
        fail.append(f"半角冒号条目: {len(half_colon)}")
    if src_leak:
        fail.append(f"来源标注残留: {src_leak} 处")
    print(f"机检: {len(items)} 条 | 标签分布 " +
          " ".join(f"{t}:{sum(1 for x,_,_ in items if x==t)}" for t in TAGS
                   if any(x == t for x, _, _ in items)) +
          f" | <40字 {short} 条, >110字 {over} 条")
    return {"items": len(items), "short": short, "over": over,
            "bad_tags": bad_tags, "fail": fail}
