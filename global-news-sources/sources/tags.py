"""源标签回填表(2026-09-03 双标签制): 市场/定位/渠道(legacy)/语言/形态/简介。

@source 注册时未显式给的, 由本表补齐; 兜底: markets=[] / positioning 按
channel×kind 推导(taxonomy.positioning_of) / lang=""。
修法: 直接改 TAGS 里对应行。枚举真源在 sources/taxonomy.py。

定位枚举: 官方(交易所/监管/政府/官媒) | 机构(数据商/券商/平台号/自建) |
  大V(社交个人/KOL聚合) | 快讯源(滚动快讯栏) | 新闻源(商业财经媒体)
channel 为 legacy 内部列(兼容期保留), 展示/筛选一律用 positioning。

brief: 独立撰写的一句话简介(是什么/覆盖什么/特点, ≤40字), 禁止复读 title。
NOTES: 运维备忘(备用标记/TLS故障/配额鉴权/抓取通道), 不回填 meta、不进 /v1/sources。
"""

TAGS = {
    "sina_7x24": (["A股", "全球"], "快讯源", "data_vendor", "zh", "", "A股与全球要闻滚动快讯"),
    "eastmoney_fast": (["A股"], "快讯源", "data_vendor", "zh", "", "偏A股盘面与公司公告的焦点快讯"),
    "jin10_flash": (["全球"], "快讯源", "data_vendor", "zh", "", "全球宏观外汇秒级快讯，带精确时间戳"),
    "fxstreet_flash": (["全球"], "快讯源", "media_finance", "en", "", "英文外汇与央行决议快讯"),
    "investinglive_flash": (["全球", "美国"], "快讯源", "media_finance", "en", "", "英文外汇、美股与宏观快讯，原名ForexLive"),
    "eastmoney_zaozhidao": (["A股"], "机构", "data_vendor", "zh", "", "盘前要闻专栏汇编"),
    "wscn_breakfast": (["A股", "全球"], "新闻源", "media_finance", "zh", "", "工作日早餐，全球隔夜与A股要点"),
    "futu_morning": (["香港", "美国"], "机构", "broker_research", "zh", "", "港美股隔夜行情与开盘要点"),
    "cls_morning": (["A股", "全球"], "新闻源", "media_finance", "zh", "", "每日07:00左右更新的有声早报"),
    "aa_morning": (["土耳其", "全球"], "官方", "media_official", "en", "", "土耳其官方通讯社英文晨报，覆盖土欧宏观"),
    "turkey_morning": (["土耳其"], "新闻源", "media_finance", "tr", "", "彭博土耳其频道汇总，土股与里拉"),
    "cnbc_morning": (["美国", "全球"], "新闻源", "media_finance", "en", "", "工作日美股开盘综述，覆盖隔夜与风险资产"),
    "japan_morning": (["日本"], "官方", "media_official", "ja", "", "当日日经与日本宏观要闻"),
    "korea_morning": (["韩国"], "官方", "media_official", "ko", "", "当日韩股与韩国宏观要闻"),
    "em_research": (["A股"], "机构", "broker_research", "zh", "", "券商晨会、宏观与策略研报索引"),
    "sina_vip": (["A股"], "大V", "kol", "zh", "view", "首席经济学家与大V专栏观点"),
    "cnyes_tw": (["台湾"], "新闻源", "media_finance", "zh", "", "台股要闻精选，周末照常更新"),
    "threads_kol_digest": (["台湾"], "大V", "aggregator", "zh", "view", "台股Threads达人观点日报汇编"),
    "twitter_kol_flash": (["全球", "美国", "台湾", "日本", "韩国", "土耳其"], "大V", "kol", "", "", "媒体官号与数据机器人快讯池"),
    "twitter_kol_views": (["全球", "美国", "台湾", "日本", "韩国", "土耳其"], "大V", "kol", "", "view", "分析师、交易员与KOL观点池"),
    "etnet_open": (["香港"], "新闻源", "media_finance", "zh", "", "港股工作日08:30开市综述"),
    "newsquawk_open": (["美国", "全球"], "新闻源", "media_finance", "en", "", "交易日午后至傍晚的欧美开盘综述"),
    "smm_metals": (["全球", "A股"], "机构", "data_vendor", "zh", "", "有色金属隔夜行情与基本面日报"),
    "gangtise": (["A股"], "机构", "broker_research", "zh", "", "覆盖A股策略与行业的投研早报"),
    "yuanbao_gangtise": (["A股"], "机构", "broker_research", "zh", "", "经元宝网页抓取的Gangtise日报全文"),
    "calendar": (["全球"], "机构", "aggregator", "zh", "", "当日经济数据与事件日程"),
    "global_markets": (["全球"], "机构", "aggregator", "zh", "", "股汇油金等主要资产隔夜涨跌摘要"),
    "cls_announcements": (["A股"], "新闻源", "media_finance", "zh", "", "A股上市公司重点公告速览"),
    "peer_mornings": (["全球"], "新闻源", "aggregator", "zh", "", "多市场同行早报一次汇编"),
    "extras": (["全球"], "机构", "aggregator", "zh", "", "日历、行情、公告与同行素材打包"),
    "marketaux_news": (["美国"], "快讯源", "data_vendor", "en", "", "美股新闻标题流，带股票代码标注"),
    "finnhub_news": (["美国"], "快讯源", "data_vendor", "en", "", "美股市场新闻标题流"),
    "alphavantage_news": (["美国"], "快讯源", "data_vendor", "en", "", "美股新闻流，附带市场情绪标签"),
    "sec_edgar": (["美国"], "官方", "exchange", "en", "", "美股上市公司8-K重大事项申报"),
    "frankfurter_fx": (["全球"], "机构", "data_vendor", "en", "", "欧央行参考汇率，交易日一更，不含台币"),
    "goldprice_metals": (["全球"], "机构", "data_vendor", "en", "", "现货金价快照，仅覆盖黄金"),
    "fred_macro": (["美国"], "机构", "data_vendor", "en", "", "美国CPI、失业率、利率与十年期国债最新值"),
    "cls_telegraph": (["A股", "全球"], "快讯源", "media_finance", "zh", "", "7×24实时电报，覆盖A股与全球要闻"),
    "eastmoney_global": (["美国", "香港", "全球"], "快讯源", "data_vendor", "zh", "", "美股、港股与宏观快讯"),
    "cninfo_latest": (["A股"], "官方", "exchange", "zh", "", "A股官方信披最新公告，按日期归集"),
    "nbs_pmi": (["A股"], "官方", "exchange", "zh", "", "月度制造业、非制造业与综合PMI"),
    "pboc_social_financing": (["A股"], "官方", "exchange", "zh", "", "月度社融总量及贷款、政府债、企业债分项"),
    "treasury_yield_curve": (["美国"], "官方", "exchange", "en", "", "3M/2Y/10Y/30Y国债收益率及10Y-2Y利差，日更"),
    "cftc_cot": (["全球", "美国"], "官方", "exchange", "en", "", "金银铜油、外汇与股指投机净多持仓"),
    "nasdaq_earnings": (["美国"], "官方", "exchange", "en", "", "当日美股财报披露与预期EPS"),
    "gelonghui": (["香港", "美国", "A股"], "新闻源", "media_finance", "zh", "", "港股、美股与A股评论要闻精选"),
    "miningcom": (["全球"], "新闻源", "media_finance", "en", "", "全球矿业与大宗商品当日要闻"),
    "liberty_street": (["美国"], "官方", "exchange", "en", "", "纽约联储经济学家分析，约每周1-2篇"),
    "wscn_live": (["全球"], "快讯源", "media_finance", "zh", "", "实时快讯与早餐互补；含非财经需筛选"),
    "longbridge_topics": (["香港", "美国"], "机构", "broker_research", "zh", "", "港美股话题热点要闻"),
    "jin10_calendar": (["全球"], "机构", "data_vendor", "zh", "", "经济数据与事件日历，附重要性星级"),
    "ths_flash": (["A股", "全球"], "快讯源", "data_vendor", "zh", "", "全球财经快讯，带重要性标记"),
    "caixin_flash": (["A股", "全球"], "快讯源", "media_finance", "zh", "", "中文财经快讯，带栏目标签"),
    "yahoo_headlines": (["美国"], "快讯源", "data_vendor", "en", "", "美股盘面英文头条，带来源署名"),
    "sec_insider": (["美国"], "官方", "exchange", "en", "", "美股高管与大股东买卖申报"),
    "cctv_xwlb": (["A股"], "官方", "media_official", "zh", "", "当日联播文稿，政策信号供背景不入早报聚合"),
    "polymarket_sentiment": (["全球"], "机构", "data_vendor", "en", "", "活跃财经预测合约概率与24小时成交量"),
    "stocktwits_stream": (["美国"], "大V", "kol", "en", "", "美股散户与大V观点，带多空标记"),
    "reddit_hot": (["美国"], "大V", "kol", "en", "", "财经版热帖，含标题、分数与评论数"),
    "cn_index_snapshot": (["A股"], "机构", "data_vendor", "zh", "", "上证、深成、创业板与科创50点位涨跌"),
    "em_sector_board": (["A股"], "机构", "data_vendor", "zh", "", "行业与概念板块领涨领跌各Top5"),
    "tcmb_fx": (["土耳其", "全球"], "官方", "exchange", "tr", "", "美元欧元等现汇买卖价，交易日一更"),
    "dailysabah_rss": (["土耳其"], "快讯源", "media_finance", "en", "", "土耳其英文财经新闻，日内高频更新"),
    "hurriyet_rss": (["土耳其"], "快讯源", "media_finance", "en", "", "土耳其英文商业新闻，带全文摘要"),
    "dunya_rss": (["土耳其"], "快讯源", "media_finance", "tr", "", "土耳其主流财经日报，约5分钟刷新"),
    "tcmb_evds": (["土耳其"], "官方", "exchange", "tr", "", "利率、通胀与汇率官方时间序列"),
    "cna_flash": (["台湾"], "官方", "media_official", "zh", "", "台湾官方通讯社产经快讯"),
    "twse_news": (["台湾"], "官方", "exchange", "zh", "", "证交所官方新闻及法说会日程"),
    "udn_rss": (["台湾"], "快讯源", "media_finance", "zh", "", "台湾主流财经报纸即时要闻"),
    "ltn_rss": (["台湾"], "快讯源", "media_finance", "zh", "", "台湾自由时报财经频道要闻"),
    "technews_rss": (["台湾"], "快讯源", "media_finance", "zh", "", "台湾半导体与供应链科技新闻"),
    "moneydj_flash": (["台湾"], "快讯源", "data_vendor", "zh", "", "台股盘口快讯"),
    "tw_cbc_stats": (["台湾"], "官方", "exchange", "zh", "", "台湾央行官方金融统计数据"),
    "finmind_news": (["台湾"], "快讯源", "data_vendor", "zh", "", "台股个股新闻，数据集丰富"),
    "fed_press": (["美国", "全球"], "官方", "exchange", "en", "", "FOMC决议与监管执法官方新闻稿"),
    "marketwatch_rt": (["美国"], "快讯源", "media_finance", "en", "", "道琼斯分钟级美股电头快讯"),
    "prnewswire": (["美国", "全球"], "新闻源", "media_finance", "en", "", "美股财报与公告原稿第一落点"),
    "sec_press": (["美国"], "官方", "exchange", "en", "", "执法行动与规则制定，有别于EDGAR申报"),
    "treasury_press": (["美国"], "官方", "exchange", "en", "", "财政部官方政策与融资新闻稿"),
    "foxbusiness_rss": (["美国"], "快讯源", "media_finance", "en", "", "福克斯商业频道英文财经要闻"),
    "benzinga_rss": (["美国"], "快讯源", "media_finance", "en", "", "美股个股快讯与分析；含加密内容需筛选"),
    "eia_energy": (["全球", "美国"], "官方", "exchange", "en", "", "美国能源署工作日能源基本面日报"),
    "finviz_news": (["美国"], "快讯源", "data_vendor", "en", "", "聚合彭博路透WSJ等来源，带原文链接"),
    "nyfed_rates": (["美国"], "官方", "exchange", "en", "", "SOFR、EFFR、OBFR与TGCR最新官方利率"),
    "bls_macro": (["美国"], "官方", "exchange", "en", "", "美国CPI、非农与失业率最新官方值"),
    "fiscal_debt": (["美国"], "官方", "exchange", "en", "", "国债余额日更，T+1发布"),
    "globenewswire": (["美国", "全球"], "新闻源", "media_finance", "en", "", "上市公司新闻稿发布流"),
    "hkexnews": (["香港"], "官方", "exchange", "zh", "", "港股法定披露一手源，含代码与PDF链接"),
    "mingpao_rss": (["香港"], "快讯源", "media_finance", "zh", "", "港股IPO、中报与本地宏观，盘中高频"),
    "yahoo_hk_rss": (["香港"], "快讯源", "data_vendor", "zh", "", "港股快讯繁体带代码，内容出自AASTOCKS"),
    "scmp_biz_rss": (["香港"], "快讯源", "media_finance", "en", "", "英文港股与中国财经，标题摘要免费"),
    "eastmoney_hkus": (["香港", "美国"], "快讯源", "data_vendor", "zh", "", "港股与美股滚动快讯"),
    "hkma_press": (["香港"], "官方", "exchange", "zh", "", "金管局政策与市场官方新闻稿"),
    "kap_disclosures": (["土耳其"], "官方", "exchange", "tr", "", "土耳其上市公司法定公告一手源"),
    "cnbce_rss": (["土耳其"], "快讯源", "media_finance", "tr", "", "土耳其土语财经快讯，更新密集"),
    "foreks_rss": (["土耳其"], "快讯源", "data_vendor", "tr", "", "土耳其本土财经数据商土语快讯"),
    "sabah_rss": (["土耳其"], "快讯源", "media_finance", "tr", "", "土耳其宏观日程与政策，偏日更早报"),
    "tcmb_press": (["土耳其"], "官方", "exchange", "tr", "", "利率决议与流动性操作，事件驱动"),
    "yahoo_tw_rss": (["台湾"], "快讯源", "data_vendor", "zh", "", "台股盘面快讯，可按个股订阅"),
    "twse_mops": (["台湾"], "官方", "exchange", "zh", "", "证交所上市公司重大讯息，日更出表"),
    "tpex_mops": (["台湾"], "官方", "exchange", "zh", "", "柜买中心上柜公司重大讯息，与上市互补"),
    "fsc_press": (["台湾"], "官方", "exchange", "zh", "", "金管会监管与市场政策新闻稿"),
    "bea_rss": (["美国"], "官方", "exchange", "en", "", "GDP与PCE等数据发布，通常08:30 ET"),
    "seekingalpha_rt": (["美国"], "快讯源", "media_finance", "en", "", "分钟级美股突发快讯，带股票代码"),
    "gdpnow_rss": (["美国"], "官方", "exchange", "en", "", "GDPNow现时预测，发布即推送"),
    "finra_press": (["美国"], "官方", "exchange", "en", "", "经纪商执法与纪律处分公告"),
    "hkex_press": (["香港"], "官方", "exchange", "zh", "", "交易所规则、产品与市场动态，有别于披露易"),
    "sfc_press": (["香港"], "官方", "exchange", "zh", "", "执法、互联互通与季报等监管发布"),
    "rthk_finance": (["香港"], "官方", "media_official", "zh", "", "近7×24财经快讯，周末覆盖ADR与金油汇"),
    "hkgov_finance": (["香港"], "官方", "exchange", "zh", "", "港府财经政策与官方新闻"),
}

# 运维备忘(不回填 meta, 不进 /v1/sources)。前端资讯卡只展示 title+brief。
NOTES = {
    "fxstreet_flash": "2026-08-30起出口IP被Cloudflare整站403, 待恢复",
    "investinglive_flash": "原ForexLive, 作为FXStreet同赛道顶替",
    "cls_morning": "专栏id=1151(抓取定位)",
    "japan_morning": "当日RSS过滤",
    "korea_morning": "当日RSS过滤",
    "threads_kol_digest": "数据来自 threads-tw-monitor 本地产物",
    "twitter_kol_flash": "经 FxTwitter 免登录池抓取(媒体官号/数据平台/官方机构)",
    "twitter_kol_views": "经 FxTwitter 免登录池抓取(分析师/交易员/KOL/内部人士)",
    "gangtise": "经搜狗微信链抓取",
    "yuanbao_gangtise": "需 Playwright 登录态; 作为 gangtise 源的可靠替代。首次需 yuanbao_fetch.py --login",
    "peer_mornings": "聚合富途+财联社+AA+BHT+CNBC+日韩台+etnet+SMM+gangtise",
    "extras": "聚合日历+行情+公告+同行",
    "marketaux_news": "备用源; 标题+ticker标注; 免费约100次/天, 需 apiKey",
    "finnhub_news": "备用源; 免费60次/分, 需 apiKey",
    "alphavantage_news": "备用源; 免费仅25次/天, 应急; 需 apiKey",
    "sec_edgar": "备用源; 官方免费, 申报式UA已内置",
    "frankfurter_fx": "备用源; 无key",
    "goldprice_metals": "备用源; 仅黄金, 无key",
    "fred_macro": "备用源; 免费key即申即得",
    "cls_telegraph": "本地签名零key",
    "eastmoney_global": "与财联社电报不同风控面, 可作备胎",
    "cftc_cot": "官方 Socrata 接口",
    "nasdaq_earnings": "周末/假期无数据属正常",
    "gelonghui": "早报聚合17源之一",
    "wscn_live": "官方API零key; 全球频道含非财经条目, 下游粗筛过滤",
    "longbridge_topics": "页内 TanStack 脱水 JSON 解析",
    "jin10_calendar": "2026-08-31起官方CDN域名NXDOMAIN, 待恢复",
    "ths_flash": "与东财/财联社不同风控面",
    "sec_insider": "与 sec_edgar 同端点 type=4",
    "cctv_xwlb": "时政占比高供 synth 背景, 不入早报聚合",
    "stocktwits_stream": "2026-08-31出口IP被Cloudflare拦截, 待恢复",
    "reddit_hot": "需免费 OAuth 凭证",
    "cn_index_snapshot": "新浪 hq 接口, 零key",
    "em_sector_board": "零key",
    "tcmb_fx": "官方XML零key",
    "tcmb_evds": "备用源; 免费key即申即得",
    "cna_flash": "JSON API, 產經分类, 零key",
    "twse_news": "OpenAPI零key; 民国年日期已转换",
    "udn_rss": "RSS零key",
    "ltn_rss": "RSS零key",
    "moneydj_flash": "SSR HTML解析; 其RSS已退化空壳",
    "tw_cbc_stats": "备用源; 官方零key; 2026-08-31本机出口TLS被重置, 待部署环境复测",
    "finmind_news": "备用源; 50+dataset; 免费token即申即得",
    "fed_press": "RSS零key",
    "marketwatch_rt": "零key",
    "treasury_press": "仅 /rss.xml 有效路径",
    "foxbusiness_rss": "英文零key",
    "finviz_news": "纯SSR零key",
    "nyfed_rates": "Markets API 零key",
    "bls_macro": "公共API v1 零key, 日限25次",
    "fiscal_debt": "Fiscal Data 零key免注册",
    "globenewswire": "备用源; 2026-08-31本机出口IP多次ReadTimeout, 疑IDC段限制待复测",
    "hkexnews": "检索API, 零key",
    "mingpao_rss": "盘中高频零key",
    "yahoo_hk_rss": "AASTOCKS AAFN快讯内容, 零key",
    "eastmoney_hkus": "fastColumn=104, 与焦点栏目102不同",
    "hkma_press": "备用源; 官方Open API零key; 2026-08-31本机出口TLS被重置, 待部署环境复测",
    "kap_disclosures": "POST JSON 零key",
    "cnbce_rss": "ttl约5分钟, 单次约250条",
    "yahoo_tw_rss": "ttl=5",
    "twse_mops": "证交所OpenAPI, 零key",
    "tpex_mops": "柜买中心OpenAPI, 零key",
    "fsc_press": "备用源; 2026-08-31本机出口TLS被重置, 待部署环境复测",
    "seekingalpha_rt": "feed自述限 personal/non-commercial, 注意ToS",
    "gdpnow_rss": "无需解析xlsx",
    "finra_press": "必须走http, https握手失败",
    "hkgov_finance": "备用源; 2026-08-31本机出口TLS被重置, 待部署环境复测",
}


_KIND_TO_CHANNEL = {"flash": "media_finance", "peer_article": "media_finance",
                    "announcement": "exchange", "market": "data_vendor",
                    "calendar": "data_vendor"}


def apply(registry: dict) -> None:
    """把 TAGS 回填进 REGISTRY meta(只补空位, 注册时显式给的优先)。

    NOTES 故意不写入 meta, 以免 list_sources / /v1/sources 泄露运维备忘。
    """
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
