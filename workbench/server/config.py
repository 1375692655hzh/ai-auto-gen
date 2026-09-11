"""工作台配置读写(data/workbench/settings.json 是唯一写口)。

shape 本期定型, 上云零改前端:
  source: {mode: local|lan|cloud, base_url, api_key, timeout_s}
  ui:     {theme, page_size, remember_filters}
  cloud:  {endpoint, account, sync_token, sync_enabled, last_synced_at}  # 预留, 本期不消费
追踪账号清单: data/workbench/tracked_accounts.json
关注来源清单: data/workbench/followed_sources.json(资讯页「关注」筛选 + 来源详情 ⭐)
data/ 目录已被 gitignore, 配置永不入库。
"""

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]          # workbench/server/config.py → 仓库根
DATA_DIR = REPO / "data" / "workbench"
SETTINGS_FILE = DATA_DIR / "settings.json"
ACCOUNTS_FILE = DATA_DIR / "tracked_accounts.json"

DEFAULTS = {
    "tts": {
        "default": {"provider_id": "edge", "voice": "zh-CN-XiaoxiaoNeural"},
        "providers": [
            {"id": "edge", "name": "Edge TTS（免费）", "engine": "edge", "enabled": True,
             "api_key": "", "base_url": "",
             "voices": [{"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓 · 女声"},
                        {"id": "zh-CN-YunxiNeural", "name": "云希 · 男声"},
                        {"id": "zh-CN-YunyangNeural", "name": "云扬 · 男声·新闻"}]},
            {"id": "dashscope", "name": "DashScope（阿里云）", "engine": "dashscope", "enabled": False,
             "api_key": "", "base_url": "",
             "voices": [{"id": "longanlufeng", "name": "陆锋 · 男声"},
                        {"id": "longanlingxin", "name": "灵欣 · 女声"}]},
        ],
    },
    "source": {
        "mode": "local",                            # local=本机 | lan=局域网数据站 | cloud=未来云端
        "base_url": "http://127.0.0.1:8787",
        "api_key": "",                              # 仅存服务端, 永不明文回显给浏览器
        "timeout_s": 15,
    },
    "ui": {"theme": "light", "page_size": 100, "remember_filters": True},   # 出厂默认亮色
    "translate": {                                  # 浏览层/轮末推文翻译(OpenAI兼容链, 免费优先)
        "base_url": "",                             # 单服务三项(用户显式配置, 链头优先)
        "api_key": "",                              # 仅存服务端, 打码回显
        "model": "",                                # 如 deepseek-v4-flash
        "models": [                                  # 模型链兜底: 依次尝试, 前一失败自动落下一
            {"base_url": "http://127.0.0.1:20128/v1", "api_key": "omniroute-local",
             "model": "oc/muse-spark-1.2-contributor-free"},   # 主力免费(docs/翻译模型实测与推荐.md)
            {"base_url": "http://127.0.0.1:20128/v1", "api_key": "omniroute-local",
             "model": "oc/mimo-v2.5-free"},                    # 免费替补: muse 用完/挂自动落这
        ],
    },
    "youtube": {                                    # YouTube 热点追踪(Data API v3, 视频页)
        "api_key": "",                              # 仅存服务端, 打码回显
    },
    "gemini": {                                     # 视频工坊看片分析(Gemini API, 仅存服务端)
        "api_key": "",
        "model": "gemini-3.6-flash",
    },
    "analysis_paths": {                             # 视频工坊·本地文件分析扫描根(4槽位, 设置页可改;
        "paths": ["", "", "", ""],                  #  出厂全空, 由用户自己选目录)
    },
    "compose": {                                    # 内容生成·成稿专用 LLM(2026-09-07 用户拍板:
        "base_url": "",                             # 独立于翻译链, 用户自填, 不动翻译额度;
        "api_key": "",                              # 未配置则生成报 no_llm_config, 不回落翻译链)
        "model": "",
        "extra_body": {},                           # 厂商私有请求参数(选填), 如智谱推理模型
                                                    # {"thinking": {"type": "disabled"}} 防思考吃光 max_tokens
        "models": [],                               # 2026-09-10 多元化: 成稿模型链, 列表序=优先级,
                                                    # 依次尝试前一失败自动落下一; 顶层四字段为旧单
                                                    # 配置遗留, 读取一律走 compose_chain()
    },
    "finnhub": {                                    # 内容生成·聚合分析增强(投行评级/目标价, 仅美股)
        "api_key": "",                              # 免费档 finnhub.io 注册即得, 仅存服务端打码回显
    },
    "market": {"source_pref": "auto"},  # auto=yfinance主力东财兜底 | em_first=东财优先 | yf_only=仅用yfinance
    "workbench": {                              # 工作台自身(2026-09-11 对外绑定写面鉴权)
        "api_key": "",                          # 非 loopback 绑定时 wb-api 写方法(POST/PUT/DELETE)
    },                                          # 必须带 Bearer 此 key; 空=对外绑定拒绝一切写
    "gen_defaults": {"lang": "en", "tier": "free", "template": "catalyst-take"},
    "cloud": {                                      # 云端同步预留(本期后端不消费)
        "endpoint": "", "account": "", "sync_token": "",
        "sync_enabled": False, "last_synced_at": None,
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        out[k] = _merge(base.get(k, {}), v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


_LOAD_CACHE: dict = {"mtime_ns": None, "data": None}


def load() -> dict:
    """读 settings.json 并合并出厂默认。mtime 进程内缓存(2026-09-11 复审 P2):
    文件没变直接回深拷贝, 省掉每请求多次的磁盘读+合并; save/apply_patch 写盘后
    mtime 变化自动失效。返回值永远是新建对象, 调用方改脏不影响缓存。"""
    try:
        mt = _settings_file().stat().st_mtime_ns
    except OSError:
        mt = -1
    if _LOAD_CACHE["mtime_ns"] == mt and _LOAD_CACHE["data"] is not None:
        return json.loads(json.dumps(_LOAD_CACHE["data"]))
    try:
        saved = json.loads(_settings_file().read_text(encoding="utf-8"))
        merged = _merge(DEFAULTS, saved)
        if isinstance(saved.get("tts"), dict) and "default" in saved["tts"]:
            merged["tts"]["default"] = saved["tts"]["default"]
        # 出厂免费兜底位强制在链: 老机器 settings 冻结了旧 models 列表(_merge 对列表
        # 整段替换), muse 用完自动落 mimo 的替补位必须补回; 用户自定义链位原位保留。
        tr = merged.get("translate") or {}
        if isinstance(tr.get("models"), list):
            have = {str(m.get("model") or "") for m in tr["models"] if isinstance(m, dict)}
            for slot in DEFAULTS["translate"]["models"]:
                if slot["model"] not in have:
                    tr["models"].append(dict(slot))
        # 成稿模型链实体化迁移(2026-09-10): 存档 compose 无 models 键(升级前)而旧单
        # 配置有值 → 合成链头一条进 merged; 下次任意保存即固化, 老用户零感知。
        # 此后链以 models 为准: 用户在 UI 删光链位 ≠ 旧单配置回魂。
        sc = saved.get("compose") if isinstance(saved.get("compose"), dict) else {}
        mc = merged.get("compose") or {}
        if "models" not in sc and not mc.get("models"):
            base, key, model = (str(mc.get(k) or "").strip()
                                for k in ("base_url", "api_key", "model"))
            if all((base, key, model)):
                mc["models"] = [{"id": "default", "name": "默认成稿模型", "enabled": True,
                                 "base_url": base, "api_key": key, "model": model,
                                 "extra_body": mc.get("extra_body")
                                 if isinstance(mc.get("extra_body"), dict) else {}}]
        _LOAD_CACHE.update({"mtime_ns": mt, "data": merged})
        return json.loads(json.dumps(merged))
    except Exception:
        d = json.loads(json.dumps(DEFAULTS))        # 深拷贝出厂默认
        _LOAD_CACHE.update({"mtime_ns": mt, "data": d})
        return json.loads(json.dumps(d))


def save(cfg: dict) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    merged = _merge(load(), cfg)
    if isinstance(cfg.get("tts"), dict) and "default" in cfg["tts"]:
        merged["tts"]["default"] = cfg["tts"]["default"]
    fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")   # 原子写, 防半写损坏
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _settings_file())
    # 主动失效 mtime 缓存: 不赌文件系统时间戳粒度(同戳替换会读到旧对象), 写完直接换血
    _LOAD_CACHE.update({"mtime_ns": None, "data": None})
    return merged


def _settings_file() -> Path:
    # 保留旧调用方 patch SETTINGS_FILE 的兼容性；DATA_DIR 改写时随之隔离。
    return DATA_DIR / "settings.json" if DATA_DIR != REPO / "data" / "workbench" else SETTINGS_FILE


def compose_chain(cfg: dict | None = None) -> list:
    """成稿模型链: 按优先级(列表序)返回启用的模型
    [{id, name, base_url, api_key, model, extra_body}]。

    升级前的旧单配置由 load() 实体化进 models(下次保存即固化); 这里只在拿到
    未经 load() 的裸配置(无 models 键)时才兜底读顶层旧字段。"""
    c = (cfg or load()).get("compose") or {}
    out = []
    for m in c.get("models") or []:
        if not isinstance(m, dict) or not m.get("enabled", True):
            continue
        base, key, model = (str(m.get(k) or "").strip() for k in ("base_url", "api_key", "model"))
        if not all((base, key, model)):
            continue                                    # 三项不全的链位视为未配好, 跳过
        eb = m.get("extra_body")
        out.append({"id": str(m.get("id") or ""), "name": str(m.get("name") or m.get("id") or ""),
                    "base_url": base, "api_key": key, "model": model,
                    "extra_body": dict(eb) if isinstance(eb, dict) else {}})
    if not out and "models" not in c:
        base, key, model = (str(c.get(k) or "").strip() for k in ("base_url", "api_key", "model"))
        if all((base, key, model)):
            eb = c.get("extra_body")
            out.append({"id": "default", "name": "默认成稿模型", "base_url": base,
                        "api_key": key, "model": model,
                        "extra_body": dict(eb) if isinstance(eb, dict) else {}})
    return out


def public_view(cfg: dict) -> dict:
    """回显给浏览器的视图: api_key/sync_token 打码, 不回明文。"""
    v = json.loads(json.dumps(cfg))
    for provider in (v.get("tts") or {}).get("providers", []):
        key = provider.get("api_key") or ""
        provider.update(api_key="", has_key=bool(key), key_tail=key[-4:] if key else "")
    key = v["source"].get("api_key") or ""
    v["source"]["api_key"] = ""
    v["source"]["has_key"] = bool(key)
    v["source"]["key_tail"] = key[-4:] if key else ""
    tkey = (v.get("translate") or {}).get("api_key") or ""
    v["translate"]["api_key"] = ""
    v["translate"]["has_key"] = bool(tkey)
    v["translate"]["key_tail"] = tkey[-4:] if tkey else ""
    for m in (v.get("translate") or {}).get("models") or []:   # 链位 key 同打码
        if isinstance(m, dict):
            mk = m.get("api_key") or ""
            m["api_key"] = ""
            m["has_key"] = bool(mk)
            m["key_tail"] = mk[-4:] if mk else ""
    ykey = (v.get("youtube") or {}).get("api_key") or ""
    v["youtube"]["api_key"] = ""
    v["youtube"]["has_key"] = bool(ykey)
    v["youtube"]["key_tail"] = ykey[-4:] if ykey else ""
    gkey = (v.get("gemini") or {}).get("api_key") or ""
    v["gemini"]["api_key"] = ""
    v["gemini"]["has_key"] = bool(gkey)
    v["gemini"]["key_tail"] = gkey[-4:] if gkey else ""
    ckey = (v.get("compose") or {}).get("api_key") or ""
    v["compose"]["api_key"] = ""
    v["compose"]["has_key"] = bool(ckey)
    v["compose"]["key_tail"] = ckey[-4:] if ckey else ""
    for m in (v.get("compose") or {}).get("models") or []:   # 链位 key 同打码
        if isinstance(m, dict):
            mk = m.get("api_key") or ""
            m["api_key"] = ""
            m["has_key"] = bool(mk)
            m["key_tail"] = mk[-4:] if mk else ""
    fkey = (v.get("finnhub") or {}).get("api_key") or ""
    v["finnhub"]["api_key"] = ""
    v["finnhub"]["has_key"] = bool(fkey)
    v["finnhub"]["key_tail"] = fkey[-4:] if fkey else ""
    wkey = (v.get("workbench") or {}).get("api_key") or ""
    v["workbench"]["api_key"] = ""
    v["workbench"]["has_key"] = bool(wkey)
    v["workbench"]["key_tail"] = wkey[-4:] if wkey else ""
    v["cloud"]["sync_token"] = ""
    v["cloud"]["has_token"] = bool(cfg["cloud"].get("sync_token"))
    return v


def _tts_id_ok(value) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[\w-]+", value))


def _tts_voices(voices) -> list:
    out, seen = [], set()
    for v in voices or []:
        if not isinstance(v, dict):
            continue
        vid = v.get("id")
        if not _tts_id_ok(vid) or vid in seen:
            continue
        seen.add(vid)
        name = str(v.get("name") or vid).strip()[:40]
        out.append({"id": vid, "name": name or vid})
    return out


def _tts_provider(prev, incoming: dict) -> dict | None:
    """白名单合并一条供应商; id 非法则丢弃。api_key 缺省/空串保持原值。"""
    prev = prev if isinstance(prev, dict) else {}
    pid = incoming.get("id")
    if not _tts_id_ok(pid):
        return None
    engine = incoming.get("engine", prev.get("engine") or "edge")
    if engine not in ("edge", "dashscope", "volc"):
        engine = prev.get("engine") if prev.get("engine") in ("edge", "dashscope", "volc") else "edge"
    name = incoming["name"] if "name" in incoming else prev.get("name") or pid
    enabled = incoming["enabled"] if "enabled" in incoming else prev.get("enabled", True)
    base_url = incoming["base_url"] if "base_url" in incoming else prev.get("base_url", "")
    api_key = prev.get("api_key") or ""
    if incoming.get("api_key"):
        api_key = str(incoming["api_key"])
    voices = (_tts_voices(incoming["voices"]) if "voices" in incoming
              else _tts_voices(prev.get("voices")))
    return {"id": pid, "name": str(name or pid).strip()[:40] or pid, "engine": engine,
            "enabled": bool(enabled), "api_key": api_key, "base_url": str(base_url or ""),
            "voices": voices}


def _tts_fix_default(tts: dict) -> dict:
    """默认供应商被删或不存在时回落到仍在清单里的第一条(优先已启用)。"""
    default = tts.get("default") if isinstance(tts.get("default"), dict) else {}
    providers = tts.get("providers") or []
    ids = {p["id"]: p for p in providers if isinstance(p, dict) and p.get("id")}
    pid = default.get("provider_id")
    if pid not in ids:
        pick = next((p for p in providers if p.get("enabled")), providers[0] if providers else None)
        if not pick:
            tts["default"] = {"provider_id": "", "voice": ""}
            return tts
        pid = pick["id"]
        voices = [v.get("id") for v in pick.get("voices") or [] if v.get("id")]
        tts["default"] = {"provider_id": pid, "voice": voices[0] if voices else ""}
        return tts
    tts["default"] = {"provider_id": pid, "voice": str(default.get("voice") or "")}
    return tts


def _compose_model(prev, incoming: dict) -> dict | None:
    """白名单合并一条成稿模型; id 非法则丢弃。api_key 缺省/空串保持原值;
    extra_body 必须是 dict(前端已校验 JSON)。"""
    prev = prev if isinstance(prev, dict) else {}
    mid = incoming.get("id")
    if not _tts_id_ok(mid):
        return None
    name = incoming["name"] if "name" in incoming else prev.get("name") or mid
    enabled = incoming["enabled"] if "enabled" in incoming else prev.get("enabled", True)
    base_url = incoming["base_url"] if "base_url" in incoming else prev.get("base_url", "")
    model = incoming["model"] if "model" in incoming else prev.get("model", "")
    eb = incoming.get("extra_body", prev.get("extra_body"))
    api_key = prev.get("api_key") or ""
    if incoming.get("api_key"):
        api_key = str(incoming["api_key"])
    return {"id": mid, "name": str(name or mid).strip()[:40] or mid,
            "enabled": bool(enabled), "base_url": str(base_url or ""),
            "api_key": api_key, "model": str(model or ""),
            "extra_body": dict(eb) if isinstance(eb, dict) else {}}


def apply_patch(patch: dict) -> dict:
    """设置页保存: api_key 留空表示保持不变(前端不持有明文)。"""
    patch = dict(patch or {})
    if isinstance(patch.get("tts"), dict):
        incoming = patch["tts"]
        tts = json.loads(json.dumps(load()["tts"]))
        providers = {p["id"]: p for p in tts["providers"]
                     if isinstance(p, dict) and p.get("id")}
        for rid in incoming.get("remove_ids") or []:
            if isinstance(rid, str):
                providers.pop(rid, None)
        for p in incoming.get("providers") or []:
            if not isinstance(p, dict):
                continue
            p = dict(p)
            p.pop("has_key", None)
            p.pop("key_tail", None)
            if p.get("api_key") == "":
                p.pop("api_key")
            row = _tts_provider(providers.get(p.get("id")), p)
            if row:
                providers[row["id"]] = row
        tts["providers"] = list(providers.values())
        if "default" in incoming and isinstance(incoming["default"], dict):
            tts["default"] = incoming["default"]
        patch["tts"] = _tts_fix_default(tts)
    if isinstance(patch.get("compose"), dict):
        incoming = patch["compose"]
        compose = json.loads(json.dumps(load().get("compose") or {}))
        if "models" in incoming:                      # 链式保存: 按 id 合并, 列表序=优先级
            models = {m["id"]: m for m in compose.get("models") or []
                      if isinstance(m, dict) and m.get("id")}
            for rid in incoming.get("remove_ids") or []:
                if isinstance(rid, str):
                    models.pop(rid, None)
            ordered = []
            for m in incoming.get("models") or []:
                if not isinstance(m, dict):
                    continue
                m = dict(m)
                m.pop("has_key", None)
                m.pop("key_tail", None)
                if m.get("api_key") == "":
                    m.pop("api_key")
                row = _compose_model(models.pop(m.get("id"), None), m)
                if row:
                    ordered.append(row)
            compose["models"] = ordered
            patch["compose"] = compose
        else:                                          # 旧单配置字段级保存(兼容老调用)
            s = dict(incoming)
            if "api_key" in s and not s["api_key"]:
                s.pop("api_key")
            patch["compose"] = s if s else None
            if not s:
                patch.pop("compose", None)
    for sec in ("source", "translate", "youtube", "gemini", "finnhub", "workbench"):
        s = dict(patch.get(sec) or {})
        if "api_key" in s and not s["api_key"]:
            s.pop("api_key")
        if s:
            patch[sec] = s
        else:
            patch.pop(sec, None)
    merged = _merge(load(), patch)
    if "tts" in patch:
        merged["tts"] = patch["tts"]
    result = save(merged)
    return result


# ── 通用 JSON 清单存取(追踪账号/草稿/自动化任务, 全部原子写) ─────────────────

SEED_DIR = Path(__file__).resolve().parent / "seed"   # 仓内首跑播种源(scripts/sync_seeds.py 生成)


# ── CLI 子进程启动前缀(自适应 Python 版本) ──────────────────────────────────

_py_cmd: list | None = None


def py_cmd() -> list:
    """spawn cli.py 的命令前缀: 优先 py -3.11(项目契约), 探测失败退当前解释器。

    分发用户只装 3.12 时, 硬编码 py -3.11 会报 'No suitable Python runtime found',
    报错文本被端点当 JSON 解析 → invalid_cli_response(2026-09-10 同事事故)。
    服务端本体解释器必然能跑本仓代码(依赖已装), 是零假设的安全兜底。结果缓存。"""
    global _py_cmd
    if _py_cmd is None:
        import subprocess
        if os.name == "nt" and shutil.which("py"):
            try:
                r = subprocess.run(["py", "-3.11", "-c", "import sys"],
                                   capture_output=True, timeout=15)
                _py_cmd = ["py", "-3.11"] if r.returncode == 0 else [sys.executable]
            except Exception:
                _py_cmd = [sys.executable]
        else:
            _py_cmd = [sys.executable]
    return list(_py_cmd)


def seed_if_missing(name: str) -> bool:
    """首跑播种: data/workbench/<name> 不存在而仓内 seed/ 有同名件 → 复制过去。

    只在用户自有文件缺失时触发一次——播种后启停/开关全写用户自己的文件,
    仓库 seed 后续更新永不回写覆盖(分发用户与开发者清单看齐、状态各自独立的契约)。
    """
    dst, src = DATA_DIR / name, SEED_DIR / name
    if dst.exists() or not src.is_file():
        return False
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        return True
    except OSError:
        return False


def _seed_stamp_f(name: str) -> Path:
    return DATA_DIR / f".seed-applied-{name}"


def seed_tombstone(name: str, row: dict | None) -> None:
    """用户删除种子播种的行时记墓碑: 后续种子升级合并不得复活该行。"""
    if not isinstance(row, dict):
        return
    keys = {str(row.get(k) or "") for k in ("channel_id", "value", "handle")} - {""}
    if not keys:
        return
    rem_f = DATA_DIR / f".seed-removed-{name}"
    try:
        gone = set(json.loads(rem_f.read_text(encoding="utf-8"))) if rem_f.exists() else set()
        gone |= keys
        rem_f.write_text(json.dumps(sorted(gone), ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def seed_merge_if_updated(name: str, key_fields: tuple = ("channel_id", "value")) -> dict:
    """种子升级合并(2026-09-11, 解决「存量用户吃不到开发者清单更新」):
    seed 内容哈希变化时, 把新增行并入已存在的本地库——
    - 只新增本地没有的行(按 key_fields 判重), 绝不改/删本地已有行(启停状态安全);
    - 墓碑(.seed-removed-<name>)里的行不复活(用户主动删过的);
    - 哈希版本戳(.seed-applied-<name>)同版本只跑一次。
    首跑播种仍归 seed_if_missing, 两者兼容(合并对全新用户是无操作)。"""
    src, dst = SEED_DIR / name, DATA_DIR / name
    if not src.is_file() or not dst.exists():
        return {"skipped": "missing"}
    try:
        seed_bytes = src.read_bytes()
        stamp_f = _seed_stamp_f(name)
        digest = hashlib.sha1(seed_bytes).hexdigest()
        if stamp_f.exists() and stamp_f.read_text(encoding="utf-8").strip() == digest:
            return {"skipped": "same_version"}
        seed_rows = json.loads(seed_bytes.decode("utf-8"))
        local_rows = json.loads(dst.read_text(encoding="utf-8"))
        if not isinstance(seed_rows, list) or not isinstance(local_rows, list):
            return {"skipped": "not_list"}
        removed = set()
        rem_f = DATA_DIR / f".seed-removed-{name}"
        if rem_f.exists():
            try:
                removed = set(json.loads(rem_f.read_text(encoding="utf-8")))
            except Exception:
                removed = set()

        def row_keys(r: dict) -> set:
            return {str(r.get(k) or "") for k in key_fields} - {""}

        local_keys: set = set()
        for r in local_rows:
            local_keys |= row_keys(r)
        added = 0
        for row in seed_rows:
            ks = row_keys(row)
            if not ks or (ks & local_keys) or (ks & removed):
                continue
            local_rows.append(row)
            local_keys |= ks
            added += 1
        if added:
            save_rows(name, local_rows)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        stamp_f.write_text(digest, encoding="utf-8")
        return {"added": added, "seed_n": len(seed_rows), "local_n": len(local_rows)}
    except (OSError, ValueError) as e:
        return {"error": type(e).__name__, "hint": str(e)[:120]}


def load_rows(name: str) -> list:
    try:
        return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))
    except Exception:
        return []


class file_lock:
    """跨进程读改写互斥(短临界区, 2026-09-11 复审 P0): 先进程内线程锁串行化, 再
    msvcrt 锁 data/workbench/<name>.lock 首字节做跨进程互斥。
    注意: msvcrt 区域锁在同进程两线程抢同一字节时**立即报 EDEADLK 而不是等待**,
    进程内线程锁必须先行(压测实证); 跨进程竞争则由 LK_LOCK 阻塞至系统 ~10s 上限。
    用法: with config.file_lock("video_jobs"): load→改→save。"""

    _LOCAL: dict = {}

    def __init__(self, name: str):
        if not re.fullmatch(r"[\w-]+", name or ""):
            raise ValueError("bad lock name")
        self._name = name
        self._fh = None
        self._lk = None

    def __enter__(self):
        import threading
        self._lk = self._LOCAL.setdefault(self._name, threading.Lock())
        self._lk.acquire()                           # dict.setdefault 在 GIL 下原子
        if os.name == "nt":
            import msvcrt
            try:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                self._fh = open(DATA_DIR / f"{self._name}.lock", "a+b")
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_LOCK, 1)
            except Exception:
                self._lk.release()
                self._lk = None
                raise
        return self

    def __exit__(self, *exc):
        fh, self._fh = self._fh, None
        if fh is not None:
            import msvcrt
            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            fh.close()
        lk, self._lk = self._lk, None
        if lk is not None:
            lk.release()
        return False


def save_rows(name: str, rows: list) -> list:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_DIR / name)
    return rows


def load_accounts() -> list:
    return load_rows("tracked_accounts.json")


def save_accounts(rows: list) -> list:
    return save_rows("tracked_accounts.json", rows)


def load_yt_channels() -> list:
    """视频页【追踪账号】子页的 YouTube 账号库(与 tracked_accounts.json 物理隔离,
    见 yt_track.py 模块头竞态说明)。首跑无自有文件时从仓内 seed 播种(清单看齐开发者,
    启停状态此后归本机)。"""
    seed_if_missing("yt_channels.json")
    return load_rows("yt_channels.json")


def save_yt_channels(rows: list) -> list:
    return save_rows("yt_channels.json", rows)


def load_yt_own_channels() -> list:
    """追踪页 YTB 自有频道库(用户自己的账号; 与视频页【账号管理】他人频道库独立,
    2026-09-11 用户拍板)。"""
    return load_rows("yt_own_channels.json")


def save_yt_own_channels(rows: list) -> list:
    return save_rows("yt_own_channels.json", rows)


def load_video_pool() -> list:
    rows = load_rows("video_pool.json")
    return rows if isinstance(rows, list) and all(isinstance(r, dict) for r in rows) else []


def save_video_pool(rows: list) -> list:
    return save_rows("video_pool.json", rows)


def load_video_scripts() -> list:
    rows = load_rows("video_scripts.json")
    return rows if isinstance(rows, list) and all(isinstance(r, dict) for r in rows) else []


def save_video_scripts(rows: list) -> list:
    return save_rows("video_scripts.json", rows)


def load_video_makes() -> list:
    rows = load_rows("video_makes.json")
    return rows if isinstance(rows, list) and all(isinstance(r, dict) for r in rows) else []


def save_video_makes(rows: list) -> list:
    return save_rows("video_makes.json", rows)


def load_video_assets() -> list:
    rows = load_rows("video_assets.json")
    return rows if isinstance(rows, list) and all(isinstance(r, dict) for r in rows) else []


def save_video_assets(rows: list) -> list:
    return save_rows("video_assets.json", rows)


def load_drafts() -> list:
    return load_rows("drafts.json")


def save_drafts(rows: list) -> list:
    return save_rows("drafts.json", rows)


def load_automation() -> list:
    return load_rows("automation.json")


def save_automation(rows: list) -> list:
    return save_rows("automation.json", rows)


def load_followed() -> list:
    return load_rows("followed_sources.json")


def save_followed(rows: list) -> list:
    return save_rows("followed_sources.json", rows)


# ── X 账号偏好(图文页·账号管理) ──────────────────────────────────────────────
# 注意: 这里是 {handle: {...}} 字典式, 与 followed_sources 的 [{id},...] 行式
# 刻意不同——本场景按 handle O(1) 开关, 勿"顺手统一"成行式。

def load_x_prefs() -> dict:
    try:
        d = json.loads((DATA_DIR / "x_account_prefs.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_x_prefs(prefs: dict) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_DIR / "x_account_prefs.json")
    return prefs
