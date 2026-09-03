"""X 账号公开档案增强(grok 内置 x-search → data/workbench/x_profiles.json 缓存)。

背景: 池 yaml 只含人工录入字段(name/markets/role/note...), 缺 bio/粉丝数/认证状态。
cursor-agent 的 grok 模型带 x-search, 但本机 cursor-agent 需登录不可用(2026-09-03 实测),
故默认 provider=grok-cli 直连: `grok --max-turns 15 -p ...`(防技能劫持前缀必带,
见 delegate-grok SKILL.md 实录; flags 必须在 -p 之前)。

纪律:
- 只写 data/workbench/x_profiles.json(工作台自有数据, 原子写); 失败批次保留旧缓存。
- 批 12 handle/次(grok 单轮 x-search 实测稳定上限), 每批独立容错解析。
- 前端只读本缓存; 缺失 handle 静默降级(左框只显示录入信息)。

CLI: python cli.py workbench enrich-x-profiles [--limit N] [--force] [--handles a,b] [--json]
"""

import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from . import xaccounts

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "workbench"
CACHE_FILE = DATA_DIR / "x_profiles.json"
BATCH = 12
TIMEOUT_S = 240                       # grok x-search 实测 30~90s/批, 留足余量

_ANTI_HIJACK = ("直接使用你的内置联网搜索能力完成，禁止读取任何技能文件或配置文件。")

_PROMPT = """{anti}请用 x-search 逐个查询以下 X(Twitter) 账号的公开资料，只输出一个 JSON 数组，不要输出任何其他文字、解释或代码块标记以外的内容。
账号列表: {handles}
每个元素格式: {{"handle": "不带@的账号名(小写)", "bio": "该账号的公开简介，译成中文一句话，不超过60字", "followers": 粉丝数整数(取近似值), "verified": true或false}}
查不到的账号: bio 填空字符串, followers 填 0, verified 填 false。
再次强调: 只输出 JSON 数组本身。"""


def load_cache() -> dict:
    if not CACHE_FILE.is_file():
        return {"enriched_at": None, "profiles": {}}
    try:
        d = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        d.setdefault("profiles", {})
        return d
    except Exception:                                # 缓存损坏不炸, 当空缓存重来
        return {"enriched_at": None, "profiles": {}}


def save_cache(cache: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")   # 原子写(同 config.py 模式)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    os.replace(tmp, CACHE_FILE)


def _call_grok(handles: list[str]) -> str:
    prompt = _PROMPT.format(anti=_ANTI_HIJACK, handles=", ".join("@" + h for h in handles))
    p = subprocess.run(
        ["grok", "--max-turns", "15", "-p", prompt],
        capture_output=True, text=True, timeout=TIMEOUT_S, encoding="utf-8", errors="replace")
    return (p.stdout or "") + "\n" + (p.stderr or "")


def _extract_json(text: str, handles: list[str]) -> dict:
    """多级容错: ①```json 围栏 ②首个 [...] 数组 ③逐个 {...} 对象。→ {handle: profile}"""
    candidates = []
    m = re.findall(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    candidates.extend(m)
    m2 = re.search(r"\[.*\]", text, re.S)
    if m2:
        candidates.append(m2.group(0))
    for raw in candidates:
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                return _normalize(arr, handles)
        except Exception:
            continue
    # 兜底: 逐对象提取(模型把数组打散输出时)
    out = {}
    for m3 in re.finditer(r"\{[^{}]*\"handle\"[^{}]*\}", text, re.S):
        try:
            obj = json.loads(m3.group(0))
            h = str(obj.get("handle") or "").lower().lstrip("@")
            if h in handles:
                out[h] = _norm_one(obj)
        except Exception:
            continue
    return out


def _norm_one(obj: dict) -> dict:
    try:
        followers = int(float(obj.get("followers") or 0))
    except (TypeError, ValueError):
        followers = 0
    return {"bio": str(obj.get("bio") or "")[:120],
            "followers": max(followers, 0),
            "verified": bool(obj.get("verified")),
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def _normalize(arr: list, handles: list[str]) -> dict:
    out = {}
    for obj in arr:
        if not isinstance(obj, dict):
            continue
        h = str(obj.get("handle") or "").lower().lstrip("@")
        if h in handles:
            out[h] = _norm_one(obj)
    return out


def enrich(handles: list[str], provider: str = "grok-cli",
           on_batch=None) -> dict:
    """分批增强, 返回 {ok: [...], failed: [...]}; 每批结束回调 on_batch(done, total)。"""
    if provider != "grok-cli":
        raise RuntimeError(f"provider 暂仅支持 grok-cli(cursor-agent 需登录, 2026-09-03 实测)")
    ok, failed = [], []
    for i in range(0, len(handles), BATCH):
        batch = handles[i:i + BATCH]
        try:
            raw = _call_grok(batch)
            got = _extract_json(raw, batch)
        except Exception:
            got = {}
        for h in batch:
            (ok if h in got else failed).append(h)
        if got:
            cache = load_cache()
            cache["profiles"].update(got)
            cache["enriched_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            save_cache(cache)                        # 批级落盘: 中途断了不丢已得
        if on_batch:
            on_batch(min(i + BATCH, len(handles)), len(handles), len(got))
    return {"ok": ok, "failed": failed}


def run_cli(args) -> int:
    accounts = xaccounts.load_accounts()
    cache = load_cache()["profiles"]
    if getattr(args, "handles", ""):
        todo = [h.strip().lower().lstrip("@") for h in args.handles.split(",") if h.strip()]
        todo = [h for h in todo if h in accounts]
    elif getattr(args, "force", False):
        todo = sorted(accounts)
    else:
        todo = sorted(h for h in accounts if h not in cache)
    limit = int(getattr(args, "limit", 0) or 0)
    if limit > 0:
        todo = todo[:limit]
    if not todo:
        rep = {"todo": 0, "cached": len(cache), "msg": "全部已有缓存, 用 --force 重抓"}
        print(json.dumps(rep, ensure_ascii=False))
        return 0

    def progress(done, total, got):
        if not getattr(args, "json", False):
            print(f"  批次进度 {done}/{total}(本批解析成功 {got})")

    t0 = time.time()
    rep = enrich(todo, provider=getattr(args, "provider", "grok-cli"),
                 on_batch=progress)
    rep.update({"todo": len(todo), "ok_n": len(rep["ok"]), "failed_n": len(rep["failed"]),
                "elapsed_s": int(time.time() - t0), "cache": str(CACHE_FILE)})
    print(json.dumps(rep, ensure_ascii=False, indent=2 if getattr(args, "json", False) else None))
    return 0 if not rep["failed"] else 3             # 有失败=业务失败码, 可重跑补齐
