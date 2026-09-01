"""源四标签回填表(2026-09-01 分类体系落地): 市场/渠道/语言。

@source 注册时未显式给 markets/channel/lang 的, 由本表补齐;
本表也没有的, 兜底: markets=[] / channel 按 kind 推导 / lang=""。
修法: 直接改 TAGS 里对应行, 不要动 builtin.py 的 110 处注册。

channel 枚举: exchange 交易所/监管/政府官方 | media_official 官媒通讯社 |
  media_finance 财经媒体 | data_vendor 数据商/终端 | broker_research 券商投顾研究 |
  kol 社交个人 | social_official 社交平台机构号 | aggregator 自建聚合
"""

#            id:                         (markets,                                   channel,            lang, form覆盖)
TAGS = {
    # ── A股/中国 ──
    "cctv_xwlb":            (["A股"],                    "media_official",  "zh", ""),
    "cninfo_latest":        (["A股"],                    "exchange",        "zh", ""),
    "nbs_pmi":              (["A股"],                    "exchange",        "zh", ""),
    "pboc_social_financing": (["A股"],                   "exchange",        "zh", ""),
    "sina_7x24":            (["A股", "全球"],            "data_vendor",     "zh", ""),
    "sina_vip":             (["A股"],                    "kol",             "zh", "view"),
    "eastmoney_fast":       (["A股"],                    "data_vendor",     "zh", ""),
    "eastmoney_zaozhidao":  (["A股"],                    "data_vendor",     "zh", ""),
    "em_research":          (["A股"],                    "broker_research", "zh", ""),
    "em_sector_board":      (["A股"],                    "data_vendor",     "zh", ""),
    "cn_index_snapshot":    (["A股"],                    "data_vendor",     "zh", ""),
    "cls_telegraph":        (["A股", "全球"],            "media_finance",   "zh", ""),
    "cls_morning":          (["A股", "全球"],            "media_finance",   "zh", ""),
    "cls_announcements":    (["A股"],                    "media_finance",   "zh", ""),
    "caixin_flash":         (["A股", "全球"],            "media_finance",   "zh", ""),
    "ths_flash":            (["A股", "全球"],            "data_vendor",     "zh", ""),
    "wscn_breakfast":       (["A股", "全球"],            "media_finance",   "zh", ""),
    "wscn_live":            (["全球"],                   "media_finance",   "zh", ""),
    "gangtise":             (["A股"],                    "broker_research", "zh", ""),
    "yuanbao_gangtise":     (["A股"],                    "broker_research", "zh", ""),
    "eastmoney_global":     (["美股", "港股", "全球"],   "data_vendor",     "zh", ""),
    "eastmoney_hkus":       (["港股", "美股"],           "data_vendor",     "zh", ""),
    "gelonghui":            (["港股", "美股", "A股"],    "media_finance",   "zh", ""),
    # ── 港股 ──
    "hkexnews":             (["港股"],                   "exchange",        "zh", ""),
    "hkex_press":           (["港股"],                   "exchange",        "zh", ""),
    "hkgov_finance":        (["港股"],                   "exchange",        "zh", ""),
    "hkma_press":           (["港股"],                   "exchange",        "zh", ""),
    "sfc_press":            (["港股"],                   "exchange",        "zh", ""),
    "rthk_finance":         (["港股"],                   "media_official",  "zh", ""),
    "mingpao_rss":          (["港股"],                   "media_finance",   "zh", ""),
    "scmp_biz_rss":         (["港股"],                   "media_finance",   "en", ""),
    "etnet_open":           (["港股"],                   "media_finance",   "zh", ""),
    "yahoo_hk_rss":         (["港股"],                   "data_vendor",     "zh", ""),
    "futu_morning":         (["港股", "美股"],           "broker_research", "zh", ""),
    "longbridge_topics":    (["港股", "美股"],           "broker_research", "zh", ""),
    # ── 台股 ──
    "twse_mops":            (["台湾"],                   "exchange",        "zh", ""),
    "twse_news":            (["台湾"],                   "exchange",        "zh", ""),
    "tpex_mops":            (["台湾"],                   "exchange",        "zh", ""),
    "fsc_press":            (["台湾"],                   "exchange",        "zh", ""),
    "tw_cbc_stats":         (["台湾"],                   "exchange",        "zh", ""),
    "cna_flash":            (["台湾"],                   "media_official",  "zh", ""),
    "cnyes_tw":             (["台湾"],                   "media_finance",   "zh", ""),
    "moneydj_flash":        (["台湾"],                   "data_vendor",     "zh", ""),
    "ltn_rss":              (["台湾"],                   "media_finance",   "zh", ""),
    "udn_rss":              (["台湾"],                   "media_finance",   "zh", ""),
    "yahoo_tw_rss":         (["台湾"],                   "data_vendor",     "zh", ""),
    "technews_rss":         (["台湾"],                   "media_finance",   "zh", ""),
    "finmind_news":         (["台湾"],                   "data_vendor",     "zh", ""),
    "threads_kol_digest":   (["台湾"],                   "aggregator",      "zh", "view"),
    # ── 美股/官方机构 ──
    "fed_press":            (["美股", "全球"],           "exchange",        "en", ""),
    "treasury_press":       (["美股"],                   "exchange",        "en", ""),
    "treasury_yield_curve": (["美股"],                   "exchange",        "en", ""),
    "fiscal_debt":          (["美股"],                   "exchange",        "en", ""),
    "bea_rss":              (["美股"],                   "exchange",        "en", ""),
    "bls_macro":            (["美股"],                   "exchange",        "en", ""),
    "nyfed_rates":          (["美股"],                   "exchange",        "en", ""),
    "gdpnow_rss":           (["美股"],                   "exchange",        "en", ""),
    "liberty_street":       (["美股"],                   "exchange",        "en", ""),
    "sec_edgar":            (["美股"],                   "exchange",        "en", ""),
    "sec_insider":          (["美股"],                   "exchange",        "en", ""),
    "sec_press":            (["美股"],                   "exchange",        "en", ""),
    "finra_press":          (["美股"],                   "exchange",        "en", ""),
    "nasdaq_earnings":      (["美股"],                   "exchange",        "en", ""),
    "cftc_cot":             (["大宗", "外汇", "美股"],   "exchange",        "en", ""),
    # ── 美股/媒体与数据商 ──
    "cnbc_morning":         (["美股", "全球"],           "media_finance",   "en", ""),
    "benzinga_rss":         (["美股"],                   "media_finance",   "en", ""),
    "foxbusiness_rss":      (["美股"],                   "media_finance",   "en", ""),
    "marketwatch_rt":       (["美股"],                   "media_finance",   "en", ""),
    "seekingalpha_rt":      (["美股"],                   "media_finance",   "en", ""),
    "newsquawk_open":       (["美股", "全球"],           "media_finance",   "en", ""),
    "prnewswire":           (["美股", "全球"],           "media_finance",   "en", ""),
    "globenewswire":        (["美股", "全球"],           "media_finance",   "en", ""),
    "yahoo_headlines":      (["美股"],                   "data_vendor",     "en", ""),
    "finnhub_news":         (["美股"],                   "data_vendor",     "en", ""),
    "marketaux_news":       (["美股"],                   "data_vendor",     "en", ""),
    "alphavantage_news":    (["美股"],                   "data_vendor",     "en", ""),
    "fred_macro":           (["美股"],                   "data_vendor",     "en", ""),
    "finviz_news":          (["美股"],                   "data_vendor",     "en", ""),
    "stocktwits_stream":    (["美股"],                   "kol",             "en", ""),
    "reddit_hot":           (["美股"],                   "kol",             "en", ""),
    # ── 外汇/大宗/预测市场 ──
    "fxstreet_flash":       (["外汇"],                   "media_finance",   "en", ""),
    "investinglive_flash":  (["外汇", "美股"],           "media_finance",   "en", ""),
    "frankfurter_fx":       (["外汇"],                   "data_vendor",     "en", ""),
    "smm_metals":           (["大宗", "A股"],            "data_vendor",     "zh", ""),
    "miningcom":            (["大宗"],                   "media_finance",   "en", ""),
    "goldprice_metals":     (["大宗"],                   "data_vendor",     "en", ""),
    "eia_energy":           (["大宗", "美股"],           "exchange",        "en", ""),
    "polymarket_sentiment": (["全球"],                   "data_vendor",     "en", ""),
    # ── 日本/韩国 ──
    "japan_morning":        (["日本"],                   "media_official",  "ja", ""),
    "korea_morning":        (["韩国"],                   "media_official",  "ko", ""),
    # ── 土耳其 ──
    "kap_disclosures":      (["土耳其"],                 "exchange",        "tr", ""),
    "tcmb_press":           (["土耳其"],                 "exchange",        "tr", ""),
    "tcmb_fx":              (["土耳其", "外汇"],         "exchange",        "tr", ""),
    "tcmb_evds":            (["土耳其"],                 "exchange",        "tr", ""),
    "aa_morning":           (["土耳其", "全球"],         "media_official",  "en", ""),
    "turkey_morning":       (["土耳其"],                 "media_finance",   "tr", ""),
    "cnbce_rss":            (["土耳其"],                 "media_finance",   "tr", ""),
    "dunya_rss":            (["土耳其"],                 "media_finance",   "tr", ""),
    "foreks_rss":           (["土耳其"],                 "data_vendor",     "tr", ""),
    "dailysabah_rss":       (["土耳其"],                 "media_finance",   "en", ""),
    "hurriyet_rss":         (["土耳其"],                 "media_finance",   "en", ""),
    "sabah_rss":            (["土耳其"],                 "media_finance",   "tr", ""),
    # ── X 大V池(分区随池子走, 这里是池级标签) ──
    "twitter_kol_flash":    (["土耳其", "台湾", "全球"], "kol",             "", ""),
    "twitter_kol_views":    (["土耳其", "台湾", "全球"], "kol",             "", "view"),
    # ── 全球/聚合 ──
    "jin10_flash":          (["全球"],                   "data_vendor",     "zh", ""),
    "jin10_calendar":       (["全球"],                   "data_vendor",     "zh", ""),
    "calendar":             (["全球"],                   "aggregator",      "zh", ""),
    "global_markets":       (["全球"],                   "aggregator",      "zh", ""),
    "peer_mornings":        (["全球"],                   "aggregator",      "zh", ""),
    "extras":               (["全球"],                   "aggregator",      "zh", ""),
}

_KIND_TO_CHANNEL = {"flash": "media_finance", "peer_article": "media_finance",
                    "announcement": "exchange", "market": "data_vendor",
                    "calendar": "aggregator",
                    "peer_group": "aggregator", "extras_group": "aggregator"}


def apply(registry: dict) -> None:
    """把 TAGS 回填进 REGISTRY meta(只补空位, 注册时显式给的优先)。"""
    for sid, e in registry.items():
        m = e["meta"]
        t = TAGS.get(sid)
        if t:
            markets, channel, lang, form = t
            if not m.get("markets"):
                m["markets"] = markets
            if not m.get("channel"):
                m["channel"] = channel
            if not m.get("lang"):
                m["lang"] = lang
            if form:
                m["form"] = form
        if not m.get("channel"):
            m["channel"] = _KIND_TO_CHANNEL.get(m.get("kind", ""), "media_finance")
