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


def _pool_mtime() -> float:
    """主池与 local 覆盖的最新 mtime——local 变更同样必须触发重读。"""
    mt = 0.0
    for f in (POOL_FILE, POOL_FILE.with_name("twitter_pool.local.yaml")):
        try:
            mt = max(mt, f.stat().st_mtime)
        except OSError:
            pass
    return mt


def _acct_view(a: dict, pos_map: dict) -> dict:
    """池账号行 → 前端视图。load_accounts / manage_payload 共用的单一映射源。"""
    handle = str(a.get("handle") or "").strip().lstrip("@")
    role = str(a.get("role") or "")
    return {
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


def load_accounts(force: bool = False) -> dict:
    """→ {handle_key: account_view}(仅启用账号); mtime 缓存(含 local 覆盖), 变更自动重读。"""
    mtime = _pool_mtime()
    if not force and _cache["accounts"] is not None and _cache["mtime"] == mtime:
        return _cache["accounts"]

    pos_map = _role_positioning_map()
    out = {}
    for a in (_load_raw().get("accounts") or []):
        v = _acct_view(a, pos_map)
        if not v["handle"] or a.get("enabled", True) is False:
            continue
        out[v["handle"].lower()] = v
    _cache["mtime"] = mtime
    _cache["accounts"] = out
    return out


def pool_handles() -> set:
    """全池 handle 键集(含停用账号), 供偏好写入校验防孤儿键。"""
    keys = set(load_accounts())
    for a in (_load_raw().get("accounts") or []):
        h = str(a.get("handle") or "").strip().lstrip("@").lower()
        if h:
            keys.add(h)
    return keys


def manage_payload() -> dict:
    """账号管理页数据面: 全池(含停用) + grok 档案(followers/verified) + 本地偏好。

    启用部分复用 load_accounts()(单一映射源), 仅停用账号补 _acct_view 映射;
    关注/备注写 data/workbench/x_account_prefs.json(板块四唯一写口, 红线7),
    池内字段只读——启停/角色/市场须改池文件或 local 覆盖。
    """
    from . import config as wb_config, x_profile_enricher    # 函数级 import 防环
    live = load_accounts()
    pos_map = _role_positioning_map()
    profiles = x_profile_enricher.load_cache()["profiles"]
    prefs = wb_config.load_x_prefs()
    rows = []
    for a in (_load_raw().get("accounts") or []):
        key = str(a.get("handle") or "").strip().lstrip("@").lower()
        base = live.get(key)
        if base is not None:
            row, enabled = dict(base), True
        else:
            row = _acct_view(a, pos_map)                     # 池内 enabled=False 被滤
            if not row["handle"]:
                continue
            enabled = False
        prof = profiles.get(key) or {}
        pref = prefs.get(key) or {}
        row.update({
            "enabled": enabled,
            "followers": int(prof.get("followers") or 0),
            "verified": bool(prof.get("verified")),
            "bio": str(prof.get("bio") or ""),
            "follow": bool(pref.get("follow")),
            "local_note": str(pref.get("note") or ""),       # 与池内 note 严格区分
        })
        rows.append(row)
    rows.sort(key=lambda r: (not r["follow"], -(r["followers"] or 0), r["handle"]))
    return {"accounts": rows, "count": len(rows),
            "followed_n": sum(1 for r in rows if r["follow"]),
            "disabled_n": sum(1 for r in rows if not r["enabled"]),
            "loaded_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def payload() -> dict:
    accounts = load_accounts()
    return {"accounts": accounts, "count": len(accounts),
            "pool_sources": list(_POOL_SOURCES),
            "loaded_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def pool_account_count(source_id: str) -> int:
    """来源详情用: 池源行标注「池内 N 账号」, 非池源返回 0。"""
    return len(load_accounts()) if source_id in _POOL_SOURCES else 0
