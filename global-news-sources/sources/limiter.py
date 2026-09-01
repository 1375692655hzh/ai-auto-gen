"""域名闸门: 同域名串行+最小间隔+抖动, 防多源并发撞同一风控面(东财系教训)。

refresh 调度逐源调用 gate(url) 后再发请求; 命中 403/429 由 refresh 记健康熔断,
闸门本身只管节奏不管判定。
"""

import random
import threading
import time
from urllib.parse import urlparse

# 高碰撞域(共用风控面), 最小间隔单独压大(秒)
HEAVY = {"eastmoney.com": 5.0, "cls.cn": 5.0, "sina.com.cn": 5.0,
         "wallstreetcn.com": 5.0, "sec.gov": 2.0, "futunn.com": 5.0}
DEFAULT_INTERVAL = (0.8, 1.5)     # 一般域名最小间隔区间(随机抖动)

_locks: dict[str, threading.Lock] = {}
_last: dict[str, float] = {}
_guard = threading.Lock()


def _domain_of(url_or_host: str) -> str:
    host = urlparse(url_or_host).netloc or url_or_host
    parts = host.lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host.lower()


def gate(url_or_host: str) -> None:
    """阻塞到允许向该域名发下一个请求为止。"""
    d = _domain_of(url_or_host)
    with _guard:
        lock = _locks.setdefault(d, threading.Lock())
    with lock:                      # 同域名天然串行
        interval = HEAVY.get(d) or random.uniform(*DEFAULT_INTERVAL)
        gap = time.time() - _last.get(d, 0)
        if gap < interval:
            time.sleep(interval - gap)
        _last[d] = time.time()
