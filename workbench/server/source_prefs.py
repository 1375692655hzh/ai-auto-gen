"""来源视图偏好(资讯页「来源详情」开关, 2026-09-18 用户裁决后的语义):

工作台是客户级工具, 开关 = "我的视图隐藏/显示该源"——只写 workbench 自有
data/workbench/source_prefs.json, 零网络写操作, 不影响数据站采集与其他接入者。
(旧语义"透传数据站启停"已废弃: 客户级不该有改服务端配置的通道。)

数据站管理员级的真启停(影响采集)入口 = 数据站控制台/cli sources enable。
"""

import json
import os
import tempfile
from pathlib import Path

from . import config

_FILE = "source_prefs.json"


def _path() -> Path:
    return Path(config.DATA_DIR) / _FILE


def disabled() -> set:
    """本机视图隐藏的源 id 清单(缺文件/损坏 = 空集, 即全放行)。"""
    try:
        d = json.loads(_path().read_text(encoding="utf-8"))
        return {str(x) for x in (d.get("disabled") or [])}
    except Exception:
        return set()


def set_enabled(sid: str, on: bool) -> dict:
    """on=True 从隐藏清单移除, False 加入。返回最新状态。"""
    cur = disabled()
    cur.discard(sid) if on else cur.add(sid)
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"disabled": sorted(cur)}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    return {"id": sid, "hidden": (not on)}
