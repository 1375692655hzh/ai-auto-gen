"""来源健康: 连续失败自动标记 dead 并在 gather 时跳过, 修复后 check 复位。

健康文件: data/health/sources-health.json
  {id: {"status": "ok|degraded|dead", "consecutive_failures": n,
        "last_ok": "...", "last_error": "..."}}
"""

import json
from datetime import datetime
from pathlib import Path

HEALTH_FILE = Path(__file__).resolve().parent.parent / "data" / "health" / "sources-health.json"
DEAD_AFTER = 3          # 连续失败 N 次 → dead


def _read() -> dict:
    try:
        return json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def record(source_id: str, ok: bool, error: str = "") -> None:
    d = _read()
    rec = d.get(source_id) or {"consecutive_failures": 0}
    if ok:
        rec.update({"status": "ok", "consecutive_failures": 0,
                    "last_ok": datetime.now().strftime("%Y-%m-%d %H:%M")})
        rec.pop("last_error", None)
    else:
        n = rec.get("consecutive_failures", 0) + 1
        rec.update({"status": "dead" if n >= DEAD_AFTER else "degraded",
                    "consecutive_failures": n, "last_error": error[:200]})
    d[source_id] = rec
    try:
        HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        HEALTH_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    except Exception:
        pass


def is_dead(source_id: str) -> bool:
    return (_read().get(source_id) or {}).get("status") == "dead"


def get(source_id: str) -> dict:
    return _read().get(source_id) or {"status": "unknown"}


def report() -> dict:
    return _read()
