#!/usr/bin/env bash
# aag 数据站云端一键部署(Ubuntu 22.04/24.04 LTS; 需 sudo; 仓库需先 git clone)
# 做四件事: venv 装依赖 → 生成 systemd 单元(serve 常驻/refresh 15min/备份每日) → 启用
# 详细方案与安全基线见 docs/云端部署方案.md
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$REPO/.venv"
echo "仓库: $REPO"

command -v python3 >/dev/null || { echo "缺 python3"; exit 1; }
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" -q install -r "$REPO/global-news-sources/requirements.txt"

UNITS=""
for u in aag-serve.service aag-refresh.service aag-refresh.timer \
         aag-backup.service aag-backup.timer; do
    sed -e "s|@REPO@|$REPO|g" "$REPO/deploy/cloud/$u" | sudo tee "/etc/systemd/system/$u" >/dev/null
done

# 翻译层: 2026-09-14 用户拍板, 数据站不做预翻译(工作台浏览层按需翻译承接),
# 云端默认不装 Node/OmniRoute。确需免费预翻再装: Node≥22 + npm i -g omniroute
# + sudo cp deploy/cloud/aag-omniroute.service /etc/systemd/system/ 并 enable,
# 然后板块根 config.local.yaml 开 sources.translate 并配 oc/mimo-v2.5-free 链
# (HK 出口实测: muse 403 区域封锁 / mimo 可用)。

sudo systemctl daemon-reload
sudo systemctl enable --now aag-serve.service aag-refresh.timer aag-backup.timer $UNITS

sleep 2
systemctl --no-pager is-active aag-serve.service && echo "serve 已监听 127.0.0.1:8787"
systemctl --no-pager list-timers 'aag-*' | head -5
echo
echo "下一步: 填 3 个 local 配置(见 docs/云端部署方案.md 第 4 步) → Caddy HTTPS → ufw"
