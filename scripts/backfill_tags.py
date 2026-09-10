"""打标回填: tagger 词典/正则更新后, 对存量服务库重跑 enrich, 只补空字段。

口径对齐 store.put(2026-09-09): tickers/event_type/sectors/sentiment 只在原值为空时补,
markets 并集扩展不覆盖。不改 text/时间/聚类等任何其它列。

用法:
    py -3.11 scripts/backfill_tags.py [--db data/serve/items.db] [--dry-run]
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "global-news-sources"))
from sources import tagger  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/serve/items.db")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    db = sqlite3.connect(a.db, timeout=30)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT id, text, tickers, event_type, sectors, markets, sentiment FROM items"
    ).fetchall()
    updated = 0
    for r in rows:
        tag = tagger.enrich(r["text"] or "")
        old_t = json.loads(r["tickers"] or "[]")
        old_s = json.loads(r["sectors"] or "[]")
        old_m = json.loads(r["markets"] or "[]")
        new_t = old_t or tag["tickers"]                 # 只补空, 不覆盖
        new_ev = r["event_type"] or tag["event_type"]
        new_s = old_s or tag["sectors"]
        new_m = old_m + [m for m in tag["markets"] if m not in old_m]
        new_sent = r["sentiment"] or tag["sentiment"]
        if (new_t == old_t and new_ev == (r["event_type"] or "")
                and new_s == old_s and new_m == old_m
                and new_sent == (r["sentiment"] or "")):
            continue
        updated += 1
        if not a.dry_run:
            db.execute(
                "UPDATE items SET tickers=?, event_type=?, sectors=?, markets=?, sentiment=? "
                "WHERE id=?",
                (json.dumps(new_t, ensure_ascii=False), new_ev,
                 json.dumps(new_s, ensure_ascii=False),
                 json.dumps(new_m, ensure_ascii=False), new_sent, r["id"]))
    if not a.dry_run:
        db.commit()
    print(f"scanned {len(rows)}, updated {updated}" + (" (dry-run)" if a.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
