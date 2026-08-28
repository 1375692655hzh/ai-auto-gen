"""精排步骤:粗筛 + LLM 选条。"""

from flows.steps import step


@step("rank_items")
def rank_items(ctx, wf, params):
    """with: {items: N}(默认取 config daily.items)。产出 ranked。"""
    import daily
    items = int(params.get("items") or 0) or int(_cfg_daily_items())
    coarse = daily.coarse_filter(ctx["items"])
    print(f"粗筛: {len(ctx['items'])} → {len(coarse)} 条")
    ranked = daily.rank_items(coarse, items)
    print(f"精排入选 {len(ranked)} 条")
    return {"coarse_count": len(coarse), "ranked": ranked}


def _cfg_daily_items():
    import common
    return common.load_cfg().get("daily", {}).get("items", 15)
