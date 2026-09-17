"""飞书披露双自动化(2026-09-17 用户裁决):

A. 15min 情报摘要(run_digest): refresh 轮末调用——本轮新增 twitter 条目
   → 话题聚合+传播热度(同题账号数)+作者标注 → LLM 摘要(经 zen_bridge 链) → 发群。
   LLM 挂→规则兜底(账号+条目直列)。新增 <min_items 静默跳过不刷群。
B. 1min 账号池监控(watch_loop): FxTwitter v2 时间线逐账号对比 last_seen,
   有更新即发群(原文+链接)。账号池 = sources.feishu.watch.handles(用户指定),
   每轮循环重读配置, 改完即生效; 首见账号只登记不回填(防入群刷屏)。

配置(sources.feishu, 写 config.local.yaml — 凭证绝不入库):
  enabled: true
  app_id / app_secret / chat_id            # 飞书自建应用 + 群 chat_id(oc_ 前缀)
  digest_models: [{base_url,api_key,model}]  # 缺省复用 sources.translate.models(zen_bridge 链)
  min_items: 2                             # 摘要触发下限
  watch: {enabled: true, interval_s: 60, handles: []}

状态: data/health/feishu.json(token/最近发送记录) + data/health/feishu-watch.json(last_seen)
纪律: 发送失败只记不炸(抛给 refresh 记 failures); 机器人不在群(230002)时报告一次原因。
"""
import json
import re
import time
import urllib.request
import urllib.error
from pathlib import Path

from . import _cfg_section, data_dir, store as _store

_STATE = "feishu.json"
_WATCH_STATE = "feishu-watch.json"
MAX_TEXT = 3400          # 飞书单条文本安全长度(留裕量)


def _conf() -> dict:
    c = (_cfg_section().get("feishu") or {})
    return {"enabled": bool(c.get("enabled", False)),
            "digest_enabled": bool(c.get("digest_enabled", True)),   # 摘要独立开关(2026-09-17 用户暂停)
            "app_id": str(c.get("app_id") or ""),
            "app_secret": str(c.get("app_secret") or ""),
            "chat_id": str(c.get("chat_id") or ""),
            "digest_models": c.get("digest_models") or [],
            "min_items": int(c.get("min_items", 2)),
            "watch": dict(c.get("watch") or {})}


def _state_path(name: str) -> Path:
    p = data_dir() / "health"
    p.mkdir(parents=True, exist_ok=True)
    return p / name


def _load_state(name: str) -> dict:
    try:
        return json.loads(_state_path(name).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(name: str, d: dict) -> None:
    try:
        tmp = _state_path(name).with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(_state_path(name))
    except Exception:
        pass


def _post(url: str, payload: dict, token: str = "", timeout: int = 20) -> dict:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ── 飞书客户端 ─────────────────────────────────────────────────────────────
def _token(conf: dict) -> str:
    st = _load_state(_STATE)
    if st.get("token") and time.time() < float(st.get("token_exp", 0)):
        return st["token"]
    d = _post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
              {"app_id": conf["app_id"], "app_secret": conf["app_secret"]})
    tok = d.get("tenant_access_token")
    if not tok:
        raise RuntimeError(f"飞书 token 失败: {str(d)[:120]}")
    st["token"] = tok
    st["token_exp"] = time.time() + int(d.get("expire", 7200)) - 300
    _save_state(_STATE, st)
    return tok


def send_text(conf: dict, text: str) -> tuple[bool, str]:
    """发文本消息到群。返回 (ok, err)。"""
    if not (conf["enabled"] and conf["app_id"] and conf["chat_id"]):
        return False, "feishu 未配置(enabled/app_id/chat_id)"
    try:
        d = _post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                  {"receive_id": conf["chat_id"], "msg_type": "text",
                   "content": json.dumps({"text": text[:MAX_TEXT]}, ensure_ascii=False)},
                  token=_token(conf))
        if d.get("code") == 0:
            return True, ""
        return False, f"code={d.get('code')} {str(d.get('msg'))[:100]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:100]}"


# ── A. 15min 情报摘要 ───────────────────────────────────────────────────────
_SYS = """你是财经情报摘要员。输入是 15 分钟内 X(推特)上财经账号的新帖(JSON, 含浏览量v/点赞lk)。
输出要求:
1. 开头一行: 【15min-X热帖】 {标题时间}
一句话总览全局(20字内)。
2. 按话题聚合同类帖, 列出 3-8 条热点, 每条一行:
   🔥<一句话说清事件/观点(中文)> — @主账号 浏览量N(等N账号)
   行尾必须标注账号与其浏览量(如 浏览量1.2万, 万以下直接数字); 多账号同题再列其他账号。
   排序以流量为主: 浏览量高/同题账号多的排最前; 同题 ≥3 账号标🔥🔥。
3. 不要逐条罗列账号废话, 不要解释你的过程。
4. 末尾附: 详情→ {board_url}"""


def _enrich_stats(items: list[dict], max_handles: int = 12) -> None:
    """FxTwitter 现拉浏览量(v)/点赞(lk): 按作者聚合一次时间线调用, sid 匹配回填。
    失败/超 max_handles 静默缺省(LLM 会省略未标注字段)。"""
    try:
        from fetchers.basic import _tw_fetch_statuses
    except Exception:
        return
    by_handle: dict[str, dict[str, tuple]] = {}
    for it in items:
        h = (it.get("author_handle") or "").strip()
        sid = str(it.get("url") or "").rstrip("/").split("/")[-1]
        if h and sid.isdigit():
            by_handle.setdefault(h, {})[sid] = None
    for h in list(by_handle)[:max_handles]:
        try:
            for s in _tw_fetch_statuses(h, 20, False):
                posts = s.get("statuses") or [] if s.get("type") == "thread" else [s]
                for p in posts:
                    sid = str(p.get("id") or "")
                    if sid in by_handle[h]:
                        by_handle[h][sid] = (p.get("views"), p.get("likes"))
        except Exception:
            continue
    for it in items:
        h = (it.get("author_handle") or "").strip()
        sid = str(it.get("url") or "").rstrip("/").split("/")[-1]
        hit = by_handle.get(h, {}).get(sid) if sid.isdigit() else None
        if hit:
            it["views"], it["likes"] = hit[0], hit[1]


def _digest_prompt(items: list[dict], bj: str) -> str:
    board = "https://board.haiwai.ltd/#k=vb_9a80545a5ce190ea"
    lines = []
    for it in items:
        d = {"h": (it.get("author_handle") or "?"),
             "t": ((it.get("text_zh") or it.get("text") or ""))[:400]}
        if it.get("views") is not None:
            d["v"] = it["views"]
        if it.get("likes") is not None:
            d["lk"] = it["likes"]
        lines.append(d)
    return (f"时间: {bj}\n看板链接: {board}\n新帖JSON:\n"
            + json.dumps(lines, ensure_ascii=False))


def _llm_digest(conf: dict, prompt: str) -> str:
    models = conf["digest_models"] or (_cfg_section().get("translate") or {}).get("models") or []
    import requests
    for m in models:
        base = str(m.get("base_url") or "").strip()
        key = str(m.get("api_key") or "").strip()
        model = str(m.get("model") or "").strip()
        if not (base and model):
            continue
        try:
            r = requests.post(f"{base.rstrip('/')}/chat/completions",
                              headers={"Authorization": f"Bearer {key or 'x'}",
                                       "Content-Type": "application/json"},
                              json={"model": model,
                                    "messages": [{"role": "system", "content": _SYS},
                                                 {"role": "user", "content": prompt}]},
                              timeout=120)
            r.raise_for_status()
            out = (r.json().get("choices") or [{}])[0].get("message", {}).get("content")
            if out and out.strip():
                return out.strip()
        except Exception:
            continue
    return ""


def run_digest(since_fetched_at: str) -> dict:
    """refresh 轮末调用。返回报告(进 rep['feishu'], 失败进 failures)。"""
    conf = _conf()
    rep = {"enabled": conf["enabled"], "sent": 0, "items": 0, "fallback": 0, "errors": []}
    if not conf["enabled"]:
        rep["errors"].append("未启用(sources.feishu.enabled)")
        return rep
    if not conf["digest_enabled"]:
        rep["skipped"] = "摘要已暂停(sources.feishu.digest_enabled=false)"
        return rep
    conn = _store._connect()
    try:
        rows = conn.execute(
            "SELECT source_id, time, text, text_zh, url, author_handle FROM items "
            "WHERE fetched_at>=? AND source_id LIKE '%twitter%' "
            "ORDER BY time DESC LIMIT 150", (since_fetched_at,)).fetchall()
    finally:
        conn.close()
    items = [{"source_id": r[0], "time": r[1], "text": r[2], "text_zh": r[3],
              "url": r[4], "author_handle": r[5]} for r in rows]
    rep["items"] = len(items)
    if len(items) < conf["min_items"]:
        rep["skipped"] = f"新增 {len(items)} 条 < 下限 {conf['min_items']}, 静默"
        return rep
    bj = time.strftime("%m-%d %H:%M")
    _enrich_stats(items)
    text = _llm_digest(conf, _digest_prompt(items, bj))
    if not text:
        rep["fallback"] = 1
        board = "https://board.haiwai.ltd/#k=vb_9a80545a5ce190ea"
        lines = [f"【15min-X热帖】 {bj}\n近15分钟 {len(items)} 条新帖(LLM 暂挂, 规则直列):"]
        for it in sorted(items, key=lambda x: -(x.get("views") or 0))[:6]:
            t = (it.get("text_zh") or it.get("text") or "")[:120].replace("\n", " ")
            v = f" 浏览量{it['views']}" if it.get("views") is not None else ""
            lines.append(f"· @{it.get('author_handle') or '?'}{v}: {t}")
        lines.append(f"详情→ {board}")
        text = "\n".join(lines)
    ok, err = send_text(conf, text)
    st = _load_state(_STATE)
    st["last_digest"] = {"ts": time.time(), "ok": ok, "err": err, "items": len(items)}
    _save_state(_STATE, st)
    if ok:
        rep["sent"] = 1
    else:
        rep["errors"].append(f"发送失败: {err}")
    return rep


# ── B. 1min 账号池监控 ─────────────────────────────────────────────────────
def _watch_conf(conf: dict) -> tuple[bool, int, list]:
    w = conf["watch"]
    handles = [str(h).strip().lstrip("@") for h in (w.get("handles") or []) if str(h).strip()]
    return bool(w.get("enabled", False)), int(w.get("interval_s") or 60), handles


def _fx_latest(handle: str) -> list[dict]:
    """复用 fetchers 的 FxTwitter v2 通路。返回 [{sid, ts, text, url}] 新→旧。"""
    from fetchers.basic import _tw_fetch_statuses
    out = []
    for s in _tw_fetch_statuses(handle, 5, False):
        posts = s.get("statuses") or [] if s.get("type") == "thread" else [s]
        for p in posts:
            au = p.get("author") or {}
            if str(au.get("screen_name", "")).lower() != handle.lower():
                continue
            text = str(((p.get("raw_text") or {}).get("text")) or p.get("text") or "").strip()
            sid = str(p.get("id") or "")
            if sid and text:
                out.append({"sid": sid, "ts": p.get("created_timestamp") or 0, "text": text,
                            "url": p.get("url") or f"https://x.com/{handle}/status/{sid}"})
    return out


def watch_loop() -> int:
    """常驻循环。每 interval_s 扫一遍账号池, 有更新即发群。"""
    print("[feishu-watch] 启动(账号池来自 config.local.yaml sources.feishu.watch)", flush=True)
    err_streak: dict[str, int] = {}
    while True:
        conf = _conf()
        w_enabled, interval, handles = _watch_conf(conf)
        if not (conf["enabled"] and w_enabled and handles):
            time.sleep(max(interval, 30))
            continue
        st = _load_state(_WATCH_STATE)
        last = st.setdefault("last", {})
        changed = False
        for h in handles:
            if err_streak.get(h, 0) >= 3:                # 连错3次歇一轮
                err_streak[h] -= 1
                continue
            try:
                posts = _fx_latest(h)
                err_streak[h] = 0
            except Exception as e:
                err_streak[h] = err_streak.get(h, 0) + 1
                print(f"[feishu-watch] @{h} 抓取失败({err_streak[h]}): {str(e)[:80]}", flush=True)
                time.sleep(1)
                continue
            if not posts:
                continue
            newest = max(posts, key=lambda p: int(p["sid"]))
            prev = str(last.get(h) or "")
            if not prev:                                  # 首见只登记不回填
                last[h] = newest["sid"]
                changed = True
                print(f"[feishu-watch] @{h} 基线登记 {newest['sid']}", flush=True)
                continue
            fresh = sorted((p for p in posts if int(p["sid"]) > int(prev)),
                           key=lambda p: int(p["sid"]))
            for p in fresh:
                ok, err = send_text(conf,
                                    f"🚨 @{h} 更新:\n{p['text'][:2800]}\n{p['url']}")
                print(f"[feishu-watch] @{h} 新帖 {p['sid']} 推送 {'ok' if ok else 'FAIL '+err}",
                      flush=True)
                time.sleep(0.5)
            if fresh:
                last[h] = newest["sid"]
                changed = True
            time.sleep(0.5)
        if changed:
            _save_state(_WATCH_STATE, st)
        time.sleep(interval)
