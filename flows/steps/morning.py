"""早报汇总步骤:抓四源早报(当日校验) → LLM 汇总分类(素材) → 按产出形式渲染(文章等)。"""

import json
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


# ---------- 解读标签(tag 步): LLM 出 JSON, 代码渲染插行 ----------

DIRECTIONS = ["利好", "利空", "中性", "承压", "关注"]


def _load_sectors(pack_dir: Path) -> list:
    """板块词表: 包内 sectors.yaml(单一来源, 用户可直接改)。"""
    import yaml
    f = Path(pack_dir) / "sectors.yaml"
    if not f.exists():
        sys.exit(f"缺少板块词表: {f}")
    groups = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("sectors") or []
    return [w for g in groups for w in g]


@step("tag_morning_items")
def tag_morning_items(ctx, wf, params):
    """成品文章 → 逐条「板块×方向」解读标签。
    LLM 只出结构化 JSON, 解析/校验/插行全部由代码完成(排版是构造性保证)。
    with: {enabled: true}。产出 tagged_path/tags_path。"""
    import daily
    from common import llm_complete
    if not params.get("enabled", True):
        print("解读标签未启用(--set tag_lines=false)")
        return {}
    article_p = ctx.get("article_path")
    if not article_p or not Path(article_p).exists():
        sys.exit("缺少文章产物(先跑 article 步骤)")
    article = Path(article_p).read_text(encoding="utf-8")
    material = ""
    mp = ctx.get("material_path")
    if mp and Path(mp).exists():
        material = Path(mp).read_text(encoding="utf-8")

    sectors = _load_sectors(wf.pack_dir)
    items, ann_zone = _index_items(article)          # 编号条目 + 公告区定位
    if not items:
        sys.exit("文章里没找到可打标的条目(格式异常?)")

    tpl = daily.load_prompt("morning_tags")
    if not tpl:
        sys.exit("缺少提示词 morning_tags")
    user = (tpl.replace("<<DATE>>", wf.date)
               .replace("<<ARTICLE>>", article)
               .replace("<<MATERIAL>>", material[:12000])
               .replace("<<SECTORS>>", "、".join(sectors)))
    system = daily.load_prompt("morning_tags_system",
                               "你是量化资讯编辑,只输出严格 JSON。")
    print(f"解读标签: {len(items)} 条正文条目 / 送模型 {len(user)} 字 ...")
    raw = llm_complete(user, system=system, max_tokens=4000, temperature=0.2)
    parsed, err = _parse_tags(raw, sectors, items)
    if err:
        print(f"⚠ JSON 校验失败({err}), 重试一次 ...")
        raw = llm_complete(user, system=system, max_tokens=4000, temperature=0.2)
        parsed, err = _parse_tags(raw, sectors, items)
    if err:
        print(f"⚠ 解读标签失败({err}), 降级发布无解读版")
        return {"tagged_path": article_p, "tag_error": err}

    tagged, report = _render_tags(article, items, ann_zone, parsed, sectors)
    # 备份无解读原稿 + 覆盖待发版
    raw_backup = wf.run_dir / f"article-raw-{wf.date}.md"
    raw_backup.write_text(article, encoding="utf-8")
    Path(article_p).write_text(tagged, encoding="utf-8")
    (wf.run_dir / f"tag-{wf.date}.json").write_text(
        json.dumps({"items": parsed, "lint": report}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"解读标签: {report['tagged']}/{len(items)} 条已标注 | 公告汇总: {report['ann_summary'] or '无'}")
    if report["fail"]:
        sys.exit(f"解读标签机检未过: {report['fail']}")
    return {"tagged_path": article_p, "tags_path": str(wf.run_dir / f"tag-{wf.date}.json"),
            "tag_report": report}


def _index_items(article: str):
    """给正文六分类条目编号。返回 ([{n,line,tag,text}], 公告区条目n列表)。"""
    items, ann = [], []
    zone = None
    for i, line in enumerate(article.splitlines()):
        m = re.match(r"^## (.+)", line)
        if m:
            zone = m.group(1).strip()
            continue
        m = re.match(r"^- \*\*([^*]+)\*\*：(.*)", line)
        if m and zone and zone != "今日焦点":
            n = len(items) + 1
            items.append({"n": n, "line": i, "tag": m.group(1), "text": m.group(2)})
            if zone == "公司公告":
                ann.append(n)
    return items, ann


def _parse_tags(raw: str, sectors: list, items: list):
    """解析+硬校验 LLM JSON。返回 (清理后的 items 映射, 错误)。"""
    import json as _j
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.S)            # 容错: 剥多余文本
    if not m:
        return None, "输出里没有 JSON"
    try:
        data = _j.loads(m.group(0))
    except Exception as e:
        return None, f"JSON 解析失败: {e}"
    valid_n = {it["n"] for it in items}
    secset, out = set(sectors), {}
    for o in data.get("items") or []:
        n = o.get("n")
        if not isinstance(n, int) or n not in valid_n:
            continue                                  # 越界编号直接丢弃
        dirs = []
        for d in o.get("dirs") or []:
            key = d.get("d")
            ss = [x for x in (d.get("s") or []) if x in secset]
            if key in DIRECTIONS and ss:
                dirs.append({"d": key, "s": ss[:3]})
        if dirs:
            out[n] = dirs
    if not out:
        return None, "无有效条目"
    return out, ""


def _render_tags(article: str, items: list, ann_zone: list,
                 parsed: dict, sectors: list):
    """渲染插行(构造性保证格式)。免标规则在此代码侧兜底过滤。"""
    lines = article.splitlines()
    by_tag = {it["n"]: it for it in items}
    fail, warn = [], []
    inserts = {}          # line_idx -> [解读行...]
    used_dirs = []
    ann_sector_count = {}
    for n, dirs in sorted(parsed.items()):
        it = by_tag[n]
        # 免标兜底: 行情条/传闻条不给方向; 地缘条只允许降格词
        if it["tag"] == "行情":
            warn.append(f"#{n} 行情条被过滤"); continue
        if re.search(r"据报|被曝|据报道|消息人士", it["text"]):
            warn.append(f"#{n} 传闻条被过滤"); continue
        if it["tag"] == "地缘":
            dirs = [d for d in dirs if d["d"] in ("中性", "承压", "关注")] or None
            if dirs is None:
                continue
        if it["n"] in ann_zone:
            for d in dirs:                            # 公告条: 收热度, 非中性才逐条渲染
                for s in d["s"]:
                    ann_sector_count[s] = ann_sector_count.get(s, 0) + 1
                if d["d"] == "中性":
                    dirs = [x for x in dirs if x["d"] != "中性"]
            if not dirs:
                continue
        rows = [f"  ↳ {d['d']}：{'、'.join(d['s'])}" for d in dirs
                if d["d"] in DIRECTIONS]
        if rows:
            inserts.setdefault(it["line"], []).extend(rows)
            used_dirs.extend(d["d"] for d in dirs)
    # 公告区汇总行: 插在公告区最后一条(含其解读行)之后
    if ann_sector_count:
        top = sorted(ann_sector_count.items(), key=lambda x: -x[1])[:6]
        summary = "、".join(f"{s}×{c}" for s, c in top)
        last_ann = max(by_tag[n]["line"] for n in ann_zone if n in by_tag)
        inserts.setdefault(last_ann, []).append(f"  ↳ 今日公告热度：{summary}")
    # 免责升级: 覆盖板块方向归类(合规配套)
    for i in range(len(lines) - 1, -1, -1):
        if "投资建议" in lines[i]:
            lines[i] = ("本文基于公开信息整理,板块影响标注仅为对消息面的客观归类,"
                        "不代表对任何证券或板块走势的预测,不构成投资建议。"
                        "市场有风险,投资需谨慎。")
            break
    # 倒序插行
    for idx in sorted(inserts, reverse=True):
        lines[idx + 1:idx + 1] = inserts[idx]
    # 比例监控
    n_dir = len([d for d in used_dirs if d in ("利好", "利空")])
    if n_dir:
        bull = used_dirs.count("利好") / n_dir
        if bull > 0.8 or bull < 0.3:
            warn.append(f"方向比例失衡: 利好占 {bull:.0%}, 请人工复核")
    report = {"tagged": len(inserts), "fail": fail, "warn": warn,
              "ann_summary": "、".join(f"{s}×{c}" for s, c in
                                       sorted(ann_sector_count.items(), key=lambda x: -x[1])[:4])}
    return chr(10).join(lines) + chr(10), report


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