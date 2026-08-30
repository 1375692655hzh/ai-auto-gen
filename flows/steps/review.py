"""大盘复盘步骤(market-review 工作流): 盘面数据归集 → LLM 复盘合成 → 成品渲染。

结构移植自 sunny-kobe/daily_stock_analysis 的大盘复盘(盘面信号分数/板块Top/三日线索/
明日观察/风险提示), 按发布内容定位改造: 只写观察不写买卖建议(我们不是投顾)。
数字约束同生成链铁律: LLM 输出数字必须逐字来自素材。
"""

import datetime

from flows.steps import step

_REGION_NAMES = {"hk": {"恒生指数", "恒生科技"},
                 "us": {"道琼斯", "纳斯达克", "标普500"},
                 "jp": {"日经225"}}


@step("review_data")
def review_data(ctx, wf, params):
    """with: {region: cn|hk|us|jp|all}。产出 review_material(指数/板块/近三日线索)。"""
    region = str(params.get("region") or "cn").lower()
    material = {"region": region, "indices": [], "sectors": None, "clues": []}

    import sources as gs
    if region in ("cn", "all"):
        try:
            material["indices"] += gs.fetch_cn_index_snapshot()
        except Exception as e:
            print(f"  ⚠ A股指数失败({type(e).__name__}: {str(e)[:60]})")
    if region != "cn":
        import extra_sources as ges
        try:
            gm = ges.fetch_global_markets()
            keep = None if region == "all" else _REGION_NAMES.get(region, set())
            material["indices"] += [x for x in gm if keep is None or x["name"] in keep]
        except Exception as e:
            print(f"  ⚠ 外围指数失败({type(e).__name__}: {str(e)[:60]})")

    if region in ("cn", "all"):
        try:
            material["sectors"] = gs.fetch_em_sector_board()
        except Exception as e:
            print(f"  ⚠ 板块榜失败({type(e).__name__}: {str(e)[:60]})")

    # 近三日线索: fetch_news 抓的快讯池按时间窗过滤(含当日往前共 3 个自然日)
    day = datetime.date.fromisoformat(str(wf.date))
    cutoff = (day - datetime.timedelta(days=2)).isoformat()
    for it in ctx.get("items", []):
        if (it.get("time") or "")[:10] >= cutoff:
            material["clues"].append({"time": it.get("time", ""), "source": it.get("source", ""),
                                      "text": (it.get("text") or "")[:120],
                                      "url": it.get("url", "")})
    material["clues"] = material["clues"][-60:]     # 最多最近 60 条, 防 prompt 膨胀

    if not material["indices"] and not material["sectors"]:
        raise RuntimeError("复盘素材为空: 指数与板块全失败(故障冒泡, 不静默降级)")
    print(f"  复盘素材: 指数 {len(material['indices'])} | "
          f"板块 {'✓' if material['sectors'] else '✗'} | 线索 {len(material['clues'])} 条")
    return {"review_material": material}


@step("review_synth")
def review_synth(ctx, wf, params):
    """with: {model}。LLM 合成复盘 markdown, 产出 review_md。"""
    from common import gen_llm
    m = ctx["review_material"]
    idx_lines = "\n".join(f"- {x['name']}: {x['price']} ({x['chg_pct']})" for x in m["indices"])
    sec_lines = ""
    if m["sectors"]:
        import sources as gs
        sec_lines = "\n".join(f"- {x['text']}" for x in gs.sector_board_text(m["sectors"]))
    clue_lines = "\n".join(f"- [{c['time']}|{c['source']}] {c['text']}" for c in m["clues"])

    user = f"""日期: {wf.date}  市场: {m['region']}

【指数明细】
{idx_lines or '(无)'}

【板块涨跌榜】
{sec_lines or '(无)'}

【近三日市场线索(快讯池)】
{clue_lines or '(无)'}

按以下结构写大盘复盘(markdown):
# 大盘复盘 {wf.date}
## 盘面信号
NN/100(偏暖/中性/偏冷, 一句理由) —— 分数由你基于指数涨跌与板块涨跌家数给出, 纯文本表达
## 指数明细
表格呈现
## 板块风向
领涨/领跌各一段, 点出板块名与涨跌幅
## 近三日市场线索
3-6 条, 每条一行: 事件——来源
## 明日观察
3-5 点, 只写值得观察的事件/数据/时点
## 风险提示
2-3 点"""
    system = ("你是财经内容编辑, 为公众号读者写盘后复盘。铁律: ①所有数字/板块名/事件必须逐字来自素材, "
              "不得编造或换算; ②只写观察与风险, 禁止任何买卖建议、目标价、仓位指导(我们是内容号不是投顾); "
              "③素材里没有的板块/事件不写; ④盘面信号分数必须有, 且只给一句理由。")
    md = gen_llm(str(params.get("model", "")), user, system, 6000, 0.3)
    if "盘面信号" not in md:
        raise RuntimeError("复盘合成缺「盘面信号」段(格式异常, 故障冒泡)")
    return {"review_md": md}


@step("review_render")
def review_render(ctx, wf, params):
    """成品落盘 articles_dir(待发队列)。← 审核点: 人工确认后再续跑。"""
    from common import out_dir, save_text
    region = ctx["review_material"]["region"]
    path = save_text(out_dir("articles_dir") / f"大盘复盘-{wf.date}-{region}.md", ctx["review_md"])
    print(f"复盘成品: {path}")
    return {"review_path": str(path)}
