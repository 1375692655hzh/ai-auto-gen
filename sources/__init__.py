"""来源库(板块一)对外 API。

与旧 generator/sources.py 的 gather/gather_refs 签名与返回值完全兼容,
在其上叠加: 磁盘缓存(TTL) + 健康检查(dead 自动跳过 + 失败记录)。

用法:
  from sources import gather, gather_refs, render_items, render_refs
  items, failed = gather()               # 与旧版一致
  items, err = fetch_one("futu_morning") # 单源抓取(带缓存)
"""

import re
from pathlib import Path

from sources import builtin              # noqa: F401  (触发注册)
from sources.base import REGISTRY
from sources import cache as _cache
from sources import health as _health

_GEN_CFG = Path(__file__).resolve().parent.parent / "generator" / "config.yaml"


def _cfg_section() -> dict:
    """enabled 开关沿用 generator/config.yaml 的 sources: 段(不另起配置)。"""
    try:
        import yaml
        return (yaml.safe_load(_GEN_CFG.read_text(encoding="utf-8")) or {}).get("sources") or {}
    except Exception:
        return {}


def list_sources() -> list:
    """全部已注册来源 + 启用状态 + 健康状态。"""
    sec = _cfg_section()
    out = []
    for sid, e in REGISTRY.items():
        meta = dict(e["meta"])
        conf = sec.get(sid) or {}
        meta["enabled"] = bool(conf.get("enabled", meta["default_enabled"]))
        meta["health"] = _health.get(sid).get("status", "unknown")
        out.append(meta)
    return sorted(out, key=lambda m: (m["kind"], m["id"]))


def fetch_one(source_id: str, conf: dict | None = None, fresh: bool = False):
    """单源抓取(带 TTL 缓存与健康记录)。返回 (items, error); error="" 即成功。"""
    if source_id not in REGISTRY:
        return [], f"未知来源: {source_id} (已注册: {sorted(REGISTRY)})"
    e = REGISTRY[source_id]
    conf = conf or _cfg_section().get(source_id) or {}
    if not fresh:
        hit = _cache.load(source_id, conf, e["meta"]["ttl_min"])
        if hit is not None:
            return hit, ""
    try:
        items = e["run"](conf) or []
    except Exception as ex:
        _health.record(source_id, False, f"{type(ex).__name__}: {ex}")
        return [], f"{type(ex).__name__}: {str(ex)[:120]}"
    _health.record(source_id, True)
    _cache.save(source_id, conf, items)
    return items, ""


def gather(cfg: dict | None = None, limit: int = 0, fresh: bool = False) -> tuple:
    """抓所有启用的快讯来源, 去重、按时间倒序。返回 (条目列表, 挂掉的来源)。

    dead 来源自动跳过(在 failed 里标注), 其余语义与旧版一致。
    """
    sec = cfg if cfg is not None else _cfg_section()
    items, failed = [], []
    for sid, e in REGISTRY.items():
        if e["meta"]["kind"] != "flash":
            continue
        conf = sec.get(sid) or {}
        if not conf.get("enabled", e["meta"]["default_enabled"]):
            continue
        if _health.is_dead(sid):
            failed.append(f"{sid}(dead,自动跳过, 修复后 cli sources check --id {sid} 复位)")
            continue
        got, err = fetch_one(sid, conf, fresh=fresh)
        if err:
            failed.append(f"{sid}({err})")
        elif got:
            items.extend(got)
        else:
            failed.append(f"{sid}(空结果)")
    # 去重:正文相同取时间新的(与旧版一致)
    seen, deduped = set(), []
    for it in sorted(items, key=lambda x: x["time"], reverse=True):
        k = re.sub(r"\s", "", it["text"])[:60]
        if k in seen:
            continue
        seen.add(k)
        deduped.append(it)
    if limit and len(deduped) > limit:
        deduped = deduped[:limit]
    return deduped, failed


def gather_refs(cfg: dict | None = None, fresh: bool = False) -> tuple:
    """抓启用的同行早报文章, 按时间倒序。返回 (文章列表, 挂掉的来源)。"""
    sec = cfg if cfg is not None else _cfg_section()
    refs, failed = [], []
    for sid, e in REGISTRY.items():
        if e["meta"]["kind"] != "peer_article":
            continue
        conf = sec.get(sid) or {}
        if not conf.get("enabled", e["meta"]["default_enabled"]):
            continue
        if _health.is_dead(sid):
            failed.append(f"{sid}(dead,自动跳过)")
            continue
        got, err = fetch_one(sid, conf, fresh=fresh)
        if err:
            failed.append(f"{sid}({err})")
        elif got:
            refs.extend(got)
        else:
            failed.append(f"{sid}(空结果)")
    refs.sort(key=lambda x: x["time"], reverse=True)
    return refs, failed


def render_items(items: list) -> str:
    return "\n".join(f"[{it['time']}]({it['source']}) {it['text']}" for it in items)


def render_refs(refs: list) -> str:
    return "\n\n".join(f"《{r['title']}》({r['media']} {r['time']})\n{r['text']}"
                       for r in refs)
