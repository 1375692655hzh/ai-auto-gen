"""浏览层按需翻译(2026-09-09 用户拍板): 视口内缺译文的卡片由前端批量请求本端点。

数据站写侧翻译受额度/字数限制(批量10/截断1500), 浏览层改为"看才翻、翻过即存":
- 免费优先: 复用 settings.json translate 段(本机=omniroute 本地 muse 免费)
- 哈希缓存落盘 data/workbench/translate_ondemand.json: 同一文本跨会话/跨页/跨用户零成本
- 超长分段: >1500 字符按句切, 逐段串行翻后拼接(数据站截断的浏览层答案; 上限 8 段≈1.2万字符)
- 已中文(_is_zh)直接回显原文, 零外呼; 前端 localStorage 再做一层, 命中即零请求
"""

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path

from . import x_surge

CACHE_FILE = x_surge.DATA_DIR / "translate_ondemand.json"   # {md5: {zh, ts}}

SEG_CHARS = 1500        # 单段上限(与 _call_translate 的 max_tokens=600 译文匹配)
MAX_CHARS = 12000       # 单条总上限, 超出截断(宁短勿无)
SEG_MAX = 8             # 分段数上限
BATCH_MAX = 20          # 单批条数上限
MIN_CHARS = 8           # 低于此长度不翻(徽章/标签类)
SLEEP = 0.2             # 条间间隔, 防 API 限流

_SENT_RE = re.compile(r"(?<=[.!?。！？\n])\s+")


def _load() -> dict:
    if not CACHE_FILE.is_file():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(cache: dict) -> None:
    x_surge.DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(x_surge.DATA_DIR), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, CACHE_FILE)


def _h(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:16]


def _segments(text: str) -> list:
    text = text.strip()[:MAX_CHARS]
    if len(text) <= SEG_CHARS:
        return [text]
    parts, buf = [], ""
    for seg in _SENT_RE.split(text):
        while len(seg) > SEG_CHARS:            # 无空格长串(URL/粘贴残留)硬切
            parts.append(seg[:SEG_CHARS])
            seg = seg[SEG_CHARS:]
        if len(parts) >= SEG_MAX:
            break
        if len(buf) + len(seg) + 1 > SEG_CHARS and buf:
            parts.append(buf)
            buf = seg
        else:
            buf = (buf + " " + seg).strip() if buf else seg
    if buf and len(parts) < SEG_MAX:
        parts.append(buf)
    return parts[:SEG_MAX] or [text[:SEG_CHARS]]


def _translate_one(base: str, key: str, model: str, text: str) -> str | None:
    segs = _segments(text)
    out = []
    for n, seg in enumerate(segs):
        if n:
            time.sleep(SLEEP)
        # max_tokens=1600: 1500 字符英文段的完整译文(~1000 token), 防 600 截断
        zh = x_surge._call_translate(base, key, model, seg, max_tokens=1600)
        if not zh:
            return None            # 任一段失败整条放弃, 下轮/下次再试
        out.append(zh)
    return "\n\n".join(out)


def translate_batch(items: list) -> dict:
    """items: [{"i": 前端序号, "text": 原文}] →
    {"results": [{"i","hash","zh"}], "failed": n, "native": n, "cached": n, "unconfigured": bool}"""
    from . import config as wb_config
    cfg = wb_config.load().get("translate") or {}
    base, key, model = cfg.get("base_url"), cfg.get("api_key"), cfg.get("model")
    cache = _load()
    now_s = time.strftime("%Y-%m-%d %H:%M:%S")
    results, todo = [], []
    native = cached = failed = 0
    for it in items[:BATCH_MAX]:
        if not isinstance(it, dict):
            continue
        text = (it.get("text") or "").strip()
        if len(text) < MIN_CHARS:
            continue
        i = it.get("i")
        if x_surge._is_zh(text):
            results.append({"i": i, "hash": _h(text), "zh": text})
            native += 1
            continue
        h = _h(text)
        if h in cache:
            results.append({"i": i, "hash": h, "zh": cache[h]["zh"]})
            cached += 1
            continue
        todo.append((i, h, text))
    unconfigured = not (base and key and model)
    if not unconfigured:
        for n, (i, h, text) in enumerate(todo):
            if n:
                time.sleep(SLEEP)
            zh = _translate_one(base, key, model, text)
            if zh:
                cache[h] = {"zh": zh, "ts": now_s}
                results.append({"i": i, "hash": h, "zh": zh})
            else:
                failed += 1
    else:
        failed = len(todo)
    if todo and not unconfigured:
        _save(cache)
    return {"results": results, "failed": failed, "native": native,
            "cached": cached, "unconfigured": unconfigured}
