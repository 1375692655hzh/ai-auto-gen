#!/usr/bin/env bash
# 账号成分推送一键升级(2026-09-21; 0923 二修) — 在云端数据站仓库根执行
# (bash deploy/cloud/upgrade-account-push.sh)
# 做: git pull → 幂等合并 config.local.yaml 的 feishu 段(现有凭证/watch 不动, 改前备份)
#   → 可选注入 MiniMax-M3 翻译链头(需先 export AAG_MINIMAX_KEY=sk-.., key 不进仓)
#   → 打印机器人凭证 → dry-run 自检。
# 0923 修复: 配置路径双探测——云端 sparse checkout 无 ai-workflow/ 目录, 真正生效的
#   覆盖文件是 global-news-sources/config.local.yaml(0917 飞书凭证所在); 本机则是
#   ai-workflow/generator/config.local.yaml。按 _cfg_section 同序探测。
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
import datetime, os, shutil, sys
from pathlib import Path
import yaml
# 双探测(与 _cfg_section 同序): ai-workflow 优先, sparse 云端回退 global-news-sources
cands = [Path("ai-workflow/generator/config.local.yaml"),
         Path("global-news-sources/config.local.yaml")]
p = None
for c in cands:
    if c.is_file():
        try:
            fs0 = ((yaml.safe_load(c.read_text(encoding="utf-8")) or {})
                   .get("sources", {}) or {}).get("feishu")
        except Exception:
            continue
        if isinstance(fs0, dict) and str(fs0.get("app_id") or "").strip():
            p = c
            break
if not p:
    print("!! 两条路径都无 sources.feishu.app_id — 机器人凭证不在预期位置, 手工检查后重跑")
    sys.exit(1)
cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
fs = cfg.setdefault("sources", {}).setdefault("feishu", {})
shutil.copy2(p, p.with_name(f"config.local.backup-{datetime.datetime.now():%Y%m%d-%H%M%S}.yaml"))
ap = fs.setdefault("account_push", {}) or {}
ap.update({"enabled": True, "interval_h": 2, "window_h": 2,
           "chat_id": "oc_eb27ec292106627b466b4cd7b8500cbb", "top_total": 10})
ap["doc"] = dict(ap.get("doc") or {})
ap["doc"].update({"enabled": True})   # 飞书电子表格披露(缺云文档权限自动回退消息卡片)
# 账号清单真源 = 仓内 deploy/cloud/account-push-accounts.yaml(腾讯文档2026-09-22录入13号),
# 每次升级覆盖同步; 文件缺失才尊重已有配置/回退示例。
repo_accs_f = Path("deploy/cloud/account-push-accounts.yaml")
if repo_accs_f.is_file():
    lst = (yaml.safe_load(repo_accs_f.read_text(encoding="utf-8")) or {}).get("accounts")
    if isinstance(lst, list) and lst:
        ap["accounts"] = lst
elif not (ap.get("accounts") or []):
    ap["accounts"] = [{"name": "Owenwin888", "owner": "黄正汉",
                       "mix": {"美股": 60, "亚太股市": 10, "AI与科技": 30}}]
# MiniMax-M3 翻译链注入(0923: 兜底翻译主力, 实测3.9s/批·零思考泄漏; key 走 env 防泄密)
mm_key = os.environ.get("AAG_MINIMAX_KEY", "").strip()
lst = [m for m in (fs.get("digest_models") or []) if isinstance(m, dict)]
has_mm = any("minimaxi" in str(m.get("base_url") or "") for m in lst)
if mm_key and not has_mm:
    lst.insert(0, {"base_url": "https://api.minimaxi.com/v1", "api_key": mm_key,
                   "model": "MiniMax-M3",
                   "extra": {"thinking": {"type": "disabled"}, "max_tokens": 16384}})
    fs["digest_models"] = lst
    print("翻译链: MiniMax-M3 已注链头(思考关闭)")
elif has_mm:
    print("翻译链: 已含 MiniMax(幂等跳过)")
else:
    print("翻译链: 未设 AAG_MINIMAX_KEY, 跳过 MiniMax 注入(可选, 现有链继续用)")
fs["account_push"] = ap
p.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
print(f"配置已合并 → {p} (备份: config.local.backup-*.yaml; 账号 {len(ap['accounts'])} 个)")
PYEOF

echo "== 3/4 机器人凭证(请抄走) =="
CFG=""
for c in ai-workflow/generator/config.local.yaml global-news-sources/config.local.yaml; do
  if [ -f "$c" ] && grep -q "app_id:" "$c" 2>/dev/null; then CFG="$c"; break; fi
done
[ -n "$CFG" ] && grep -E "^\s*(app_id|app_secret):" "$CFG" \
  || echo "!! 凭证文件未定位到(不影响推送, 仅展示用)"

echo "== 4/4 dry-run 自检(不发群) =="
"$PY" cli.py sources feishu push --dry-run --window 6 | head -60

echo
echo "完成。后续: 账号成分/名称/所有人 改配置的 sources.feishu.account_push.accounts"
echo "(每轮重读, 改完即生效); 真@提醒给账号条目补 owner_open_id(ou_..)。"
echo "手动立即推: $PY cli.py sources feishu push --force"
systemctl is-active aag-refresh.timer >/dev/null 2>&1 \
  && echo "aag-refresh.timer 在跑(15min轮末自动带飞)" \
  || echo "!! aag-refresh.timer 未激活, 推送不会自动发生"
