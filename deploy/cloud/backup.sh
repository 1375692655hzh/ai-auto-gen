#!/usr/bin/env bash
# aag 数据站每日备份: SQLite 在线备份(不锁库) + 两份 local 配置, 保留最近 7 份
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
B="$REPO/data/backups"
mkdir -p "$B"
STAMP=$(date +%F)
"$REPO/.venv/bin/python" - "$REPO/data/serve/items.db" "$B/items-$STAMP.db" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
c = sqlite3.connect(src)
d = sqlite3.connect(dst)
c.backup(d)                      # 在线备份 API, 写入中的库也安全
d.close(); c.close()
PY
for f in "$REPO/global-news-sources/config/api_keys.local.json" \
         "$REPO/ai-workflow/generator/config.local.yaml"; do
    [ -f "$f" ] && cp -f "$f" "$B/" || true
done
ls -1t "$B"/items-*.db 2>/dev/null | tail -n +8 | xargs -r rm -f
echo "backup done: $B/items-$STAMP.db"
