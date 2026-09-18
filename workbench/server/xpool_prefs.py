"""X 账号池本机偏好(图文页【账号管理】的 启用/备注 写口, 2026-09-18 用户裁决)。

权限模型照抄 source_prefs(来源详情开关): 工作台是客户级工具, 开关 = "我的视图
隐藏/显示该账号"、备注 = 展示覆盖层——只写 workbench 自有
data/workbench/xpool_prefs.json, 零网络写操作, 不动板块一 twitter_pool.yaml。

shape = {handle_lower: {"enabled": false?, "note": "...", "updated_at": "..."}}:
与旧 x_account_prefs.json 同构(按 handle O(1) 开关的字典式, 勿"顺手"改成行式)。
- 启用 on=False 记 enabled=false → xaccounts._pref_disabled_handles 计入,
  被关账号从图文页数据面(推荐信息/蹭蹭流量/账号管理)隐藏; on=True 清标记回池默认。
- 备注 = 覆盖层: 展示时 note 覆盖池内 note, 池文件本身永不回写。
"""

import json
import os
import tempfile
import time
from pathlib import Path

from . import config

_FILE = "xpool_prefs.json"


def _path() -> Path:
    return Path(config.DATA_DIR) / _FILE


def load() -> dict:
    """→ {handle_lower: pref_dict}; 缺文件/损坏 = 空表(全放行, 与 source_prefs 同宽容)。"""
    try:
        d = json.loads(_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save(prefs: dict) -> dict:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")   # 原子写(同 config.py 模式)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    return prefs


def disabled_handles() -> set:
    """本机视图停用的 handle 集(enabled is False 的键)。"""
    return {h for h, p in load().items()
            if isinstance(p, dict) and p.get("enabled") is False}


def note_overlay(handle: str) -> str:
    """备注覆盖值(未设置 = 空串, 展示侧回退池内 note)。"""
    p = load().get(str(handle or "").strip().lstrip("@").lower()) or {}
    return str(p.get("note") or "") if isinstance(p, dict) else ""


def _update(handle: str, patch: dict, drops: tuple = ()) -> dict:
    """合并 patch / 删除 drops 键后落盘; 空偏好(enabled、note 全无)不落孤儿键。"""
    key = str(handle or "").strip().lstrip("@").lower()
    prefs = load()
    p = prefs.setdefault(key, {})
    p.update(patch)
    for k in drops:
        p.pop(k, None)
    p["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if not any(k in p for k in ("enabled", "note")):
        prefs.pop(key, None)                               # 空偏好不落孤儿键
    save(prefs)
    return {"handle": key, **{k: p[k] for k in ("enabled", "note") if k in p}}


def set_enabled(handle: str, on: bool) -> dict:
    """on=True 恢复看(清本地停用标记, 回池默认); on=False 停看(推荐/蹭流量隐藏)。"""
    out = _update(handle, {} if on else {"enabled": False},
                  drops=("enabled",) if on else ())
    out.setdefault("enabled", True)
    return out


def set_note(handle: str, note: str) -> dict:
    """备注覆盖层(空串 = 清除覆盖, 回显池内 note)。"""
    note = str(note or "").strip()[:200]
    out = _update(handle, {"note": note} if note else {},
                  drops=("note",) if not note else ())
    out["note"] = note
    return out
