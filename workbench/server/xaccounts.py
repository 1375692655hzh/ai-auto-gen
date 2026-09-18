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
POOL_SEED = Path(__file__).resolve().parent / "seed" / "twitter_pool.yaml"  # 稀疏检出兜底
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
    """读主池 + local 覆盖(整条替换, 与 basic.py 同规则)。池缺失=空池不抛(读侧宽容)。
    纯工作台稀疏检出没有板块一目录 → 回退仓内 seed 池(与主池同步维护, scripts/sync_seeds.py)。"""
    if not POOL_FILE.is_file():
        if not POOL_SEED.is_file():
            return {}
        pool = yaml.safe_load(POOL_SEED.read_text(encoding="utf-8")) or {}
    else:
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
    """池账号行 → 前端视图。load_accounts / manage_payload 共用的单一映射源。

    positioning: 池内 per-account 一句话定位(2026-09-18 回填)优先, 缺失回退
    role → ROLE_TO_POSITIONING(旧口径, 池里还没回填的账号仍有着落)。
    tags = 池内概念词列表(3~5个, 回填脚本产出); followers = 池内粉丝量(回填, 可 0)。
    """
    handle = str(a.get("handle") or "").strip().lstrip("@")
    role = str(a.get("role") or "")
    try:
        followers = int(a.get("followers") or 0)
    except (TypeError, ValueError):
        followers = 0
    return {
        "handle": handle,
        "uid": str(a.get("uid") or ""),
        "name": str(a.get("name") or ""),
        "homepage": str(a.get("homepage") or f"https://x.com/{handle}"),
        "markets": [str(m) for m in (a.get("markets") or [])],
        "role": role,
        "positioning": str(a.get("positioning") or "").strip() or pos_map.get(role, ""),
        "tags": [str(t).strip() for t in (a.get("tags") or []) if str(t).strip()],
        "followers": followers,
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
    prefs_off = _pref_disabled_handles()
    out = {}
    for a in (_load_raw().get("accounts") or []):
        v = _acct_view(a, pos_map)
        if not v["handle"] or a.get("enabled", True) is False:
            continue
        if v["handle"].lower() in prefs_off:             # 本地偏好停用(看与不看开关)
            continue
        out[v["handle"].lower()] = v
    _cache["mtime"] = mtime
    _cache["accounts"] = out
    return out


def invalidate() -> None:
    """本机偏好(xpool_prefs)变更后手动失效 load_accounts 缓存——偏好文件不进
    mtime 键, 不失效的话 stats/资讯页要等池文件变化才看到停用生效。"""
    _cache["mtime"] = 0.0
    _cache["accounts"] = None


def _pref_disabled_handles() -> set:
    """本地偏好里被停用的 handle 集: xpool_prefs.json(现行写口, 2026-09-18)
    ∪ x_account_prefs.json(旧写口, 只读兼容存量数据, 不再新写)。"""
    from . import config as wb_config, xpool_prefs
    off = xpool_prefs.disabled_handles()
    prefs = wb_config.load_x_prefs()
    return off | {h for h, p in prefs.items()
                  if isinstance(p, dict) and p.get("enabled") is False}


def disabled_handles() -> set:
    """全量停用集 = 池内 enabled=False + 本地偏好 enabled=False; 供视图/采集过滤(看与不看)。"""
    off = set()
    for a in (_load_raw().get("accounts") or []):
        if a.get("enabled", True) is False:
            h = str(a.get("handle") or "").strip().lstrip("@").lower()
            if h:
                off.add(h)
    return off | _pref_disabled_handles()


def set_enabled(handle: str, on: bool) -> dict:
    """看与不看开关(板块四自有写口 xpool_prefs.json, 池文件保持只读守红线7)。

    本机视图过滤语义(同 source_prefs 模式, 2026-09-18): on=False 停看——推荐信息/
    蹭蹭流量/账号管理全部隐藏该账号; on=True 恢复看(清本地停用标记, 回池默认)。
    """
    from . import xpool_prefs
    key = str(handle or "").strip().lstrip("@").lower()
    if key not in pool_handles():
        raise KeyError(key)
    out = xpool_prefs.set_enabled(key, on)
    invalidate()                                         # 停用立即对 stats/资讯页生效
    return out


def set_note(handle: str, note: str) -> dict:
    """备注覆盖层(写 xpool_prefs.json, 展示时覆盖池内 note; 池文件只读)。"""
    from . import xpool_prefs
    key = str(handle or "").strip().lstrip("@").lower()
    if key not in pool_handles():
        raise KeyError(key)
    return xpool_prefs.set_note(key, note)


def set_follow(handle: str, on: bool) -> dict:
    """关注开关 = 映射 X 账号追踪(追踪页 X 模块数据面): on 加进追踪库
    (x_track.add_account, 复用其结构与写口), off 移出; 关注状态 = 是否在追踪库。"""
    from . import x_track
    key = str(handle or "").strip().lstrip("@").lower()
    if key not in pool_handles():
        raise KeyError(key)
    if on:
        row, err = x_track.add_account(key, note="")
        if err and "已在追踪列表" not in str(err.get("error") or ""):
            raise RuntimeError(str(err.get("error") or "add_failed"))
        if row is not None and not row.get("name"):        # 补池内名称(追踪页展示用)
            src = load_accounts().get(key) or {}
            if src.get("name"):
                with x_track.store_locked():
                    store = x_track.load_store()
                    if key in store["accounts"] and not store["accounts"][key].get("name"):
                        store["accounts"][key]["name"] = src["name"]
                        x_track.save_store(store)
    else:
        x_track.remove_account(key)
    return {"handle": key, "follow": on}


def pool_handles() -> set:
    """全池 handle 键集(含停用账号), 供偏好写入校验防孤儿键。"""
    keys = set(load_accounts())
    for a in (_load_raw().get("accounts") or []):
        h = str(a.get("handle") or "").strip().lstrip("@").lower()
        if h:
            keys.add(h)
    return keys


def manage_payload() -> dict:
    """账号管理页数据面: 全池(含停用) + 档案增强 + 本机偏好合成的行数据。

    列契约(2026-09-18 用户裁决九列): 账号名/@handle/市场/定位/标签/粉丝量/启用/关注/备注。
    - 定位/标签/粉丝量: 池内回填字段(_acct_view), 粉丝缺失回退 grok 档案缓存。
    - 启用/备注写 xpool_prefs.json, 关注映射账号追踪(x_track 库)——三者都是板块四
      自有写口(红线7), twitter_pool.yaml 只读。
    - note_effective = 本机备注覆盖 || 池内 note(展示口径); note_local 只存覆盖值。
    """
    from . import config as wb_config, x_profile_enricher, x_track, xpool_prefs  # 函数级 import 防环
    live = load_accounts()
    pos_map = _role_positioning_map()
    profiles = x_profile_enricher.load_cache()["profiles"]
    prefs = xpool_prefs.load()
    followed = set((x_track.load_store().get("accounts") or {}).keys())
    pref_off = _pref_disabled_handles()
    rows = []
    for a in (_load_raw().get("accounts") or []):
        key = str(a.get("handle") or "").strip().lstrip("@").lower()
        base = live.get(key)
        pool_on = a.get("enabled", True) is not False
        if base is not None:
            row, enabled = dict(base), True
        else:
            row = _acct_view(a, pos_map)                     # 池内 enabled=False 被滤
            if not row["handle"]:
                continue
            enabled = False
        prof = profiles.get(key) or {}
        pref = prefs.get(key) or {}
        note_local = str(pref.get("note") or "") if isinstance(pref, dict) else ""
        row.update({
            "enabled": pool_on and key not in pref_off,      # 生效状态(池 ∧ 本机)
            "pool_enabled": pool_on,                         # 池内原生状态(UI 区分停用来源)
            "followers": row.get("followers") or int(prof.get("followers") or 0),
            "verified": bool(prof.get("verified")),
            "bio": str(prof.get("bio") or ""),
            "follow": key in followed,                       # 关注 = 在账号追踪库
            "note_local": note_local,                        # 本机覆盖值(编辑框回显)
            "note_effective": note_local or row.get("note", ""),  # 展示口径
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
