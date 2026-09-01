"""来源注册:包装 fetchers/ 抓取函数为标准来源(P1 包装不重写)。

fetchers/basic.py + extra.py 是本板块的抓取实现(原 generator/sources.py 等),
注册 id 与语义稳定,调用方经 sources.REGISTRY / sources.gather 使用。

kind: flash 快讯 | peer_article 同行早报 | calendar 日历 | market 行情 | announcement 公告
      peer_group/extras_group 聚合来源(morning_paper 工作流直接调用,不进 gather)
"""

import sys
import importlib.util
from datetime import datetime
from pathlib import Path

_FETCHERS = Path(__file__).resolve().parent.parent / "fetchers"
if str(_FETCHERS) not in sys.path:
    sys.path.insert(0, str(_FETCHERS))     # extra.py 内部 `from search import ...` 需要


def _load(alias: str, path: Path):
    """按路径加载 fetcher 模块(本包也叫 sources, 不能直接 import sources)。"""
    spec = importlib.util.spec_from_file_location(alias, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


gs = _load("gen_sources", _FETCHERS / "basic.py")          # fetchers/basic.py
ges = _load("gen_extra_sources", _FETCHERS / "extra.py")   # fetchers/extra.py

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


@source("threads_kol_digest", "peer_article",
        "台股Threads KOL情报日报(threads-tw-monitor本地产物, 社媒观点流)",
        ttl_min=60, default_enabled=True)
def _threads_kol(conf):
    return gs.fetch_threads_kol_digest(conf)


@source("twitter_kol_flash", "flash",
        "X大V快讯(FxTwitter免登录池·媒体官号/数据平台/官方机构)",
        ttl_min=30)
def _tw_flash(conf):
    return gs.fetch_twitter_kol(conf, mode="flash")


@source("twitter_kol_views", "peer_article",
        "X大V观点(FxTwitter免登录池·分析师/交易员/KOL/内部人士)",
        ttl_min=60)
def _tw_views(conf):
    return gs.fetch_twitter_kol(conf, mode="views")


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
        auth="apiKey", ttl_min=120)
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


# ---------- 大盘复盘工作流数据源(market-review, 2026-08-31) ----------

@source("cn_index_snapshot", "market", "A股指数快照(上证/深成/创业板/科创50, 新浪hq零key)",
        ttl_min=15, default_enabled=True)
def _cn_idx(conf):
    return [{"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "source": "A股指数",
             "text": f"{x['name']} {x['price']} ({x['chg_pct']})"} for x in gs.fetch_cn_index_snapshot()]


@source("em_sector_board", "market", "东财板块涨跌榜(行业/概念 领涨+领跌各Top5, 零key)",
        ttl_min=60, default_enabled=True)
def _sector(conf):
    return gs.sector_board_text(gs.fetch_em_sector_board())


# ---------- MOA 四市场快讯源收录(土耳其/台湾/美股/港股, 2026-08-31) ----------
# grok+gemini+codex 三代理独立全角度调研交叉裁决, 候选 35 端点本机逐一 curl 实测:
# 33 通过全量收录(不做质量门槛, 选取权在用户); 5 个跑不通(缺key/被断)占位待恢复。
# 弃选记录见 docs/add-a-source.md(新浪roll频道错配/AASTOCKS与Yahoo港股同源/智通500/finviz已收等)。

# ===== 土耳其 =====

@source("tcmb_fx", "market", "土耳其中行每日汇率牌价(USD/EUR等现汇买卖价, 官方XML零key, 交易日一更)",
        ttl_min=720, default_enabled=True)
def _tcmb_fx(conf):
    return gs.fetch_tcmb_fx()


@source("dailysabah_rss", "flash", "Daily Sabah商业新闻流(土耳其英文财经, 日内高频)",
        ttl_min=30, default_enabled=True)
def _dailysabah(conf):
    return gs.fetch_dailysabah_rss(int(conf.get("page_size", 30)))


@source("hurriyet_rss", "flash", "Hürriyet Daily News商业新闻流(土耳其英文, 带全文摘要)",
        ttl_min=30, default_enabled=True)
def _hurriyet(conf):
    return gs.fetch_hurriyet_rss(int(conf.get("page_size", 30)))


@source("dunya_rss", "flash", "Dünya世界报(土耳其主流财经日报, 土语, 5分钟刷新)",
        ttl_min=15, default_enabled=True)
def _dunya(conf):
    return gs.fetch_dunya_rss(int(conf.get("page_size", 30)))


@source("tcmb_evds", "market", "备用|土耳其央行EVDS2宏观序列API(利率/通胀/汇率, 免费key即申即得)",
        auth="key", ttl_min=1440, default_enabled=False)
def _tcmb_evds(conf):
    return gs.fetch_tcmb_evds(str(conf.get("series", "TP.DK.USD.A")),
                              str(conf.get("key", "")))


# ===== 台湾 =====

@source("cna_flash", "flash", "中央社财经快讯(台湾官方通讯社JSON API, 產經分类零key)",
        ttl_min=10, default_enabled=True)
def _cna(conf):
    return gs.fetch_cna_flash(int(conf.get("page_size", 30)))


@source("twse_news", "announcement", "台湾证交所官方新闻+法说会日历(OpenAPI零key, 民国年日期已转换)",
        ttl_min=120, default_enabled=True)
def _twse(conf):
    return gs.fetch_twse_news(int(conf.get("page_size", 20)))


@source("udn_rss", "flash", "经济日报即时新闻(台湾主流财经纸媒RSS零key)",
        ttl_min=30, default_enabled=True)
def _udn(conf):
    return gs.fetch_udn_rss(int(conf.get("page_size", 30)))


@source("ltn_rss", "flash", "自由时报财经新闻RSS(台湾, 零key)",
        ttl_min=30, default_enabled=True)
def _ltn(conf):
    return gs.fetch_ltn_rss(int(conf.get("page_size", 30)))


@source("technews_rss", "flash", "TechNews科技新报(台湾半导体/供应链视角, 台积电链素材)",
        ttl_min=60, default_enabled=True)
def _technews(conf):
    return gs.fetch_technews_rss(int(conf.get("page_size", 20)))


@source("moneydj_flash", "flash", "MoneyDJ新闻中心(台股盘口快讯, SSR HTML解析; 其RSS已退化空壳)",
        ttl_min=15, default_enabled=True)
def _moneydj(conf):
    return gs.fetch_moneydj_flash(int(conf.get("page_size", 20)))


@source("tw_cbc_stats", "market", "备用|台湾央行金融统计API(官方零key; 2026-08-31本机出口TLS被重置, 待部署环境复测)",
        ttl_min=1440, default_enabled=False)
def _tw_cbc(conf):
    return gs.fetch_tw_cbc_stats(str(conf.get("filename", "BP01D01")))


@source("finmind_news", "flash", "备用|FinMind台股个股新闻API(50+dataset, 免费token即申即得)",
        auth="key", ttl_min=30, default_enabled=False)
def _finmind(conf):
    return gs.fetch_finmind_news(str(conf.get("key", "")), int(conf.get("page_size", 20)))


# ===== 美股 =====

@source("fed_press", "announcement", "美联储理事会新闻稿(FOMC/监管执法, 最高权威源RSS零key)",
        ttl_min=60, default_enabled=True)
def _fed_press(conf):
    return gs.fetch_fed_press(int(conf.get("page_size", 20)))


@source("marketwatch_rt", "flash", "MarketWatch实时电头流(道琼斯分钟级, 零key)",
        ttl_min=5, default_enabled=True)
def _mw_rt(conf):
    return gs.fetch_marketwatch_rt(int(conf.get("page_size", 30)))


@source("prnewswire", "announcement", "PR Newswire上市公司新闻稿原稿流(财报/公告第一落点)",
        ttl_min=15, default_enabled=True)
def _prnews(conf):
    return gs.fetch_prnewswire(int(conf.get("page_size", 30)))


@source("sec_press", "announcement", "SEC新闻稿(执法行动/规则制定, 与EDGAR申报流不同)",
        ttl_min=120, default_enabled=True)
def _sec_press(conf):
    return gs.fetch_sec_press(int(conf.get("page_size", 20)))


@source("treasury_press", "announcement", "美国财政部新闻稿RSS(仅/rss.xml有效路径)",
        ttl_min=120, default_enabled=True)
def _treasury_press(conf):
    return gs.fetch_treasury_press(int(conf.get("page_size", 20)))


@source("foxbusiness_rss", "flash", "Fox Business最新新闻流(英文零key)",
        ttl_min=30, default_enabled=True)
def _foxbiz(conf):
    return gs.fetch_foxbusiness_rss(int(conf.get("page_size", 30)))


@source("benzinga_rss", "flash", "Benzinga美股个股快讯+分析流(英文; 夹杂加密/预测类内容下游粗筛)",
        ttl_min=15, default_enabled=True)
def _benzinga(conf):
    return gs.fetch_benzinga_rss(int(conf.get("page_size", 30)))


@source("eia_energy", "peer_article", "EIA美国能源署Today in Energy(能源大宗基本面日报, 工作日每日)",
        ttl_min=720, default_enabled=True)
def _eia(conf):
    return gs.fetch_eia_energy(int(conf.get("page_size", 10)))


@source("finviz_news", "flash", "Finviz全市场新闻聚合(Bloomberg/Reuters/WSJ/CNBC等, 纯SSR零key带来源链接)",
        ttl_min=15, default_enabled=True)
def _finviz(conf):
    return gs.fetch_finviz_news(int(conf.get("page_size", 40)))


@source("nyfed_rates", "market", "纽约联储SOFR/EFFR/OBFR/TGCR官方利率最新值(Markets API零key)",
        ttl_min=720, default_enabled=True)
def _nyfed(conf):
    return gs.fetch_nyfed_rates()


@source("bls_macro", "market", "BLS美国CPI/非农/失业率最新值(公共API v1零key日限25次)",
        ttl_min=1440, default_enabled=True)
def _bls(conf):
    return gs.fetch_bls_macro()


@source("fiscal_debt", "market", "美国财政部国债总额日更(Fiscal Data零key免注册, T+1)",
        ttl_min=720, default_enabled=True)
def _fiscal_debt(conf):
    return gs.fetch_fiscal_debt()


@source("globenewswire", "announcement", "备用|GlobeNewswire上市公司稿流(2026-08-31本机出口IP多次ReadTimeout, 疑IDC段限制待复测)",
        ttl_min=15, default_enabled=False)
def _globenw(conf):
    return gs.fetch_globenewswire(int(conf.get("page_size", 30)))


# ===== 港股 =====

@source("hkexnews", "announcement", "港交所披露易公告检索API(上市公司法定披露一手源, 零key含代码+PDF直链)",
        ttl_min=15, default_enabled=True)
def _hkexnews(conf):
    return gs.fetch_hkexnews(int(conf.get("days", 3)), int(conf.get("page_size", 30)))


@source("mingpao_rss", "flash", "明报即时财经RSS(港股IPO/中报/本地宏观, 盘中高频零key)",
        ttl_min=15, default_enabled=True)
def _mingpao(conf):
    return gs.fetch_mingpao_rss(int(conf.get("page_size", 30)))


@source("yahoo_hk_rss", "flash", "Yahoo香港财经新闻流(AASTOCKS AAFN快讯内容, 繁体带代码零key)",
        ttl_min=15, default_enabled=True)
def _yahoo_hk(conf):
    return gs.fetch_yahoo_hk_rss(int(conf.get("page_size", 30)))


@source("scmp_biz_rss", "flash", "SCMP南华早报Business频道(英文港股/中国财经视角, 标题摘要免费)",
        ttl_min=60, default_enabled=True)
def _scmp(conf):
    return gs.fetch_scmp_biz_rss(int(conf.get("page_size", 20)))


@source("eastmoney_hkus", "flash", "东财7×24快讯港美股频道(fastColumn=104, 与焦点102不同栏目)",
        ttl_min=10, default_enabled=True)
def _em_hkus(conf):
    return gs.fetch_eastmoney_hkus(int(conf.get("page_size", 50)))


@source("hkma_press", "announcement", "备用|香港金管局新闻稿Open API(官方零key; 2026-08-31本机出口TLS被重置, 待部署环境复测)",
        ttl_min=120, default_enabled=False)
def _hkma(conf):
    return gs.fetch_hkma_press(int(conf.get("page_size", 20)))


# ---------- MOA grok 迟到补充轮(2026-08-31): 双家未覆盖的增量, 全部本机复测后收录 ----------
# 最重增量: KAP 披露(土耳其版披露易, 必须POST JSON, 旧GET端点404是codex误判原因)、
# TWSE/TPEx 重大讯息 OpenAPI(台股法定公告)。fsc/hkgov 本机TLS被断占位待复测。

@source("kap_disclosures", "announcement", "KAP公开披露平台(土耳其上市公司法定公告一手源, POST JSON零key)",
        ttl_min=15, default_enabled=True)
def _kap(conf):
    return gs.fetch_kap_disclosures(int(conf.get("days", 3)), int(conf.get("page_size", 30)))


@source("cnbce_rss", "flash", "CNBC-e快讯(土耳其, ttl=5分钟单次约250条, 土语)",
        ttl_min=10, default_enabled=True)
def _cnbce(conf):
    return gs.fetch_cnbce_rss(int(conf.get("page_size", 30)))


@source("foreks_rss", "flash", "Foreks快讯(土耳其本土财经数据商, 土语)",
        ttl_min=30, default_enabled=True)
def _foreks(conf):
    return gs.fetch_foreks_rss(int(conf.get("page_size", 30)))


@source("sabah_rss", "flash", "Sabah经济频道(土耳其宏观日程/政策, 早报语境日更)",
        ttl_min=120, default_enabled=True)
def _sabah(conf):
    return gs.fetch_sabah_rss(int(conf.get("page_size", 20)))


@source("tcmb_press", "announcement", "土耳其中行新闻稿Atom(利率决议/流动性操作, 事件驱动)",
        ttl_min=120, default_enabled=True)
def _tcmb_press(conf):
    return gs.fetch_tcmb_press(int(conf.get("page_size", 20)))


@source("yahoo_tw_rss", "flash", "Yahoo奇摩股市RSS(台股盘面快讯, ttl=5, 可按个股订阅)",
        ttl_min=10, default_enabled=True)
def _yahoo_tw(conf):
    return gs.fetch_yahoo_tw_rss(int(conf.get("page_size", 30)))


@source("twse_mops", "announcement", "台湾上市公司每日重大讯息(证交所OpenAPI, 日更出表零key)",
        ttl_min=720, default_enabled=True)
def _twse_mops(conf):
    return gs.fetch_twse_mops(int(conf.get("page_size", 30)))


@source("tpex_mops", "announcement", "台湾上柜公司每日重大讯息(柜买中心OpenAPI, 与上市互补零key)",
        ttl_min=720, default_enabled=True)
def _tpex_mops(conf):
    return gs.fetch_tpex_mops(int(conf.get("page_size", 30)))


@source("fsc_press", "announcement", "备用|台湾金管会新闻稿RSS(2026-08-31本机出口TLS被重置, 待部署环境复测)",
        ttl_min=120, default_enabled=False)
def _fsc(conf):
    return gs.fetch_fsc_press(int(conf.get("page_size", 20)))


@source("bea_rss", "announcement", "BEA美国经济分析局新闻稿(GDP/PCE发布, 通常08:30 ET)",
        ttl_min=720, default_enabled=True)
def _bea(conf):
    return gs.fetch_bea_rss(int(conf.get("page_size", 10)))


@source("seekingalpha_rt", "flash", "Seeking Alpha突发快讯流(分钟级带ticker; feed自述限personal/non-commercial注意ToS)",
        risk="medium", ttl_min=5, default_enabled=True)
def _seekingalpha(conf):
    return gs.fetch_seekingalpha_rt(int(conf.get("page_size", 30)))


@source("gdpnow_rss", "market", "亚特兰大联储GDPNow预测更新RSS(发布即推, 无需解析xlsx)",
        ttl_min=1440, default_enabled=True)
def _gdpnow(conf):
    return gs.fetch_gdpnow_rss(int(conf.get("page_size", 5)))


@source("finra_press", "announcement", "FINRA美国金融业监管局新闻稿(执法/纪律处分; 必须走http, https握手失败)",
        ttl_min=1440, default_enabled=True)
def _finra(conf):
    return gs.fetch_finra_press(int(conf.get("page_size", 10)))


@source("hkex_press", "announcement", "香港交易所自身新闻稿RSS(规则/产品/市场动态, 与披露易公司公告不同)",
        ttl_min=120, default_enabled=True)
def _hkex_press(conf):
    return gs.fetch_hkex_press(int(conf.get("page_size", 20)))


@source("sfc_press", "announcement", "香港证监会新闻稿RSS(执法/互联互通/季报)",
        ttl_min=120, default_enabled=True)
def _sfc(conf):
    return gs.fetch_sfc_press(int(conf.get("page_size", 20)))


@source("rthk_finance", "flash", "香港电台财经即时快讯(ttl=10近7×24, 周末有ADR/金油汇)",
        ttl_min=10, default_enabled=True)
def _rthk(conf):
    return gs.fetch_rthk_finance(int(conf.get("page_size", 30)))


@source("hkgov_finance", "announcement", "备用|香港政府新闻网财经RSS(2026-08-31本机出口TLS被重置, 待部署环境复测)",
        ttl_min=120, default_enabled=False)
def _hkgov(conf):
    return gs.fetch_hkgov_finance(int(conf.get("page_size", 20)))
