"""多形态产出步骤:长图卡片 / 群发模板 / 同行式早报文章(含日历/外围/公告板块)。"""

from flows.steps import step


@step("render_formats")
def render_formats(ctx, wf, params):
    """依赖 ctx['extras'](fetch_extras 产物)。产出长图/群发/早报文章路径。"""
    import formats
    r = formats.run_all(wf.date, ctx.get("extras"))
    print(f"长图: {r['image']}\n群发: {r['group']}\n早报文章: {r['article']}")
    return {k: str(v) for k, v in r.items()}
