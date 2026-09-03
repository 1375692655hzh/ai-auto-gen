"""来源库(板块一)对外 API。

与旧 generator/sources.py 的 gather/gather_refs 签名与返回值完全兼容,
在其上叠加: 磁盘缓存(TTL) + 健康检查(dead 自动跳过 + 失败记录)。

用法:
  from sources import gather, gather_refs, gather_by, render_items, render_refs
  items, failed = gather()               # 与旧版一致
  items, err = fetch_one("futu_morning") # 单源抓取(带缓存)
  items, failed = gather_by(markets=["美股"], kinds=["flash"])  # 按标签聚合(2026-09-01)

路径约定(2026-09-01 显式化): AAG_ROOT 环境变量指定项目根, GNS_DATA_DIR 指定数据目录;
不设时回退仓库布局启发式(parents[2]), 独立下载板块时落板块根。
"""

import os
import re
from pathlib import Path

IMPORT_ERRORS = []          # 防炸库: 注册期异常记这里, 已注册条目继续可用
try:
    from sources import builtin              # noqa: F401  (触发注册; 中途异常时保留已注册部分)
except Exception as _ex:                     # 单文件异常不拖垮整个 CLI
    IMPORT_ERRORS.append(f"builtin 注册中断(已注册的源不受影响): {type(_ex).__name__}: {_ex}")
from sources.base import REGISTRY
from sources import tags as _tags
_tags.apply(REGISTRY)
from sources import cache as _cache
from sources import health as _health


def proj_root() -> Path:
    """AAG_ROOT > 布局启发式(向上找含 ai-workflow 或 auto-publisher 的目录) > 板块根。"""
    env = os.environ.get("AAG_ROOT")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for p in [here.parents[1]] + list(here.parents[1].parents):
        if (p / "ai-workflow").is_dir() or (p / "auto-publisher").is_dir():
            return p
    return here.parents[1]


def data_dir() -> Path:
    """GNS_DATA_DIR > AAG_ROOT/data > 布局兜底 data/。"""
    env = os.environ.get("GNS_DATA_DIR")
    if env:
        return Path(env)
    return proj_root() / "data"


_PROJ = proj_root()
_GEN_CFG = _PROJ / "ai-workflow" / "generator" / "config.yaml"
if not _GEN_CFG.exists():
    _GEN_CFG = Path(__file__).resolve().parent.parent / "config.yaml"


def _cfg_section() -> dict:
    """enabled 开关沿用 ai-workflow/generator/config.yaml 的 sources: 段(不另起配置)。

    本机覆盖(2026-09-01 分发场景): 同目录 config.local.yaml(gitignored) 的 sources:
    段逐源深合并——同事本机调参不动库文件, git pull 不冲突。
    """
    out = {}
    try:
        import yaml
        out = (yaml.safe_load(_GEN_CFG.read_text(encoding="utf-8")) or {}).get("sources") or {}
    except Exception:
        pass
    loc = _GEN_CFG.with_name("config.local.yaml")
    if loc.exists():
        try:
            import yaml
            over = (yaml.safe_load(loc.read_text(encoding="utf-8")) or {}).get("sources") or {}
            for sid, c in over.items():
                if isinstance(c, dict) and isinstance(out.get(sid), dict):
                    out[sid] = {**out[sid], **c}
                else:
                    out[sid] = c
        except Exception:
            pass
    return out


def list_sources(markets: list | None = None, channels: list | None = None,
                 forms: list | None = None, kinds: list | None = None,
                 positionings: list | None = None) -> list:
    """全部已注册来源 + 启用状态 + 健康状态。可按市场/定位/渠道(旧)/形态/kind 过滤。
    2026-09-03 双标签制: markets 输入接受旧别名(美股→美国等); 新增 positionings。"""
    from sources.taxonomy import norm_markets
    if markets:
        markets = norm_markets(list(markets))
    sec = _cfg_section()
    out = []
    for sid, e in REGISTRY.items():
        meta = dict(e["meta"])
        conf = sec.get(sid) or {}
        meta["enabled"] = bool(conf.get("enabled", meta["default_enabled"]))
        meta["health"] = _health.get(sid).get("status", "unknown")
        out.append(meta)
    if markets:
        ms = set(markets)
        out = [m for m in out if ms & set(m.get("markets") or [])]
    if channels:
        out = [m for m in out if m.get("channel") in channels]
    if positionings:
        out = [m for m in out if m.get("positioning") in positionings]
    if forms:
        out = [m for m in out if m.get("form") in forms]
    if kinds:
        out = [m for m in out if m.get("kind") in kinds]
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
    if items:                      # 空结果不写缓存(避免偶发空返回被缓存数小时)
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


def gather_by(markets: list | None = None, kinds: list | None = None,
              channels: list | None = None, forms: list | None = None,
              source_ids: list | None = None, cfg: dict | None = None,
              limit: int = 0, fresh: bool = False) -> tuple:
    """按标签聚合抓取(通用版 gather)。返回 (条目列表, 挂掉的来源)。

    过滤维度全部可选且可组合; 都不给 = 全部启用源(含 market/announcement,
    与旧 gather 只抓 flash 不同)。默认遵循 TTL 缓存; fresh=True 强制重抓。
    """
    sec = cfg if cfg is not None else _cfg_section()
    items, failed = [], []
    for m in list_sources(markets=markets, kinds=kinds, channels=channels, forms=forms):
        sid = m["id"]
        if source_ids and sid not in source_ids:
            continue
        if m["kind"] in ("peer_group", "extras_group"):
            continue                                  # 聚合组不是叶子源
        if not m["enabled"] and not source_ids:
            continue                                  # 显式点名(--ids)不受 enabled 约束
        if _health.is_dead(sid):
            failed.append(f"{sid}(dead,自动跳过, 修复后 cli sources check --id {sid} 复位)")
            continue
        got, err = fetch_one(sid, sec.get(sid) or {}, fresh=fresh)
        if err:
            failed.append(f"{sid}({err})")
        elif got:
            items.extend(got)
        else:
            failed.append(f"{sid}(空结果)")
    seen, deduped = set(), []
    for it in sorted(items, key=lambda x: x.get("time", ""), reverse=True):
        k = re.sub(r"\s", "", it.get("text", ""))[:60]
        if k and k in seen:
            continue
        seen.add(k)
        deduped.append(it)
    if limit and len(deduped) > limit:
        deduped = deduped[:limit]
    return deduped, failed


def render_items(items: list) -> str:
    return "\n".join(f"[{it['time']}]({it['source']}) {it['text']}" for it in items)


def render_refs(refs: list) -> str:
    return "\n\n".join(f"《{r['title']}》({r['media']} {r['time']})\n{r['text']}"
                       for r in refs)
