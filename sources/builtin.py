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


@source("fxstreet_flash", "flash", "FXStreet外汇央行快讯(英文, 2026-08-30起出口IP被Cloudflare整站403, 待恢复)",
        ttl_min=10, default_enabled=False)
def _fxstreet(conf):
    return gs.fetch_fxstreet_flash(int(conf.get("page_size", 30)))


@source("investinglive_flash", "flash", "investingLive外汇/美股/宏观快讯(英文, 原ForexLive, FXStreet同赛道顶替)",
        ttl_min=10, default_enabled=True)
def _ilive(conf):
    return gs.fetch_investinglive_flash(int(conf.get("page_size", 30)))


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


@source("smm_metals", "peer_article", "SMM上海有色网大宗商品日报(隔夜行情等系列, 资产类别源)", ttl_min=120)
def _smm(conf):
    r = ges.fetch_smm_metals()
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

@source("peer_mornings", "peer_group", "同行早报聚合(富途+财联社+AA+BHT+CNBC+日韩台+etnet+SMM+gangtise)", ttl_min=120)
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


# ---------- 备用源(public-apis 名录收录 2026-08-30) ----------
# 模型: 能跑通的在册即可用(default_enabled=True); 需 key 的配好 key 后把 default_enabled 翻开。
# 工作流层用 --set peer_sources=/flash_sources= 按名选取源, 不靠禁用开关做排除。

@source("marketaux_news", "flash", "备用|MarketAux美股市场新闻(标题+ticker标注, 免费~100次/天)",
        auth="apiKey", ttl_min=30)
def _marketaux(conf):
    return gs.fetch_marketaux_news(int(conf.get("page_size", 30)))


@source("finnhub_news", "flash", "备用|Finnhub美股市场新闻headline流(免费60次/分)",
        auth="apiKey", ttl_min=30)
def _finnhub(conf):
    return gs.fetch_finnhub_news(int(conf.get("page_size", 30)))


@source("alphavantage_news", "flash", "备用|AlphaVantage美股新闻+情绪标签(免费仅25次/天, 应急)",
        auth="apiKey", ttl_min=60)
def _av(conf):
    return gs.fetch_alphavantage_news(int(conf.get("page_size", 30)))


@source("sec_edgar", "announcement", "备用|SEC EDGAR美股8-K重大公告(官方免费, 申报式UA内置)",
        ttl_min=30, default_enabled=True)
def _edgar(conf):
    return gs.fetch_sec_edgar_filings(int(conf.get("page_size", 30)))


@source("frankfurter_fx", "market", "备用|Frankfurter汇率快照(ECB参考汇率, 无key, 交易日一更, 不含TWD)",
        ttl_min=360, default_enabled=True)
def _frank(conf):
    return gs.fetch_frankfurter_fx()


@source("goldprice_metals", "market", "备用|goldprice.dev金价快照(仅黄金, 无key)",
        ttl_min=60, default_enabled=True)
def _gold(conf):
    return gs.fetch_goldprice_metals()


@source("fred_macro", "market", "备用|FRED美宏观CPI/失业率/利率/10Y国债最新值(免费key即申即得)",
        auth="apiKey", ttl_min=720)
def _fred(conf):
    return gs.fetch_fred_macro()


# ---------- 扩展源(simonlin1212 目录项目收录 + 前两轮调研遗漏补收 2026-08-30) ----------
# 全部零鉴权且已逐一直调实测通过; 休刊日返回空属正常(nasdaq 周末/miningcom 当日无更)。
# nbs_pmi/pboc 为月频官方数据: 发现层翻页/三级跳已内置, 措辞改版会 fail-fast 报警。

@source("cls_telegraph", "flash", "财联社电报快讯流(本地签名零key, 7×24实时)",
        ttl_min=5, default_enabled=True)
def _cls_tele(conf):
    return gs.fetch_cls_telegraph(int(conf.get("page_size", 50)))


@source("eastmoney_global", "flash", "东财全球资讯快讯(美/港/宏观, 与电报不同风控面备胎)",
        ttl_min=10, default_enabled=True)
def _em_global(conf):
    return gs.fetch_eastmoney_global(int(conf.get("page_size", 50)))


@source("cninfo_latest", "announcement", "巨潮全市场最新公告(A股官方信披, 按日期归集)",
        ttl_min=30, default_enabled=True)
def _cninfo(conf):
    return gs.fetch_cninfo_latest(int(conf.get("page_size", 30)))


@source("nbs_pmi", "market", "国家统计局PMI(月度, 制造业/非制造业/综合+企业分档, 官方)",
        ttl_min=720, default_enabled=True)
def _nbs(conf):
    return gs.fetch_nbs_pmi()


@source("pboc_social_financing", "market", "人民银行社融增量(月度, 总量+贷款/政府债/企业债, 官方)",
        ttl_min=720, default_enabled=True)
def _pboc(conf):
    return gs.fetch_pboc_social_financing()


@source("treasury_yield_curve", "market", "美债收益率曲线日更(3M/2Y/10Y/30Y+10Y-2Y利差, 官方)",
        ttl_min=720, default_enabled=True)
def _ust(conf):
    return gs.fetch_treasury_yield_curve()


@source("cftc_cot", "market", "CFTC持仓周报(金银铜油/外汇/股指投机净多, 官方Socrata)",
        ttl_min=1440, default_enabled=True)
def _cot(conf):
    return gs.fetch_cftc_cot(int(conf.get("page_size", 10)))


@source("nasdaq_earnings", "market", "Nasdaq美股财报日历(当日披露+预期EPS, 周末/假期无数据正常)",
        ttl_min=720, default_enabled=True)
def _earnings(conf):
    return gs.fetch_nasdaq_earnings()


@source("gelonghui", "peer_article", "格隆汇精选(港/美/A评论要闻, 早报聚合17源之一)",
        ttl_min=120, default_enabled=True)
def _glh(conf):
    r = ges.fetch_gelonghui()
    return [r] if r else []


@source("miningcom", "peer_article", "MINING.COM大宗矿业新闻机器汇总(当日RSS条目, 资产类别源)",
        ttl_min=120, default_enabled=True)
def _mining(conf):
    r = ges.fetch_miningcom()
    return [r] if r else []


@source("liberty_street", "peer_article", "纽约联储Liberty Street分析博客(联储经济学家, 周1-2篇)",
        ttl_min=720, default_enabled=True)
def _liberty(conf):
    r = ges.fetch_liberty_street()
    return [r] if r else []


# ---------- NEWS 项目移植(D:\AI项目\NEWS, 2026-08-31) ----------
# 见闻快讯/长桥海豚实测通过默认启用; 金十日历官方 CDN 域名 cdn-rili.jin10.com 已 NXDOMAIN
# (Cloudflare/阿里/腾讯 DoH 三方向均确认, 金十官方日历站同源故障), 代码在册待恢复。

@source("wscn_live", "flash", "见闻全球快讯(官方API零key, 与见闻早餐文章互补的实时流; 全球频道含非财经条目, 下游粗筛过滤)",
        ttl_min=10, default_enabled=True)
def _wscn_live(conf):
    return gs.fetch_wscn_live(int(conf.get("page_size", 50)))


@source("longbridge_topics", "flash", "长桥海豚要闻(港美券商话题热点, 页内TanStack脱水JSON解析)",
        ttl_min=15, default_enabled=True)
def _longbridge(conf):
    return gs.fetch_longbridge_topics(int(conf.get("page_size", 10)))


@source("jin10_calendar", "market", "金十财经日历(经济数据+事件+星级; 2026-08-31起官方CDN域名NXDOMAIN, 待恢复)",
        ttl_min=360, default_enabled=False)
def _jin10_cal(conf):
    return gs.fetch_jin10_calendar()


# ---------- 13 开源项目源收录(akshare/yfinance/edgartools 端点移植, 2026-08-31) ----------
# 全零鉴权实测通过默认启用。cctv_xwlb 政策信号源不进早报聚合元组(防时政稀释财经浓度), 按需选取。

@source("ths_flash", "flash", "同花顺全球财经直播快讯(带重要性标记, 与东财/财联社不同风控面)",
        ttl_min=10, default_enabled=True)
def _ths(conf):
    return gs.fetch_ths_flash(int(conf.get("page_size", 20)))


@source("caixin_flash", "flash", "财新数据通快讯(高质量中文财经, 带栏目标签)",
        ttl_min=10, default_enabled=True)
def _caixin(conf):
    return gs.fetch_caixin_flash(int(conf.get("page_size", 30)))


@source("yahoo_headlines", "flash", "Yahoo财经大盘头条RSS(美股盘面英文, 出版方署名)",
        ttl_min=30, default_enabled=True)
def _yahoo(conf):
    return gs.fetch_yahoo_headlines(int(conf.get("page_size", 20)),
                                    str(conf.get("symbol", "SPY")))


@source("sec_insider", "announcement", "SEC Form4内部人交易申报(高管/大股东买卖, 与sec_edgar同端点type=4)",
        ttl_min=30, default_enabled=True)
def _insider(conf):
    return gs.fetch_sec_edgar_filings(int(conf.get("page_size", 30)), form_type="4")


@source("cctv_xwlb", "peer_article", "央视新闻联播当日文字稿(A股政策信号: 国常会/部委/立法; 时政占比高供synth背景, 不入聚合)",
        ttl_min=720, default_enabled=True)
def _cctv(conf):
    r = ges.fetch_cctv_xwlb()
    return [r] if r else []


# ---------- 情绪/观点流 + 预测市场(2026-08-31 用户裁决: 一律入库, 选取权在用户) ----------

@source("polymarket_sentiment", "market", "Polymarket预测市场财经情绪(活跃财经市场概率+24h成交量, 零key)",
        ttl_min=120, default_enabled=True)
def _polymarket(conf):
    return gs.fetch_polymarket_sentiment(int(conf.get("page_size", 10)))


@source("stocktwits_stream", "flash", "StockTwits美股情绪流(散户+大V观点, 带Bullish/Bearish标记; 2026-08-31出口IP被Cloudflare拦截, 待恢复)",
        ttl_min=15, default_enabled=False)
def _stocktwits(conf):
    return gs.fetch_stocktwits_stream(str(conf.get("symbol", "SPY")), int(conf.get("page_size", 30)))


@source("reddit_hot", "flash", "Reddit财经sub热帖(观点/情绪, 标题+分数+评论数; 需免费OAuth凭证)",
        auth="oauth", ttl_min=15, default_enabled=False)
def _reddit(conf):
    return gs.fetch_reddit_hot(str(conf.get("subreddit", "stocks")), int(conf.get("page_size", 25)))
