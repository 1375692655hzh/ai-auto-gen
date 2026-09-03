"""X 账号池只读视图(资讯页按账号展示的数据供给)。

twitter_kol_flash/views 是池源(FxTwitter 抓 131 账号), 信息流条目带 author_handle,
前端按账号渲染左框需要账号档案。本模块读 global-news-sources/config/twitter_pool.yaml
(只读红线: 不修改板块一任何文件), 键 = handle.lower().lstrip('@')。

local 合并规则镜像 fetchers/basic.py:364-381 —— twitter_pool.local.yaml(gitignored)
同 handle **整条替换**(不是字段级 merge), 两边口径必须一致, 否则前端看到的
账号信息与抓取侧不一致。

账号定位: role → positioning 用 taxonomy.py ROLE_TO_POSITIONING(单一真相, 文件级
import 避免 sys.path 污染; 加载失败回退本地小映射, 漂移风险注释标明)。
"""

import importlib.util
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]               # workbench/server/xaccounts.py → 仓库根
POOL_FILE = REPO / "global-news-sources" / "config" / "twitter_pool.yaml"
TAXONOMY_FILE = REPO / "global-news-sources" / "sources" / "taxonomy.py"

_POOL_SOURCES = ("twitter_kol_flash", "twitter_kol_views")

_cache = {"mtime": 0.0, "accounts": None}


def _role_positioning_map() -> dict:
    """taxonomy.ROLE_TO_POSITIONING 文件级加载; 失败回退(2026-09-03 口径快照)。"""
    try:
        spec = importlib.util.spec_from_file_location("aag_taxonomy_ro", TAXONOMY_FILE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return dict(mod.ROLE_TO_POSITIONING)
    except Exception:
        return {"media": "新闻源", "data_bot": "快讯源", "breaks": "快讯源",
                "company": "机构", "analyst": "大V", "trader": "大V",
                "kol": "大V", "insider": "大V"}


def _load_raw() -> dict:
    """读主池 + local 覆盖(整条替换, 与 basic.py 同规则)。池缺失=空池不抛(读侧宽容)。"""
    if not POOL_FILE.is_file():
        return {}
    pool = yaml.safe_load(POOL_FILE.read_text(encoding="utf-8")) or {}
    loc = POOL_FILE.with_name("twitter_pool.local.yaml")
    if loc.is_file():
        try:
            lp = yaml.safe_load(loc.read_text(encoding="utf-8")) or {}
            base = {str(a.get("handle", "")).lower(): a for a in (pool.get("accounts") or [])}
            for a in (lp.get("accounts") or []):
                base[str(a.get("handle", "")).lower()] = a
            pool["accounts"] = list(base.values())
        except Exception:
            pass
    return pool


def load_accounts(force: bool = False) -> dict:
    """→ {handle_key: account_view}; mtime 缓存, 池文件变更自动重读。"""
    try:
        mtime = POOL_FILE.stat().st_mtime
    except OSError:
        mtime = 0.0
    if not force and _cache["accounts"] is not None and _cache["mtime"] == mtime:
        return _cache["accounts"]

    pos_map = _role_positioning_map()
    out = {}
    for a in (_load_raw().get("accounts") or []):
        handle = str(a.get("handle") or "").strip().lstrip("@")
        if not handle or a.get("enabled", True) is False:
            continue
        key = handle.lower()
        role = str(a.get("role") or "")
        out[key] = {
            "handle": handle,
            "uid": str(a.get("uid") or ""),
            "name": str(a.get("name") or ""),
            "homepage": str(a.get("homepage") or f"https://x.com/{handle}"),
            "markets": [str(m) for m in (a.get("markets") or [])],
            "role": role,
            "positioning": pos_map.get(role, ""),
            "lang": str(a.get("lang") or ""),
            "tier": str(a.get("tier") or ""),
            "priority": str(a.get("priority") or ""),
            "note": str(a.get("note") or ""),
        }
    _cache["mtime"] = mtime
    _cache["accounts"] = out
    return out


def payload() -> dict:
    accounts = load_accounts()
    return {"accounts": accounts, "count": len(accounts),
            "pool_sources": list(_POOL_SOURCES),
            "loaded_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def pool_account_count(source_id: str) -> int:
    """来源详情用: 池源行标注「池内 N 账号」, 非池源返回 0。"""
    return len(load_accounts()) if source_id in _POOL_SOURCES else 0
