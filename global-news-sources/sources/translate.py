"""统一中译模块(MoA 四方案收敛, 2026-09-02)。

refresh 轮末对非中文条目批量翻译成简体中文(工作台/早报全是中国用户)。
- 复用项目统一 LLM 配置(deepseek-v4-flash), 批量 10/截断 1500/temperature 0
- 判定: lang 字段为主, lang 空(X池)走 CJK 占比检测; 繁体 zh 不翻(可直接读)
- 幂等三层: zh_status 状态机(''/skip/ok/partial/fail) + zh_attempts<3 熔断
  + zh_cache 哈希缓存(跨源同文/重跑零消耗); 簇成员 skip_dup(默认只展示代表条)
- 失败不阻塞 refresh, 保留原文, 下轮自动重试
- 关闭: config.yaml sources.translate.enabled: false
"""

import hashlib
import json
import re
import time

from sources import store as _store

DEFAULT_MODEL = "deepseek-v4-flash"
BATCH = 10
MAX_CHARS = 1500
MAX_ATTEMPTS = 3
ROUND_CAP = 120
SLEEP = 0.3

_ZH_LANGS = {"zh", "zh-cn", "zh-tw", "zh-hk", "zh-hans", "zh-hant"}
_CJK_RE = re.compile(r"[一-鿿]")
_TR_CHARS = set("çğıöşüÇĞİÖŞÜ")                     # 土耳其语特征字符
_SYS = """你是专业财经新闻翻译器。把每条输入译成简体中文, 术语按中文财经媒体惯例(如 Fed=美联储, KAP=土耳其公开披露平台)。
保留不译: 数字、股票代码(2330.TW/NVDA)、@账号、#话题、$TICKER、URL、机构缩写(Fed/SEC/TCMB/BIST 等首次保留可附中文)。
只输出 JSON 数组 [{"i":序号,"zh":"译文","title_zh":"标题译文(无标题给空串)"}], 不要任何多余文字。"""


def _conf() -> dict:
    try:
        from sources import _cfg_section
        c = _cfg_section().get("translate") or {}
        return {"enabled": bool(c.get("enabled", True)),
                "model": c.get("model", DEFAULT_MODEL),
                "batch": int(c.get("batch", BATCH)),
                "max_chars": int(c.get("max_chars", MAX_CHARS)),
                "round_cap": int(c.get("round_cap", ROUND_CAP))}
    except Exception:
        return {"enabled": True, "model": DEFAULT_MODEL, "batch": BATCH,
                "max_chars": MAX_CHARS, "round_cap": ROUND_CAP}


def _detect_lang(text: str) -> str:
    """lang 为空时的内容检测。返回 zh/en/tr/ja/ko/'' 。"""
    sample = (text or "")[:500]
    cjk = len(_CJK_RE.findall(sample))
    latin = sum(1 for c in sample if c.isascii() and c.isalpha())
    kana = sum(1 for c in sample if "぀" <= c <= "ヿ")
    hangul = sum(1 for c in sample if "가" <= c <= "힯")
    total = cjk + latin + kana + hangul
    if total == 0:
        return ""
    if cjk >= 4 and cjk / total >= 0.3:
        return "zh"
    if kana > 3:
        return "ja"
    if hangul > 3:
        return "ko"
    if any(c in _TR_CHARS for c in sample):
        return "tr"
    return "en" if latin else ""


def _need_zh(lang: str, text: str) -> tuple[bool, str]:
    """返回 (要不要翻, 检测出的语言/原文lang)。"""
    if not (text or "").strip():
        return False, "skip-empty"
    l = (lang or "").strip().lower()
    if l in _ZH_LANGS:
        return False, "skip-zh"
    if l:
        return True, l
    detected = _detect_lang(text)
    if detected == "zh":
        return False, "skip-detected-zh"
    if not detected:
        return False, "skip-noalpha"
    return True, detected


def _text_hash(text: str) -> str:
    import unicodedata
    return hashlib.md5(unicodedata.normalize("NFKC", (text or "").strip())
                       .encode("utf-8")).hexdigest()


def _chat(base: str, key: str, model: str, prompt: str) -> str:
    import requests
    r = requests.post(f"{base.rstrip('/')}/chat/completions",
                      headers={"Authorization": f"Bearer {key}",
                               "Content-Type": "application/json"},
                      json={"model": model,
                            "messages": [{"role": "system", "content": _SYS},
                                         {"role": "user", "content": prompt}],
                            "temperature": 0},
                      timeout=90)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def run(since_fetched_at: str) -> dict:
    """翻译本轮新条目(不足 round_cap 时顺带回填存量 fail/未处理)。返回报告。"""
    from sources.llm_tag import _llm_cfg
    conf = _conf()
    rep = {"enabled": conf["enabled"], "translated": 0, "skipped": 0,
           "cached": 0, "batches": 0, "errors": []}
    if not conf["enabled"]:
        return rep
    base, key, _ = _llm_cfg()
    if not key:
        rep["errors"].append("无 LLM key(翻译跳过)")
        return rep

    conn = _store._connect()
    try:
        rows = conn.execute(
            "SELECT id, text, title, lang, cluster_id, zh_status, zh_attempts FROM items "
            "WHERE zh_status IN ('','fail') AND zh_attempts<? "
            "ORDER BY (fetched_at>=?) DESC, time ASC LIMIT ?",
            (MAX_ATTEMPTS, since_fetched_at, conf["round_cap"])).fetchall()
        rep_ok = {r[0] for r in conn.execute(
            "SELECT representative_id FROM clusters").fetchall()}
    finally:
        conn.close()

    todo, updates = [], []
    for rid, text, title, lang, cid, st, att in rows:
        need, det = _need_zh(lang, text)
        if not need:
            updates.append(("skip", "", "", det if det.startswith("skip-detected") else "",
                            rid))                       # 状态, text_zh, title_zh, lang_detected, id
            rep["skipped"] += 1
            continue
        if cid and rid not in rep_ok:                   # 簇成员不翻(默认只展示代表条)
            updates.append(("skip", "", "", "", rid))
            rep["skipped"] += 1
            continue
        todo.append((rid, text, title, det))

    # 哈希缓存先吃一轮
    remain = []
    if todo:
        conn = _store._connect()
        try:
            for rid, text, title, det in todo:
                h = _text_hash(text)
                hit = conn.execute(
                    "SELECT text_zh, title_zh FROM zh_cache WHERE text_hash=?",
                    (h,)).fetchone()
                if hit:
                    updates.append(("ok", hit[0], hit[1], det, rid))
                    rep["cached"] += 1
                else:
                    remain.append((rid, text, title, det, h))
        finally:
            conn.close()

    bs = conf["batch"]
    for off in range(0, len(remain), bs):
        chunk = remain[off:off + bs]
        parts = []
        for n, t in enumerate(chunk):
            head = f"标题: {t[2]}\n" if t[2] else ""
            parts.append(f"[{n}] {head}{(t[1] or '')[:conf['max_chars']]}")
        prompt = "\n\n".join(parts)
        try:
            out = _chat(base, key, conf["model"], prompt)
            m = re.search(r"\[.*\]", out, re.S)
            arr = json.loads(m.group(0)) if m else []
        except Exception as ex:
            rep["errors"].append(f"batch{off}: {type(ex).__name__}: {str(ex)[:80]}")
            conn = _store._connect()
            try:
                for rid, *_ in chunk:
                    conn.execute("UPDATE items SET zh_attempts=zh_attempts+1, "
                                 "zh_status=CASE WHEN zh_attempts+1>=? THEN 'fail' ELSE '' END "
                                 "WHERE id=?", (MAX_ATTEMPTS, rid))
                conn.commit()
            finally:
                conn.close()
            continue
        got_i = set()
        conn = _store._connect()
        try:
            for d in arr:
                try:
                    i = int(d.get("i", -1))
                    if not (0 <= i < len(chunk)):
                        continue
                    rid, text, title, det, h = chunk[i]
                    zh = (d.get("zh") or "").strip()
                    tzh = (d.get("title_zh") or "").strip()
                    if not zh:
                        continue
                    partial = len(text or "") > conf["max_chars"]
                    if partial:
                        zh += " …(译文有删减,原文见长)"
                    status = "partial" if partial else "ok"
                    updates.append((status, zh, tzh, det, rid))
                    conn.execute("INSERT OR IGNORE INTO zh_cache VALUES(?,?,?,?,?)",
                                 (h, zh, tzh, conf["model"],
                                  time.strftime("%Y-%m-%d %H:%M:%S")))
                    got_i.add(i)
                    rep["translated"] += 1
                except Exception:
                    continue
            conn.commit()
        finally:
            conn.close()
        rep["batches"] += 1
        time.sleep(SLEEP)

    if updates:
        conn = _store._connect()
        try:
            for status, zh, tzh, det, rid in updates:
                conn.execute("UPDATE items SET zh_status=?, text_zh=?, title_zh=?, "
                             "lang_detected=? WHERE id=?", (status, zh, tzh, det, rid))
            conn.commit()
        finally:
            conn.close()
    return rep
