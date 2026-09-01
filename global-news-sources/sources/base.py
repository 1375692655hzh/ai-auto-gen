"""来源库基础设施:注册装饰器 + 统一条目构造。

来源条目保持 dict 形态(兼容 generator 侧所有调用方):
  {"time": "2026-08-28 09:30", "text": "...", "source": "新浪7×24"}
  同行文章型额外带 title/media/url。
  信息标签承载位(可选, 2026-09-01 分类体系): markets/info_type/sectors/sentiment

源 meta 四标签(源与信息分类体系.md):
  markets: 市场多选(A股/港股/美股/日本/韩国/台湾/土耳其/全球/外汇/大宗)
  channel: 渠道单选(exchange/media_official/media_finance/data_vendor/
                    broker_research/kol/social_official/aggregator)
  form:    形态单选(morning/flash/view/announce/quote/calendar), 缺省由 kind 推导
  lang:    主语言(zh/en/ja/ko/tr...)
"""

REGISTRY = {}          # id -> {"run": fn(conf)->list, "meta": dict}

KIND_TO_FORM = {"flash": "flash", "peer_article": "morning", "announcement": "announce",
                "market": "quote", "calendar": "calendar",
                "peer_group": "morning", "extras_group": "quote"}


def source(id: str, kind: str, title: str = "", risk: str = "low",
           auth: str = "none", ttl_min: int = 30, default_enabled: bool = False,
           markets: list | None = None, channel: str = "", form: str = "",
           lang: str = "", conf_schema: dict | None = None):
    """注册一个来源。run(conf: dict) -> list[dict]; 失败抛异常(由上层记录健康)。

    markets/channel/form/lang/conf_schema 缺省时由 sources/tags.py 回填表兜底。
    """
    def deco(fn):
        REGISTRY[id] = {
            "run": fn,
            "meta": {"id": id, "kind": kind, "title": title or id,
                     "risk": risk, "auth": auth, "ttl_min": ttl_min,
                     "default_enabled": default_enabled,
                     "markets": markets or [], "channel": channel,
                     "form": form or KIND_TO_FORM.get(kind, "flash"),
                     "lang": lang, "conf_schema": conf_schema or {}},
        }
        return fn
    return deco


def item(time: str, text: str, source_name: str, **extra) -> dict:
    """统一条目构造。time/text/source 必有; 信息标签位(markets/info_type/
    sectors/sentiment)与 url/title/media 等为可选 extra。"""
    d = {"time": time, "text": text, "source": source_name}
    d.update({k: v for k, v in extra.items() if v})
    return d
