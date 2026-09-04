"""对外服务库 v2: SQLite WAL。单机数据站的权威读侧存储。

v1(2026-09-01): 基础存储。v2(同日拍板): URL规范化去重 + 相似标题簇(clusters表)
+ 规则打标(tagger) + 时间可信位 + q检索 + dedup折叠 + cursor跳项修复。
v5(2026-09-03 双标签制): +item_type(聚合/快讯/资讯/分析, kind×info_type 纯函数投影)
+positioning(官方/机构/大V/快讯源/新闻源, 源定位/X按author_role派生)
+markets_legacy(市场改名前留档); markets 统一新8值域(继承源/账号 + ticker并集扩展)。

- 唯一写者: sources/refresh.py(调度进程)。读者: serve(HTTP)/CLI/板块二。
- 精确去重键: md5(source_id + (canonical_url 或 规范化正文前60字))。
- 模糊去重: 轮末 link_dups() 批量归并(bigram倒排+数字/极性硬否决), 不丢弃只挂簇。
- 保留窗: flash 48h / 其他 7d。prune 同步清理簇。
- 信息标签: info_type 按 kind 缺省(六值内部细类); item_type 四值由 taxonomy 投影;
  tickers/event_type/sentiment/sectors 由 tagger.enrich 规则打标; llm_tag 精修(M4)。
  枚举单一真相: sources/taxonomy.py。
"""

import gzip
import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

from sources import tagger as _tagger
from sources import taxonomy as _tax

KIND_TO_INFO_TYPE = {"flash": "news", "peer_article": "analysis",
                     "announcement": "filing", "market": "data", "calendar": "calendar"}
RETENTION_HOURS = {"flash": 48, "peer_article": 24 * 7, "announcement": 24 * 7,
                   "market": 24 * 7, "calendar": 24 * 7}
SCHEMA_VERSION = 5
_COLS = ["id", "source_id", "source", "time", "text", "title", "url", "media",
         "kind", "form", "channel", "risk", "markets", "lang", "info_type",
         "sectors", "sentiment", "fetched_at",
         "canonical_url", "title_norm", "cluster_id", "dup_count", "dup_scope",
         "published_at_known", "matched_terms", "tickers", "event_type",
         "author_role", "author_handle",
         "text_zh", "title_zh", "lang_detected", "zh_status", "zh_attempts",
         "item_type", "positioning", "markets_legacy"]


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
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """幂等迁移: 缺列补列, 缺表建表。schema_meta 记录版本。"""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta(k TEXT PRIMARY KEY, v TEXT)")
    base = """CREATE TABLE IF NOT EXISTS items(
        id TEXT PRIMARY KEY, source_id TEXT, source TEXT, time TEXT, text TEXT,
        title TEXT, url TEXT, media TEXT, kind TEXT, form TEXT, channel TEXT,
        risk TEXT, markets TEXT, lang TEXT, info_type TEXT, sectors TEXT,
        sentiment TEXT, fetched_at TEXT)"""
    conn.execute(base)
    have = {r[1] for r in conn.execute("PRAGMA table_info(items)")}
    new_cols = {"canonical_url": "TEXT DEFAULT ''", "title_norm": "TEXT DEFAULT ''",
                "cluster_id": "TEXT DEFAULT ''", "dup_count": "INTEGER DEFAULT 1",
                "dup_scope": "TEXT DEFAULT 'none'",
                "published_at_known": "INTEGER DEFAULT 1",
                "matched_terms": "TEXT DEFAULT '[]'", "tickers": "TEXT DEFAULT '[]'",
                "event_type": "TEXT DEFAULT ''",
                "author_role": "TEXT DEFAULT ''", "author_handle": "TEXT DEFAULT ''",
                "text_zh": "TEXT DEFAULT ''", "title_zh": "TEXT DEFAULT ''",
                "lang_detected": "TEXT DEFAULT ''", "zh_status": "TEXT DEFAULT ''",
                "zh_attempts": "INTEGER DEFAULT 0",
                # v5(2026-09-03 双标签制): 类型四值/定位五值/市场改名前留档
                "item_type": "TEXT DEFAULT ''", "positioning": "TEXT DEFAULT ''",
                "markets_legacy": "TEXT DEFAULT '[]'"}
    for c, t in new_cols.items():
        if c not in have:
            conn.execute(f"ALTER TABLE items ADD COLUMN {c} {t}")
    conn.execute("""CREATE TABLE IF NOT EXISTS zh_cache(
        text_hash TEXT PRIMARY KEY, text_zh TEXT, title_zh TEXT,
        model TEXT, created_at TEXT)""")
    # 2026-09-02 六值裁决: 存量 rating/insight/stance 一次性并入 analysis
    conn.execute("UPDATE items SET info_type='analysis' "
                 "WHERE info_type IN ('insight','rating','stance')")
    conn.execute("""CREATE TABLE IF NOT EXISTS clusters(
        cluster_id TEXT PRIMARY KEY, kind TEXT, representative_id TEXT,
        first_seen TEXT, last_seen TEXT, report_count INTEGER DEFAULT 1,
        source_count INTEGER DEFAULT 1, created_at TEXT, updated_at TEXT)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_time ON items(time DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_source ON items(source_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_kind_time ON items(kind, time DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_cluster ON items(cluster_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_canon ON items(canonical_url)")
    conn.execute("INSERT OR REPLACE INTO schema_meta VALUES('schema_version', ?)",
                 (str(SCHEMA_VERSION),))
    conn.commit()


# ── URL 规范化(层1去重) ──────────────────────────────────────────────────────

_TRACK_KEYS = {"spm", "spm_id", "scm", "scm_id", "gclid", "fbclid", "msclkid",
               "ttclid", "yclid", "dclid", "igshid", "mc_cid", "mc_eid",
               "click_id", "clickid", "sharefrom", "share_from", "share_token",
               "shareid", "share_id", "ref_src", "refsrc", "trackid",
               "tracking_id", "tracker", "trace_id", "traceid", "pvid", "pv_id",
               "request_id", "requestid", "reqid", "scene", "scene_id",
               "abtest", "ab_id", "jumpfrom", "jump_from", "_t", "_ts", "_r", "_s"}
_CONTENT_KEYS = {"id", "aid", "nid", "news_id", "newsid", "article_id", "item_id",
                 "content_id", "post_id", "msg_id", "flash_id", "docid", "doc_id",
                 "unique_id", "mid", "cid", "pid", "code", "stock", "symbol", "s",
                 "ticker", "date", "day", "page", "p", "pageno", "offset",
                 "report_id", "announce_id", "notice_id"}


def canonicalize_url(url: str) -> str:
    """剥跟踪参/fragment/尾斜杠后的规范化 URL(只做键, 展示永远用原文)。"""
    from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
    s = (url or "").strip()
    if not s.lower().startswith(("http://", "https://")):
        return ""
    try:
        u = urlparse(s)
        host = (u.netloc or "").lower().rstrip(".")
        for p in (":80", ":443"):
            if host.endswith(p):
                host = host[: -len(p)]
        if host.startswith("www."):
            host = host[4:]
        path = re.sub(r"%([0-9a-f]{2})", lambda m: "%" + m.group(1).upper(), u.path or "")
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")
        kept = []
        for k, v in parse_qsl(u.query, keep_blank_values=True):
            lk = k.lower()
            if lk.startswith("utm_") or lk in _TRACK_KEYS:
                continue
            if lk in ("t", "ts", "timestamp") and re.fullmatch(r"\d{10,13}", v):
                continue
            kept.append((k, v))                        # 未知参数默认保留(误删>误留)
        kept.sort(key=lambda kv: (kv[0].lower(), kv[1]))
        return urlunparse((u.scheme.lower(), host, path, "", urlencode(kept), ""))
    except Exception:
        return ""


# ── 标题规范化与 bigram(层2模糊簇用) ─────────────────────────────────────────

_STOP_CHARS = set("的了吗呢啊吧着过和与及或在于对将把被让从到也又还就都")
_PREFIX_RE = re.compile(r"^(【[^】]*】|\[[^\]]*\]|财联社.{0,8}电|快讯[:：]|金十.{0,4}[:：]|见闻[:：])+")


def normalize_title(text: str) -> str:
    s = (text or "")[:200]
    s = re.sub(r"<[^>]+>", "", s)
    import unicodedata
    s = unicodedata.normalize("NFKC", s).lower()
    s = _PREFIX_RE.sub("", s)
    s = "".join(c for c in s if re.match(r"[一-鿿0-9a-z.%]", c))
    s = "".join(c for c in s if c not in _STOP_CHARS)
    return s


def _bigrams(s: str) -> set:
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else set()


_NUM_RE = re.compile(r"\d+(?:\.\d+)?(?:%|bp|基点|亿|万|倍|元|美元|亿元|万亿)?")
_POLAR = [("涨", "跌"), ("升", "降"), ("加息", "降息"), ("利好", "利空"),
          ("增持", "减持"), ("买入", "卖出"), ("通过", "否决"), ("扩张", "收缩"),
          ("暂停", "重启"), ("上调", "下调"), ("surge", "plunge"), ("beat", "miss")]


def _hard_veto(a_raw: str, b_raw: str) -> bool:
    """数字集不等/代码无交集/极性对立 → 拒绝合并。"""
    na, nb = set(_NUM_RE.findall(a_raw)), set(_NUM_RE.findall(b_raw))
    if na and nb and na != nb:
        return True
    ca = set(re.findall(r"(?<!\d)\d{6}(?!\d)", a_raw)) | set(re.findall(r"\b[A-Z]{2,5}\b", a_raw))
    cb = set(re.findall(r"(?<!\d)\d{6}(?!\d)", b_raw)) | set(re.findall(r"\b[A-Z]{2,5}\b", b_raw))
    if ca and cb and not (ca & cb):
        return True
    for x, y in _POLAR:
        ax, ay = x in a_raw, y in a_raw
        bx, by = x in b_raw, y in b_raw
        if (ax and by and not (ay or bx)) or (ay and bx and not (ax or by)):
            return True
    return False


# ── 时间归一(含可信位) ──────────────────────────────────────────────────────

def _norm_time(raw: str, fallback: str) -> tuple[str, int]:
    """归一北京时间, 返回 (time, published_at_known)。fallback 命中 → known=0。"""
    s = (raw or "").strip()
    bj = __import__("datetime").timezone(__import__("datetime").timedelta(hours=8))
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?", s):
            return s[:16], 1
        if re.match(r"\d{4}-\d{2}-\d{2}T", s):
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=bj)
            return dt.astimezone(bj).strftime("%Y-%m-%d %H:%M"), 1
        if "," in s:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(s).astimezone(bj).strftime("%Y-%m-%d %H:%M"), 1
        m = re.fullmatch(r"(\d{1,2})-(\d{1,2}) (\d{1,2}):(\d{2})", s)
        if m:
            return f"{datetime.now().year}-{int(m[1]):02d}-{int(m[2]):02d} {int(m[3]):02d}:{m[4]}", 1
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
        if m:
            return f"{datetime.now().strftime('%Y-%m-%d')} {int(m[1]):02d}:{m[2]}", 0
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return s + " 00:00", 0
    except Exception:
        pass
    return fallback, 0


def _item_id(source_id: str, canon: str, text: str) -> str:
    key = canon or "".join((text or "").split())[:60]
    return hashlib.md5(f"{source_id}|{key}".encode("utf-8")).hexdigest()


# ── 入库 ────────────────────────────────────────────────────────────────────

def _decide_info_type(it: dict, kind: str, text: str) -> str:
    """六值类型瀑布(2026-09-02 裁决): fetcher显式 > rumor否决 > kind锁 > 观点信号 > 缺省。"""
    if it.get("info_type"):
        return it["info_type"]
    if _tagger.rumor_hit(text):
        return "rumor"
    locked = {"announcement": "filing", "market": "data", "calendar": "calendar"}.get(kind)
    if locked:
        return locked
    if kind in ("flash", "peer_article") and _tagger.opinion_hit(text):
        return "analysis"
    return KIND_TO_INFO_TYPE.get(kind, "news")


def put(source_id: str, meta: dict, items: list) -> int:
    """入库(幂等 + 规则打标 + 精确去重)。返回新增条数。"""
    if not items:
        return 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    info_default = KIND_TO_INFO_TYPE.get(meta.get("kind", ""), "news")
    kind = meta.get("kind", "")
    rows = []
    for it in items:
        text = it.get("text", "") or ""
        canon = canonicalize_url(it.get("url", "") or "")
        t_norm = normalize_title(text)
        t_str, t_known = _norm_time(it.get("time", ""), now)
        tag = _tagger.enrich(text, kind=kind)
        sectors = it.get("sectors") or tag["sectors"]
        info_type = _decide_info_type(it, kind, text)
        author_role = it.get("author_role") or ""
        # 市场(2026-09-03 grok裁决): 继承源/账号为底, ticker 命中只并集扩展不覆盖;
        # 全部走新值域(美股→美国等)。
        base_mkts = it.get("markets") or meta.get("markets") or []
        merged_mkts = _tax.norm_markets(list(base_mkts) + [
            m for m in tag["markets"] if m not in base_mkts])
        # 定位: X 条目按账号 role 派生(覆盖大源定位), 其余继承源 meta。
        positioning = (_tax.ROLE_TO_POSITIONING.get(author_role)
                       or meta.get("positioning", ""))
        item_type = it.get("item_type") or _tax.derive_item_type(
            kind, info_type, source_id)
        rows.append((
            _item_id(source_id, canon, text), source_id,
            it.get("source") or meta.get("title", ""), t_str, text,
            it.get("title", "") or "", it.get("url", "") or "", it.get("media", "") or "",
            kind, meta.get("form", ""), meta.get("channel", ""), meta.get("risk", ""),
            json.dumps(merged_mkts, ensure_ascii=False),
            it.get("lang") or meta.get("lang", ""),
            info_type,
            json.dumps(sectors, ensure_ascii=False),
            it.get("sentiment") or tag["sentiment"], now,
            canon, t_norm, "", 1, "none", t_known,
            json.dumps(tag["matched_terms"], ensure_ascii=False),
            json.dumps(it.get("tickers") or tag["tickers"], ensure_ascii=False),
            it.get("event_type") or tag["event_type"],
            author_role, it.get("author_handle") or "",
            "", "", "", "", 0,
            item_type, positioning, "[]"))
    sql = ("INSERT OR IGNORE INTO items(" + ",".join(_COLS) + ") VALUES(" +
           ",".join("?" * len(_COLS)) + ")")
    conn = _connect()
    try:
        cur = conn.executemany(sql, rows)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# ── 轮末模糊归并(link_dups) ──────────────────────────────────────────────────

_WINDOW_H = {"flash": 6, "peer_article": 12}
_J_T = {"flash": 0.65, "peer_article": 0.70}
_C_T = {"flash": 0.80, "peer_article": 0.82}


def _similar(a: dict, b: dict, kind: str) -> bool:
    """Jaccard 主判据 + 包含度补充(标题⊂长文放行, 需短者≥10字+包含度≥0.9)。"""
    if _hard_veto(a["text"], b["text"]):
        return False
    A, B = a["grams"], b["grams"]
    if not A or not B:
        return a["norm"] == b["norm"] and bool(a["norm"])
    inter = len(A & B)
    if not inter:
        return False
    j = inter / len(A | B)
    if j >= _J_T[kind]:
        return True
    c = inter / min(len(A), len(B))
    if c >= _C_T[kind]:
        la, lb = len(a["norm"]), len(b["norm"])
        ratio = min(la, lb) / max(la, lb)
        if ratio >= 0.65:                          # 相近长度的扩写
            return True
        if min(la, lb) >= 10 and c >= 0.9:         # 快讯标题被长文全文包含
            return True
    return False


def link_dups() -> dict:
    """refresh 轮末调用: 近窗代表条 bigram 倒排 + 并查集, 簇写入 clusters 表。
    只对 flash/peer_article 做模糊簇; 条目不删除只挂 cluster_id。"""
    conn = _connect()
    stats = {"scanned": 0, "linked": 0, "clusters": 0}
    try:
        for kind, win_h in _WINDOW_H.items():
            since = (datetime.now() - timedelta(hours=win_h)).strftime("%Y-%m-%d %H:%M")
            rows = conn.execute(
                "SELECT id, source_id, time, text, title_norm FROM items "
                "WHERE kind=? AND time>=? ORDER BY time ASC, id ASC",
                (kind, since)).fetchall()
            if not rows:
                continue
            reps = [{"id": r[0], "sid": r[1], "time": r[2], "text": r[3],
                     "norm": r[4], "grams": _bigrams(r[4])} for r in rows]
            stats["scanned"] += len(reps)
            inv: dict[str, list[int]] = {}          # bigram 倒排
            for i, r in enumerate(reps):
                for g in r["grams"]:
                    inv.setdefault(g, []).append(i)
            parent = list(range(len(reps)))

            def find(x):
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            seen_pairs = set()
            for g, idxs in inv.items():
                if len(idxs) < 2 or len(idxs) > 64:   # 高频 bigram 无区分度
                    continue
                for x in range(len(idxs)):
                    for y in range(x + 1, len(idxs)):
                        i, j = idxs[x], idxs[y]
                        key = (i, j)
                        if key in seen_pairs:
                            continue
                        seen_pairs.add(key)
                        if find(i) == find(j):
                            continue
                        if _similar(reps[i], reps[j], kind):
                            parent[find(i)] = find(j)
                            stats["linked"] += 1
            # 成簇: 只保留 size>=2 的组
            groups: dict[int, list[int]] = {}
            for i in range(len(reps)):
                groups.setdefault(find(i), []).append(i)
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            for root, members in groups.items():
                if len(members) < 2:
                    continue
                members.sort(key=lambda i: (reps[i]["time"], reps[i]["id"]))
                rep = reps[members[0]]                   # 最早发布=代表
                cid = hashlib.md5(f"cluster|{rep['id']}".encode()).hexdigest()[:24]
                sids = {reps[i]["sid"] for i in members}
                scope = "same_source" if len(sids) == 1 else "cross_source"
                first, last = reps[members[0]]["time"], reps[members[-1]]["time"]
                conn.execute(
                    "INSERT INTO clusters VALUES(?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(cluster_id) DO UPDATE SET "
                    "representative_id=excluded.representative_id, "
                    "last_seen=excluded.last_seen, report_count=excluded.report_count, "
                    "source_count=excluded.source_count, updated_at=excluded.updated_at",
                    (cid, kind, rep["id"], first, last, len(members), len(sids), now, now))
                for i in members:
                    conn.execute(
                        "UPDATE items SET cluster_id=?, dup_count=?, dup_scope=? WHERE id=?",
                        (cid, len(members), scope, reps[i]["id"]))
                stats["clusters"] += 1
        conn.commit()
    finally:
        conn.close()
    return stats


# ── 清理 ────────────────────────────────────────────────────────────────────

def prune() -> int:
    conn = _connect()
    total = 0
    try:
        for kind, hours in RETENTION_HOURS.items():
            cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
            cur = conn.execute("DELETE FROM items WHERE kind=? AND time<?", (kind, cutoff))
            total += cur.rowcount
        # 清理空簇(成员被删光)
        conn.execute("""DELETE FROM clusters WHERE cluster_id NOT IN
                        (SELECT DISTINCT cluster_id FROM items WHERE cluster_id<>'')""")
        conn.commit()
    finally:
        conn.close()
    return total


# ── 查询 ────────────────────────────────────────────────────────────────────

def query(markets: list | None = None, kinds: list | None = None,
          info_types: list | None = None, channels: list | None = None,
          forms: list | None = None, source_ids: list | None = None,
          tickers: list | None = None, sentiments: list | None = None,
          event_types: list | None = None,
          item_types: list | None = None, positionings: list | None = None,
          sectors: list | None = None,
          q: str = "", since: str = "", limit: int = 200, cursor: str = "",
          dedup: bool = True) -> tuple[list, str]:
    """只读查询。dedup=True(默认)只出簇代表条; q 拆词 LIKE AND。
    cursor = "time|id" 完整 keyset(修同分钟跳项 bug)。
    2026-09-03 双标签制: item_types/positionings 新过滤; markets 输入接受旧别名
    (美股→美国/港股→香港/外汇大宗→全球)。
    2026-09-04 赛道实时筛选: sectors 输入 L1 名, 命中任一选中赛道即中(路径首段前缀匹配)。"""
    markets = _tax.norm_markets(list(markets or []))
    sql, args = "SELECT * FROM items WHERE 1=1", []
    if dedup:
        sql += (" AND (cluster_id='' OR id IN "
                "(SELECT representative_id FROM clusters))")
    if kinds:
        sql += f" AND kind IN ({','.join('?' * len(kinds))})"; args += kinds
    if info_types:
        sql += f" AND info_type IN ({','.join('?' * len(info_types))})"; args += info_types
    if event_types:
        sql += f" AND event_type IN ({','.join('?' * len(event_types))})"; args += event_types
    if channels:
        sql += f" AND channel IN ({','.join('?' * len(channels))})"; args += channels
    if item_types:
        sql += f" AND item_type IN ({','.join('?' * len(item_types))})"; args += item_types
    if positionings:
        sql += f" AND positioning IN ({','.join('?' * len(positionings))})"; args += positionings
    if forms:
        sql += f" AND form IN ({','.join('?' * len(forms))})"; args += forms
    if source_ids:
        sql += f" AND source_id IN ({','.join('?' * len(source_ids))})"; args += source_ids
    if sentiments:
        sql += f" AND sentiment IN ({','.join('?' * len(sentiments))})"; args += sentiments
    if sectors:                              # 赛道 L1: "L1>L2>..." 首段前缀, 选中值之间 OR
        conds = []
        for s in sectors:
            conds.append("sectors LIKE ?"); args.append(f'%"{s}>%')
            conds.append("sectors LIKE ?"); args.append(f'%"{s}"%')
        sql += " AND (" + " OR ".join(conds) + ")"
    if since:
        sql += " AND time>?"; args.append(since)
    for mk in (markets or []):
        sql += " AND markets LIKE ?"; args.append(f'%"{mk}"%')
    for tk in (tickers or []):
        sql += " AND tickers LIKE ?"; args.append(f'%"{tk}"%')
    for w in [w for w in re.split(r"\s+", (q or "").strip()) if w]:
        sql += " AND (text LIKE ? OR text_zh LIKE ? OR title_zh LIKE ?)"
        args += [f"%{w}%", f"%{w}%", f"%{w}%"]
    if cursor:
        ct, _, cid = cursor.partition("|")
        if ct and cid:                                # 完整 keyset: 同分钟不跳项
            sql += " AND (time<? OR (time=? AND id>?))"
            args += [ct, ct, cid]
        elif ct:
            sql += " AND time<?"; args.append(ct)
    sql += " ORDER BY time DESC, id ASC LIMIT ?"
    lim = min(limit, 1000)
    args.append(lim + 1)
    conn = _connect()
    try:
        rows = conn.execute(sql, args).fetchall()
    finally:
        conn.close()
    page = rows[:lim]
    next_cursor = (f"{page[-1][3]}|{page[-1][0]}"
                   if len(rows) > len(page) and page else "")
    return [_row_to_dict(r) for r in page], next_cursor


def _row_to_dict(r) -> dict:
    d = dict(zip(_COLS, r))
    for k in ("markets", "sectors", "matched_terms", "tickers"):
        try:
            d[k] = json.loads(d[k] or "[]")
        except Exception:
            d[k] = []
    # 展示字段(中文用户): 有译文用译文, 无译文回落原文
    d["text_display"] = d["text_zh"] if d.get("zh_status") in ("ok", "partial") \
        and d.get("text_zh") else d["text"]
    d["title_display"] = d["title_zh"] if d.get("title_zh") else d.get("title", "")
    return d


def stats() -> dict:
    conn = _connect()
    try:
        n = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        latest = conn.execute("SELECT MAX(time) FROM items").fetchone()[0]
        per_kind = dict(conn.execute(
            "SELECT kind, COUNT(*) FROM items GROUP BY kind").fetchall())
        clusters = conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
        return {"items": n, "latest_time": latest, "per_kind": per_kind,
                "clusters": clusters, "db": str(db_path())}
    finally:
        conn.close()


def export_snapshot(out_dir: Path | None = None) -> dict:
    dist = out_dir or (_serve_dir().parent / "dist")
    dist.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM items ORDER BY time DESC, id ASC").fetchall()
    finally:
        conn.close()
    items = [_row_to_dict(r) for r in rows]

    def _write_gz(path: Path, payload: list) -> None:
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            for d in payload:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        os.replace(tmp, path)

    _write_gz(dist / "latest.json.gz", items)
    by_mk: dict[str, list] = {}
    for d in items:
        for mk in (d.get("markets") or ["未标注"]):
            by_mk.setdefault(mk, []).append(d)
    (dist / "by-market").mkdir(exist_ok=True)
    for mk, arr in by_mk.items():
        _write_gz(dist / "by-market" / f"{mk}.json.gz", arr)
    manifest = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "schema_version": SCHEMA_VERSION, "items": len(items),
                "by_market": {k: len(v) for k, v in by_mk.items()}}
    tmp = dist / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, dist / "manifest.json")
    return manifest
