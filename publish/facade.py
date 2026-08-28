"""发布统一门面(板块三)。

职责:
  - 平台矩阵视图(publish/targets.yaml: 14 平台 × 引擎 × 验证状态)
  - 状态聚合(autopub 账本 + 待发队列 + kit 说明)
  - 路由: autopub 引擎 → autopub/publish_all.py 等既有入口(不重写);
          kit 引擎 → 学习包未投产, 显式拒绝而不是静默失败

发布安全语义(继承 autopub/state.py): published/uncertain 跳过, uncertain 需人工核实。
"""

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PUBLISH_ROOT = Path(__file__).resolve().parent


def load_targets() -> dict:
    return (yaml.safe_load((PUBLISH_ROOT / "targets.yaml").read_text(encoding="utf-8"))
            or {}).get("platforms", {})


def platform_status() -> list:
    """平台矩阵: targets.yaml × autopub config enabled。"""
    targets = load_targets()
    try:
        cfg = yaml.safe_load((ROOT / "autopub" / "config.yaml").read_text(encoding="utf-8"))
        plat_cfg = (cfg.get("platforms") or {})
    except Exception:
        plat_cfg = {}
    out = []
    for pid, t in targets.items():
        enabled = bool((plat_cfg.get(pid) or {}).get("enabled"))
        out.append({"id": pid, "title": t.get("title", pid), "engine": t.get("engine"),
                    "enabled": enabled, "verified": t.get("verified", "")})
    return out


def ledger_view() -> dict:
    """统一账本视图: autopub state.json(权威) + kit 平台标注。"""
    targets = load_targets()
    state_f = ROOT / "autopub" / "state.json"
    ledger = {}
    if state_f.exists():
        try:
            ledger = json.loads(state_f.read_text(encoding="utf-8"))
        except Exception:
            ledger = {"<error>": "账本损坏, 见 autopub/state.py 的熔断机制"}
    kit_note = {pid: "kit 学习包未投产, 无账本"
                for pid, t in targets.items() if t.get("engine") == "kit"}
    return {"ledger": ledger, "kit": kit_note,
            "path": str(state_f)}


def run_publish(platforms: list | None = None, draft: bool = False) -> int:
    """统一发布入口: 只路由到 autopub 引擎; kit 平台显式拒绝。"""
    targets = load_targets()
    picked = platforms or []
    bad = [p for p in picked if p in targets and targets[p].get("engine") == "kit"]
    if bad:
        print(f"⚠ {bad} 是 adapters-kit 学习包平台(未投产), 已跳过", file=sys.stderr)
        picked = [p for p in picked if p not in bad]
    import subprocess
    cmd = [sys.executable, str(ROOT / "autopub" / "publish_all.py")]
    if picked:
        cmd += ["--platforms", ",".join(picked)]
    if draft:
        cmd += ["--draft"]
    return subprocess.run(cmd, cwd=str(ROOT)).returncode
