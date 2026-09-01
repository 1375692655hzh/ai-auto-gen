"""来源磁盘缓存: TTL 内直接读盘, 保护反爬源 + 调试重跑不重复抓。

缓存文件: data/cache/sources/<id>__<conf哈希8位>.json  {"ts": epoch, "items": [...]}
"""

import hashlib
import json
import os
import time
from pathlib import Path


def _cache_dir() -> Path:
    """GNS_DATA_DIR > AAG_ROOT/data > 布局兜底(调用时求值, env 后设也生效)。"""
    env = os.environ.get("GNS_DATA_DIR")
    if env:
        return Path(env) / "cache" / "sources"
    root = os.environ.get("AAG_ROOT")
    if root:
        return Path(root) / "data" / "cache" / "sources"
    return Path(__file__).resolve().parents[2] / "data" / "cache" / "sources"


def _key(source_id: str, conf: dict) -> Path:
    raw = json.dumps(conf or {}, sort_keys=True, ensure_ascii=False)
    h = hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]
    return _cache_dir() / f"{source_id}__{h}.json"


def load(source_id: str, conf: dict, ttl_min: int) -> list | None:
    """TTL 内命中返回 items; 未命中/过期/损坏返回 None。"""
    f = _key(source_id, conf)
    if not f.exists():
        return None
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        if time.time() - d.get("ts", 0) < ttl_min * 60:
            return d.get("items")
    except Exception:
        pass
    return None


def save(source_id: str, conf: dict, items: list) -> None:
    try:
        _cache_dir().mkdir(parents=True, exist_ok=True)
        _key(source_id, conf).write_text(
            json.dumps({"ts": time.time(), "items": items}, ensure_ascii=False),
            encoding="utf-8")
    except Exception:
        pass                              # 缓存写失败不影响主流程
