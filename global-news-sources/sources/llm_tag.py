"""M4 LLM 精标(批量/截断/规则兜底/可开关, 2026-09-01 用户裁决必开)。

refresh 轮末对本轮新入库条目批量精修 sectors/sentiment/event_type。
- 批量 20 条/次(指令开销摊薄), 文本截断 1500 字符
- 模型走项目统一 LLM 配置(secret.local.json 的 base_url/api_key, 默认 deepseek-v4-flash 便宜档)
- LLM 失败/超时 → 保留规则打标结果(兜底), 不阻塞 refresh
- 关闭方式: config.yaml sources.llm_tag.enabled: false
"""

import json
import re
import time

from sources import store as _store

DEFAULT_MODEL = "deepseek-v4-flash"
BATCH = 20
MAX_CHARS = 1500

_SYS = """你是财经信息打标器。对每条输入输出: sectors(赛道数组, 形如"板块>赛道", 板块从[宏观与政策/半导体/AI与算力/互联网与传媒/消费电子/通信与卫星/汽车与智能驾驶/新能源与电力/油气与能源/金属与矿业/化工与新材料/医药生物/金融与加密/地产与基建/消费/军工与航空航天/工业与机器人/交通运输/农业与食品]选, 无赛道属性给[])、sentiment(bullish/bearish/neutral)、event_type(从[earnings/guidance/rating/mna/dividend/offering/fda/legal/policy/macro/contract/personnel/product]选, 都不是给"")、type(内容类型纠偏: 客观事实报道给news, 含主观研判/评级/目标价/推演/观点给analysis, 拿不准给""不改动)。
所有条目一视同仁——分析/观点/研报/KOL帖同样必须输出 sectors 与 sentiment。
只输出 JSON 数组, 每个元素 {"i":序号, "sectors":[...], "sentiment":"...", "event_type":"...", "type":"..."}, 不要任何多余文字。"""


def _conf() -> dict:
    try:
        from sources import _cfg_section
        c = _cfg_section().get("llm_tag") or {}
        return {"enabled": bool(c.get("enabled", True)),
                "model": c.get("model", DEFAULT_MODEL),
                "batch": int(c.get("batch", BATCH))}
    except Exception:
        return {"enabled": True, "model": DEFAULT_MODEL, "batch": BATCH}


def _llm_cfg() -> tuple[str, str, str]:
    """(base_url, api_key, model)。复用项目统一 LLM 配置。"""
    import os
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fetchers"))
    try:
        from _runtime import secret_value, AUTOPUB_ROOT
        import json as _j
        base, key = "", secret_value("api_key")
        try:
            d = _j.loads((AUTOPUB_ROOT / "secret.local.json").read_text(encoding="utf-8"))
            base = d.get("base_url", "")
        except Exception:
            pass
        return base or "https://ark.cn-beijing.volces.com/api/plan/v3", key, ""
    except Exception:
        return "https://ark.cn-beijing.volces.com/api/plan/v3", "", ""


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
    """对 fetched_at >= since 的条目做 LLM 精标。返回报告。"""
    conf = _conf()
    rep = {"enabled": conf["enabled"], "tagged": 0, "batches": 0, "errors": []}
    if not conf["enabled"]:
        return rep
    base, key, _ = _llm_cfg()
    if not key:
        rep["errors"].append("无 LLM key(保留规则打标)")
        return rep
    conn = _store._connect()
    try:
        rows = conn.execute(
            "SELECT id, text, sectors, sentiment, event_type FROM items "
            "WHERE fetched_at>=? ORDER BY time ASC", (since_fetched_at,)).fetchall()
    finally:
        conn.close()
    if not rows:
        return rep
    bs = conf["batch"]
    for off in range(0, len(rows), bs):
        chunk = rows[off:off + bs]
        prompt = "\n".join(f"[{n}] {(r[1] or '')[:MAX_CHARS]}"
                           for n, r in enumerate(chunk))
        try:
            out = _chat(base, key, conf["model"], prompt)
            m = re.search(r"\[.*\]", out, re.S)
            arr = json.loads(m.group(0)) if m else []
        except Exception as ex:
            rep["errors"].append(f"batch{off}: {type(ex).__name__}: {str(ex)[:80]}")
            continue
        conn = _store._connect()
        try:
            for d in arr:
                try:
                    i = int(d.get("i", -1))
                    if not (0 <= i < len(chunk)):
                        continue
                    rid = chunk[i][0]
                    sectors = d.get("sectors")
                    sent = d.get("sentiment") if d.get("sentiment") in (
                        "bullish", "bearish", "neutral") else ""
                    etype = d.get("event_type") or ""
                    ttype = d.get("type") if d.get("type") in ("news", "analysis") else ""
                    sets, args = [], []
                    if sectors:
                        sets.append("sectors=?")
                        args.append(json.dumps(sectors, ensure_ascii=False))
                    if sent:
                        sets.append("sentiment=?"); args.append(sent)
                    if etype:
                        sets.append("event_type=?"); args.append(etype)
                    if ttype:                          # 仅允许 news↔analysis 纠偏
                        sets.append("info_type=?"); args.append(ttype)
                    if sets:
                        conn.execute(
                            f"UPDATE items SET {','.join(sets)} WHERE id=?",
                            args + [rid])
                    rep["tagged"] += 1
                except Exception:
                    continue
            conn.commit()
        finally:
            conn.close()
        rep["batches"] += 1
        time.sleep(0.3)                                # 批次间礼让
    return rep
