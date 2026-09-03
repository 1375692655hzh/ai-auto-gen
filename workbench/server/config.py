"""工作台配置读写(data/workbench/settings.json 是唯一写口)。

shape 本期定型, 上云零改前端:
  source: {mode: local|lan|cloud, base_url, api_key, timeout_s}
  ui:     {theme, page_size, remember_filters}
  cloud:  {endpoint, account, sync_token, sync_enabled, last_synced_at}  # 预留, 本期不消费
追踪账号清单: data/workbench/tracked_accounts.json
data/ 目录已被 gitignore, 配置永不入库。
"""

import json
import os
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]          # workbench/server/config.py → 仓库根
DATA_DIR = REPO / "data" / "workbench"
SETTINGS_FILE = DATA_DIR / "settings.json"
ACCOUNTS_FILE = DATA_DIR / "tracked_accounts.json"

DEFAULTS = {
    "source": {
        "mode": "local",                            # local=本机 | lan=局域网数据站 | cloud=未来云端
        "base_url": "http://127.0.0.1:8787",
        "api_key": "",                              # 仅存服务端, 永不明文回显给浏览器
        "timeout_s": 15,
    },
    "ui": {"theme": "dark", "page_size": 100, "remember_filters": True},
    "cloud": {                                      # 云端同步预留(本期后端不消费)
        "endpoint": "", "account": "", "sync_token": "",
        "sync_enabled": False, "last_synced_at": None,
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        out[k] = _merge(base.get(k, {}), v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load() -> dict:
    try:
        return _merge(DEFAULTS, json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except Exception:
        return json.loads(json.dumps(DEFAULTS))     # 深拷贝出厂默认


def save(cfg: dict) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    merged = _merge(load(), cfg)
    fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")   # 原子写, 防半写损坏
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SETTINGS_FILE)
    return merged


def public_view(cfg: dict) -> dict:
    """回显给浏览器的视图: api_key/sync_token 打码, 不回明文。"""
    v = json.loads(json.dumps(cfg))
    key = v["source"].get("api_key") or ""
    v["source"]["api_key"] = ""
    v["source"]["has_key"] = bool(key)
    v["source"]["key_tail"] = key[-4:] if key else ""
    v["cloud"]["sync_token"] = ""
    v["cloud"]["has_token"] = bool(cfg["cloud"].get("sync_token"))
    return v


def apply_patch(patch: dict) -> dict:
    """设置页保存: api_key 留空表示保持不变(前端不持有明文)。"""
    patch = dict(patch or {})
    src = dict(patch.get("source") or {})
    if "api_key" in src and not src["api_key"]:
        src.pop("api_key")
    if src:
        patch["source"] = src
    return save(_merge(load(), patch))


# ── 通用 JSON 清单存取(追踪账号/草稿/自动化任务, 全部原子写) ─────────────────

def load_rows(name: str) -> list:
    try:
        return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))
    except Exception:
        return []


def save_rows(name: str, rows: list) -> list:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_DIR / name)
    return rows


def load_accounts() -> list:
    return load_rows("tracked_accounts.json")


def save_accounts(rows: list) -> list:
    return save_rows("tracked_accounts.json", rows)


def load_drafts() -> list:
    return load_rows("drafts.json")


def save_drafts(rows: list) -> list:
    return save_rows("drafts.json", rows)


def load_automation() -> list:
    return load_rows("automation.json")


def save_automation(rows: list) -> list:
    return save_rows("automation.json", rows)
