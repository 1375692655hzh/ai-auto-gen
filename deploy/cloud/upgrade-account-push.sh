#!/usr/bin/env bash
# 账号成分推送一键升级(2026-09-21) — 在云端数据站仓库根执行(bash deploy/cloud/upgrade-account-push.sh)
# 做: git pull → 幂等合并 ai-workflow/generator/config.local.yaml 的 feishu.account_push 段
#     (现有 app_id/app_secret/watch 不动, 改前备份) → 打印机器人凭证 → dry-run 自检。
# 运行时机制: refresh 每15min轮末调 run_account_push, 函数内部 2h 节流到点才真推,
# 不新增任何 systemd 单元(复用废弃的15min摘要挂点)。
# 前置: 机器人已拉进新群 oc_eb27ec292106627b466b4cd7b8500cbb(否则首推报 230002)。
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO"
PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || PY=python3

echo "== 1/4 git pull =="
git pull --ff-only

echo "== 2/4 幂等合并 feishu.account_push 配置(备份先行) =="
"$PY" - <<'PYEOF'
import datetime, shutil, sys
from pathlib import Path
import yaml
p = Path("ai-workflow/generator/config.local.yaml")
cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
fs = (cfg.setdefault("sources", {}) or {}).get("feishu")
if not isinstance(fs, dict) or not str(fs.get("app_id") or "").strip():
    print("!! 未找到 sources.feishu.app_id — 机器人凭证(2026-09-17)不在预期位置, 手工检查后重跑")
    sys.exit(1)
shutil.copy2(p, p.with_name(f"config.local.backup-{datetime.datetime.now():%Y%m%d-%H%M%S}.yaml"))
ap = fs.setdefault("account_push", {}) or {}
ap.update({"enabled": True, "interval_h": 2, "window_h": 2,
           "chat_id": "oc_eb27ec292106627b466b4cd7b8500cbb", "top_total": 10})
if not (ap.get("accounts") or []):        # 已有账号清单则完全尊重, 只补缺
    ap["accounts"] = [{"name": "Owen聊投资", "owner": "Owen",
                       "mix": {"美股": 60, "亚太股市": 10, "AI与科技": 30}}]
fs["account_push"] = ap
p.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
print(f"配置已合并(备份: config.local.backup-*.yaml; 账号清单 {len(ap['accounts'])} 个)")
PYEOF

echo "== 3/4 机器人凭证(请抄走) =="
grep -E "^\s*(app_id|app_secret):" ai-workflow/generator/config.local.yaml

echo "== 4/4 dry-run 自检(不发群) =="
"$PY" cli.py sources feishu push --dry-run --window 6 | head -60

echo
echo "完成。后续: 账号成分/名称/所有人 改 ai-workflow/generator/config.local.yaml 的"
echo "sources.feishu.account_push.accounts(每轮重读, 改完即生效); 真@提醒给账号条目补"
echo "owner_open_id(ou_..)。手动立即推: $PY cli.py sources feishu push --force"
systemctl is-active aag-refresh.timer >/dev/null 2>&1 \
  && echo "aag-refresh.timer 在跑(15min轮末自动带飞)" \
  || echo "!! aag-refresh.timer 未激活, 推送不会自动发生"
