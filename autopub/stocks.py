"""文章 → 关联上市公司抽取

数据: A股全量(新浪行情列表, ~5700家, 本地缓存 stocks_cache.json)
      + 港/美股常用公司内置表(财经内容高频标的)
用法:
  from stocks import extract
  hits = extract(article_text, top=5)   # -> [(code, name, market)] market: SH/SZ/BJ/HK/US
"""

import json
import re
import time
import urllib.request
from pathlib import Path

CACHE = Path(__file__).resolve().parent / "stocks_cache.json"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0",
       "Referer": "https://finance.sina.com.cn/"}

# 港股/美股常用(代码, 名称, 别名...)
HK_KNOWN = [
    ("1810", "小米集团-W", "小米"),
    ("9988", "阿里巴巴-W", "阿里巴巴", "阿里"),
    ("0700", "腾讯控股", "腾讯"),
    ("3690", "美团-W", "美团"),
    ("9888", "百度集团-SW", "百度"),
    ("9618", "京东集团-SW", "京东"),
    ("9999", "网易-S", "网易"),
    ("1211", "比亚迪股份", "比亚迪"),
    ("0981", "中芯国际", "中芯国际"),
    ("0883", "中国海洋石油", "中海油"),
    ("0857", "中国石油股份", "中石油"),
    ("0386", "中国石油化工股份", "中石化"),
    ("0939", "中国建设银行", "建设银行"),
    ("1398", "工商银行", "工商银行"),
    ("0941", "中国移动", "中国移动"),
    ("2015", "理想汽车-W", "理想汽车", "理想"),
    ("9866", "蔚来-SW", "蔚来"),
    ("9868", "小鹏汽车-W", "小鹏汽车", "小鹏"),
    ("9626", "哔哩哔哩-W", "B站", "哔哩哔哩"),
    ("9961", "携程集团-S", "携程"),
    ("1024", "快手-W", "快手"),
    ("0772", "阅文集团", "阅文"),
    ("0268", "金蝶国际", "金蝶"),
]
US_KNOWN = [
    ("NVDA", "NVIDIA", "英伟达"),
    ("TSLA", "Tesla", "特斯拉"),
    ("AAPL", "Apple", "苹果"),
    ("MSFT", "Microsoft", "微软"),
    ("GOOGL", "Alphabet", "谷歌", "Google"),
    ("AMZN", "Amazon", "亚马逊"),
    ("META", "Meta Platforms", "Meta"),
    ("PDD", "PDD", "拼多多"),
    ("AMD", "AMD", "超威"),
    ("INTC", "Intel", "英特尔"),
    ("QCOM", "QUALCOMM", "高通"),
    ("AVGO", "Broadcom", "博通"),
    ("MU", "Micron", "美光科技", "美光"),
    ("NFLX", "Netflix", "奈飞"),
    ("BABA", "Alibaba", "阿里巴巴美股"),
    ("TSM", "TSMC", "台积电"),
    ("ARM", "Arm", "ARM"),
    ("SNDK", "SanDisk", "闪迪"),
    ("MRNA", "Moderna", "莫德纳"),
    ("CRCL", "Circle", "Circle"),
    ("COIN", "Coinbase", "Coinbase"),
    ("PLTR", "Palantir", "Palantir"),
    ("BA", "Boeing", "波音"),
    ("KO", "Coca-Cola", "可口可乐"),
    ("XOM", "Exxon Mobil", "埃克森美孚"),
]


def _fetch_a() -> list:
    out, page = [], 1
    while True:
        url = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
               "Market_Center.getHQNodeData?page=%d&num=100&sort=symbol&asc=1&node=hs_a" % page)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=30) as r:
                    d = json.loads(r.read().decode("gbk"))
                break
            except Exception:
                if attempt == 2:
                    return out
                time.sleep(1.5)
        if not d:
            break
        out.extend(d)
        if len(d) < 100:
            break
        page += 1
        time.sleep(0.3)
    return out


def _build_cache() -> dict:
    mapping = {}
    for row in _fetch_a():
        sym, name = row.get("symbol", ""), (row.get("name") or "").strip()
        if not sym or not name or len(name) < 2:
            continue
        code = sym[-6:]
        market = "BJ" if sym.startswith("bj") else ("SH" if sym.startswith(("sh", "6")) else "SZ")
        mapping[name] = [code, market]
    for code, name, *aliases in HK_KNOWN:
        for n in [name] + aliases:
            mapping[n] = [code, "HK"]
    for code, name, *aliases in US_KNOWN:
        for n in [name] + aliases:
            mapping[n] = [code, "US"]
    CACHE.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    return mapping


def _load() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass
    m = _build_cache()
    if len(m) < 500:
        raise RuntimeError(f"股票列表拉取不完整({len(m)}条)")
    return m


_SUFFIX = re.compile(r"[-·]([WHABRSPD]{1,3})$")


def extract(text: str, top: int = 5) -> list:
    """从正文抽关联公司, 按出现次数排序。-> [(code, name, market)]"""
    m = _load()
    counts = {}
    for name, (code, market) in m.items():
        if len(name) < 2:
            continue
        n = text.count(name)
        if n > 0:
            base = _SUFFIX.sub("", name)
            key = (code, base, market)
            counts[key] = counts.get(key, 0) + n
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0][1])))[:top]
    return [k for k, _ in ranked]


def tag_text(code: str, name: str, market: str, style: str) -> str:
    """按平台风格生成股票标记文本。"""
    if style == "xueqiu":                 # 雪球 cashtag
        if market == "US":
            return f"${name}({code})$"
        if market == "HK":
            return f"${name}(HK{code})$"
        return f"${name}({code})$"
    if style == "eastmoney":              # 东财 $名字(代码)$
        if market == "US":
            return f"${name}({code}.US)$"
        if market == "HK":
            return f"${name}({code}.HK)$"
        return f"${name}({code})$"
    return name                            # 其他平台: 纯名字(UI 另行关联)


if __name__ == "__main__":
    m = _load()
    print("缓存公司数:", len(m))
    demo = "小米汽车业务爬坡, 英伟达和特斯拉大涨, 贵州茅台创新低, 腾讯发布财报, 宁德时代扩产"
    for code, name, market in extract(demo):
        print(code, name, market, "| 雪球:", tag_text(code, name, market, "xueqiu"),
              "| 东财:", tag_text(code, name, market, "eastmoney"))
