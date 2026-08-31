"""来源库基础设施:注册装饰器 + 统一条目构造。

来源条目保持 dict 形态(兼容 generator 侧所有调用方):
  {"time": "2026-08-28 09:30", "text": "...", "source": "新浪7×24"}
  同行文章型额外带 title/media/url。
"""

REGISTRY = {}          # id -> {"run": fn(conf)->list, "meta": dict}


def source(id: str, kind: str, title: str = "", risk: str = "low",
           auth: str = "none", ttl_min: int = 30, default_enabled: bool = False):
    """注册一个来源。run(conf: dict) -> list[dict]; 失败抛异常(由上层记录健康)。"""
    def deco(fn):
        REGISTRY[id] = {
            "run": fn,
            "meta": {"id": id, "kind": kind, "title": title or id,
                     "risk": risk, "auth": auth, "ttl_min": ttl_min,
                     "default_enabled": default_enabled},
        }
        return fn
    return deco


def item(time: str, text: str, source_name: str, **extra) -> dict:
    d = {"time": time, "text": text, "source": source_name}
    d.update({k: v for k, v in extra.items() if v})
    return d
