"""视频分析·可核验拆解工作流(copylab 移植, 用户拍板"把参考项目做进来")。

与 Gemini 看片(G0) 完全不同的路线: 不看画面, 只看文案——
  yt-dlp 元数据/章节/字幕(确定性) → 逐字稿(真值文档) → 节奏纯计算
  → LLM 只读文本拆框架(每处引用带 [MM:SS] 原话) → 引用 grep 回逐字稿核验
  (EXACT/FUZZY/MISSING/TIME_OFF), 编造就地标红。
参考项目 copylab(移植来源)的三文件已并入: prompts/copylab_analyze.md(分析提示词)
+ 本模块内的 fetch/rhythm/verify 移植实现。

约束: 仅支持 YouTube(需要字幕); 外呼仅发生在 CLI 分析进程; 只读配置不写库外文件。
"""

import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

from . import config, vstudio

PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "copylab_analyze.md"
SUB_LANGS = "zh-Hans,zh-Hant,zh-CN,zh-TW,zh,zh-HK,en"


# ── 第一层: 确定性取数(移植 fetch.py, 走 vstudio 同款 yt-dlp 调用) ─────────────
def _video_id_of(url: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


def _ytdlp(args: list, cwd: str, timeout: int = 600) -> tuple[str, str, int]:
    cmd = ["py", "-3.12", "-m", "yt_dlp", "--no-warnings", "--js-runtimes", "node"] + args
    cookies = Path(__import__("os").environ.get("USERPROFILE", "")) / ".config" / "yt-dlp" / "cookies.txt"
    if cookies.is_file():
        cmd += ["--cookies", str(cookies)]
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return p.stdout or "", p.stderr or "", p.returncode


def fetch_meta(url: str, tmp: str) -> dict:
    out, err, _ = _ytdlp(["--skip-download", "--dump-single-json", url], tmp)
    if not out.strip() or out.strip() == "null":
        # 把 yt-dlp 真实报错透出去(bot-check 场景要知道怎么修)
        hint = err.strip().splitlines()[-1][:240] if err.strip() else "无输出"
        if "not a bot" in err or "cookies" in err:
            hint = ("YouTube 反爬拦截: 需登录 cookies —— 浏览器装 Get cookies.txt 扩展,"
                    "在 youtube.com 导出后存到 %USERPROFILE%\\.config\\yt-dlp\\cookies.txt "
                    "再重试(本机会自动读)。" + hint[:120])
        raise RuntimeError(hint)
    d = json.loads(out)
    desc = d.get("description") or ""
    chapters = [{"start": c.get("start_time"), "title": c.get("title")}
                for c in (d.get("chapters") or [])]
    if not chapters:                                   # 简介文本兜底解析作者自标章节
        for t, x in re.findall(r"\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?[\s\-—、.]*(.{2,60})", desc):
            p = [int(v) for v in t.split(":")]
            sec = p[0] * 60 + p[1] if len(p) == 2 else p[0] * 3600 + p[1] * 60 + p[2]
            chapters.append({"start": sec, "title": x.strip()})
    return {"video_id": d.get("id"), "title": d.get("title") or "",
            "channel": d.get("channel") or "", "duration": d.get("duration") or 0,
            "chapters": chapters, "upload_date": d.get("upload_date") or "",
            "view_count": d.get("view_count")}


def fetch_segments(url: str, tmp: str) -> tuple[list | None, str | None]:
    """优先作者上传字幕, 其次自动字幕 → [{start,end,text}]。"""
    for flag, source in (("--write-subs", "manual_sub"), ("--write-auto-subs", "auto_sub")):
        _ytdlp(["--skip-download", flag, "--sub-langs", SUB_LANGS,
                "--sub-format", "vtt", "-o", "sub.%(ext)s", url], tmp)
        vtts = sorted(Path(tmp).glob("sub*.vtt"))
        if vtts:
            segs = _parse_vtt(vtts[0])
            for v in vtts:
                v.unlink(missing_ok=True)
            if segs:
                return segs, source
    return None, None


def _parse_vtt(path: Path) -> list:
    """极简 VTT 解析 + 合并 YouTube 自动字幕滚动重复行(移植 fetch.py)。"""
    segs, last_text = [], None
    ts = re.compile(r"(\d+):(\d+):(\d+)\.(\d+)\s+-->\s+(\d+):(\d+):(\d+)\.(\d+)")
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    i = 0
    while i < len(lines):
        m = ts.search(lines[i])
        if not m:
            i += 1
            continue
        g = [int(x) for x in m.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        i += 1
        buf = []
        while i < len(lines) and lines[i].strip() and not ts.search(lines[i]):
            buf.append(re.sub(r"<[^>]+>", "", lines[i]).strip())
            i += 1
        text = " ".join(b for b in buf if b).strip()
        if text and text != last_text:
            segs.append({"start": round(start, 2), "end": round(end, 2), "text": text})
            last_text = text
    return segs


# ── 第二层: 节奏纯计算(移植 rhythm.py, 零模型推断) ─────────────────────────────
_PUNCT = re.compile(r"[\s，。！？；：、「」『』（）()《》【】…—\-,.!?;:\"'“”‘’·]")
import statistics  # noqa: E402


def _chars(text: str) -> int:
    return len(_PUNCT.sub("", text))


def _mmss(sec: float) -> str:
    return f"{int(sec)//60:02d}:{int(sec)%60:02d}"


def rhythm_compute(segments: list, duration: float) -> dict:
    if not segments:
        return {}
    total_chars = sum(_chars(s["text"]) for s in segments)
    spoken = sum(max(0.0, s["end"] - s["start"]) for s in segments)
    win = 60
    n_win = max(1, int(duration // win) + 1)
    per_win = [0] * n_win
    for s in segments:
        per_win[min(int(s["start"] // win), n_win - 1)] += _chars(s["text"])
    mean_rate = statistics.mean(per_win) if per_win else 0
    windows = [{"t": _mmss(i * win), "chars_per_min": c} for i, c in enumerate(per_win)]
    fast = [w["t"] for w in windows if mean_rate and w["chars_per_min"] > 1.2 * mean_rate]
    slow = [w["t"] for w in windows if mean_rate and 0 < w["chars_per_min"] < 0.8 * mean_rate]
    pauses = []
    for a, b in zip(segments, segments[1:]):
        gap = b["start"] - a["end"]
        if gap > 0.8:
            pauses.append({"t": _mmss(a["end"]), "gap_sec": round(gap, 1),
                           "before": a["text"][-30:], "after": b["text"][:30]})
    pauses.sort(key=lambda p: -p["gap_sec"])
    sents = [x for s in segments for x in re.split(r"[。！？!?]", s["text"]) if _chars(x) >= 2]
    sent_len = [_chars(x) for x in sents]
    fifth = duration / 5
    density = [{"part": f"{k*20}–{(k+1)*20}%", "range": f"{_mmss(k*fifth)}–{_mmss((k+1)*fifth)}",
                "chars": sum(_chars(s["text"]) for s in segments
                             if k * fifth <= s["start"] < (k + 1) * fifth),
                "chars_per_min": round(sum(_chars(s["text"]) for s in segments
                                           if k * fifth <= s["start"] < (k + 1) * fifth)
                                       / (fifth / 60), 1) if fifth else 0}
               for k in range(5)]
    open_chars = sum(_chars(s["text"]) for s in segments if s["start"] < 30)
    return {"method": "全部由字幕/转写时间戳直接计算，无模型推断",
            "total_chars": total_chars, "duration_sec": duration,
            "overall_chars_per_min": round(total_chars / (duration / 60), 1) if duration else 0,
            "spoken_ratio": round(spoken / duration, 2) if duration else 0,
            "opening_30s_chars_per_min": round(open_chars * 2, 1),
            "sentence_len_median": statistics.median(sent_len) if sent_len else 0,
            "sentence_len_max": max(sent_len) if sent_len else 0,
            "short_sentence_ratio": round(sum(1 for x in sent_len if x <= 8) / len(sent_len), 2) if sent_len else 0,
            "fast_windows": fast, "slow_windows": slow,
            "top_pauses": pauses[:8], "density_curve": density, "windows": windows}


def rhythm_summary(r: dict) -> str:
    if not r:
        return "（无节奏数据）"
    return "\n".join([
        f"- 全片语速 {r['overall_chars_per_min']} 字/分；开场30秒 {r['opening_30s_chars_per_min']} 字/分",
        f"- 句长中位 {r['sentence_len_median']} 字，最长 {r['sentence_len_max']} 字，≤8字短句占比 {r['short_sentence_ratio']}",
        f"- 加速窗口（>1.2×均值）起点: {', '.join(r['fast_windows']) or '无'}",
        f"- 减速窗口（<0.8×均值）起点: {', '.join(r['slow_windows']) or '无'}",
        "- 最长停顿: " + "; ".join(f"{p['t']} 停{p['gap_sec']}s" for p in r["top_pauses"][:5]),
        "- 密度曲线: " + " | ".join(f"{d['part']} {d['chars_per_min']}字/分" for d in r["density_curve"]),
    ])


# ── 第三层: 引用核验(移植 verify.py, 不用模型) ──────────────────────────────────
_STRIP = re.compile(r"[\s，。！？；：、「」『』（）()《》【】…—\-,.!?;:\"'“”‘’·~～\[\]]")
QUOTE_RE = re.compile(r"「([^「」]{2,200})」")
PLACEHOLDER_RE = re.compile(r"_{2,}|(?<![A-Za-z])[XY](?![A-Za-z])")
TS_RE = re.compile(r"\[?(\d{1,2}):(\d{2})\]?")
import difflib  # noqa: E402

try:
    from zhconv import convert as _zhconv
except Exception:
    def _zhconv(s, lang):
        return s


def _norm(s: str) -> str:
    return _STRIP.sub("", _zhconv(s, "zh-cn")).lower()


class _Transcript:
    def __init__(self, segments, duration):
        self.segs, self.duration = segments, duration
        self.text, self.times = "", []
        for s in segments:
            t = _norm(s["text"])
            self.text += t
            self.times += [s["start"]] * len(t)

    def locate(self, quote: str, claimed_ts=None):
        q = _norm(quote)
        if len(q) < 2:
            return None
        hits, i = [], self.text.find(q)
        while i >= 0:
            hits.append(self.times[i])
            i = self.text.find(q, i + 1)
        if hits:
            pos = min(hits, key=lambda t: abs(t - claimed_ts)) if claimed_ts is not None else hits[0]
            return {"status": "EXACT", "pos_sec": pos, "ratio": 1.0, "occurrences": len(hits)}
        best, best_i, L = 0.0, -1, len(q)
        step = max(1, L // 4)
        for i in range(0, max(1, len(self.text) - L + 1), step):
            r = difflib.SequenceMatcher(None, q, self.text[i:i + L]).ratio()
            if r > best:
                best, best_i = r, i
        if best >= 0.80:
            lo, hi = max(0, best_i - step), min(len(self.text) - L, best_i + step)
            for i in range(lo, hi + 1):
                r = difflib.SequenceMatcher(None, q, self.text[i:i + L]).ratio()
                if r > best:
                    best, best_i = r, i
            return {"status": "FUZZY", "pos_sec": self.times[best_i], "ratio": round(best, 3)}
        return {"status": "MISSING", "pos_sec": None, "ratio": round(best, 3)}


def verify(report_md: str, segments: list, duration: float, time_tol: float = 45.0) -> dict:
    tr = _Transcript(segments, duration)
    items, seen = [], set()
    for line in report_md.splitlines():
        m = TS_RE.search(line)
        claimed = int(m.group(1)) * 60 + int(m.group(2)) if m else None
        for q in QUOTE_RE.findall(line):
            if q in seen or PLACEHOLDER_RE.search(q):
                continue
            seen.add(q)
            loc = tr.locate(q, claimed)
            item = {"quote": q, "claimed_ts": claimed, **(loc or {"status": "SKIP"})}
            if loc and loc["status"] in ("EXACT", "FUZZY") and claimed is not None \
                    and abs(loc["pos_sec"] - claimed) > time_tol:
                item["status"] = "TIME_OFF"
                item["actual_ts"] = int(loc["pos_sec"])
            items.append(item)
    bad_ts = sorted({m for m in (int(a) * 60 + int(b) for a, b in TS_RE.findall(report_md))
                     if m > duration + 5})
    counts = {k: sum(1 for i in items if i["status"] == k)
              for k in ("EXACT", "FUZZY", "MISSING", "TIME_OFF")}
    n_ok = counts["EXACT"] + counts["FUZZY"]
    return {"total_quotes": len(items), "verified": n_ok,
            "pass_rate": round(n_ok / len(items), 3) if items else None,
            "counts": counts, "timestamps_out_of_range": bad_ts, "items": items}


def annotate(report_md: str, result: dict) -> str:
    out = report_md
    for it in result["items"]:
        q = it["quote"]
        if it["status"] == "MISSING":
            out = out.replace(f"「{q}」", f"⚠️❌「{q}」⟨逐字稿中不存在，已剔除⟩")
        elif it["status"] == "TIME_OFF":
            m, s = divmod(it["actual_ts"], 60)
            out = out.replace(f"「{q}」", f"⚠️⏱「{q}」⟨实际位于 {m:02d}:{s:02d}⟩")
    return out


# ── 编排: 取数 → 节奏 → LLM 文本拆解 → 核验 → 落盘 ────────────────────────────
def run(target: dict, key: str, request: dict) -> tuple[dict, int]:
    """copylab 工作流主入口(仅 CLI 进程)。target 已由 vstudio._target 解析。"""
    attempted = []
    # 2026-09-10 用户拍板: LLM 步走成稿模型(compose 段), 不再挂翻译段
    chain = config.compose_chain()
    if not chain:
        return {"error": "no_compose_config",
                "hint": "copylab 走成稿模型, 到设置页配置成稿模型(GLM/DeepSeek 等, 可配多条按优先级兜底)"}, 4

    vstudio.tick("analyze", "copylab", 8, "yt-dlp 取元数据/字幕…")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            meta = fetch_meta(target["url"], tmp)
        except Exception as e:
            return {"error": f"yt-dlp 元数据失败: {str(e)[:200]}"}, 3
        segments, src = fetch_segments(target["url"], tmp)
    if not segments:
        rec = vstudio._analysis_record(
            target, key, attempted, "failed", "copylab", "", {},
            error="未取得字幕(manual/auto 均无)。若提示反爬: 需 YouTube 登录 cookies"
                  "(Get cookies.txt 扩展导出 youtube.com → %USERPROFILE%\\.config\\yt-dlp\\cookies.txt)")
        vstudio._save_analysis(rec)
        return rec, 3
    attempted.append({"tier": "fetch", "result": "success",
                      "evidence": f"{src} · {len(segments)} 段 · {meta['duration']}s"})

    vstudio.tick("analyze", "copylab", 30, "节奏计算(纯时间戳)…")
    rhythm = rhythm_compute(segments, meta["duration"])
    transcript_txt = "\n".join(f"[{_mmss(s['start'])}] {s['text']}" for s in segments)

    vstudio.tick("analyze", "copylab", 50, "LLM 只读文本拆解框架…")
    tpl = PROMPT_FILE.read_text(encoding="utf-8")
    d = meta["duration"]
    chapters = "\n".join(f"  [{int(c['start'])//60:02d}:{int(c['start'])%60:02d}] {c['title']}"
                         for c in (meta.get("chapters") or [])) or "  （无）"
    prompt = (tpl.replace("{{TITLE}}", meta["title"])
                 .replace("{{CHANNEL}}", meta["channel"])
                 .replace("{{DURATION}}", f"{int(d)//60:02d}:{int(d)%60:02d}（{int(d)} 秒）")
                 .replace("{{SOURCE}}", src or "")
                 .replace("{{CHAPTERS}}", chapters)
                 .replace("{{RHYTHM}}", rhythm_summary(rhythm))
                 .replace("{{TRANSCRIPT}}", transcript_txt))
    raw, used = None, None
    for m in chain:                                 # 成稿模型链: 前一失败自动落下一
        raw = vstudio.chat_completions(m["base_url"], m["api_key"], m["model"],
                                       [{"role": "user", "content": prompt}],
                                       0.1, 8000, 300, extra=m.get("extra_body") or None)
        if raw:
            used = m
            break
    if not raw:
        attempted.append({"tier": "llm", "result": "failed", "evidence": "文本模型链全部未返回内容"})
        rec = vstudio._analysis_record(target, key, attempted, "failed", "copylab", "",
                                       {"rhythm": rhythm}, error="文本模型链全部未返回内容")
        vstudio._save_analysis(rec)
        return rec, 3
    attempted.append({"tier": "llm", "result": "success",
                      "evidence": f"{used['name']}({used['model']}) · {len(raw)} 字"})

    vstudio.tick("analyze", "copylab", 80, "引用核验(机器核对)…")
    result = verify(raw, segments, d)
    verified = annotate(raw, result)
    pr = result["pass_rate"]
    header = (f"## 核验头(机器核对, 无模型参与)\n"
              f"- 引用 {result['total_quotes']} 处: 逐字 {result['counts']['EXACT']} + "
              f"近似 {result['counts']['FUZZY']} | 编造剔除 {result['counts']['MISSING']} | "
              f"时间错位 {result['counts']['TIME_OFF']}\n"
              f"- **通过率: {pr}**\n- 字幕来源: {src} · 逐字稿 {len(segments)} 段\n\n---\n\n")
    rec = vstudio._analysis_record(
        target, key, attempted, "ok" if (pr or 0) >= 0.8 else "partial",
        "copylab", header + verified,
        {"rhythm": rhythm, "verify": {k: result[k] for k in
                                      ("total_quotes", "verified", "pass_rate", "counts",
                                       "timestamps_out_of_range")}},
        model=tmodel, error="" if (pr or 0) >= 0.8 else f"引用通过率 {pr}")
    vstudio.tick("analyze", "save", 95, "落盘")
    vstudio._save_analysis(rec)
    return rec, 0
