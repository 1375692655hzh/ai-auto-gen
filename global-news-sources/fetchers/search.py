"""豆包搜索 Custom 版封装(实时联网信息,给日报详情与解读供证据)。

端点: POST https://open.feedcoopapi.com/search_api/web_search
密钥: autopub/secret.local.json 的 search_api_key 字段,或环境变量 DOUBAO_SEARCH_KEY
配额: 每月免费 500 次(个人账号),所以只在 daily 流水线的入选条目上调用。
"""

import json
import re
import sys

import requests

try:
    from common import AUTOPUB_ROOT
except ImportError:
    from _runtime import AUTOPUB_ROOT

ENDPOINT = "https://open.feedcoopapi.com/search_api/web_search"


def _load_key() -> str:
    import os
    f = AUTOPUB_ROOT / "secret.local.json"
    if f.exists():
        try:
            key = (json.loads(f.read_text(encoding="utf-8")) or {}).get("search_api_key", "")
            if key:
                return key
        except Exception:
            pass
    return os.environ.get("DOUBAO_SEARCH_KEY", "")


def web_search(query: str, count: int = 3, time_range: str = "OneWeek",
               need_content: bool = False) -> list:
    """返回 [{title, site, url, time, summary}],失败抛异常(调用方决定降级)。"""
    key = _load_key()
    if not key:
        raise RuntimeError("未配置搜索密钥:在 autopub/secret.local.json 加 search_api_key 字段,"
                           "或设环境变量 DOUBAO_SEARCH_KEY")
    r = requests.post(ENDPOINT,
                      headers={"Authorization": f"Bearer {key}",
                               "Content-Type": "application/json"},
                      json={"Query": query[:100], "SearchType": "web", "Count": count,
                            "Filter": {"NeedContent": need_content, "NeedUrl": True},
                            "TimeRange": time_range},
                      timeout=25)
    r.raise_for_status()
    data = r.json()
    err = (data.get("ResponseMetadata") or {}).get("Error")
    if err:
        raise RuntimeError(f"搜索接口错误 {err.get('Code')}: {err.get('Message')}")
    out = []
    for w in (data.get("Result") or {}).get("WebResults") or []:
        text = (w.get("Summary") or w.get("Snippet") or "").strip()
        if not text:
            continue
        out.append({"title": w.get("Title", ""), "site": w.get("SiteName", ""),
                    "url": w.get("Url", ""), "time": (w.get("PublishTime") or "")[:10],
                    "text": text[:1500]})
    return out


def search_safe(query: str, **kw) -> list:
    """容错版:失败返回空列表并提示(不中断流水线)。"""
    try:
        return web_search(query, **kw)
    except Exception as e:
        print(f"  ⚠ 搜索失败({str(e)[:80]}),该条目退回原有证据")
        return []


def make_query(item: dict) -> str:
    """从快讯条目提炼搜索词:去括号内容/标点,取前 30 字。"""
    t = re.sub(r"[【】\[\]()（）]", " ", item["text"])
    t = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9 ]+", " ", t)
    return " ".join(t.split())[:30]


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "苹果 折叠屏 iPhone"
    for w in web_search(q):
        print(f"[{w['time']}]({w['site']}) {w['title'][:40]} | {len(w['text'])}字")
