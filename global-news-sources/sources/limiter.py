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


# 二级公共后缀: 取注册域时须多留一段(2026-09-11 修复: finance.sina.com.cn 曾被
# 切成 com.cn, HEAVY 的 sina.com.cn 5s 礼貌间隔从未命中, 所有 *.com.cn 挤一把锁)
_MULTI_TLD = {"com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn", "ac.cn",
              "com.hk", "com.tw", "com.sg", "com.au", "com.br", "com.mx",
              "co.uk", "co.jp", "co.kr", "co.in", "co.za", "or.jp", "ne.jp"}


def _domain_of(url_or_host: str) -> str:
    host = urlparse(url_or_host).netloc or url_or_host
    host = host.split("@")[-1].split(":")[0].lower()   # 剥 userinfo/端口
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _MULTI_TLD:
        return ".".join(parts[-3:])                    # finance.sina.com.cn → sina.com.cn
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


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
