"""抓取步骤:快讯 + 同行早报 + 版式素材(免 LLM)。"""

import re
import sys

from flows.steps import step


@step("fetch_news")
def fetch_news(ctx, wf, params):
    """快讯(gather) + 同行早报(gather_refs + 富途/财联社/gangtise 聚合)。
    源选取(用户定): --set peer_sources=鉅亨台股,SMM大宗商品 只抓指定早报源;
    --set flash_sources=jin10_flash,investinglive_flash 只抓指定快讯源。空=全部。"""
    import sources
    import extra_sources
    flash_only = _split(params.get("flash_sources"))
    if flash_only:
        cfg = {sid: {"enabled": sid in flash_only}
               for sid, e in sources.REGISTRY.items() if e["meta"]["kind"] == "flash"}
        items, failed = sources.gather(cfg)
    else:
        items, failed = sources.gather()
    refs, ref_failed = sources.gather_refs()
    if failed or ref_failed:
        print(f"⚠ 不可用来源: {', '.join(failed + ref_failed)}")
    peers, peer_failed = extra_sources.fetch_peer_mornings(only=_split(params.get("peer_sources")))
    refs = peers + refs
    if peer_failed:
        print(f"⚠ 同行早报缺失: {', '.join(peer_failed)}")
    if not items:
        sys.exit("没有抓到快讯")
    print(f"抓取: 快讯 {len(items)} 条 + 同行早报 {len(refs)} 篇")
    return {"items": items, "refs": refs}


def _split(v) -> list:
    """逗号/空白分隔的源名参数 → 列表; 空= None(不选取, 全部)。"""
    s = str(v or "").strip()
    return ([x for x in re.split(r"[,，\s]+", s) if x] or None) if s else None


@step("fetch_extras")
def fetch_extras(ctx, wf, params):
    """版式素材:财经日历/外围市场/重点公告(长图与早报文章的板块数据)。"""
    import extra_sources
    return {"extras": extra_sources.fetch_extras()}
