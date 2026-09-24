"""飞书披露双自动化(2026-09-17 用户裁决):

A. 15min 情报摘要(run_digest): refresh 轮末调用——本轮新增 twitter 条目
   → 话题聚合+传播热度(同题账号数)+作者标注 → LLM 摘要(经 zen_bridge 链) → 发群。
   LLM 挂→规则兜底(账号+条目直列)。新增 <min_items 静默跳过不刷群。
B. 1min 账号池监控(watch_loop): FxTwitter v2 时间线逐账号对比 last_seen,
   有更新即发群(原文+链接)。账号池 = sources.feishu.watch.handles(用户指定),
   每轮循环重读配置, 改完即生效; 首见账号只登记不回填(防入群刷屏)。
C. 账号成分推送(run_account_push, 2026-09-21): 每2h 收集近2h X帖 → 9大类投影
   (L1优先/继承作者) → 按账号成分mix选各主题热度Top → @账号所有人发群。
   复用A的refresh轮末挂点(A已停用不冲突), 配置 sources.feishu.account_push。

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
import os
import re
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

try:
    import fcntl                                # Linux(云端)
except ImportError:                             # pragma: no cover
    fcntl = None
try:
    import msvcrt                               # Windows(本机)
except ImportError:                             # pragma: no cover
    msvcrt = None

from . import _cfg_section, data_dir, store as _store
from . import chain_guard as _guard

_STATE = "feishu.json"
_PUSH_LOCK_FH = None


def _acquire_push_lock() -> bool:
    """推送单实例锁(0924 双推事故: 手跑push与refresh轮末push并发, 闸口check-then-act
    竞态致 13 账号双页双消息)。同 refresh.lock 模式: fcntl/msvcrt 非阻塞锁, 进程死
    内核自动释放; 锁不上=另一实例在跑, 本轮静默跳过。"""
    global _PUSH_LOCK_FH
    if msvcrt is None and fcntl is None:
        return True
    p = _store._serve_dir() / "account-push.lock"
    p.parent.mkdir(parents=True, exist_ok=True)
    fh = open(p, "a+b")
    try:
        if msvcrt is not None:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.lockf(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False
    fh.seek(0)
    fh.truncate()
    fh.write(f"pid={os.getpid()} started={datetime.now():%F %T}".encode())
    fh.flush()
    _PUSH_LOCK_FH = fh
    return True
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
            "watch": dict(c.get("watch") or {}),
            "account_push": dict(c.get("account_push") or {})}


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
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:                 # 飞书错误体在响应里, 透出不裸抛
        try:
            return json.loads(e.read().decode())
        except Exception:
            raise e                                     # low-2: 重抛HTTPError保状态码, 不压成JSON解析错


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


def send_text(conf: dict, text: str, receive: dict | None = None) -> tuple[bool, str]:
    """发文本消息。receive={"type":"chat_id"|"open_id","id":...}; 缺省=群(chat_id)。
    open_id(ou_..)=私发个人(应用需在该成员可用范围内)。返回 (ok, err)。"""
    rid_type = str((receive or {}).get("type") or "chat_id")
    rid = str((receive or {}).get("id") or "")
    if rid_type == "chat_id" and not rid:
        rid = conf["chat_id"]
    if not (conf["enabled"] and conf["app_id"] and rid):
        return False, "feishu 未配置(enabled/app_id/接收ID)"
    try:
        d = _post(f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={rid_type}",
                  {"receive_id": rid, "msg_type": "text",
                   "content": json.dumps({"text": text[:MAX_TEXT]}, ensure_ascii=False)},
                  token=_token(conf))
        if d.get("code") == 0:
            return True, ""
        err = f"code={d.get('code')} {str(d.get('msg'))[:100]}"
        if d.get("code") == 230002:
            err += "（机器人对收件人不可见: 群发=先拉进群, 私发=应用可用范围需含该成员）"
        return False, err
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


_LLM_EXTRA_OK = {"thinking", "max_tokens", "max_completion_tokens", "top_p",
                 "seed", "reasoning_split", "stream"}


def _llm_extra(m: dict) -> dict:
    """链项 extra 请求体透传(白名单过滤, low-5: 防 **extra 静默覆盖 model/messages)。"""
    ex = m.get("extra") if isinstance(m.get("extra"), dict) else {}
    return {k: v for k, v in ex.items() if k in _LLM_EXTRA_OK}


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
            extra = _llm_extra(m)                       # low-1: MiniMax链尾兜底时关思考/防思考混content
            r = requests.post(f"{base.rstrip('/')}/chat/completions",
                              headers={"Authorization": f"Bearer {key or 'x'}",
                                       "Content-Type": "application/json"},
                              json={"model": model,
                                    "messages": [{"role": "system", "content": _SYS},
                                                 {"role": "user", "content": prompt}],
                                    **extra},
                              timeout=120)
            r.raise_for_status()
            out = (r.json().get("choices") or [{}])[0].get("message", {}).get("content")
            out = re.sub(r"<think>.*?</think>", "", out or "", flags=re.S)
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


# ── C. 账号成分推送 run_account_push(2026-09-21, 复用废弃的15min摘要挂点) ────
# 每 interval_h(默认2h) 收集近 window_h 的 X 帖 → 投影到 9 大类 → 按每个账号的
# 成分 mix(如 美股60/亚太10/AI30) 选各主题热度Top → @账号所有人 发群。
# 分类纪律(与 2026-09-21 分类方案一致): 条目 L1 投影优先, 无标签则继承作者账号
# (池 tags/note 规则, 已停用账号如土耳其池不参与); 投不进任何类 = 不推(宁漏勿误)。
# 热度 = FxTwitter 现拉浏览量(_enrich_stats 复用), 缺失按 0 参与排序。
# 配置(sources.feishu.account_push, config.local.yaml):
#   enabled / interval_h=2 / window_h=2 / chat_id(缺省用上层feishu.chat_id)
#   top_total=10(每账号总条数, 按mix%最大余数法分到各主题, 每主题≥1)
#   accounts: [{name, owner(显示名) | owner_open_id(ou_..真@), mix: {主题: 百分比}}]
_PUSH_STATE = "feishu-account-push.json"

TOPICS = ("美股", "A股", "亚太股市", "加密", "AI与科技",
          "产业链与制造", "宏观与政策", "大宗与周期", "投教科普")

# L1(19赛道) → 大类; 金融与加密走 L2 细分(_CRYPTO_L2/市场规则), 不在此表。
_L1_TOPIC = {
    "互联网与传媒": "AI与科技", "半导体": "AI与科技", "AI与算力": "AI与科技",
    "消费电子": "AI与科技", "通信与卫星": "AI与科技",
    "汽车与智能驾驶": "产业链与制造", "新能源与电力": "产业链与制造",
    "军工与航空航天": "产业链与制造", "交通运输": "产业链与制造",
    "工业与机器人": "产业链与制造", "医药生物": "产业链与制造", "消费": "产业链与制造",
    "油气与能源": "大宗与周期", "金属与矿业": "大宗与周期", "化工与新材料": "大宗与周期",
    "农业与食品": "大宗与周期", "地产与基建": "大宗与周期",
    "宏观与政策": "宏观与政策",
}
_CRYPTO_L2 = {"加密资产", "支付金科", "交易所"}
# 文本加密锁(附加不替换): 命中即补"加密"主题, 防止币帖被纯美股作者继承独占。
_CRYPTO_TXT_PAT = re.compile(
    r"(?i)\b(btc|bitcoin|ethereum|eth|xrp|solana|stablecoin|crypto|altcoin)\b")
# 观点型判定(v1 规则, 2026-09-22 用户裁决"观点优先, 流量为次"): 账号身份是大V/分析师/
# 交易员 → 其帖默认观点; 条目类型=分析 → 观点; 文本命中第一人称/立场词 → 观点。
_OPINION_ROLES = {"analyst", "trader", "kol", "insider"}
_OPINION_PAT = re.compile(
    r"(?i)\b(i think|in my view|my take|i believe|we should|must (buy|sell|avoid)|"
    r"overvalued|undervalued|bubble|mispriced|我认为|依我看|我的看法|看多|看空|"
    r"加仓|减仓|清仓|抄底|追高|逻辑是|观点[是:])")
_TIME_FMT = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")


def _parse_time(s: str):
    import datetime as _dt
    for f in _TIME_FMT:
        try:
            return _dt.datetime.strptime(str(s or "").strip(), f)
        except ValueError:
            continue
    return None


def _rate(it: dict, now) -> float:
    """浏览增速 = 浏览量/发布时长(小时), 时长<15min 按0.25h 兜底防除零/爆表。"""
    v = it.get("views") or 0
    if not v:
        return 0.0
    t = _parse_time(it.get("time"))
    age_h = max((now - t).total_seconds() / 3600, 0.25) if t else 24.0
    return v / min(age_h, 24.0)


def _is_opinion(it: dict) -> bool:
    if str(it.get("author_role") or "") in _OPINION_ROLES:
        return True
    if str(it.get("item_type") or "") == "分析":
        return True
    return bool(_OPINION_PAT.search(it.get("text") or ""))
_APAC_MKTS = ("香港", "台湾", "日本", "韩国")
_EDU_PAT = re.compile("教学|课程|科普|入门|教程|教育|方法论|怎么读|一文读懂|估值课")
_TAG_TOPIC = {"美股": "美股", "加密": "加密", "AI": "AI与科技", "科技": "AI与科技",
              "A股": "A股", "港股": "亚太股市", "台股": "亚太股市",
              "日股": "亚太股市", "韩股": "亚太股市"}


def _push_conf(conf: dict) -> dict:
    ap = conf.get("account_push") or {}
    return {"enabled": bool(ap.get("enabled", False)),
            "interval_h": float(ap.get("interval_h") or 2),
            "window_h": float(ap.get("window_h") or 2),
            "schedule": [int(h) for h in (ap.get("schedule") or []) if isinstance(h, (int, float))],
            "chat_id": str(ap.get("chat_id") or conf.get("chat_id") or ""),
            "top_total": int(ap.get("top_total") or 10),
            "doc": dict(ap.get("doc") or {}),
            "accounts": [a for a in (ap.get("accounts") or []) if isinstance(a, dict)]}


def _pool_accounts() -> list:
    """启用账号池(只读; local 覆盖规则镜像 fetchers.basic; 任何异常=空池不炸)。"""
    import yaml
    pool_f = Path(__file__).resolve().parents[1] / "config" / "twitter_pool.yaml"
    try:
        pool = yaml.safe_load(pool_f.read_text(encoding="utf-8")) or {}
        loc = pool_f.with_name("twitter_pool.local.yaml")
        if loc.is_file():
            lp = yaml.safe_load(loc.read_text(encoding="utf-8")) or {}
            base = {str(a.get("handle", "")).lower(): a for a in (pool.get("accounts") or [])}
            for a in (lp.get("accounts") or []):
                base[str(a.get("handle", "")).lower()] = a
            pool["accounts"] = list(base.values())
        return [a for a in (pool.get("accounts") or [])
                if a.get("enabled", True) and a.get("handle")]
    except Exception:
        return []


def _author_topics() -> dict:
    """{handle小写: {大类}} —— 池 tags + note/positioning 投教信号。"""
    out: dict[str, set] = {}
    for a in _pool_accounts():
        h = str(a.get("handle") or "").strip().lstrip("@").lower()
        if not h:
            continue
        tp = {_TAG_TOPIC[str(t).strip()] for t in (a.get("tags") or [])
              if str(t).strip() in _TAG_TOPIC}
        blob = f"{a.get('note') or ''} {a.get('positioning') or ''}"
        if _EDU_PAT.search(blob):
            tp.add("投教科普")
        out[h] = tp
    return out


def _item_topics(sectors: str, markets: str, author: str, a_topics: dict,
                 text: str = "") -> set:
    """条目 → 大类集合。L1 投影优先(加密锁最高), 无标签继承作者, 再无=空(不推);
    文本命中加密词则附加"加密"(不替换已有主题)。"""
    tp: set = set()
    try:
        secs = json.loads(sectors or "[]")
    except ValueError:
        secs = []
    try:
        mkts = json.loads(markets or "[]")
    except ValueError:
        mkts = []
    for s in secs:
        parts = str(s).split(">")
        l1 = parts[0] if parts else ""
        l2 = parts[1] if len(parts) > 1 else ""
        if l1 == "金融与加密":
            if l2 in _CRYPTO_L2:
                tp.add("加密")
            else:                                   # 银行/券商等 → 按市场落股市桶
                if "A股" in mkts:
                    tp.add("A股")
                elif "美国" in mkts:
                    tp.add("美股")
                elif any(m in mkts for m in _APAC_MKTS):
                    tp.add("亚太股市")
        elif l1 in _L1_TOPIC:
            tp.add(_L1_TOPIC[l1])
    if tp:
        if _CRYPTO_TXT_PAT.search(text or ""):
            tp.add("加密")
        return tp
    tp = set(a_topics.get(str(author or "").strip().lstrip("@").lower() or "", ()))
    if _CRYPTO_TXT_PAT.search(text or ""):
        tp.add("加密")
    return tp


def _split_quota(mix: dict, total: int) -> dict:
    """mix{主题:pct>0} → 各主题条数(和=total, 每主题≥1; 最大余数法)。"""
    themes = [t for t, p in mix.items() if p and p > 0]
    if not themes:
        return {}
    total = max(total, len(themes))
    raw = {t: mix[t] / sum(mix[t] for t in themes) * total for t in themes}
    quota = {t: max(1, int(raw[t])) for t in themes}
    while sum(quota.values()) > total:              # 每主题≥1 可能超编 → 砍小数部分最大者
        cuttable = [t for t in themes if quota[t] > 1]   # M4: 只在可砍集里选, 防带 sum>total 退出
        if not cuttable:
            break
        t_cut = max(cuttable, key=lambda t: (quota[t] - raw[t], raw[t]))
        quota[t_cut] -= 1
    while sum(quota.values()) < total:              # 余数从大到小补
        quota[max(themes, key=lambda t: raw[t] - quota[t])] += 1
    return quota


# ── C2. 飞书电子表格披露(doc 模式, 2026-09-23 用户裁决替代分块消息) ─────────
# 每账号一个电子表格(首次推送时创建+授权给群), 每次推送新增子表"年-月-日-时:分",
# 全量命中候选逐行写入(不再受消息长度/条数限制), 群里只发一条短@+链接通知。
# 表头: 第1行=账号/所属人/成分/窗口/命中; 第2行=列名; 第3行起每条一行。
_DOC_COLS = ["主题", "类型", "作者", "浏览量", "浏览增速(次/时)", "金融价值",
             "人设匹配", "中文译文", "原文内容", "原文链接", "发布时间"]
_DOC_BATCH_ROWS = 200


def _doc_enabled(ap: dict) -> bool:
    return bool((ap.get("doc") or {}).get("enabled", False))


def _ensure_doc(conf: dict, acc: dict, ap: dict, st: dict) -> tuple:
    """账号 → (spreadsheet_token, url)。首次创建「选题推送-{账号名}」并授权群可编辑,
    之后从状态缓存直取。返回 ("", "") = 失败(调用方回退消息模式)。"""
    docs = st.setdefault("docs", {})
    key = str(acc.get("name") or "")
    hit = docs.get(key) or {}
    if hit.get("token") and hit.get("url"):
        return hit["token"], hit["url"]
    try:
        d = _post("https://open.feishu.cn/open-apis/sheets/v3/spreadsheets",
                  {"title": f"选题推送-{key}"}, token=_token(conf))
        if d.get("code") != 0:
            return "", f"建表失败 code={d.get('code')} {str(d.get('msg'))[:80]}"
        data = d.get("data") or {}
        spread = data.get("spreadsheet") or {}
        token, url = str(spread.get("spreadsheet_token") or ""), str(spread.get("url") or "")
        if not token:
            return "", "建表返回缺 token"
        if not url:
            url = f"https://feishu.cn/sheets/{token}"
        note = ""
        if ap.get("chat_id"):                     # 授权目标群可编辑
            p = _post(f"https://open.feishu.cn/open-apis/drive/v1/permissions/{token}/members"
                      "?type=sheet&need_notification=false",
                      {"member_type": "chat", "member_id": ap["chat_id"], "perm": "edit"},
                      token=_token(conf))
            if p.get("code") != 0:                # 授权失败不阻断, 链接仍可访问性受影响
                note = f" (群授权失败 code={p.get('code')}, 机器人分享链接可达)"
        docs[key] = {"token": token, "url": url}   # 缓存只存净URL(M1: 错误尾巴永久污染修复)
        return token, url + note                   # 通知文本带备注, 缓存干净
    except Exception as e:
        return "", f"{type(e).__name__}: {str(e)[:80]}"


def _doc_sheet_title(now=None) -> str:
    import datetime as _dt
    t = now or _dt.datetime.now()
    return f"{t.year}-{t.month}-{t.day}-{t.hour}:{t.minute:02d}"


# 列宽布局(0924 用户裁决; 端点 0-based 左闭右开): A,B,D,E,F,G,I,J,K=50; C=100; H=700(译文主读区)
_DOC_COL_W = ((0, 2, 50), (2, 3, 100), (3, 7, 50), (7, 8, 700), (8, 11, 50))


def _doc_set_col_widths(conf: dict, token: str, sid: str) -> list:
    """v3 update_dimension + properties.pixel_size(0924 二次实测定案: 端点三重校验
    活着=1310251 枚举/9499 类型/范围≤1000, 假成功疑虑排除; 首轮 v2 dimension_range
    +camelCase 是错端点错字段全被吞)。样式体验项: 逐段失败不阻断数据, 错误清单
    返回给调用方披露——绝不再静默吞。"""
    errs = []
    for start, end, w in _DOC_COL_W:
        try:
            d = _post(f"https://open.feishu.cn/open-apis/sheets/v3/spreadsheets/{token}"
                      f"/sheets/{sid}/update_dimension",
                      {"dimension_range": {"major_dimension": "COLUMNS",
                                           "start_index": start, "end_index": end},
                       "properties": {"pixel_size": w}}, token=_token(conf))
            if d.get("code") != 0:
                errs.append(f"列宽[{start + 1}-{end}列] {str(d.get('msg'))[:60]}")
        except Exception as e:
            errs.append(f"列宽[{start + 1}-{end}列] {e}")
    return errs


def _doc_add_sheet(conf: dict, token: str, title: str) -> tuple:
    """新建子表 → (sheet_id, err)。同名(同分钟重推)自动加 -2 后缀重试一次。
    端点=sheets_batch_update/addSheet(旧 sheets_post 已 404 下线, 0923 实测)。"""
    for t in (title, f"{title}-2"):
        try:
            d = _post(f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{token}"
                      "/sheets_batch_update",
                      {"requests": [{"addSheet": {"properties": {"title": t}}}]},
                      token=_token(conf))
            if d.get("code") == 0:
                replies = ((d.get("data") or {}).get("replies") or [])
                sid = str((((replies[0] if replies else {}).get("addSheet") or {})
                           .get("properties") or {}).get("sheetId") or "")
                if sid:
                    return sid, ""
        except Exception as e:
            return "", f"{type(e).__name__}: {str(e)[:80]}"
    return "", "子表创建失败"


def _doc_write_rows(conf: dict, token: str, sid: str, rows: list) -> str:
    """按 _DOC_BATCH_ROWS 行分批 PUT 写入, 全部成功返回 ""。"""
    import requests
    n_cols = len(_DOC_COLS)
    for start in range(0, len(rows), _DOC_BATCH_ROWS):
        chunk = [[f"'{c}" if isinstance(c, str) and c[:1] in "=+-@" else c
                  for c in row]                       # 公式防护: USER_ENTERED下前导符转文本
                 for row in rows[start:start + _DOC_BATCH_ROWS]]
        rng = f"{sid}!A{start + 1}:{chr(ord('A') + n_cols - 1)}{start + len(chunk)}"
        try:
            r = requests.put(
                f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{token}/values"
                "?valueInputOption=USER_ENTERED",
                headers={"Authorization": f"Bearer {_token(conf)}",
                         "Content-Type": "application/json"},
                data=json.dumps({"valueRange": {"range": rng, "values": chunk}},
                                ensure_ascii=False).encode(), timeout=30)
            d = r.json()
            if d.get("code") != 0:
                return f"写入失败 code={d.get('code')} {str(d.get('msg'))[:80]}"
        except Exception as e:
            return f"{type(e).__name__}: {str(e)[:80]}"
    return ""


# ── C3. 金融价值分 FV + 人设正则匹配(0923 用户裁决: FV列用译文算/人设先正则版) ────
# FV 六维与 workbench/server/x_surge.py calc_fv 一字同源(词典/阈值改动须双向同步);
# 差异仅: text 输入=中文译文优先回退原文, 意外度恒缺省(原设计 M1 即如此)。
_FV_EVENT = {"macro": 28, "policy": 26, "legal": 24,
             "guidance": 20, "mna": 20, "earnings": 16,
             "contract": 13, "product": 13, "fda": 12, "offering": 10,
             "dividend": 6, "rating": 6, "personnel": 5}
_FV_MACRO_RE = re.compile(
    r"FOMC|美联储|联邦储备|ECB|日本央行|央行|非农|关税|出口管制|实体清单|制裁|地缘|空袭|停火", re.I)
_FV_REVISION_RE = re.compile(r"修订|修正|终值|revised|revision", re.I)
_FV_T1_TICKERS = {"NVDA", "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "TSLA",
                  "TSM", "ASML", "AVGO", "AMD", "MU", "000660"}
_FV_T1_TEXT_RE = re.compile(
    r"美联储|FOMC|ECB|日本央行|央行|财政部|白宫|台积电|TSMC|ASML|阿斯麦|英伟达|海力士|"
    r"美光|博通|CoWoS|HBM|EUV|CPO|硅光|光模块", re.I)
_FV_HOT_L2 = ("HBM", "CPO", "EUV", "CoWoS", "光模块", "硅光", "先进制程")
_FV_SOURCE = {"官方": 15, "机构": 12, "快讯源": 8, "新闻源": 6, "大V": 5}
_FV_TIERS = ((75, "P0"), (60, "P1"), (40, "P2"))


def _fv_item_score(it: dict, now=None) -> str:
    """条目金融价值分 → "78·P1"。纯规则毫秒级, 缺字段走中性/保守档(同 x_surge)。"""
    import datetime as _dt
    now = now or _dt.datetime.now()
    text = (it.get("text_zh") or "").strip() or str(it.get("text") or "")
    try:
        secs = json.loads(it.get("tickers") or "[]")
    except ValueError:
        secs = []
    tickers = [s for s in secs if isinstance(s, str)]
    try:
        mkts = json.loads(it.get("markets") or "[]")
    except ValueError:
        mkts = []
    try:
        sectors = json.loads(it.get("sectors") or "[]")
    except ValueError:
        sectors = []
    ev = _FV_EVENT.get(it.get("event_type") or "", 2)
    if _FV_MACRO_RE.search(text):
        ev = max(ev, 24)
    if _FV_REVISION_RE.search(text):
        ev = max(ev - 6, 2)
    if set(tickers) & _FV_T1_TICKERS or _FV_T1_TEXT_RE.search(text):
        ent = 22
    elif any(k in str(s) for s in sectors for k in _FV_HOT_L2):
        ent = 12
    elif tickers:
        ent = 8
    else:
        ent = 2
    src = _FV_SOURCE.get(it.get("positioning") or "", 3)
    if len(mkts) >= 3 or "全球" in mkts:
        imp = 12
    elif len(mkts) == 2:
        imp = 8
    elif len(mkts) == 1:
        imp = 5
    elif sectors:
        imp = 3
    else:
        imp = 0
    t0 = _parse_time(str(it.get("time") or ""))
    age_h = max((now - t0).total_seconds() / 3600, 0.0) if t0 else 24
    dup = int(it.get("dup_count") or 1)
    proof = 7 if dup >= 5 else 5 if dup >= 3 else 3 if dup >= 2 else 1
    fresh = (6 if age_h <= 2 else 5 if age_h <= 6 else 3 if age_h <= 24
             else 1 if age_h <= 72 else 0)
    score = min(ev + ent + src + imp + 5 + proof + fresh, 100)
    if ev >= 24 and src >= 15:
        score = max(score, 80)
    if ev <= 6 and ent <= 2:
        score = min(score, 40)
    tier = next((t for th, t in _FV_TIERS if score >= th), "P3")
    return f"{score}·{tier}"


# 人设正则匹配: 九类词典(中文为主+英文高频词兜底, 译文计算)。命中词数×mix权重 → 0-10。
# 词典养的=高频显性词; 语义贴合("实战风格")测不到——那是 LLM 版能力, 正则版管杀零命中噪声。
# 英文词全小写(匹配走 lower 文本), 中文词原样。
_PERSONA_DICT = {
    "美股": ("美股", "标普", "纳指", "纳斯达克", "道琼", "道指", "美联储", "FOMC", "非农",
             "财报", "华尔街", "美债", "美元指数", "波动率", "美股市场", "纽约联储",
             "特斯拉", "苹果", "微软", "谷歌", "亚马逊", "Meta", "期权", "做空", "多头",
             "空头", "龙头股", "科技七巨头", "标普500",
             "s&p", "nasdaq", "dow jones", "fed", "fomc", "earnings", "tesla",
             "apple", "wall street", "u.s. stocks", "us stocks"),
    "A股": ("A股", "沪指", "上证", "深证", "创业板", "科创板", "北交所", "证监会", "沪深",
            "涨停", "跌停", "北向资金", "两融", "中证", "券商股", "A股市场", "人民币中间价",
            "shanghai composite", "shenzhen", "china stocks"),
    "亚太股市": ("港股", "恒生", "恒指", "日经", "东证", "台股", "加权指数", "韩股", "KOSPI",
                "亚太股市", "港交所", "恒生科技", "港股通", "日股", "富士康", "台积电",
                "日圆", "日元汇率",
                "hang seng", "nikkei", "kospi", "taiwan stocks", "tsmc"),
    "加密": ("比特币", "BTC", "以太坊", "ETH", "加密货币", "数字货币", "区块链", "稳定币",
             "USDT", "USDC", "币安", "Coinbase", "山寨币", "减半", "链上", "矿机",
             "Solana", "狗狗币", "比特币ETF",
             "bitcoin", "ethereum", "crypto", "blockchain", "stablecoin", "binance"),
    "AI与科技": ("AI", "人工智能", "OpenAI", "GPT", "大模型", "芯片", "GPU", "算力",
                "英伟达", "台积电", "半导体", "自动驾驶", "机器人", "ChatGPT", "Claude",
                "DeepSeek", "智能体", "Agent", "训练", "推理芯片", "科技股",
                "nvidia", "chatgpt", "openai", "semiconductor", "gpu", "ai agent"),
    "产业链与制造": ("供应链", "产能", "出货量", "工厂", "制造", "封装", "光刻", "上游",
                   "下游", "订单", "库存", "零部件", "原材料", "涨价", "元器件",
                   "生产线", "代工", "组装", "交付",
                   "supply chain", "capacity", "shipment", "inventory", "foundry"),
    "宏观与政策": ("CPI", "通胀", "利率", "GDP", "衰退", "关税", "央行", "财政部", "白宫",
                 "国会", "货币政策", "制裁", "地缘", "国债", "收益率", "汇率", "宽松",
                 "紧缩", "宏观", "就业数据",
                 "inflation", "interest rate", "recession", "tariff", "treasury",
                 "white house", "sanctions", "yield"),
    "大宗与周期": ("黄金", "金价", "原油", "油价", "铜价", "大宗商品", "OPEC", "天然气",
                 "白银", "铁矿石", "煤炭", "农产品", "周期股", "金属", "油轮",
                 "gold", "silver", "crude", "oil price", "copper", "opec"),
    "投教科普": ("教学", "入门", "科普", "教程", "一文读懂", "方法论", "估值", "止损",
               "仓位", "风险管理", "新手", "图解", "复盘", "技术分析", "基本面分析",
               "beginner", "tutorial", "guide to"),
}


# 预编译: ASCII词→小写+首尾非字母数字边界(防 said 命中 ai / feed 命中 fed,
# 且中文相邻算边界 "AI部队" 可命中); 中文词→子串(None)。
_PERSONA_RE = {
    t: [((w, re.compile(rf"(?<![a-z0-9]){re.escape(w.lower())}(?![a-z0-9])"))
         if w.isascii() else (w, None)) for w in ws]
    for t, ws in _PERSONA_DICT.items()}


def _persona_score(text: str, mix: dict) -> int:
    """译文×九类词典命中数, 按 mix 权重加权 → 0-10。零成本毫秒级。
    ASCII 词走小写+边界正则(未译回退英文原文时兜底), 中文词子串。"""
    if not text:
        return 0
    low = text.lower()
    total = 0.0
    for t, pct in mix.items():
        words = _PERSONA_RE.get(t)
        if not words or not pct:
            continue
        hits = sum(1 for w, pat in words if (pat.search(low) if pat else w in text))
        if hits:
            total += float(pct) / 100.0 * (0.5 if hits == 1
                                           else 0.8 if hits == 2 else 1.0)
    return round(min(total, 1.0) * 10)


_CJK_RE = re.compile(r"[一-鿿]")


def _looks_zh(t: str) -> bool:
    """原文是否中文(CJK占比)——全站翻译对中文条目 skip, text_zh 恒空。"""
    smp = (t or "")[:200]
    if not smp:
        return False
    cjk = len(_CJK_RE.findall(smp))
    return cjk >= 4 and cjk / max(len(smp), 1) >= 0.3


def _doc_rows(acc: dict, mix: dict, ordered: list, bj: str, cand_n: int,
              now=None) -> list:
    """账号卡 → 二维行数组: 第1行档案 + 第2行列名 + 全量条目行(主题按mix降序,
    节内观点在前增速降序)。ordered = [(主题, [item...]), ...]。"""
    import datetime as _dt
    now = now or _dt.datetime.now()
    mix_s = " · ".join(f"{t}{int(p)}%" for t, p in sorted(mix.items(), key=lambda kv: -kv[1]))
    rows = [[f"账号: {acc.get('name') or '?'}", f"所属人: {acc.get('owner') or '?'}",
             f"成分: {mix_s}", f"窗口: {bj}", f"命中: {cand_n} 条"], list(_DOC_COLS)]
    for t, its in ordered:
        for it in its:
            txt = str(it.get("text") or "").strip()
            zh = (it.get("text_zh") or "").strip()
            native = (not zh) and _looks_zh(txt)   # 原文即中文(全站翻译skip类, 无译文)
            rows.append([
                t, "观点" if _is_opinion(it) else "资讯",
                str(it.get("author_handle") or ""), int(it.get("views") or 0),
                int(_rate(it, now)),
                _fv_item_score(it, now),
                _persona_score(zh or txt, mix),
                zh or txt,                            # 0924用户裁决: 不允许[未译]——无译文显示原文
                "" if native else txt,                # 中文帖原文列留空(译文列已是同内容)
                str(it.get("url") or ""),
                str(it.get("time") or "")])
    return rows


def _doc_order_all(cand: list, mix: dict, now=None) -> list:
    """doc 模式不用配额: 全量命中按 主题(mix降序)→观点→增速 组织。"""
    import datetime as _dt
    now = now or _dt.datetime.now()
    order = sorted(mix, key=lambda t: -mix[t])
    ranked = sorted(cand, key=lambda x: (0 if _is_opinion(x) else 1, -_rate(x, now)))
    return [(t, [it for it in ranked if t in (it.get("topics") or ())]) for t in order]


def _fmt_views(v) -> str:
    if v is None:
        return ""
    try:
        v = int(v)
    except (TypeError, ValueError):
        return ""
    return f"{v / 10000:.1f}万".replace(".0万", "万") if v >= 10000 else str(v)


def _pick_for_account(items: list, acc: dict, top_total: int, now=None) -> dict:
    """按成分选各主题 Top。排序(2026-09-22 用户裁决): 观点型优先, 其下按浏览增速
    (浏览量/发布时长)降序; 条目在一个账号卡内最多出现一次(归入mix最高的命中主题,
    该主题满额再落其他命中主题)。返回 {主题: [item按序]}。"""
    import datetime as _dt
    now = now or _dt.datetime.now()
    mix = {str(k): float(v) for k, v in (acc.get("mix") or {}).items()
           if str(k) in TOPICS and float(v) > 0}
    if not mix:
        return {}
    quota = _split_quota(mix, top_total)
    order = sorted(mix, key=lambda t: -mix[t])      # 主题排序=成分占比降序
    per = {t: [] for t in order}
    ranked = sorted(items, key=lambda x: (0 if _is_opinion(x) else 1, -_rate(x, now)))
    for it in ranked:
        hit = [t for t in order if t in (it.get("topics") or ())]
        if not hit:
            continue
        for t in sorted(hit, key=lambda t: -mix[t]):
            if len(per[t]) < quota[t]:
                per[t].append(it)
                break
    return {t: per[t] for t in order if per[t]}


def _fmt_rate(r: float) -> str:
    return f"{_fmt_views(int(r))}/时" if r >= 1 else ""


def _compose_push(acc: dict, per: dict, mix: dict, bj: str, cand: int,
                  hits: dict | None = None, now=None) -> list:
    """账号卡 → 消息块列表(飞书单条长度限制, 超长自动分块, 每块≤2800字)。
    每条目=【观点|资讯】增速@作者 + 中文译文(未译标注) + 原文全文 + 链接, 不截断。
    主题节内: 观点在前资讯在后, 各自按浏览增速降序(_pick 已排好)。"""
    import datetime as _dt
    now = now or _dt.datetime.now()
    oid = str(acc.get("owner_open_id") or "").strip()
    owner = str(acc.get("owner") or "").strip() or "账号所有人"
    name = acc.get("name") or "?"
    if acc.get("dm") and oid:
        head = f"{owner} 你好｜账号「{name}」"
    elif oid:
        head = f'<at user_id="{oid}"></at> 账号「{name}」'
    else:
        head = f"@{owner} 账号「{name}」"
    mix_s = " · ".join(f"{t}{int(p)}%" for t, p in
                       sorted(mix.items(), key=lambda kv: -kv[1]))
    body: list = [f"{head}近几小时按成分选题",
                  f"成分: {mix_s}｜窗口 {bj}｜候选命中 {cand} 条（按观点优先+浏览增速取Top，每板块显示 命中/取用）"]
    for t, its in per.items():
        n_hit = (hits or {}).get(t, len(its))
        n_op = sum(1 for x in its if _is_opinion(x))
        body.append(f"\n▍{t}（命中{n_hit}·取{len(its)}｜观点{n_op}/资讯{len(its)-n_op}）")
        for i, it in enumerate(its, 1):
            tag = "观点" if _is_opinion(it) else "资讯"
            rt = _fmt_rate(_rate(it, now))
            v = _fmt_views(it.get("views"))
            vs = f"👁{v}" if v else ""
            rs = f"·{rt}" if rt else ""
            zh = (it.get("text_zh") or "").strip()
            zh_line = f"译: {zh}" if zh else "译: [未译]"
            body.append(f"{i}.【{tag}】{vs}{rs} @{it.get('author_handle') or '?'}")
            body.append(zh_line)
            body.append(f"原: {it.get('text') or ''}")
            body.append(str(it.get("url") or ""))
    body.append("\n—— 数据站按账号成分自动整理(观点优先·浏览增速排序)")
    chunks, cur, cur_len = [], [], 0
    for ln in body:                                  # 分块: 行粒度, ≤2800字/块
        if cur_len + len(ln) > 2800 and cur:
            chunks.append("\n".join(cur))
            cur, cur_len = [f"（续）{head}"], 0
        cur.append(ln)
        cur_len += len(ln) + 1
    if cur:
        chunks.append("\n".join(cur))
    return [c[:MAX_TEXT] for c in chunks]


_SYS_TR = """你是财经翻译。输入是编号的X帖子原文JSON数组, 逐条译成简体中文,
保留数字/代码/符号, 语气忠实。只输出JSON数组(同序), 每元素为对应中文译文字符串。"""


_TR_TEXT_MAX = 10000     # 单条翻译输入上限(实测真实7693字符帖完整译; X长推留余量)
_TR_BATCH_N = 12          # 每批条数上限(短文吞吐)


def _tr_batches(todo: list, max_chars: int = 6000) -> list:
    """按输入字符预算切批: ≤12条且累计≤max_chars——短文依旧12条/批, 长文自动
    小批(12条×3000字译文会撑爆输出max_tokens致JSON撕裂, 0923长文实测后定)。"""
    out, buf, cur = [], [], 0
    for it in todo:
        sz = min(len(str(it.get("text") or "")), _TR_TEXT_MAX)
        if buf and (len(buf) >= _TR_BATCH_N or cur + sz > max_chars):
            out.append(buf)
            buf, cur = [], 0
        buf.append(it)
        cur += sz
    if buf:
        out.append(buf)
    return out


def _save_zh(batch: list):
    """兜底译文回写 items(只补空不覆盖, 防与全站翻译打架; 容错不抛)。"""
    try:
        conn = _store._connect()
        with conn:
            for it in batch:
                zh = (it.get("text_zh") or "").strip()
                u = str(it.get("url") or "")
                if zh and u:
                    conn.execute("UPDATE items SET text_zh=? WHERE url=? "
                                 "AND (text_zh IS NULL OR text_zh='')", (zh, u))
    except Exception:
        pass


def _tr_record(base: str, model: str, ok: bool, ecls: str, t0: float,
               usage: dict | None = None) -> None:
    """非桥调用(MiniMax 等)调用侧记录; Zen 流量由 zen_bridge 记, 不重复计(0924 额度统计)。"""
    if _guard.is_bridge(base):
        return
    try:
        u = usage or {}
        _guard.record(logger="caller", node=_guard.node_of(base), model=model, ok=ok,
                      ecls=ecls, latency_ms=int((time.time() - t0) * 1000),
                      tokens={"prompt": u.get("prompt_tokens") or 0,
                              "completion": u.get("completion_tokens") or 0,
                              "total": u.get("total_tokens") or 0})
    except Exception:
        pass


def _translate_missing(conf: dict, items: list, cap: int = 12,
                       deadline: float | None = None) -> int:
    """推送前兜底翻译: 对缺 text_zh 的条目批量过一遍 LLM(链=digest_models
    缺省复用 translate.models, 云端zen_bridge/本地均可), 12条/批循环到 cap,
    LLM 批次偶发漏翻 → 共两轮(第二轮只补仍缺); 成功即回写库(下轮同条目免重翻)。
    deadline(epoch) 过线即停(M3: refresh轮末尾预算防挤占后续llm_tag)。
    失败静默保[未译]。返回补译成功数。链序过 guard.order_chain(额度统计/熔断)。"""
    import requests
    todo = [it for it in items if not (it.get("text_zh") or "").strip()][:cap]
    if not todo:
        return 0
    models = conf.get("digest_models") or (_cfg_section().get("translate") or {}).get("models") or []
    try:
        models = _guard.order_chain(models)
    except Exception:
        pass
    done = 0
    for _round in range(2):
        if deadline and time.time() > deadline:
            break
        todo = [it for it in todo if not (it.get("text_zh") or "").strip()]
        if not todo:
            break
        for batch in _tr_batches(todo):
            if deadline and time.time() > deadline:
                break
            payload = json.dumps([str(it.get("text") or "")[:_TR_TEXT_MAX] for it in batch],
                                 ensure_ascii=False)
            for m in models:
                base = str(m.get("base_url") or "").strip().rstrip("/")
                model = str(m.get("model") or "").strip()
                if not (base and model):
                    continue
                t0 = time.time()
                try:
                    extra = _llm_extra(m)                    # low-5: 白名单透传
                    r = requests.post(f"{base}/chat/completions",
                                      headers={"Authorization": f"Bearer {str(m.get('api_key') or 'x')}",
                                               "Content-Type": "application/json"},
                                      json={"model": model,
                                            "messages": [{"role": "system", "content": _SYS_TR},
                                                         {"role": "user", "content": payload}], **extra},
                                      timeout=90)
                    r.raise_for_status()
                    rj = r.json()
                    out = (rj.get("choices") or [{}])[0].get("message", {}).get("content") or ""
                    out = re.sub(r"<think>.*?</think>", "", out, flags=re.S)  # M2.x 思考混 content
                    arr = json.loads(re.sub(r"^```(json)?|```$", "", out.strip(), flags=re.M).strip())
                    if isinstance(arr, list):
                        for it, zh in zip(batch, arr):
                            if isinstance(zh, str) and zh.strip():
                                it["text_zh"] = zh.strip()
                                done += 1
                        _save_zh(batch)         # 回写库, 下轮窗口重叠条目免重翻
                        _tr_record(base, model, True, "ok", t0, rj.get("usage"))
                        break                   # 本批成功, 下一批
                except Exception as ex:
                    _tr_record(base, model, False, _guard.classify(exc=ex), t0)
                    continue
        # 终极兜底: 批量两轮后仍缺的逐条单翻——批量JSON输出偶发漏项, 单条成功率≈100%,
        # 保证披露里不再出现[未译](0923 用户裁决: 未译必须消灭而非降概率)
        for it in [x for x in todo if not (x.get("text_zh") or "").strip()]:
            if deadline and time.time() > deadline:
                break
            payload = json.dumps([str(it.get("text") or "")[:_TR_TEXT_MAX]], ensure_ascii=False)
            for m in models:
                base = str(m.get("base_url") or "").strip().rstrip("/")
                model = str(m.get("model") or "").strip()
                if not (base and model):
                    continue
                t0 = time.time()
                try:
                    extra = _llm_extra(m)                    # low-5: 白名单透传
                    r = requests.post(f"{base}/chat/completions",
                                      headers={"Authorization": f"Bearer {str(m.get('api_key') or 'x')}",
                                               "Content-Type": "application/json"},
                                      json={"model": model,
                                            "messages": [{"role": "system", "content": _SYS_TR},
                                                         {"role": "user", "content": payload}], **extra},
                                      timeout=60)
                    r.raise_for_status()
                    rj = r.json()
                    out = (rj.get("choices") or [{}])[0].get("message", {}).get("content") or ""
                    out = re.sub(r"<think>.*?</think>", "", out, flags=re.S)
                    arr = json.loads(re.sub(r"^```(json)?|```$", "", out.strip(),
                                            flags=re.M).strip())
                    if isinstance(arr, list) and arr and isinstance(arr[0], str) and arr[0].strip():
                        it["text_zh"] = arr[0].strip()
                        done += 1
                        _save_zh([it])
                        _tr_record(base, model, True, "ok", t0, rj.get("usage"))
                        break
                except Exception as ex:
                    _tr_record(base, model, False, _guard.classify(exc=ex), t0)
                    continue
    return done


def _anchor_hour(lt) -> int:
    """锚点小时: 午夜 tm_hour=0 → 24(用户 schedule 写 24 点档)。"""
    return lt.tm_hour if lt.tm_hour else 24


def run_account_push(dry_run: bool = False, force: bool = False,
                     window_h: float | None = None,
                     deadline: float | None = None) -> dict:
    """入口(refresh 轮末挂点 / cli feishu push)。dry_run=组卡打印不发不记状态。"""
    conf = _conf()
    ap = _push_conf(conf)
    rep = {"enabled": ap["enabled"], "dry_run": dry_run, "accounts": len(ap["accounts"]),
           "sent": 0, "errors": []}
    if not ap["accounts"]:
        rep["skipped"] = "无账号成分配置(account_push.accounts)"
        return rep
    if not _acquire_push_lock():                    # 0924 双推事故防复发: 闸口+长翻译非原子
        rep["skipped"] = "另一推送实例在跑(单实例锁), 本轮跳过"
        return rep
    st = _load_state(_PUSH_STATE)                   # dry_run 也 load: 窗口段读 last_push_at
    if not dry_run:
        if not ap["enabled"]:
            rep["skipped"] = "未启用(account_push.enabled)"
            return rep
        slot = ""
        if ap["schedule"] and not force:
            lt = time.localtime()                    # 0924 五锚点制: 9/13/17/21/24 点档,
            hour = _anchor_hour(lt)                  # 午夜 tm_hour=0 必须映射 24, 否则 24 档永不触发
            slot = f"{time.strftime('%Y-%m-%d')}-{hour}"
            if hour not in ap["schedule"]:           # 窗口=上次推送完成时刻起(自然覆盖 0~9 等)
                rep["skipped"] = f"非锚点时段(schedule={ap['schedule']})"
                return rep
            if st.get("last_slot") == slot:
                rep["skipped"] = f"本档已推({slot})"
                return rep
        last = float(st.get("last_ts") or 0)
        due = force or (time.time() - last) >= ap["interval_h"] * 3600
        if not due:
            rep["skipped"] = f"距上次推送不足 {ap['interval_h']}h"
            return rep
    import datetime as _dt
    if window_h is not None:
        win_h = float(window_h)
    elif ap["schedule"] and (st.get("last_push_at") or ""):
        win_h = None                                  # 窗口=上次推送完成时刻(锚点档距自然成立)
    else:
        win_h = float(ap["window_h"])
    since = ((st.get("last_push_at") or "").replace("T", " ") if win_h is None else
             (_dt.datetime.now() - _dt.timedelta(hours=win_h)).strftime("%Y-%m-%d %H:%M:%S"))
    if not since:
        win_h = float(ap["window_h"])
        since = (_dt.datetime.now() - _dt.timedelta(hours=win_h)
                 ).strftime("%Y-%m-%d %H:%M:%S")
    conn = _store._connect()
    try:
        rows = conn.execute(
            "SELECT source_id, time, text, text_zh, url, author_handle, sectors, markets, "
            "item_type, author_role, tickers, event_type, dup_count, positioning FROM items "
            "WHERE fetched_at>=? AND source_id LIKE '%twitter%' "
            "ORDER BY time DESC LIMIT 400", (since,)).fetchall()
    finally:
        conn.close()
    seen, items = set(), []
    for r in rows:
        u = str(r[4] or "")
        if u and u in seen:                          # flash/views 双源同帖去重
            continue
        if u:
            seen.add(u)
        raw_txt = re.sub(r"^@\w+:\s*", "", str(r[2] or ""))   # 库内文本带"@作者:"前缀
        items.append({"text": raw_txt, "text_zh": r[3], "url": u, "time": r[1],
                      "author_handle": r[5], "sectors": r[6], "markets": r[7],
                      "item_type": r[8], "author_role": r[9],
                      "tickers": r[10], "event_type": r[11],
                      "dup_count": r[12], "positioning": r[13],
                      "views": None, "likes": None})
    rep["items"] = len(items)
    if not items:
        rep["skipped"] = (f"窗口 {since} 以来无 X 新帖, 静默" if win_h is None
                          else f"窗口 {win_h}h 内无 X 新帖, 静默")
        if not dry_run:
            st = _load_state(_PUSH_STATE)
            st["last_ts"] = time.time()
            _save_state(_PUSH_STATE, st)
        return rep
    a_topics = _author_topics()
    for it in items:
        it["topics"] = _item_topics(it["sectors"], it["markets"],
                                     it["author_handle"], a_topics, it["text"])
    cand = [it for it in items if it["topics"]]
    rep["classified"] = len(cand)
    _enrich_stats(cand, max_handles=40)              # 热度: FxTwitter 现拉浏览量
    if win_h is None:                                   # schedule 模式: 窗口起点=上次推送时刻
        bj = time.strftime("%m-%d %H:%M", time.strptime(since, "%Y-%m-%d %H:%M:%S")) \
            + "~" + time.strftime("%H:%M")
    else:
        bj = time.strftime("%m-%d %H:%M", time.localtime(time.time() - win_h * 3600)) \
            + "~" + time.strftime("%H:%M")
    send_conf = dict(conf)
    send_conf["chat_id"] = ap["chat_id"]
    preview = []
    ok_any = dry_run
    rep["translated"] = 0
    rep["docs"] = 0
    st = _load_state(_PUSH_STATE)
    docs_dirty = False
    for acc in ap["accounts"]:
        mix = {str(k): float(v) for k, v in (acc.get("mix") or {}).items()
               if str(k) in TOPICS and float(v) > 0}
        if not mix:
            rep["errors"].append(f"{acc.get('name') or '?'}: mix 无效")
            continue
        if _doc_enabled(ap):
            ordered = _doc_order_all(cand, mix)
            rows_items = [it for _, its in ordered for it in its]
            if not rows_items:
                rep["errors"].append(f"{acc.get('name') or '?'}: 窗口内无命中素材")
                continue
            title = _doc_sheet_title()
            if not dry_run:                          # M2: dry-run 不烧 LLM 不写库(升级脚本自检高频触发)
                rep["translated"] += _translate_missing(conf, rows_items, cap=200,
                                                        deadline=deadline)
            rows = _doc_rows(acc, mix, ordered, bj, len(cand))
            if dry_run:
                preview.append(f"[doc] {acc.get('name')} {title} 子表 {len(rows)} 行"
                               f"(首行 {rows[0]})")
                continue
            token, url_or_err = _ensure_doc(conf, acc, ap, st)
            if not token:
                rep["errors"].append(f"{acc.get('name') or '?'} doc回退消息: {url_or_err}")
            else:
                docs_dirty = True
                sid, aerr = _doc_add_sheet(conf, token, title)
                werr = _doc_write_rows(conf, token, sid, rows) if sid else aerr
                if sid and not werr:
                    werrs = _doc_set_col_widths(conf, token, sid)  # 0924 用户列宽布局
                    if werrs:
                        rep["errors"].append(f"{acc.get('name') or '?'} doc列宽未全成: "
                                             f"{'; '.join(werrs)}")
                    rep["docs"] += 1
                    ok_any = True
                    oid = str(acc.get("owner_open_id") or "").strip()
                    owner = str(acc.get("owner") or "").strip() or "账号所有人"
                    head = (f'<at user_id="{oid}"></at>' if oid else f"@{owner}")
                    send_text(send_conf, f"{head} 账号「{acc.get('name')}」{title} 选题已更新"
                              f"（命中{len(cand)}条·{len(rows_items)}行）→ {url_or_err}")
                    time.sleep(0.5)
                    continue
                rep["errors"].append(f"{acc.get('name') or '?'} doc回退消息: {werr or aerr}")
        # 消息卡片路径(doc 关闭或 doc 失败回退)
        per = _pick_for_account(cand, acc, ap["top_total"])
        if not per:
            rep["errors"].append(f"{acc.get('name') or '?'}: 窗口内无命中素材")
            continue
        picked = [it for its in per.values() for it in its]
        if not dry_run:                              # M2: dry-run 不烧 LLM
            rep["translated"] += _translate_missing(conf, picked,
                                                    deadline=deadline)  # 兜底翻译被选中条目
        hits = {t: sum(1 for it in cand if t in (it.get("topics") or ()))
                for t in per}
        chunks = _compose_push(acc, per, mix, bj, len(cand), hits)
        if dry_run:
            preview.extend(chunks)
            continue
        oid = str(acc.get("owner_open_id") or "").strip()
        for ci, text in enumerate(chunks):
            if acc.get("dm"):
                if not oid:
                    if ci == 0:
                        rep["errors"].append(
                            f"{acc.get('name') or '?'}: dm=true 但缺 owner_open_id, 回退群发")
                    ok, err = send_text(send_conf, text)
                else:
                    ok, err = send_text(send_conf, text, {"type": "open_id", "id": oid})
            else:
                ok, err = send_text(send_conf, text)
            if ok:
                ok_any = True
                rep["sent"] += 1
                time.sleep(0.5)
            else:
                rep["errors"].append(f"{acc.get('name') or '?'} 发送失败: {err}")
    if dry_run:
        rep["preview"] = preview
    else:
        if docs_dirty:
            _save_state(_PUSH_STATE, st)
        if ok_any:
            st["last_ts"] = time.time()
            st["last_push_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            if slot:
                st["last_slot"] = slot
            _save_state(_PUSH_STATE, st)
    return rep
