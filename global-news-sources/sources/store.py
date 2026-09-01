"""对外服务库: SQLite WAL。单机数据站的权威读侧存储(拍板 2026-09-01)。

- 唯一写者: sources/refresh.py(调度进程)。读者: serve(HTTP)/CLI/板块二。
- 幂等去重键: md5(source_id + (url 或 规范化正文前60字))。
- 保留窗: flash 48h / peer_article·announcement 7d / market·calendar 7d。
- 信息标签缺省规则(kind→info_type): announcement→filing, market→data,
  flash→news, peer_article→insight; 条目自带的优先。insight 类不打赛道(裁决)。
"""

import gzip
import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

KIND_TO_INFO_TYPE = {"flash": "news", "peer_article": "insight",
                     "announcement": "filing", "market": "data", "calendar": "calendar"}
RETENTION_HOURS = {"flash": 48, "peer_article": 24 * 7, "announcement": 24 * 7,
                   "market": 24 * 7, "calendar": 24 * 7}


def _serve_dir() -> Path:
    env = os.environ.get("GNS_DATA_DIR")
    if env:
        return Path(env) / "serve"
    root = os.environ.get("AAG_ROOT")
    if root:
        return Path(root) / "data" / "serve"
    return Path(__file__).resolve().parents[2] / "data" / "serve"


def db_path() -> Path:
    return _serve_dir() / "items.db"


def _connect() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS items(
        id TEXT PRIMARY KEY, source_id TEXT, source TEXT, time TEXT, text TEXT,
        title TEXT, url TEXT, media TEXT, kind TEXT, form TEXT, channel TEXT,
        risk TEXT, markets TEXT, lang TEXT, info_type TEXT, sectors TEXT,
        sentiment TEXT, fetched_at TEXT)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_time ON items(time DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_source ON items(source_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_kind ON items(kind)")
    return conn


def _item_id(source_id: str, it: dict) -> str:
    key = (it.get("url") or "") or "".join((it.get("text") or "").split())[:60]
    return hashlib.md5(f"{source_id}|{key}".encode("utf-8")).hexdigest()


def put(source_id: str, meta: dict, items: list) -> int:
    """入库(幂等)。返回新增条数。meta 提供源四标签, 逐条打平避免查询再 join。"""
    if not items:
        return 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    info_default = KIND_TO_INFO_TYPE.get(meta.get("kind", ""), "news")
    rows = []
    for it in items:
        rows.append((
            _item_id(source_id, it), source_id, it.get("source") or meta.get("title", ""),
            it.get("time", ""), it.get("text", "") or "",
            it.get("title", "") or "", it.get("url", "") or "", it.get("media", "") or "",
            meta.get("kind", ""), meta.get("form", ""), meta.get("channel", ""),
            meta.get("risk", ""),
            json.dumps(it.get("markets") or meta.get("markets") or [], ensure_ascii=False),
            meta.get("lang", ""),
            it.get("info_type") or info_default,
            json.dumps(it.get("sectors") or [], ensure_ascii=False),
            it.get("sentiment") or "", now))
    conn = _connect()
    try:
        cur = conn.executemany(
            "INSERT OR IGNORE INTO items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def prune() -> int:
    """按保留窗清理。返回删除条数。"""
    conn = _connect()
    total = 0
    try:
        for kind, hours in RETENTION_HOURS.items():
            cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
            cur = conn.execute("DELETE FROM items WHERE kind=? AND time<?", (kind, cutoff))
            total += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return total


def query(markets: list | None = None, kinds: list | None = None,
          info_types: list | None = None, channels: list | None = None,
          forms: list | None = None, source_ids: list | None = None,
          since: str = "", limit: int = 200, cursor: str = "") -> tuple[list, str]:
    """只读查询。返回 (items, next_cursor)。cursor = 上一页最后一条的 time|id。"""
    sql, args = "SELECT * FROM items WHERE 1=1", []
    if kinds:
        sql += f" AND kind IN ({','.join('?' * len(kinds))})"; args += kinds
    if info_types:
        sql += f" AND info_type IN ({','.join('?' * len(info_types))})"; args += info_types
    if channels:
        sql += f" AND channel IN ({','.join('?' * len(channels))})"; args += channels
    if forms:
        sql += f" AND form IN ({','.join('?' * len(forms))})"; args += forms
    if source_ids:
        sql += f" AND source_id IN ({','.join('?' * len(source_ids))})"; args += source_ids
    if since:
        sql += " AND time>?"; args.append(since)
    if cursor:
        sql += " AND (time<?)"; args.append(cursor.split("|")[0])
    for mk in (markets or []):                    # markets 存 JSON 数组文本, LIKE 匹配
        sql += " AND markets LIKE ?"; args.append(f'%"{mk}"%')
    sql += " ORDER BY time DESC, id LIMIT ?"; args.append(min(limit, 1000) + 1)
    conn = _connect()
    try:
        rows = conn.execute(sql, args).fetchall()
    finally:
        conn.close()
    cols = ["id", "source_id", "source", "time", "text", "title", "url", "media",
            "kind", "form", "channel", "risk", "markets", "lang", "info_type",
            "sectors", "sentiment", "fetched_at"]
    page = rows[:min(limit, 1000)]
    next_cursor = f"{page[-1][3]}|{page[-1][0]}" if len(rows) > len(page) and page else ""
    out = []
    for r in page:
        d = dict(zip(cols, r))
        for k in ("markets", "sectors"):
            try:
                d[k] = json.loads(d[k] or "[]")
            except Exception:
                d[k] = []
        out.append(d)
    return out, next_cursor


def stats() -> dict:
    conn = _connect()
    try:
        n = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        latest = conn.execute("SELECT MAX(time) FROM items").fetchone()[0]
        per_kind = dict(conn.execute(
            "SELECT kind, COUNT(*) FROM items GROUP BY kind").fetchall())
        return {"items": n, "latest_time": latest, "per_kind": per_kind,
                "db": str(db_path())}
    finally:
        conn.close()


def export_snapshot(out_dir: Path | None = None) -> dict:
    """全量导出: latest.json.gz + by-market/*.json.gz + manifest.json(原子替换)。"""
    dist = out_dir or (_serve_dir().parent / "dist")
    dist.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM items ORDER BY time DESC").fetchall()
    finally:
        conn.close()
    cols = ["id", "source_id", "source", "time", "text", "title", "url", "media",
            "kind", "form", "channel", "risk", "markets", "lang", "info_type",
            "sectors", "sentiment", "fetched_at"]
    items = [dict(zip(cols, r)) for r in rows]

    def _write_gz(path: Path, payload: list) -> None:
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            for d in payload:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        os.replace(tmp, path)

    _write_gz(dist / "latest.json.gz", items)
    by_mk: dict[str, list] = {}
    for d in items:
        try:
            mks = json.loads(d.get("markets") or "[]")
        except Exception:
            mks = []
        for mk in (mks or ["未标注"]):
            by_mk.setdefault(mk, []).append(d)
    (dist / "by-market").mkdir(exist_ok=True)
    for mk, arr in by_mk.items():
        _write_gz(dist / "by-market" / f"{mk}.json.gz", arr)
    manifest = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "schema_version": 1, "items": len(items),
                "by_market": {k: len(v) for k, v in by_mk.items()}}
    tmp = dist / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, dist / "manifest.json")
    return manifest
