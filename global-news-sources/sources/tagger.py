"""规则打标器(P1, 零LLM零token): ticker词典 + 事件类型正则 + 情绪关键词。

在 store.put() 入库瞬间调用 enrich(), 每条新信息即带标。
词典为冷启动种子(2026-09-01), 持续维护: 直接改 TICKERS/别名/blocklist。
设计参照 numichart-news 三通道(代码/名称/别名) + newsboard 关键词分类,
按中文场景改造(裸词通道不可用于中文, 以公司名/代码匹配为主)。
insight 类(peer_article)不打赛道(2026-09-01 用户裁决), 但 ticker/事件/情绪照打。
"""

import re

# ── ticker 宇宙(别名→(代码, 市场, 赛道)) ────────────────────────────────────
# 别名含: 代码本身/英文名/中文名/常见简称。按最长优先匹配。
_T = {
    # 美股·科技/半导体/算力
    "NVDA": ("NVDA", "美股", "半导体>AI芯片"), "英伟达": ("NVDA", "美股", "半导体>AI芯片"),
    "NVIDIA": ("NVDA", "美股", "半导体>AI芯片"),
    "AMD": ("AMD", "美股", "半导体>AI芯片"),
    "AVGO": ("AVGO", "美股", "半导体>IC设计与EDA"), "博通": ("AVGO", "美股", "半导体>IC设计与EDA"),
    "TSM": ("TSM", "美股", "半导体>代工"),
    "INTC": ("INTC", "美股", "半导体>IC设计与EDA"), "英特尔": ("INTC", "美股", "半导体>IC设计与EDA"),
    "QCOM": ("QCOM", "美股", "半导体>IC设计与EDA"), "高通": ("QCOM", "美股", "半导体>IC设计与EDA"),
    "MU": ("MU", "美股", "半导体>存储记忆体"), "美光": ("MU", "美股", "半导体>存储记忆体"),
    "ASML": ("ASML", "美股", "半导体>设备材料"),
    "AMAT": ("AMAT", "美股", "半导体>设备材料"), "应用材料": ("AMAT", "美股", "半导体>设备材料"),
    "ARM": ("ARM", "美股", "半导体>IC设计与EDA"),
    "SMCI": ("SMCI", "美股", "AI与算力>服务器与ODM"), "超微电脑": ("SMCI", "美股", "AI与算力>服务器与ODM"),
    "AAPL": ("AAPL", "美股", "消费电子>苹果链"), "苹果": ("AAPL", "美股", "消费电子>苹果链"),
    "MSFT": ("MSFT", "美股", "互联网与传媒>云与SaaS"), "微软": ("MSFT", "美股", "互联网与传媒>云与SaaS"),
    "GOOGL": ("GOOGL", "美股", "互联网与传媒>社交广告"), "谷歌": ("GOOGL", "美股", "互联网与传媒>社交广告"),
    "AMZN": ("AMZN", "美股", "互联网与传媒>电商"), "亚马逊": ("AMZN", "美股", "互联网与传媒>电商"),
    "META": ("META", "美股", "互联网与传媒>社交广告"),
    "NFLX": ("NFLX", "美股", "互联网与传媒>游戏"), "奈飞": ("NFLX", "美股", "互联网与传媒>游戏"),
    "TSLA": ("TSLA", "美股", "汽车与智能驾驶>整车"), "特斯拉": ("TSLA", "美股", "汽车与智能驾驶>整车"),
    "PLTR": ("PLTR", "美股", "互联网与传媒>云与SaaS"),
    "COIN": ("COIN", "美股", "金融与加密>加密资产"),
    "MSTR": ("MSTR", "美股", "金融与加密>加密资产"),
    "JPM": ("JPM", "美股", "金融与加密>银行"), "摩根大通": ("JPM", "美股", "金融与加密>银行"),
    "GS": ("GS", "美股", "金融与加密>券商"), "高盛": ("GS", "美股", "金融与加密>券商"),
    "XOM": ("XOM", "美股", "油气与能源>油气开采"), "埃克森美孚": ("XOM", "美股", "油气与能源>油气开采"),
    "LLY": ("LLY", "美股", "医药生物>创新药"), "礼来": ("LLY", "美股", "医药生物>创新药"),
    "NVO": ("NVO", "美股", "医药生物>创新药"), "诺和诺德": ("NVO", "美股", "医药生物>创新药"),
    "BA": ("BA", "美股", "军工与航空航天>航空制造"), "波音": ("BA", "美股", "军工与航空航天>航空制造"),
    "DIS": ("DIS", "美股", "互联网与传媒>游戏"), "迪士尼": ("DIS", "美股", "互联网与传媒>游戏"),
    # A股
    "600519": ("600519.SH", "A股", "消费>食品饮料"), "贵州茅台": ("600519.SH", "A股", "消费>食品饮料"),
    "300750": ("300750.SZ", "A股", "新能源与电力>储能"), "宁德时代": ("300750.SZ", "A股", "新能源与电力>储能"),
    "002594": ("002594.SZ", "A股", "汽车与智能驾驶>整车"), "比亚迪": ("002594.SZ", "A股", "汽车与智能驾驶>整车"),
    "601899": ("601899.SH", "A股", "金属与矿业>铜铝"), "紫金矿业": ("601899.SH", "A股", "金属与矿业>铜铝"),
    "600036": ("600036.SH", "A股", "金融与加密>银行"), "招商银行": ("600036.SH", "A股", "金融与加密>银行"),
    "601318": ("601318.SH", "A股", "金融与加密>保险"), "中国平安": ("601318.SH", "A股", "金融与加密>保险"),
    "600030": ("600030.SH", "A股", "金融与加密>券商"), "中信证券": ("600030.SH", "A股", "金融与加密>券商"),
    "002475": ("002475.SZ", "A股", "消费电子>苹果链"), "立讯精密": ("002475.SZ", "A股", "消费电子>苹果链"),
    "300760": ("300760.SZ", "A股", "医药生物>器械"), "迈瑞医疗": ("300760.SZ", "A股", "医药生物>器械"),
    "603259": ("603259.SH", "A股", "医药生物>CXO"), "药明康德": ("603259.SH", "A股", "医药生物>CXO"),
    "688981": ("688981.SH", "A股", "半导体>代工"), "中芯国际": ("688981.SH", "A股", "半导体>代工"),
    "002371": ("002371.SZ", "A股", "半导体>设备材料"), "北方华创": ("002371.SZ", "A股", "半导体>设备材料"),
    "603501": ("603501.SH", "A股", "半导体>IC设计与EDA"), "韦尔股份": ("603501.SH", "A股", "半导体>IC设计与EDA"),
    "300308": ("300308.SZ", "A股", "AI与算力>光通信CPO"), "中际旭创": ("300308.SZ", "A股", "AI与算力>光通信CPO"),
    "300502": ("300502.SZ", "A股", "AI与算力>光通信CPO"), "新易盛": ("300502.SZ", "A股", "AI与算力>光通信CPO"),
    "601138": ("601138.SH", "A股", "AI与算力>服务器与ODM"), "工业富联": ("601138.SH", "A股", "AI与算力>服务器与ODM"),
    "000063": ("000063.SZ", "A股", "通信与卫星>设备"), "中兴通讯": ("000063.SZ", "A股", "通信与卫星>设备"),
    # 台股
    "2330": ("2330.TW", "台湾", "半导体>代工"), "台积电": ("2330.TW", "台湾", "半导体>代工"),
    "台積電": ("2330.TW", "台湾", "半导体>代工"),
    "2317": ("2317.TW", "台湾", "AI与算力>服务器与ODM"), "鸿海": ("2317.TW", "台湾", "AI与算力>服务器与ODM"),
    "鴻海": ("2317.TW", "台湾", "AI与算力>服务器与ODM"),
    "2454": ("2454.TW", "台湾", "半导体>IC设计与EDA"), "联发科": ("2454.TW", "台湾", "半导体>IC设计与EDA"),
    "聯發科": ("2454.TW", "台湾", "半导体>IC设计与EDA"),
    "3711": ("3711.TW", "台湾", "半导体>封测"), "日月光": ("3711.TW", "台湾", "半导体>封测"),
    "2308": ("2308.TW", "台湾", "新能源与电力>电网设备"), "台达电": ("2308.TW", "台湾", "新能源与电力>电网设备"),
    "2382": ("2382.TW", "台湾", "AI与算力>服务器与ODM"), "广达": ("2382.TW", "台湾", "AI与算力>服务器与ODM"),
    "廣達": ("2382.TW", "台湾", "AI与算力>服务器与ODM"),
    # 港股
    "0700": ("0700.HK", "港股", "互联网与传媒>社交广告"), "腾讯": ("0700.HK", "港股", "互联网与传媒>社交广告"),
    "騰訊": ("0700.HK", "港股", "互联网与传媒>社交广告"),
    "9988": ("9988.HK", "港股", "互联网与传媒>电商"), "阿里巴巴": ("9988.HK", "港股", "互联网与传媒>电商"),
    "3690": ("3690.HK", "港股", "消费>零售电商"), "美团": ("3690.HK", "港股", "消费>零售电商"),
    "9618": ("9618.HK", "港股", "互联网与传媒>电商"), "京东": ("9618.HK", "港股", "互联网与传媒>电商"),
    "京東": ("9618.HK", "港股", "互联网与传媒>电商"),
    "1810": ("1810.HK", "港股", "消费电子>安卓链"), "小米": ("1810.HK", "港股", "消费电子>安卓链"),
    "1211": ("1211.HK", "港股", "汽车与智能驾驶>整车"), "比亚迪股份": ("1211.HK", "港股", "汽车与智能驾驶>整车"),
    "0941": ("0941.HK", "港股", "通信与卫星>运营商"), "中国移动": ("0941.HK", "港股", "通信与卫星>运营商"),
}

# 裸英文词 blocklist(这些大写词是日常词, 命中也不算 ticker)
BLOCKLIST = {"FED", "SEC", "IPO", "AI", "US", "USA", "CEO", "CFO", "GDP", "CPI", "ETF",
             "A", "B", "IT", "ALL", "NOW", "NEW", "BIG", "TOP", "LOW", "BUY", "SELL",
             "USD", "EUR", "EV", "FDA", "FBI", "IMF", "WTO", "OPEC", "NATO", "PM",
             "AM", "PMI", "PCE", "API", "APP", "GPU", "CPU", "IPO", "UK", "EU"}

# ── 事件类型正则(有序, 先中先得) ─────────────────────────────────────────────
_EVENT = [
    ("guidance", r"上调.{0,6}(预期|指引|目标)|下调.{0,6}(预期|指引|目标)|guidance|展望.{0,4}(上调|下调|乐观|悲观)"),
    ("earnings", r"财报|业绩快报|营收|净利|每股收益|EPS|earnings|revenue|季报|年报|中报|bilanço|profit"),
    ("rating",   r"评级|目标价|upgrade|downgrade|outperform|underperform|增持评级|减持评级"),
    ("mna",      r"并购|收购|合并|要约|merger|acquisition|takeover|私有化"),
    ("dividend", r"分红|派息|股息|回购|dividend|buyback|repurchase|temettü"),
    ("offering", r"增发|配售|IPO|公开发行|上市首日|offering"),
    ("fda",      r"FDA|获批上市|临床试验|获批.{0,4}药|药.{0,4}获批"),
    ("legal",    r"立案|处罚|罚款|诉讼|起诉|违规|lawsuit|penalty|sanction|制裁|antitrust|反垄断|退市"),
    ("policy",   r"国务院|发改委|工信部|央行新政|监管新规|法案|禁令|policy|regulat"),
    ("macro",    r"美联储|加息|降息|降准|LPR|CPI|通胀|非农|GDP|PMI|FOMC|PCE|社融|Fed\b|ECB|enflasyon|faiz|利率"),
    ("contract", r"中标|签约|大单|合同额|framework agreement|contract"),
    ("personnel", r"辞职|卸任|任命|升任|高管变动|resigns|appoints|new CEO"),
    ("product",  r"发布会|新品|上线|launch|unveil|正式发布"),
]
_EVENT_RE = [(k, re.compile(v, re.I)) for k, v in _EVENT]

# ── 情绪关键词 + 事件语义兜底 ─────────────────────────────────────────────────
_POS = "超预期 增长 大涨 利好 突破 中标 获批 回购 创新高 涨停 净流入 上调 看多 强劲 创纪录 beat surges rally upgrades raises boost".split()
_NEG = "低于预期 下滑 大跌 利空 亏损 处罚 退市 跌停 净流出 下调 看空 疲软 暴雷 违约 裁员 miss plunges downgrades cuts".split()
_EVENT_SENT = {"dividend": "bullish", "contract": "bullish", "legal": "bearish",
               "offering": "bearish"}

_ascii_alias = sorted({a for a in _T if a.isascii()}, key=len, reverse=True)
_cjk_alias = sorted({a for a in _T if not a.isascii()}, key=len, reverse=True)
_ASCII_RE = [(a, re.compile(rf"(?<![A-Za-z0-9]){re.escape(a)}(?![A-Za-z0-9])")) for a in _ascii_alias]


def enrich(text: str, kind: str = "") -> dict:
    """对单条文本打标。返回 {tickers, event_type, sentiment, sectors, matched_terms}。"""
    out = {"tickers": [], "event_type": "", "sentiment": "", "sectors": [], "matched_terms": []}
    if not text:
        return out
    seen_codes = set()
    for alias, rx in _ASCII_RE:                       # 英文别名: 词边界匹配
        if alias in BLOCKLIST:
            continue
        if rx.search(text):
            code, mk, sec = _T[alias]
            if code not in seen_codes:
                seen_codes.add(code)
                out["tickers"].append(code)
                out["matched_terms"].append(alias)
                if sec and sec not in out["sectors"]:
                    out["sectors"].append(sec)
    for alias in _cjk_alias:                          # 中文/代码别名: 子串匹配
        if alias in text:
            code, mk, sec = _T[alias]
            if code not in seen_codes:
                seen_codes.add(code)
                out["tickers"].append(code)
                out["matched_terms"].append(alias)
                if sec and sec not in out["sectors"]:
                    out["sectors"].append(sec)
    for k, rx in _EVENT_RE:                           # 事件类型: 先中先得
        if rx.search(text):
            out["event_type"] = k
            break
    pos = sum(1 for w in _POS if w in text)
    neg = sum(1 for w in _NEG if w in text)
    if pos > neg:
        out["sentiment"] = "bullish"
    elif neg > pos:
        out["sentiment"] = "bearish"
    elif out["event_type"] in _EVENT_SENT:
        out["sentiment"] = _EVENT_SENT[out["event_type"]]
    if kind == "peer_article":                        # insight 类不打赛道(用户裁决)
        out["sectors"] = []
    return out
