"""存量迁移 v4→v5(2026-09-03 双标签制, 幂等可重跑, --dry-run 只报告不写)。

步骤: 备份 → markets 改名(旧值存 markets_legacy) → item_type 回填(纯函数投影)
→ positioning 回填(源 meta / X 条目按 author_role 派生) → sectors 漂移归一化
(taxonomy.norm_sector) → 校验报告。
"""
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "global-news-sources"))

from sources import REGISTRY, store
from sources import taxonomy as tax

DRY = "--dry-run" in sys.argv


def main() -> None:
    db = store.db_path()
    conn = store._connect()                          # _migrate 先把 v5 列补齐
    total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    print(f"DB: {db}  条目: {total}  dry_run={DRY}")
    if not DRY:
        bak = db.with_suffix(f".bak-v4-{time.strftime('%Y%m%d-%H%M%S')}")
        conn.close()
        shutil.copy2(db, bak)
        print(f"备份: {bak}")
        conn = store._connect()

    src_meta = {sid: e["meta"] for sid, e in REGISTRY.items()}
    rows = conn.execute(
        "SELECT id, source_id, kind, info_type, markets, sectors, author_role, "
        "item_type, positioning, markets_legacy FROM items").fetchall()

    stats = {"markets_mapped": 0, "item_type_set": 0, "positioning_set": 0,
             "sector_norm": 0, "sector_dropped": 0, "sector_other": 0}
    item_type_dist, pos_dist = {}, {}
    other_strs = {}                                   # 降级到"其他"的漂移串清单
    updates = []
    for rid, sid, kind, info_type, mkts, secs, arole, old_it, old_pos, old_legacy in rows:
        # 1) markets 改名
        try:
            mk_list = json.loads(mkts or "[]")
        except Exception:
            mk_list = []
        new_mk = tax.norm_markets(mk_list)
        mk_changed = new_mk != mk_list
        if mk_changed:
            stats["markets_mapped"] += 1
        # 2) item_type 投影(幂等: 已有值且非空则跳)
        it_type = old_it or tax.derive_item_type(kind, info_type, sid)
        # 3) positioning: X 条目按 role, 其余按源 meta
        pos = old_pos or (tax.ROLE_TO_POSITIONING.get(arole or "")
                          or (src_meta.get(sid) or {}).get("positioning", ""))
        # 4) sectors 归一化
        try:
            sec_list = json.loads(secs or "[]")
        except Exception:
            sec_list = []
        new_secs, seen = [], set()
        for p in sec_list:
            np_ = tax.norm_sector(p)
            if not np_:
                stats["sector_dropped"] += 1
                continue
            if np_ != p:
                stats["sector_norm"] += 1
                parts = np_.split(">")
                if len(parts) >= 2 and parts[1] == "其他" and len(p.split(">")) >= 2:
                    stats["sector_other"] += 1
                    other_strs[p] = other_strs.get(p, 0) + 1
            if np_ not in seen:
                seen.add(np_)
                new_secs.append(np_)
        if not old_it:
            stats["item_type_set"] += 1
        if not old_pos:
            stats["positioning_set"] += 1
        item_type_dist[it_type] = item_type_dist.get(it_type, 0) + 1
        pos_dist[pos] = pos_dist.get(pos, 0) + 1
        updates.append((
            json.dumps(new_mk, ensure_ascii=False),
            json.dumps(mk_list, ensure_ascii=False) if mk_changed else (old_legacy or "[]"),
            it_type, pos,
            json.dumps(new_secs, ensure_ascii=False), rid))

    if not DRY:
        conn.executemany(
            "UPDATE items SET markets=?, markets_legacy=?, item_type=?, "
            "positioning=?, sectors=? WHERE id=?", updates)
        conn.commit()

    # ── 校验报告 ──
    print(f"\n══ 迁移{'预演' if DRY else '完成'} ══")
    print(f"markets 改名条目: {stats['markets_mapped']}")
    print(f"item_type 回填: {stats['item_type_set']}  positioning 回填: {stats['positioning_set']}")
    print(f"赛道路径改正: {stats['sector_norm']}  整条丢弃: {stats['sector_dropped']}  降级其他: {stats['sector_other']}")
    print(f"\nitem_type 分布: {json.dumps(item_type_dist, ensure_ascii=False)}")
    print(f"positioning 分布: {json.dumps(pos_dist, ensure_ascii=False)}")
    bad_type = [k for k in item_type_dist if k not in tax.ITEM_TYPES]
    bad_pos = [k for k in pos_dist if k not in tax.POSITIONINGS]
    print(f"非法 item_type: {bad_type or '无'}  非法 positioning: {bad_pos or '无'}")

    if not DRY:
        # 写后校验: distinct L2 必须 ⊆ 正典
        bad = {}
        for (s,) in conn.execute(
                "SELECT sectors FROM items WHERE sectors!='[]' AND sectors!=''"):
            for p in json.loads(s):
                parts = p.split(">")
                l1 = parts[0]
                l2 = parts[1] if len(parts) > 1 else ""
                if l1 not in tax.L1_L2 or (l2 and l2 not in tax.L1_L2[l1]):
                    bad[p] = bad.get(p, 0) + 1
        print(f"\n写后校验: 枚举外赛道路径 {len(bad)} 种")
        for k, v in sorted(bad.items(), key=lambda x: -x[1])[:20]:
            print(f"  {v:4d}  {k}")
        mk_bad = conn.execute(
            "SELECT COUNT(*) FROM items WHERE markets LIKE '%美股%' OR markets LIKE '%港股%' "
            "OR markets LIKE '%外汇%' OR markets LIKE '%大宗%'").fetchone()[0]
        print(f"旧市场值残留: {mk_bad}")
        n2 = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        print(f"条目数守恒: {total} → {n2} {'✓' if n2 == total else '✗ 不一致!'}")
    else:
        print(f"\n降级'其他'的漂移串 top20:")
        for k, v in sorted(other_strs.items(), key=lambda x: -x[1])[:20]:
            print(f"  {v:4d}  {k}")
    conn.close()


if __name__ == "__main__":
    main()
