"""源标签回填表(2026-09-03 双标签制): 市场/定位/渠道(legacy)/语言/形态/简介。

@source 注册时未显式给的, 由本表补齐; 兜底: markets=[] / positioning 按
channel×kind 推导(taxonomy.positioning_of) / lang=""。
修法: 直接改 TAGS 里对应行。枚举真源在 sources/taxonomy.py。

定位枚举: 官方(交易所/监管/政府/官媒) | 机构(数据商/券商/平台号/自建) |
  大V(社交个人/KOL聚合) | 快讯源(滚动快讯栏) | 新闻源(商业财经媒体)
channel 为 legacy 内部列(兼容期保留), 展示/筛选一律用 positioning。
"""

TAGS = {
    "sina_7x24": (["A股", "全球"], "快讯源", "data_vendor", "zh", "", "新浪财经7×24"),
    "eastmoney_fast": (["A股"], "快讯源", "data_vendor", "zh", "", "东财财经快讯"),
    "jin10_flash": (["全球"], "快讯源", "data_vendor", "zh", "", "金十数据快讯"),
    "fxstreet_flash": (["全球"], "快讯源", "media_finance", "en", "", "FXStreet外汇央行快讯"),
    "investinglive_flash": (["全球", "美国"], "快讯源", "media_finance", "en", "", "investingLive外汇/美股/宏观快讯"),
    "eastmoney_zaozhidao": (["A股"], "机构", "data_vendor", "zh", "", "东财搜索《早知道》系列"),
    "wscn_breakfast": (["A股", "全球"], "新闻源", "media_finance", "zh", "", "华尔街见闻早餐"),
    "futu_morning": (["香港", "美国"], "机构", "broker_research", "zh", "", "富途《港美早报》"),
    "cls_morning": (["A股", "全球"], "新闻源", "media_finance", "zh", "", "财联社有声早报"),
    "aa_morning": (["土耳其", "全球"], "官方", "media_official", "en", "", "AA安纳多卢通讯社英文晨报"),
    "turkey_morning": (["土耳其"], "新闻源", "media_finance", "tr", "", "BloombergHT土耳其市场"),
    "cnbc_morning": (["美国", "全球"], "新闻源", "media_finance", "en", "", "CNBC Daily Open美股晨报"),
    "japan_morning": (["日本"], "官方", "media_official", "ja", "", "共同社日本市场精选"),
    "korea_morning": (["韩国"], "官方", "media_official", "ko", "", "韩联社韩国市场精选"),
    "em_research": (["A股"], "机构", "broker_research", "zh", "", "东财研报中心机构观点索引"),
    "sina_vip": (["A股"], "大V", "kol", "zh", "view", "新浪意见领袖"),
    "cnyes_tw": (["台湾"], "新闻源", "media_finance", "zh", "", "鉅亨网台股精选"),
    "threads_kol_digest": (["台湾"], "大V", "aggregator", "zh", "view", "台股Threads KOL情报日报"),
    "twitter_kol_flash": (["全球", "美国", "台湾", "日本", "韩国", "土耳其"], "大V", "kol", "", "", "X账号池快讯入口(媒体/数据机器人/官方号)"),
    "twitter_kol_views": (["全球", "美国", "台湾", "日本", "韩国", "土耳其"], "大V", "kol", "", "view", "X账号池观点入口(分析师/交易员/KOL)"),
    "etnet_open": (["香港"], "新闻源", "media_finance", "zh", "", "etnet經濟通開市Go港股晨报"),
    "newsquawk_open": (["美国", "全球"], "新闻源", "media_finance", "en", "", "Newsquawk欧美市场开盘综述"),
    "smm_metals": (["全球", "A股"], "机构", "data_vendor", "zh", "", "SMM上海有色网大宗商品日报"),
    "gangtise": (["A股"], "机构", "broker_research", "zh", "", "Gangtise投研日报"),
    "yuanbao_gangtise": (["A股"], "机构", "broker_research", "zh", "", "元宝取Gangtise投研日报"),
    "calendar": (["全球"], "机构", "aggregator", "zh", "", "财经日历"),
    "global_markets": (["全球"], "机构", "aggregator", "zh", "", "全球市场行情摘要"),
    "cls_announcements": (["A股"], "新闻源", "media_finance", "zh", "", "财联社重点公告"),
    "peer_mornings": (["全球"], "新闻源", "aggregator", "zh", "", "同行早报聚合"),
    "extras": (["全球"], "机构", "aggregator", "zh", "", "版式素材聚合"),
    "marketaux_news": (["美国"], "快讯源", "data_vendor", "en", "", "备用|MarketAux美股市场新闻"),
    "finnhub_news": (["美国"], "快讯源", "data_vendor", "en", "", "备用|Finnhub美股市场新闻headline流"),
    "alphavantage_news": (["美国"], "快讯源", "data_vendor", "en", "", "备用|AlphaVantage美股新闻+情绪标签"),
    "sec_edgar": (["美国"], "官方", "exchange", "en", "", "备用|SEC EDGAR美股8-K重大公告"),
    "frankfurter_fx": (["全球"], "机构", "data_vendor", "en", "", "备用|Frankfurter汇率快照"),
    "goldprice_metals": (["全球"], "机构", "data_vendor", "en", "", "备用|goldprice.dev金价快照"),
    "fred_macro": (["美国"], "机构", "data_vendor", "en", "", "备用|FRED美宏观CPI/失业率/利率/10Y国债最新值"),
    "cls_telegraph": (["A股", "全球"], "快讯源", "media_finance", "zh", "", "财联社电报快讯流"),
    "eastmoney_global": (["美国", "香港", "全球"], "快讯源", "data_vendor", "zh", "", "东财全球资讯快讯"),
    "cninfo_latest": (["A股"], "官方", "exchange", "zh", "", "巨潮全市场最新公告"),
    "nbs_pmi": (["A股"], "官方", "exchange", "zh", "", "国家统计局PMI"),
    "pboc_social_financing": (["A股"], "官方", "exchange", "zh", "", "人民银行社融增量"),
    "treasury_yield_curve": (["美国"], "官方", "exchange", "en", "", "美债收益率曲线日更"),
    "cftc_cot": (["全球", "美国"], "官方", "exchange", "en", "", "CFTC持仓周报"),
    "nasdaq_earnings": (["美国"], "官方", "exchange", "en", "", "Nasdaq美股财报日历"),
    "gelonghui": (["香港", "美国", "A股"], "新闻源", "media_finance", "zh", "", "格隆汇精选"),
    "miningcom": (["全球"], "新闻源", "media_finance", "en", "", "MINING.COM大宗矿业新闻机器汇总"),
    "liberty_street": (["美国"], "官方", "exchange", "en", "", "纽约联储Liberty Street分析博客"),
    "wscn_live": (["全球"], "快讯源", "media_finance", "zh", "", "见闻全球快讯"),
    "longbridge_topics": (["香港", "美国"], "机构", "broker_research", "zh", "", "长桥海豚要闻"),
    "jin10_calendar": (["全球"], "机构", "data_vendor", "zh", "", "金十财经日历"),
    "ths_flash": (["A股", "全球"], "快讯源", "data_vendor", "zh", "", "同花顺全球财经直播快讯"),
    "caixin_flash": (["A股", "全球"], "快讯源", "media_finance", "zh", "", "财新数据通快讯"),
    "yahoo_headlines": (["美国"], "快讯源", "data_vendor", "en", "", "Yahoo财经大盘头条RSS"),
    "sec_insider": (["美国"], "官方", "exchange", "en", "", "SEC Form4内部人交易申报"),
    "cctv_xwlb": (["A股"], "官方", "media_official", "zh", "", "央视新闻联播当日文字稿"),
    "polymarket_sentiment": (["全球"], "机构", "data_vendor", "en", "", "Polymarket预测市场财经情绪"),
    "stocktwits_stream": (["美国"], "大V", "kol", "en", "", "StockTwits美股情绪流"),
    "reddit_hot": (["美国"], "大V", "kol", "en", "", "Reddit财经sub热帖"),
    "cn_index_snapshot": (["A股"], "机构", "data_vendor", "zh", "", "A股指数快照"),
    "em_sector_board": (["A股"], "机构", "data_vendor", "zh", "", "东财板块涨跌榜"),
    "tcmb_fx": (["土耳其", "全球"], "官方", "exchange", "tr", "", "土耳其中行每日汇率牌价"),
    "dailysabah_rss": (["土耳其"], "快讯源", "media_finance", "en", "", "Daily Sabah商业新闻流"),
    "hurriyet_rss": (["土耳其"], "快讯源", "media_finance", "en", "", "Hürriyet Daily News商业新闻流"),
    "dunya_rss": (["土耳其"], "快讯源", "media_finance", "tr", "", "Dünya世界报"),
    "tcmb_evds": (["土耳其"], "官方", "exchange", "tr", "", "备用|土耳其央行EVDS2宏观序列API"),
    "cna_flash": (["台湾"], "官方", "media_official", "zh", "", "中央社财经快讯"),
    "twse_news": (["台湾"], "官方", "exchange", "zh", "", "台湾证交所官方新闻+法说会日历"),
    "udn_rss": (["台湾"], "快讯源", "media_finance", "zh", "", "经济日报即时新闻"),
    "ltn_rss": (["台湾"], "快讯源", "media_finance", "zh", "", "自由时报财经新闻RSS"),
    "technews_rss": (["台湾"], "快讯源", "media_finance", "zh", "", "TechNews科技新报"),
    "moneydj_flash": (["台湾"], "快讯源", "data_vendor", "zh", "", "MoneyDJ新闻中心"),
    "tw_cbc_stats": (["台湾"], "官方", "exchange", "zh", "", "备用|台湾央行金融统计API"),
    "finmind_news": (["台湾"], "快讯源", "data_vendor", "zh", "", "备用|FinMind台股个股新闻API"),
    "fed_press": (["美国", "全球"], "官方", "exchange", "en", "", "美联储理事会新闻稿"),
    "marketwatch_rt": (["美国"], "快讯源", "media_finance", "en", "", "MarketWatch实时电头流"),
    "prnewswire": (["美国", "全球"], "新闻源", "media_finance", "en", "", "PR Newswire上市公司新闻稿原稿流"),
    "sec_press": (["美国"], "官方", "exchange", "en", "", "SEC新闻稿"),
    "treasury_press": (["美国"], "官方", "exchange", "en", "", "美国财政部新闻稿RSS"),
    "foxbusiness_rss": (["美国"], "快讯源", "media_finance", "en", "", "Fox Business最新新闻流"),
    "benzinga_rss": (["美国"], "快讯源", "media_finance", "en", "", "Benzinga美股个股快讯+分析流"),
    "eia_energy": (["全球", "美国"], "官方", "exchange", "en", "", "EIA美国能源署Today in Energy"),
    "finviz_news": (["美国"], "快讯源", "data_vendor", "en", "", "Finviz全市场新闻聚合"),
    "nyfed_rates": (["美国"], "官方", "exchange", "en", "", "纽约联储SOFR/EFFR/OBFR/TGCR官方利率最新值"),
    "bls_macro": (["美国"], "官方", "exchange", "en", "", "BLS美国CPI/非农/失业率最新值"),
    "fiscal_debt": (["美国"], "官方", "exchange", "en", "", "美国财政部国债总额日更"),
    "globenewswire": (["美国", "全球"], "新闻源", "media_finance", "en", "", "备用|GlobeNewswire上市公司稿流"),
    "hkexnews": (["香港"], "官方", "exchange", "zh", "", "港交所披露易公告检索API"),
    "mingpao_rss": (["香港"], "快讯源", "media_finance", "zh", "", "明报即时财经RSS"),
    "yahoo_hk_rss": (["香港"], "快讯源", "data_vendor", "zh", "", "Yahoo香港财经新闻流"),
    "scmp_biz_rss": (["香港"], "快讯源", "media_finance", "en", "", "SCMP南华早报Business频道"),
    "eastmoney_hkus": (["香港", "美国"], "快讯源", "data_vendor", "zh", "", "东财7×24快讯港美股频道"),
    "hkma_press": (["香港"], "官方", "exchange", "zh", "", "备用|香港金管局新闻稿Open API"),
    "kap_disclosures": (["土耳其"], "官方", "exchange", "tr", "", "KAP公开披露平台"),
    "cnbce_rss": (["土耳其"], "快讯源", "media_finance", "tr", "", "CNBC-e快讯"),
    "foreks_rss": (["土耳其"], "快讯源", "data_vendor", "tr", "", "Foreks快讯"),
    "sabah_rss": (["土耳其"], "快讯源", "media_finance", "tr", "", "Sabah经济频道"),
    "tcmb_press": (["土耳其"], "官方", "exchange", "tr", "", "土耳其中行新闻稿Atom"),
    "yahoo_tw_rss": (["台湾"], "快讯源", "data_vendor", "zh", "", "Yahoo奇摩股市RSS"),
    "twse_mops": (["台湾"], "官方", "exchange", "zh", "", "台湾上市公司每日重大讯息"),
    "tpex_mops": (["台湾"], "官方", "exchange", "zh", "", "台湾上柜公司每日重大讯息"),
    "fsc_press": (["台湾"], "官方", "exchange", "zh", "", "备用|台湾金管会新闻稿RSS"),
    "bea_rss": (["美国"], "官方", "exchange", "en", "", "BEA美国经济分析局新闻稿"),
    "seekingalpha_rt": (["美国"], "快讯源", "media_finance", "en", "", "Seeking Alpha突发快讯流"),
    "gdpnow_rss": (["美国"], "官方", "exchange", "en", "", "亚特兰大联储GDPNow预测更新RSS"),
    "finra_press": (["美国"], "官方", "exchange", "en", "", "FINRA美国金融业监管局新闻稿"),
    "hkex_press": (["香港"], "官方", "exchange", "zh", "", "香港交易所自身新闻稿RSS"),
    "sfc_press": (["香港"], "官方", "exchange", "zh", "", "香港证监会新闻稿RSS"),
    "rthk_finance": (["香港"], "官方", "media_official", "zh", "", "香港电台财经即时快讯"),
    "hkgov_finance": (["香港"], "官方", "exchange", "zh", "", "备用|香港政府新闻网财经RSS"),
}

_KIND_TO_CHANNEL = {"flash": "media_finance", "peer_article": "media_finance",
                    "announcement": "exchange", "market": "data_vendor",
                    "calendar": "data_vendor"}


def apply(registry: dict) -> None:
    """把 TAGS 回填进 REGISTRY meta(只补空位, 注册时显式给的优先)。"""
    from sources.taxonomy import positioning_of as _pos_of
    for sid, e in registry.items():
        m = e["meta"]
        t = TAGS.get(sid)
        if t:
            markets, positioning, channel, lang, form, brief = t
            m["markets"] = list(markets)              # 新值域唯一真相
            m["positioning"] = positioning
            m["brief"] = brief
            if not m.get("channel"):
                m["channel"] = channel                # legacy 内部列, 兼容期保留
            if not m.get("lang"):
                m["lang"] = lang
            if form:
                m["form"] = form
        if not m.get("channel"):
            m["channel"] = _KIND_TO_CHANNEL.get(m.get("kind", ""), "media_finance")
        if not m.get("positioning"):
            m["positioning"] = _pos_of(sid, m.get("channel", ""), m.get("kind", ""))
        if not m.get("brief"):
            m["brief"] = m.get("title", "")[:40]
