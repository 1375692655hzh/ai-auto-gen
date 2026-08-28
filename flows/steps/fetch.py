"""抓取步骤:快讯 + 同行早报 + 版式素材(免 LLM)。"""

import sys

from flows.steps import step


@step("fetch_news")
def fetch_news(ctx, wf, params):
    """快讯(gather) + 同行早报(gather_refs + 富途/财联社/gangtise 聚合)。"""
    import sources
    import extra_sources
    items, failed = sources.gather()
    refs, ref_failed = sources.gather_refs()
    if failed or ref_failed:
        print(f"⚠ 不可用来源: {', '.join(failed + ref_failed)}")
    peers, peer_failed = extra_sources.fetch_peer_mornings()
    refs = peers + refs
    if peer_failed:
        print(f"⚠ 同行早报缺失: {', '.join(peer_failed)}")
    if not items:
        sys.exit("没有抓到快讯")
    print(f"抓取: 快讯 {len(items)} 条 + 同行早报 {len(refs)} 篇")
    return {"items": items, "refs": refs}


@step("fetch_extras")
def fetch_extras(ctx, wf, params):
    """版式素材:财经日历/外围市场/重点公告(长图与早报文章的板块数据)。"""
    import extra_sources
    return {"extras": extra_sources.fetch_extras()}
