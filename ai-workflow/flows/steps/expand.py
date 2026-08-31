"""扩写步骤:逐条联网取证+扩写+AI解读+数字校验(并行,最贵的一步,单条失败降级)。"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from flows.steps import step


@step("expand_entries")
def expand_entries(ctx, wf, params):
    """with: {workers: 2}。产出 entries(按分类排序)。"""
    import daily
    ranked, refs = ctx["ranked"], ctx["refs"]
    workers = int(params.get("workers", 2))
    model = str(params.get("model", ""))

    def work(it):
        ev = daily.collect_evidence(it, refs)
        try:
            d = daily.expand_item(it, ev, model=model)
        except Exception as ex:
            print(f"  ⚠ 「{it['rank_title'][:16]}」扩写失败({type(ex).__name__}),降级为仅摘要")
            d = {"title": it["rank_title"], "summary": it["text"][:60],
                 "detail_paragraphs": [], "sectors": [], "concepts": [],
                 "direction": "中性", "impact": "", "needs_review": False}
        it.update(d)
        it["evidence_urls"] = ev["urls"]
        it["source_name"] = it["source"]
        return it

    entries = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(work, it): it for it in ranked}
        for f in as_completed(futs):
            entries.append(f.result())
    order = {c: i for i, c in enumerate(daily.CATEGORIES)}
    entries.sort(key=lambda x: order.get(x["category"], 9))
    flagged = sum(1 for e in entries if e.get("needs_review"))
    if flagged:
        print(f"⚠ {flagged} 条数字校验未过(已保留待人工复核)")
    return {"entries": entries}
