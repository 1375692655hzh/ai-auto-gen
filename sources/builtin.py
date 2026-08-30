"""来源注册:包装 generator 现有抓取函数为标准来源(P1 包装不重写)。

物理迁移(函数搬到本包、generator 留 shim)在后续阶段做——
注册 id 与语义已稳定,届时不影响调用方。

kind: flash 快讯 | peer_article 同行早报 | calendar 日历 | market 行情 | announcement 公告
      peer_group/extras_group 聚合来源(morning_paper 工作流直接调用,不进 gather)
"""

import sys
import importlib.util
from pathlib import Path

_GEN = Path(__file__).resolve().parent.parent / "generator"
if str(_GEN) not in sys.path:
    sys.path.insert(0, str(_GEN))          # extra_sources 内部 `from search import ...` 需要


def _load(alias: str, path: Path):
    """按路径加载 generator 同名模块(本包也叫 sources, 不能直接 import sources)。"""
    spec = importlib.util.spec_from_file_location(alias, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


gs = _load("gen_sources", _GEN / "sources.py")          # generator/sources.py
ges = _load("gen_extra_sources", _GEN / "extra_sources.py")

from sources.base import source            # noqa: E402


# ---------- 快讯(gather 主力) ----------

@source("sina_7x24", "flash", "新浪财经7×24", ttl_min=10, default_enabled=True)
def _sina(conf):
    return gs.fetch_sina_724(int(conf.get("page_size", 100)))


@source("eastmoney_fast", "flash", "东财财经快讯", ttl_min=10, default_enabled=True)
def _em_fast(conf):
    return gs.fetch_eastmoney_fast(int(conf.get("page_size", 50)))


@source("jin10_flash", "flash", "金十数据快讯(全球,秒级时间戳)", ttl_min=10, default_enabled=True)
def _jin10(conf):
    return gs.fetch_jin10_flash(int(conf.get("page_size", 50)))


# ---------- 同行早报文章(gather_refs) ----------

@source("eastmoney_zaozhidao", "peer_article", "东财搜索《早知道》系列", ttl_min=120,
        default_enabled=True)
def _zaozhidao(conf):
    return gs.fetch_eastmoney_zaozhidao(conf.get("keywords"))


@source("wscn_breakfast", "peer_article", "华尔街见闻早餐", ttl_min=120, default_enabled=True)
def _wscn(conf):
    return gs.fetch_wscn_breakfast(int(conf.get("count", 2)))


@source("futu_morning", "peer_article", "富途《港美早报》", risk="medium", ttl_min=120)
def _futu(conf):
    r = ges.fetch_futu_morning()
    return [r] if r else []


@source("cls_morning", "peer_article", "财联社有声早报(专栏1151, 每日07:00)", ttl_min=120)
def _cls(conf):
    r = ges.fetch_cls_morning()
    return [r] if r else []


@source("aa_morning", "peer_article", "AA安纳多卢通讯社英文晨报", ttl_min=120)
def _aa(conf):
    r = ges.fetch_aa_morning()
    return [r] if r else []


@source("turkey_morning", "peer_article", "BloombergHT土耳其市场", risk="medium", ttl_min=120)
def _turkey(conf):
    r = ges.fetch_turkey_morning()
    return [r] if r else []


@source("cnbc_morning", "peer_article", "CNBC Daily Open美股晨报(工作日)", ttl_min=120)
def _cnbc(conf):
    r = ges.fetch_cnbc_morning()
    return [r] if r else []


@source("japan_morning", "peer_article", "共同社日本市场精选(当日RSS过滤)", ttl_min=60)
def _japan(conf):
    r = ges.fetch_japan_morning()
    return [r] if r else []


@source("korea_morning", "peer_article", "韩联社韩国市场精选(当日RSS过滤)", ttl_min=60)
def _korea(conf):
    r = ges.fetch_korea_morning()
    return [r] if r else []


@source("em_research", "peer_article", "东财研报中心机构观点索引(晨会/宏观/策略)", ttl_min=120)
def _emr(conf):
    r = ges.fetch_em_research()
    return [r] if r else []


@source("sina_vip", "peer_article", "新浪意见领袖(首席经济学家/大V观点)", ttl_min=60)
def _svip(conf):
    r = ges.fetch_sina_vip()
    return [r] if r else []


@source("cnyes_tw", "peer_article", "鉅亨网台股精选(当日, 周末照常)", ttl_min=60)
def _cnyes(conf):
    r = ges.fetch_cnyes_tw()
    return [r] if r else []


@source("etnet_open", "peer_article", "etnet經濟通開市Go港股晨报(工作日08:30)", ttl_min=120)
def _etnet(conf):
    r = ges.fetch_etnet_open()
    return [r] if r else []


@source("newsquawk_open", "peer_article", "Newsquawk欧美市场开盘综述(交易日午后/傍晚)", ttl_min=120)
def _nq(conf):
    r = ges.fetch_newsquawk_open()
    return [r] if r else []


@source("gangtise", "peer_article", "Gangtise投研日报(搜狗微信链)", risk="high", ttl_min=120)
def _gangtise(conf):
    r = ges.fetch_gangtise()
    return [r] if r else []


@source("yuanbao_gangtise", "peer_article",
        "元宝取Gangtise投研日报(Playwright登录态, gangtise 的可靠替代)",
        risk="high", auth="browser_profile", ttl_min=120)
def _yuanbao(conf):
    """元宝网页版对话抓当日 gangtise 日报全文; 首次需 py -3.11 generator/yuanbao_fetch.py --login 扫码。"""
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "generator" / "yuanbao_fetch.py"
    spec = importlib.util.spec_from_file_location("yuanbao_fetch_mod", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["yuanbao_fetch_mod"] = mod
    spec.loader.exec_module(mod)
    r = mod.run()
    if not r.get("ok"):
        raise RuntimeError(r.get("error") or "元宝返回失败(未登录? 先跑 yuanbao_fetch.py --login)")
    return [{"time": r.get("date", ""), "title": f"Gangtise投研日报(元宝镜像 {r.get('date','')})",
             "text": (r.get("text") or "")[:12000], "media": "元宝/Gangtise",
             "url": r.get("article_url") or "", "source": "元宝·Gangtise"}]


# ---------- 版式素材(日历/外围行情/公告) ----------

@source("calendar", "calendar", "财经日历(今日事件)", ttl_min=120)
def _calendar(conf):
    return ges.fetch_calendar()


@source("global_markets", "market", "全球市场行情摘要", ttl_min=30)
def _markets(conf):
    return ges.fetch_global_markets()


@source("cls_announcements", "announcement", "财联社重点公告", ttl_min=30)
def _ann(conf):
    return ges.fetch_cls_announcements(int(conf.get("limit", 15)))


# ---------- 聚合来源(工作流直接调用, 仅供 aag sources fetch 手动取用) ----------

@source("peer_mornings", "peer_group", "同行早报聚合(富途+财联社+AA+BHT+CNBC+日韩台+etnet+gangtise)", ttl_min=120)
def _peers(conf):
    items, failed = ges.fetch_peer_mornings()
    if failed:
        # 聚合内部单源失败已有降级; 把失败信息附在 extra 里便于排查
        for it in items:
            it.setdefault("extra", {})
    return items


@source("extras", "extras_group", "版式素材聚合(日历+行情+公告+同行)", ttl_min=60)
def _extras(conf):
    return [ges.fetch_extras()]
