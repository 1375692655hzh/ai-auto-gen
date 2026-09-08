"""视频工坊后端：视频池、三级分析降级链、口播脚本生成与只读视图。

分析按 G0 Gemini 看片 → G1 yt-dlp 字幕 → G2 热点库元数据逐级降级；每层都记录
结果与证据，无法确认的维度显式标为 N/A。架构红线：本模块外呼仅发生在 CLI
进程，app.py 端点零外呼（除两个 Popen spawn）；端点只读缓存或写
data/workbench/ 自有 JSON。所有自有对象原子落盘，损坏文件按空库恢复。
"""

import hashlib
import copy
import shutil
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

from . import config, yt_track

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "workbench"
ANALYSES_FILE = DATA_DIR / "video_analyses.json"
JOBS_FILE = DATA_DIR / "video_jobs.json"
BUILD_LOG_DIR = DATA_DIR / "video_builds"
MAX_POOL = 500
MAX_ANALYSES = 200
MAX_SCRIPTS = 300
JOB_KINDS = ("analyze", "generate", "voice", "build")
# build 是分钟级真渲染, stale 阈值独立放宽到 60 分钟; analyze/generate 维持 20 分钟
JOB_STALE_S = {"analyze": 20 * 60, "generate": 20 * 60, "voice": 20 * 60, "build": 60 * 60}
SEMANTIC_KEYS = ("theme", "hook", "structure", "devices", "voice", "cta",
                 "reusable", "visuals", "tier_note")

STYLE_PRESETS = [
    {"id": "recap-ask-conclude", "name": "财经盘后", "format": "horizontal",
     "target_s": 210, "wc": (700, 900),
     "prompt": "开场四拍：recap → 替观众问 → 人设 → 先说结论。"},
    {"id": "shorts-60", "name": "60 秒 Shorts", "format": "vertical",
     "target_s": 60, "wc": (240, 270),
     "prompt": "五段结构：Hook / Setup / Move / Gives / Payoff + CTA。"},
    {"id": "shorts-90", "name": "90 秒 Shorts", "format": "vertical",
     "target_s": 90, "wc": (360, 405),
     "prompt": "加长五段结构：Hook / Setup / Move / Gives / Payoff + CTA。"},
    {"id": "event-fast", "name": "事件快评", "format": "horizontal",
     "target_s": 100, "wc": (320, 450),
     "prompt": "首句必须是‘谁 + 做了什么 + 带张力的结果’，禁用比喻或拟人开头。"},
    {"id": "framework", "name": "框架讲解", "format": "horizontal",
     "target_s": 210, "wc": (700, 900),
     "prompt": "给出 2—4 个可执行检查点，结论能被观众复用。"},
    {"id": "contrarian", "name": "反方拆解", "format": "horizontal",
     "target_s": 210, "wc": (700, 900),
     "prompt": "权威重构并攻击反方信源；禁止连续两段纯批评，破立交替。"},
    {"id": "from-analysis", "name": "跟随分析", "format": "horizontal",
     "target_s": 210, "wc": (700, 900),
     "prompt": "必须带 analysis_key；只参考 reusable、hook.categories、structure.arc，"
               "严禁注入或复写对方原文。"},
    {"id": "vox-doc", "name": "VOX 纪录片", "format": "horizontal",
     "target_s": 120, "wc": (400, 480),
     "prompt": "纪录片旁白(纸拼贴风)：单一散文连续旁白，节拍化短句每 5-8 字一顿；"
               "开场必须是精确的日期/地点/数字；冷静克制、悲剧不煽情、无推广内容；"
               "每句以句号结尾；结尾必须悬念收束(末句不超过12字)，给下集留钩。"
               "on_screen 用档案标签风格(全大写短词、地点/日期/人名)。"},
]
_STYLES = {s["id"]: s for s in STYLE_PRESETS}

ANALYZE_PROMPT = r"""你是财经视频内容与商业化分析师。请完整观看给定视频，输出两部分。

第一部分是供机器解析的语义 JSON：先输出一个且仅一个 ```json 代码块（JSON 必须在报告之前），字段名有且仅用以下 10 个顶层字段：
{
  "theme":{"one_liner":"不超过40字","title_formula":"这类片的标题公式(含情绪词位/悬念位)","topics":["2-5个主题"],"audience":"受众","format":"内容形态"},
  "hook":{"categories":["事实recap|替观众提问|人设议程|结论承诺"],"sequence":"开场时序结构","opening_line":"开场第一句原话","evidence":[{"timestamp":"[MM:SS-MM:SS]","quote":"原文"}]},
  "structure":{"arc":"叙事弧","chapters":[{"t":"[MM:SS-MM:SS]","label":"章节","role":"作用"}],"pacing_note":"节奏,必须含量化占比数字"},
  "devices":[{"device":"话术装置","evidence":[{"timestamp":"[MM:SS-MM:SS]","quote":"原文"}]}],
  "voice":{"persona":"人设","address":"称呼","tone":"语气"},
  "cta":{"mode":"single|multiple|none","action":"动作","touchpoints":[{"layer":"层级","timestamp":"时间码","evidence":"证据"}]},
  "reusable":{"keep":"只保留风格机制","change":"必须替换的内容表达，禁止 carbon copy","script_seeds":["可复用写法种子"]},
  "visuals":[{"category":"版式","function":"功能","timestamp":"时间码","packaging_elements":["包装"],"subtitle_style":"字幕样式","on_screen_text":"屏幕文字"}],
  "tier_note":"模型通道说明"
}
第二部分是供人阅读的 Markdown 报告，固定三段：一、内容设计分析；二、视频设计分析；三、商业化链路。

证据密度下限（不达标即不合格）：
- 开场钩子：逐句还原开场 30-60 秒，evidence 至少 3 条，每条带时间码与逐字原文；
- devices：至少 3 种话术装置（可从命中自证/权威重构/攻击反方信源/二元对立/认知反差/数据具体化/恐惧→CTA 直译中选），每种至少 2 条时间码证据；
- chapters：视频 ≥10 分钟至少 8 个章节，3-10 分钟至少 5 个，≤60 秒给 3-5 个并精确到秒；pacing_note 必须给出各章时长占比与重头戏位置（例："重头戏占全片 40%，位于中段"）；
- 时间码格式 [MM:SS-MM:SS]，超过 1 小时用 [HH:MM:SS]；
- 引文保真：quote 必须是片中实际说出的完整中文原句，逐字转录，禁止翻译腔、禁止夹杂外文词、禁止改写拼接；
- 章节占比要与真实时长一致，宁可 N/A 不可编造。
N/A 纪律：无法确认写“N/A — 原因”；看不到的描述区或置顶评论写 N/A。reusable.keep 只留风格机制，reusable.change 写必须替换的内容与表达，禁止 carbon copy。报告之后不要附加说明。"""

TEXT_ANALYZE_PROMPT = r"""你是财经视频文本分析师。根据下方字幕或元数据，先输出一个且仅一个 ```json 代码块（JSON 必须在报告之前），顶层 10 字段及结构必须为：theme:{one_liner,title_formula,topics[2-5],audience,format}；hook:{categories,sequence,opening_line,evidence:[{timestamp,quote}]}；structure:{arc,chapters:[{t,label,role}],pacing_note(必须含量化占比)}；devices:[{device,evidence:[]}]（至少 3 种装置，每种 ≥2 条证据）；voice:{persona,address,tone}；cta:{mode,action,touchpoints:[]}；reusable:{keep,change,script_seeds:[]}；visuals；tier_note。随后输出供人阅读的 Markdown 三段报告：一、内容设计分析；二、视频设计分析；三、商业化链路。证据必须来自输入；没有时间轴时 evidence.timestamp 写“N/A — 文本通道”，quote 加“[文本]”前缀且必须是输入中出现的原句，禁止夹杂外文。所有画面类维度以及 visuals 一律写“N/A — 文本通道”，禁止从文本猜画面。无法确认写“N/A — 原因”，禁止编造；reusable 只提炼机制，禁止 carbon copy。

输入材料：
"""

GEN_SYSTEM = r"""你是财经口播脚本主编。只输出一个 ```json 代码块，不要解释。
写作前逐句扫描九类禁令：
①二元对比壳（不是A而是B）；②命令模板开头（别急着）；③伪洞察标记（真正、其实、本质上、说白了）；④冒号讲义腔；⑤模糊指代（这一点、它）；⑥时态错位（曾经…如今）；⑦没有参照物的空泛比较级（更、明显）；⑧抽象施压（很多人都没意识到）；⑨隐喻口号收尾（起航、破浪）。
另禁：narration 中出现 Markdown、角色前缀、镜头/舞台指示（镜头切到、画面给出）、元话语（接下来我们看）。数字写成可念形式，例如“百分之十八”，代码和专名保留。on_screen 每条不超过 6 个词。全片只能有一个 CTA。
输出 wb-video-script/v1：
{"schema":"wb-video-script/v1","title":"不超过30字","format":"horizontal|vertical","style_id":"风格ID","duration_est_s":0,"word_count":0,"hook":{"type":"主钩子类型","variants":[{"type":"互异类型","text":"钩子"},{"type":"互异类型","text":"钩子"},{"type":"互异类型","text":"钩子"}]},"beats":[{"id":"b1","role":"hook|setup|move|gives|payoff|cta","duration_est_s":0,"narration":"纯口播","on_screen":[],"visual_hint":"画面建议","subtitle":"字幕"}],"cta":{"action":"动作","line":"唯一CTA原句"},"warnings":[]}
必须恰好给 3 个类型互异的 hook variants；满足指定字数预算。
带参考分析时：套用其开场时序与至少 2 种话术装置机制，章节推进节奏对齐其 chapters 骨架；只学机制，严禁复写参考中的原文、事实与标的。"""


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _id(prefix: str) -> str:
    # 秒级时间戳 + 毫秒尾数: 同秒内多次写入不撞 id
    return prefix + time.strftime("%m%d%H%M%S") + f"{int(time.time() * 1000) % 1000:03d}"


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def parse_video_input(text: str) -> dict | None:
    """识别常见 YouTube 视频输入，统一为 watch URL；识别失败返回 None。"""
    s = (text or "").strip()
    if not s:
        return None
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", s):
        vid = s
    else:
        patterns = (
            r"(?:https?://)?(?:www\.)?youtube\.com/watch\?[^\s#]*?\bv=([A-Za-z0-9_-]{11})",
            r"(?:https?://)?(?:www\.)?youtu\.be/([A-Za-z0-9_-]{11})(?:[?/#]|$)",
            r"(?:https?://)?(?:www\.)?youtube\.com/(?:shorts|live)/([A-Za-z0-9_-]{11})(?:[?/#]|$)",
        )
        vid = ""
        for pattern in patterns:
            m = re.search(pattern, s, re.I)
            if m:
                vid = m.group(1)
                break
        if not vid:
            return None
    return {"video_id": vid, "url": f"https://www.youtube.com/watch?v={vid}"}


def analysis_key_of(video_id: str, url: str) -> str:
    return video_id or "u" + hashlib.sha1((url or "").encode()).hexdigest()[:12]


def _word_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def validate_script(script: dict, style: dict) -> list[str]:
    """返回脚本契约警告，不因模型格式瑕疵抛异常。"""
    warnings = []
    if not isinstance(script, dict):
        return ["脚本不是 JSON 对象"]
    beats = script.get("beats") if isinstance(script.get("beats"), list) else []
    minimum = 5 if style.get("format") == "vertical" else 4
    if len(beats) < minimum:
        warnings.append(f"beats 不足：{len(beats)}，至少需要 {minimum}")
    hook_obj = script.get("hook") if isinstance(script.get("hook"), dict) else {}
    variants = hook_obj.get("variants")
    variants = variants if isinstance(variants, list) else []
    types = [v.get("type") if isinstance(v, dict) else None for v in variants]
    if len(variants) != 3 or any(not t for t in types) or len(set(types)) != 3:
        warnings.append("hook.variants 必须恰好 3 条且 type 互异")
    narrations = []
    for i, beat in enumerate(beats, 1):
        narration = str(beat.get("narration") or "") if isinstance(beat, dict) else ""
        narrations.append(narration)
        if ("**" in narration or re.search(r"^\s*#", narration, re.M)
                or "旁白：" in narration or "voiceover:" in narration.lower()):
            warnings.append(f"beat {i} narration 含禁用标记")
    count = _word_count("".join(narrations))
    lo, hi = style.get("wc", (0, 10**9))
    if count < lo * 0.8 or count > hi * 1.2:
        warnings.append(f"口播 {count} 字，与该风格写作参考区间 {lo}—{hi} 有偏差（仅写作提示，不影响制作时长）")
    cta_beats = [b for b in beats if isinstance(b, dict) and b.get("role") == "cta"]
    cta = script.get("cta") if isinstance(script.get("cta"), dict) else {}
    if len(cta_beats) != 1 or not cta.get("action") or not cta.get("line"):
        warnings.append("CTA 必须唯一，且 cta.action/cta.line 均非空")
    return warnings


def _tc_s(ts: str) -> float:
    """[MM:SS] 或 [HH:MM:SS] 时间戳 → 秒。"""
    p = str(ts).split(":")
    if len(p) == 3:
        return int(p[0]) * 3600 + int(p[1]) * 60 + int(p[2])
    return int(p[0]) * 60 + int(p[1])


def seed_from_analysis(record: dict) -> dict:
    """把分析缓存确定性转换为可编辑脚本种子，不调用 LLM。"""
    semantic = record.get("semantic") if isinstance(record.get("semantic"), dict) else {}
    hook = semantic.get("hook") if isinstance(semantic.get("hook"), dict) else {}
    categories = hook.get("categories") if isinstance(hook.get("categories"), list) else []
    category = str(categories[0]) if categories else "事实recap"
    # 真钩子文本: opening_line / script_seeds 改写, 不再用类别标签当变体
    reusable = semantic.get("reusable") if isinstance(semantic.get("reusable"), dict) else {}
    seeds = [str(x) for x in (reusable.get("script_seeds") or []) if str(x).strip()]
    opening = str(hook.get("opening_line") or "").strip()
    variants = [x for x in [opening] + seeds[:2] if x][:3] or \
               [str(record.get("title") or "未命名视频")[:30]]
    structure = semantic.get("structure") if isinstance(semantic.get("structure"), dict) else {}
    chapters = structure.get("chapters") if isinstance(structure.get("chapters"), list) else []
    if not chapters:
        chapters = [{"label": f"空拍占位 {i}"} for i in range(1, 6)]
    # 时长按章节时间码区间占比分拍(评估 P1: 原片节奏配比不再被硬编码 210s 抹平)
    spans = []
    for c in chapters:
        if not isinstance(c, dict):
            continue
        nums = [_tc_s(x) for x in re.findall(r"\d{1,2}:\d{2}(?::\d{2})?", str(c.get("t") or ""))]
        if len(nums) >= 2:
            spans.append(max(0.0, nums[1] - nums[0]))
    if spans and sum(spans) > 0:
        total_s = min(max(int(sum(spans)), 30), 1800)
        weights = spans
    else:
        total_s = 210
        weights = [1.0] * len(chapters)
    wsum = sum(weights) or 1.0
    beats = []
    for i, (chapter, w) in enumerate(zip(chapters, weights), 1):
        chapter = chapter if isinstance(chapter, dict) else {}
        role = "hook" if i == 1 else ("cta" if i == len(chapters) else "setup")
        beats.append({"id": f"b{i}", "role": role, "duration_est_s": max(1, round(total_s * w / wsum)),
                      "narration": "", "on_screen": [],
                      "visual_hint": str(chapter.get("label") or ""), "subtitle": ""})
    title = str(record.get("title") or "未命名视频")[:30]
    return {"schema": "wb-video-script/v1", "title": title, "format": "horizontal",
            "style_id": "from-analysis", "duration_est_s": total_s, "word_count": 0,
            "hook": {"type": category, "variants": variants},
            "beats": beats, "cta": {"action": "", "line": ""},
            "reusable": semantic.get("reusable"),
            "warnings": ["种子为骨架: 钩子/口播待在脚本生成页以 from-analysis 风格展开"]}


def chat_completions(base: str, key: str, model: str, messages: list,
                     temperature: float, max_tokens: int, timeout: int,
                     extra: dict | None = None) -> str | None:
    """OpenAI 兼容 /chat/completions；仅由 CLI 主流程调用。
    extra = 厂商私有参数原样合并进请求体(如智谱推理模型 {"thinking": {"type": "disabled"}}
    防 reasoning_content 吃光 max_tokens 返回空 content); 未配置则行为不变。"""
    import urllib.request
    payload = {"model": model, "temperature": temperature,
               "max_tokens": max_tokens, "messages": messages}
    if isinstance(extra, dict):
        payload.update(extra)
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read())
        return (data["choices"][0]["message"]["content"] or "").strip() or None
    except Exception:
        return None


_VIDEO_MIME = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
               ".mkv": "video/x-matroska", ".webm": "video/webm", ".avi": "video/x-msvideo",
               ".flv": "video/x-flv", ".wmv": "video/x-ms-wmv", ".ts": "video/mp2t"}


def gemini_upload_media(path: str, key: str, timeout: int = 600) -> tuple[str | None, str | None]:
    """本地视频 → Gemini Files API(可恢复两段式上传), 轮询 ACTIVE 后返回 file_uri。

    Gemini 对 file_data.file_uri 一视同仁: YouTube 链接与本地上传的 uri 都能看片。
    单文件上限 2GB; 上传后服务端转码需要时间, 最长等 5 分钟。仅由 CLI 分析进程调用。
    """
    import urllib.error
    import urllib.parse
    import urllib.request
    import time
    fp = Path(path)
    size = fp.stat().st_size
    mime = _VIDEO_MIME.get(fp.suffix.lower(), "video/mp4")
    try:
        req = urllib.request.Request(
            "https://generativelanguage.googleapis.com/upload/v1beta/files",
            method="POST",
            data=json.dumps({"file": {"display_name": fp.name}}).encode("utf-8"),
            headers={"x-goog-api-key": key, "Content-Type": "application/json",
                     "X-Goog-Upload-Protocol": "resumable",
                     "X-Goog-Upload-Command": "start",
                     "X-Goog-Upload-Content-Length": str(size),
                     "X-Goog-Upload-Content-Type": mime})
        with urllib.request.urlopen(req, timeout=30) as r:
            upload_url = r.headers.get("X-Goog-Upload-URL")
        if not upload_url:
            return None, "Files API 未返回上传地址"
        with open(fp, "rb") as f:                    # 流式发送, 不整读进内存
            req2 = urllib.request.Request(
                upload_url, method="POST", data=f,
                headers={"Content-Length": str(size), "Content-Type": mime,
                         "X-Goog-Upload-Command": "upload, finalize",
                         "X-Goog-Upload-Offset": "0"})
            with urllib.request.urlopen(req2, timeout=timeout) as r:
                meta = json.loads(r.read())
        info = meta.get("file") or meta
        fname = (info.get("name") or "").removeprefix("files/")   # name 形如 files/abc, 路径里不能再带前缀
        uri = info.get("uri") or ""
        st = info.get("state") or ""
        for i in range(60):                          # 等服务端转码 ACTIVE(≈5分钟)
            if st == "ACTIVE" and uri:
                return uri, None
            if st == "FAILED":
                return None, "Gemini 文件转码失败"
            try:
                req3 = urllib.request.Request(
                    f"https://generativelanguage.googleapis.com/v1beta/files/{fname}",
                    headers={"x-goog-api-key": key})
                with urllib.request.urlopen(req3, timeout=30) as r:
                    meta = json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code == 404 and i < 10:         # 资源刚 finalize 尚未传播到位, 稍后重试
                    time.sleep(5)
                    continue
                return None, f"Files API HTTP {e.code}: {i}"
            info = meta.get("file") or meta
            fname = (info.get("name") or fname).removeprefix("files/")
            uri = info.get("uri") or uri
            st = info.get("state") or ""
            time.sleep(5)
        return (uri, None) if (st == "ACTIVE" and uri) else (None, f"转码未完成(state={st})")
    except urllib.error.HTTPError as e:
        return None, f"Files API HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:150]}"
    except Exception as e:
        return None, f"上传失败: {type(e).__name__}: {str(e)[:120]}"


def gemini_watch_url(url: str, prompt: str, key: str, model: str,
                     timeout: int = 180) -> tuple[str | None, str | None]:
    """Gemini URL 看片请求；429/5xx/超时等瞬时失败自动重试 1 次，4xx 证据类失败不重试。"""
    import urllib.error
    import urllib.parse
    import urllib.request
    import time as _t
    endpoint = ("https://generativelanguage.googleapis.com/v1beta/models/"
                + urllib.parse.quote(model, safe="") + ":generateContent")
    body = json.dumps({"contents": [{"parts": [
        {"file_data": {"file_uri": url}}, {"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8192}}).encode("utf-8")
    req = urllib.request.Request(endpoint, data=body,
                                 headers={"x-goog-api-key": key,
                                          "Content-Type": "application/json"})
    last_evidence = None
    for attempt in (0, 1):                            # 瞬时失败重试一次
        if attempt:
            _t.sleep(3)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = json.loads(response.read())
            parts = data["candidates"][0]["content"]["parts"]
            text = "\n".join(str(p.get("text") or "") for p in parts if p.get("text")).strip()
            return (text or None), None
        except urllib.error.HTTPError as e:
            try:
                evidence = e.read().decode("utf-8", "replace")[:200]
            except Exception:
                evidence = f"HTTP {e.code}"
            last_evidence = evidence
            if e.code < 500 and e.code != 429:        # 证据类失败(配额尽/参数错)重试无意义
                return None, evidence
        except Exception as e:
            last_evidence = str(e)[:200]
    return None, last_evidence


def _empty_analyses() -> dict:
    return {"version": 1, "updated_at": None, "analyses": {}}


def _load_analyses() -> dict:
    try:
        data = json.loads(ANALYSES_FILE.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or not isinstance(data.get("analyses"), dict)
                or not all(isinstance(v, dict) for v in data["analyses"].values())):
            raise ValueError("bad store")
        data.setdefault("version", 1)
        data.setdefault("updated_at", None)
        return data
    except Exception:
        return _empty_analyses()


def _save_analyses(store: dict) -> None:
    analyses = store.get("analyses") or {}
    if len(analyses) > MAX_ANALYSES:
        keep = sorted(analyses.items(), key=lambda item: item[1].get("updated_at") or "",
                      reverse=True)[:MAX_ANALYSES]
        store["analyses"] = dict(keep)
    store["version"] = 1
    store["updated_at"] = _now()
    _atomic_json(ANALYSES_FILE, store)


def _empty_job() -> dict:
    return {"running": False, "started_at": None, "finished_at": None, "exit": None,
            "progress": {"stage": "idle", "pct": 0, "message": ""}, "request": {},
            "error": "", "hint": ""}


def _empty_build_result() -> dict:
    return {"project_id": "", "output": "", "warnings": []}


def load_jobs() -> dict:
    try:
        data = json.loads(_jobs_file().read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("bad jobs")
    except Exception:
        data = {}
    for kind in JOB_KINDS:
        base = _empty_job()
        raw = data.get(kind) if isinstance(data.get(kind), dict) else {}
        base.update(raw)
        progress = raw.get("progress") if isinstance(raw.get("progress"), dict) else {}
        base["progress"] = {**_empty_job()["progress"], **progress}
        if kind == "analyze":
            base.setdefault("result_key", "")
        elif kind == "build":
            base.setdefault("result", _empty_build_result())
        else:
            base.setdefault("result", None)
        data[kind] = base
    return {kind: data[kind] for kind in JOB_KINDS}


def _save_jobs(jobs: dict) -> None:
    _atomic_json(_jobs_file(), jobs)


def _jobs_file() -> Path:
    return config.DATA_DIR / "video_jobs.json" if config.DATA_DIR != config.REPO / "data" / "workbench" else JOBS_FILE


def begin_job(kind: str, request: dict) -> None:
    jobs = load_jobs()
    job = _empty_job()
    job.update({"running": True, "started_at": _now(), "request": dict(request or {})})
    if kind == "analyze":
        job["result_key"] = ""
    elif kind == "build":
        job["result"] = _empty_build_result()
    else:
        job["result"] = None
    jobs[kind] = job
    _save_jobs(jobs)


def tick(kind: str, stage: str, pct: int, msg: str) -> None:
    jobs = load_jobs()
    jobs[kind]["progress"] = {"stage": stage, "pct": pct, "message": msg}
    _save_jobs(jobs)


def _set_job_result(kind: str, value) -> None:
    jobs = load_jobs()
    jobs[kind]["result_key" if kind == "analyze" else "result"] = value
    _save_jobs(jobs)


def finish_job(kind: str, exit: int, error: str, hint: str = "") -> None:
    jobs = load_jobs()
    jobs[kind].update({"running": False, "finished_at": _now(), "exit": exit,
                       "error": error or "", "hint": hint or ""})
    if exit == 0:
        jobs[kind]["progress"] = {"stage": "done", "pct": 100, "message": "完成"}
    _save_jobs(jobs)


def _age_seconds(stamp: str | None) -> float:
    if not stamp:
        return float("inf")
    try:
        return time.time() - datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").timestamp()
    except Exception:
        return float("inf")


def job_running(kind: str) -> bool:
    job = load_jobs().get(kind) or {}
    stale = JOB_STALE_S.get(kind, 20 * 60)
    return bool(job.get("running")) and _age_seconds(job.get("started_at")) <= stale


def status_payload() -> dict:
    jobs = load_jobs()
    common = ("running", "started_at", "finished_at", "exit", "progress", "error",
              "hint", "request")
    out = {kind: {k: jobs[kind].get(k) for k in common} for kind in jobs}
    out["analyze"]["result_key"] = jobs["analyze"].get("result_key", "")
    out["generate"]["result"] = jobs["generate"].get("result")
    out["voice"]["result"] = jobs["voice"].get("result")
    out["build"]["result"] = jobs["build"].get("result") or _empty_build_result()
    return out


def _parse_json_reply(text: str) -> tuple[dict | None, str]:
    raw = text or ""
    match = re.search(r"```json\s*([\s\S]*?)```", raw, re.I)
    candidate = match.group(1).strip() if match else raw
    start, end = candidate.find("{"), candidate.rfind("}")
    if start < 0 or end <= start:
        return None, raw.strip()
    try:
        parsed = json.loads(candidate[start:end + 1])
        if not isinstance(parsed, dict):
            return None, raw.strip()
    except Exception:
        return None, raw.strip()
    if match:
        report = (raw[:match.start()] + raw[match.end():]).strip()
    else:
        report = (raw[:start] + raw[end + 1:]).strip()
    return parsed, report


def _normalize_semantic(value: dict | None, tier_note: str, text_only: bool = False) -> dict:
    semantic = dict(value or {})
    visuals_missing = semantic.get("visuals") in (None, "", [])
    missing = "N/A — 模型未输出该字段"
    for key in SEMANTIC_KEYS:
        semantic.setdefault(key, missing)
    theme = semantic.get("theme")
    if isinstance(theme, dict):
        theme.setdefault("title_formula", missing)   # 10 字段: 标题公式(评估 P1 增补)
    if text_only:
        semantic["visuals"] = "N/A — 文本通道"
    elif visuals_missing:
        semantic["visuals"] = "N/A — 未观看画面"
    semantic["tier_note"] = tier_note
    return semantic


def _vtt_text(paths: list[Path]) -> str:
    lines, last = [], None
    for path in paths:
        try:
            raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for line in raw_lines:
            line = line.strip()
            if (not line or line == "WEBVTT" or line.startswith(("Kind:", "Language:"))
                    or "-->" in line or re.fullmatch(r"\d+", line)):
                continue
            line = re.sub(r"<[^>]+>", "", line).strip()
            line = re.sub(r"&nbsp;", " ", line)
            if line and line != last:
                lines.append(line)
                last = line
    return "\n".join(lines)[:12000]


def _yt_meta_of(video_id: str) -> dict:
    """从热点库补展示元数据(标题/频道/时长/竖版标记), 缺库返回空。"""
    if not video_id:
        return {}
    v = (yt_track.load_store().get("videos") or {}).get(video_id) or {}
    chs = {c.get("channel_id"): c for c in config.load_yt_channels()}
    return {"title": v.get("title") or "", "channel_title": (chs.get(v.get("channel_id")) or {}).get("title") or "",
            "duration_s": v.get("duration_s"), "is_short": v.get("is_short")}


def _target(request: dict) -> tuple[dict | None, dict | None]:
    if request.get("pool_id"):
        row = next((r for r in config.load_video_pool()
                    if r.get("id") == request.get("pool_id")), None)
        if not row:
            return None, {"error": "pool_not_found", "hint": "视频池中未找到该条目"}
        t = {"video_id": row.get("video_id") or "", "url": row.get("url") or "",
             "title": row.get("title") or "", "channel_title": row.get("channel_title") or ""}
        if not t["title"]:                          # 池行快照缺失时从热点库兜底补齐
            t.update({k: v for k, v in _yt_meta_of(t["video_id"]).items()
                      if k in ("title", "channel_title") and v})
        return t, None
    lp = str(request.get("local_path") or "")
    if lp:
        fp = Path(lp)
        if not fp.is_file():
            return None, {"error": "local_file_missing", "hint": f"本地文件不存在: {lp}"}
        if fp.suffix.lower() not in _VIDEO_MIME:
            return None, {"error": "bad_video_ext", "hint": f"不支持的扩展名: {fp.suffix}"}
        return {"video_id": "", "url": f"local:{fp.resolve()}", "title": fp.stem,
                "channel_title": fp.parent.name, "local_path": str(fp.resolve())}, None
    parsed = parse_video_input(str(request.get("url") or ""))
    if not parsed:
        return None, {"error": "bad_video_input", "hint": "请输入 YouTube 视频链接或 11 位视频 ID"}
    parsed.update({"title": "", "channel_title": ""})
    meta = _yt_meta_of(parsed.get("video_id") or "")
    parsed["title"] = meta.get("title") or ""
    parsed["channel_title"] = meta.get("channel_title") or ""
    return parsed, None


def _analysis_record(target: dict, key: str, attempted: list, status: str,
                     tier: str, report_md: str, semantic: dict, model: str = "",
                     text_model: str = "", error: str = "") -> dict:
    old = (_load_analyses().get("analyses") or {}).get(key) or {}
    now = _now()
    return {"key": key, "video_id": target.get("video_id") or "",
            "url": target.get("url") or "", "title": target.get("title") or "",
            "channel_title": target.get("channel_title") or "", "status": status,
            "tier_used": tier, "tiers_attempted": attempted, "report_md": report_md,
            "semantic": semantic, "model": model, "text_model": text_model,
            "created_at": old.get("created_at") or now, "updated_at": now,
            "error": error or ""}


def _save_analysis(record: dict) -> None:
    store = _load_analyses()
    store["analyses"][record["key"]] = record
    _save_analyses(store)


def _translate_cfg(cfg: dict) -> tuple[str, str, str] | None:
    t = cfg.get("translate") or {}
    values = (str(t.get("base_url") or ""), str(t.get("api_key") or ""),
              str(t.get("model") or ""))
    return values if all(values) else None


def run_analyze(request: dict) -> tuple[dict, int]:
    """执行 G0/G1/G2 分析链；本函数只由 CLI 进程调用。"""
    target, err = _target(request or {})
    if err:
        return err, 4
    key = analysis_key_of(target["video_id"], target["url"])
    cached = (_load_analyses().get("analyses") or {}).get(key)
    if cached and cached.get("status") in ("ok", "partial") and not request.get("force"):
        return {**cached, "skipped_cache": True}, 0

    cfg = config.load()
    gem = cfg.get("gemini") or {}
    gem_key = str(gem.get("api_key") or "")
    gem_model = str(gem.get("model") or "gemini-3.6-flash")
    translate = _translate_cfg(cfg)
    if not gem_key and not translate:
        return {"error": "no_llm_config", "hint": "到设置页配置 Gemini 或翻译模型"}, 4

    attempted = []
    last_evidence = ""

    # G0：Gemini 直接观看 —— YouTube URL 或 本地上传文件(统一走 file_data.file_uri)。
    watch_uri = None
    if gem_key and target.get("local_path"):
        tick("analyze", "upload", 5, "本地文件上传到 Gemini Files API…")
        watch_uri, up_ev = gemini_upload_media(target["local_path"], gem_key)
        if not watch_uri:
            attempted.append({"tier": "gemini-file", "result": "failed",
                              "evidence": (up_ev or "")[:200]})
            last_evidence = up_ev or "本地上传失败"
            record = _analysis_record(target, key, attempted, "failed",
                                      "gemini-file", "", {}, error=last_evidence)
            tick("analyze", "save", 95, "记录失败")
            _save_analysis(record)
            return record, 3          # 本地文件没有其他通道, 不落 ytdlp/meta 兜底
    elif gem_key and target.get("video_id"):
        watch_uri = target["url"]
    if gem_key and watch_uri:
        tick("analyze", "gemini", 5, "Gemini 看片分析中…")
        prompt = ANALYZE_PROMPT
        # 时长自适应粒度: 短片重精确, 长片重覆盖面
        meta_of = _yt_meta_of(target.get("video_id") or "")
        dur_s = meta_of.get("duration_s")
        try:
            dur_s = int(dur_s) if dur_s else None
        except Exception:
            dur_s = None
        if dur_s and dur_s <= 90:
            prompt += f"\n本片约 {dur_s} 秒: chapters 给 3-5 个并精确到秒, devices 至少 2 种。"
        elif dur_s and dur_s >= 600:
            prompt += f"\n本片约 {dur_s // 60} 分钟: chapters 至少 8 个, devices 至少 4 种, 开场逐句还原前 60 秒。"
        # 描述区/标签材料(平台数据, 非画面内容): 填掉商业化链路的 N/A 洞
        if meta_of.get("description_head"):
            prompt += ("\n\n[来自平台数据的已知材料, 供交叉印证, 非画面内容]\n描述区开头: "
                       + meta_of["description_head"])
        raw, evidence = gemini_watch_url(watch_uri, prompt, gem_key, gem_model)
        if raw:
            attempted.append({"tier": "gemini", "result": "success", "evidence": gem_model})
            tick("analyze", "parse", 80, "解析语义字段")
            parsed, report_md = _parse_json_reply(raw)
            status = "ok" if parsed else "partial"
            semantic = _normalize_semantic(parsed or {"raw_saved": True},
                                           f"G0 {gem_model} 看片")
            record = _analysis_record(target, key, attempted, status, "gemini",
                                      report_md or raw, semantic, model=gem_model,
                                      error="" if parsed else "semantic_json_parse_failed")
            tick("analyze", "save", 95, "落盘")
            _save_analysis(record)
            return record, 0
        last_evidence = evidence or "Gemini 未返回内容"
        attempted.append({"tier": "gemini", "result": "failed",
                          "evidence": last_evidence[:200]})
    else:
        attempted.append({"tier": "gemini", "result": "skipped",
                          "evidence": "未配置 Gemini 或非 YouTube URL"})

    # G1：yt-dlp 获取字幕，再交给文本模型分析。
    if translate:
        tick("analyze", "ytdlp", 20, "提取字幕中…")
        base, tkey, tmodel = translate
        with tempfile.TemporaryDirectory() as tmp:
            cmd = ["py", "-3.12", "-m", "yt_dlp", "--skip-download", "--write-subs",
                   "--write-auto-subs", "--sub-langs", "zh-Hans,zh-Hant,zh,en",
                   "--js-runtimes", "node",   # 新版 yt-dlp 抽 YouTube 需 JS 运行时, 默认只认 deno
                   "--print", "after_filter:%(title)s|%(channel)s|%(duration)s"]
            cookies = Path(os.environ.get("USERPROFILE", "")) / ".config" / "yt-dlp" / "cookies.txt"
            if cookies.is_file():
                cmd += ["--cookies", str(cookies)]
            cmd.append(target["url"])
            try:
                proc = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", timeout=60)
                vtt = _vtt_text(list(Path(tmp).glob("*.vtt")))
                meta_line = next((line for line in reversed((proc.stdout or "").splitlines())
                                  if line.count("|") >= 2), "")
                if proc.returncode != 0 or not vtt:
                    raise RuntimeError((proc.stderr or "未获取到字幕")[:200])
                title, channel, duration = (meta_line.split("|", 2) + ["", "", ""])[:3]
                target["title"] = target.get("title") or title
                target["channel_title"] = target.get("channel_title") or channel
                material = f"标题: {title}\n频道: {channel}\n时长: {duration}\n字幕:\n{vtt}"
                raw = chat_completions(base, tkey, tmodel,
                                       [{"role": "system", "content": TEXT_ANALYZE_PROMPT},
                                        {"role": "user", "content": material}],
                                       0.3, 3000, 120)
                if not raw:
                    raise RuntimeError("文本模型未返回内容")
                attempted.append({"tier": "ytdlp", "result": "success",
                                  "evidence": f"字幕 {len(vtt)} 字"})
                tick("analyze", "parse", 80, "解析语义字段")
                parsed, report_md = _parse_json_reply(raw)
                status = "ok" if parsed else "partial"
                semantic = _normalize_semantic(parsed or {"raw_saved": True},
                                               f"G1 {tmodel} 字幕文本", text_only=True)
                record = _analysis_record(target, key, attempted, status, "ytdlp",
                                          report_md or raw, semantic, text_model=tmodel,
                                          error="" if parsed else "semantic_json_parse_failed")
                tick("analyze", "save", 95, "落盘")
                _save_analysis(record)
                return record, 0
            except Exception as e:
                last_evidence = (str(e) or type(e).__name__)[:200]
                attempted.append({"tier": "ytdlp", "result": "failed",
                                  "evidence": last_evidence})
    else:
        attempted.append({"tier": "ytdlp", "result": "skipped",
                          "evidence": "翻译模型未完整配置"})

    # G2：仅使用热点追踪缓存元数据，不从 app.py 端点外呼。
    if translate:
        tick("analyze", "meta", 55, "使用元数据分析…")
        base, tkey, tmodel = translate
        video = (yt_track.load_store().get("videos") or {}).get(target.get("video_id"))
        if video:
            series = video.get("series") or []
            latest = series[-1] if series else {}
            target["title"] = target.get("title") or str(video.get("title") or "")
            target["channel_title"] = target.get("channel_title") or str(video.get("channel_title") or "")
            material = json.dumps({
                "title": video.get("title"), "tags": video.get("tags"),
                "description_head": video.get("description_head"),
                "summary": (video.get("insight") or {}).get("summary"),
                "duration_s": video.get("duration_s"), "is_short": video.get("is_short"),
                "latest": {"views": latest.get("v"), "likes": latest.get("l"),
                           "comments": latest.get("c")}}, ensure_ascii=False)
            raw = chat_completions(base, tkey, tmodel,
                                   [{"role": "system", "content": TEXT_ANALYZE_PROMPT},
                                    {"role": "user", "content": material}],
                                   0.3, 3000, 120)
            if raw:
                attempted.append({"tier": "meta", "result": "success",
                                  "evidence": "命中 yt_videos 元数据快照"})
                tick("analyze", "parse", 80, "解析语义字段")
                parsed, report_md = _parse_json_reply(raw)
                semantic = _normalize_semantic(parsed or {"raw_saved": True},
                                               f"G2 {tmodel} 元数据", text_only=True)
                record = _analysis_record(target, key, attempted, "partial", "meta",
                                          report_md or raw, semantic, text_model=tmodel,
                                          error="" if parsed else "semantic_json_parse_failed")
                tick("analyze", "save", 95, "落盘")
                _save_analysis(record)
                return record, 0
            last_evidence = "元数据文本模型未返回内容"
        else:
            last_evidence = "yt_videos 未命中该 video_id"
        attempted.append({"tier": "meta", "result": "failed", "evidence": last_evidence})
    else:
        attempted.append({"tier": "meta", "result": "skipped",
                          "evidence": "翻译模型未完整配置"})

    record = _analysis_record(target, key, attempted, "failed", "", "", {},
                              error=last_evidence or "所有分析通道均失败")
    tick("analyze", "save", 95, "记录失败")
    _save_analysis(record)
    return record, 3


def _material_for_generate(request: dict) -> tuple[str | None, dict | None]:
    parts = []
    brief = str(request.get("brief") or "").strip()
    if brief:
        parts.append("一句话简报：\n" + brief)
    draft_id = str(request.get("draft_id") or "").strip()
    if draft_id:
        draft = next((d for d in config.load_drafts() if d.get("id") == draft_id), None)
        if not draft:
            return None, {"error": "draft_not_found", "hint": "所选草稿不存在"}
        parts.append("草稿正文：\n" + str(draft.get("content") or "")[:12000])
    pasted = str(request.get("pasted") or "").strip()
    if pasted:
        parts.append("粘贴材料：\n" + pasted[:20000])
    if not parts:
        return None, {"error": "no_input", "hint": "填一句话简报、粘贴文章或选草稿"}
    return "\n\n".join(parts), None


def run_generate(request: dict) -> tuple[dict, int]:
    """调用文本模型生成 wb-video-script/v1；仅由 CLI 进程调用。"""
    request = request or {}
    style_id = str(request.get("style_id") or "")
    style = _STYLES.get(style_id)
    if not style:
        return {"error": "bad_style"}, 4
    material, err = _material_for_generate(request)
    if err:
        return err, 4
    reference = ""
    if style_id == "from-analysis":
        analysis_key = str(request.get("analysis_key") or "")
        record = (_load_analyses().get("analyses") or {}).get(analysis_key)
        if not analysis_key or not record:
            return {"error": "analysis_required",
                    "hint": "跟随分析风格需要有效 analysis_key"}, 4
        semantic = record.get("semantic") if isinstance(record.get("semantic"), dict) else {}
        hook = semantic.get("hook") if isinstance(semantic.get("hook"), dict) else {}
        structure = semantic.get("structure") if isinstance(structure.get("structure"), dict) else {}
        # 机制层注入(扩充): 装置名/人设/章节骨架/开场时序/标题公式——引文 evidence 原文仍不注入
        devices = semantic.get("devices") if isinstance(semantic.get("devices"), list) else []
        chapters = structure.get("chapters") if isinstance(structure.get("chapters"), list) else []
        theme = semantic.get("theme") if isinstance(semantic.get("theme"), dict) else {}
        cta = semantic.get("cta") if isinstance(semantic.get("cta"), dict) else {}
        safe_ref = {
            "reusable": semantic.get("reusable"),
            "hook_categories": hook.get("categories"),
            "hook_sequence": hook.get("sequence"),
            "structure_arc": structure.get("arc"),
            "chapters": [{"label": c.get("label"), "role": c.get("role")}
                         for c in chapters if isinstance(c, dict)][:14],
            "devices": [str(d.get("device")) for d in devices if isinstance(d, dict) and d.get("device")],
            "voice": semantic.get("voice"),
            "title_formula": theme.get("title_formula"),
            "cta_action": cta.get("action"),
        }
        reference = ("\n参考分析（只可借鉴机制与结构节奏，严禁复写对方原文、事实与标的）：\n"
                     + json.dumps(safe_ref, ensure_ascii=False))
    cfg = config.load()
    translate = _translate_cfg(cfg)
    if not translate:
        return {"error": "no_llm_config", "hint": "到设置页配置翻译模型"}, 4
    base, key, model = translate
    lo, hi = style["wc"]
    user = (f"风格：{style['name']}（{style_id}）\n格式：{style['format']}\n"
            f"写作引导字数区间：{lo}—{hi} 字\n"
            f"风格要点：{style['prompt']}\n\n输入材料：\n{material}{reference}")
    tick("generate", "llm", 15, "生成口播脚本中…")
    raw = chat_completions(base, key, model,
                           [{"role": "system", "content": GEN_SYSTEM},
                            {"role": "user", "content": user}], 0.5, 3500, 90)
    if not raw:
        return {"error": "llm_failed", "hint": "模型未返回内容"}, 3
    tick("generate", "parse", 80, "校验脚本结构")
    script, _ = _parse_json_reply(raw)
    if not script:
        return {"error": "llm_failed", "hint": "模型返回的 JSON 无法解析"}, 3
    script["schema"] = "wb-video-script/v1"
    script["style_id"] = style_id
    script["format"] = style["format"]
    script["title"] = str(script.get("title") or "未命名脚本")[:30]
    beats = script.get("beats") if isinstance(script.get("beats"), list) else []
    count = _word_count("".join(str(b.get("narration") or "")
                                for b in beats if isinstance(b, dict)))
    script["word_count"] = count
    script["duration_est_s"] = round(count / 4.2)
    warnings = script.get("warnings") if isinstance(script.get("warnings"), list) else []
    for warning in validate_script(script, style):
        if warning not in warnings:
            warnings.append(warning)
    script["warnings"] = warnings
    _set_job_result("generate", script)
    finish_job("generate", 0, "")
    return {"style_id": style_id, "word_count": count, "warnings": warnings}, 0


def narration_hash(text: str) -> str:
    return voice_hash(re.sub(r"\s+", "", text))


def voice_hash(text: str) -> str:
    """与 Node hashNarration 完全一致：原文 UTF-8，不修剪空白。"""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def voice_root() -> Path:
    return config.DATA_DIR / "video_voice"


def assets_root() -> Path:
    return config.DATA_DIR / "video_assets"


def _safe_path(root: Path, *parts: str) -> Path:
    path = root.joinpath(*parts).resolve()
    if root.resolve() not in path.parents:
        raise ValueError("path_outside_root")
    return path


def _safe_id(value) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[\w-]+", value))


def make_get(mid: str) -> dict | None:
    return next((r for r in config.load_video_makes() if r.get("id") == mid), None)


def _make_save(row: dict) -> dict:
    rows = config.load_video_makes()
    row["updated_at"] = _now()
    rows = [row if r.get("id") == row["id"] else r for r in rows]
    if not any(r.get("id") == row["id"] for r in rows):
        rows.append(row)
    config.save_video_makes(rows)
    return row


def _new_make_id() -> str:
    mid = _id("vm")
    while make_get(mid):
        time.sleep(0.001)
        mid = _id("vm")
    return mid


def make_upsert(payload: dict) -> dict | None:
    mid = payload.get("id")
    row = make_get(mid) if mid else None
    if mid and not row:
        return None
    if row is None:
        row = {"id": _new_make_id(), "title": "未命名视频", "status": "editing_narration",
               "created_at": _now(), "updated_at": _now(), "project_id": "",
               "narration": {"source": "", "style_id": "", "ref_text": "", "text": "",
                             "locked": False, "locked_at": None, "hash": ""},
               "script": None, "script_meta": {"locked": False, "locked_at": None,
                                                "hash": "", "source_narration_hash": ""},
               "voice": {"profile_id": "", "voice": "", "voice_key": "", "items": {}},
               "assets": [],
               "video": {"mode": "unified", "aspect": "16:9", "fps": 30,
                         "theme": "terminal-dark", "layout": "auto", "enrich": "plain",
                         "hook_index": 0, "beat_overrides": []}}
    if "title" in payload:
        row["title"] = str(payload["title"])
    if not row["narration"]["locked"]:
        for key in ("text", "ref_text", "style_id", "source"):
            if key in (payload.get("narration") or {}):
                row["narration"][key] = str(payload["narration"][key] or "")
    if "script" in payload and not row["script_meta"]["locked"]:
        row["script"] = copy.deepcopy(payload["script"])
        row["status"] = "editing_script" if row["narration"]["locked"] else "editing_narration"
    if isinstance(payload.get("video"), dict):
        row["video"].update(copy.deepcopy(payload["video"]))
    for key in ("profile_id", "voice"):
        if key in (payload.get("voice") or {}):
            value = str(payload["voice"][key] or "")
            if row["voice"][key] != value:
                row["voice"]["items"] = {}
                row["voice"]["voice_key"] = ""
                if row["status"] in ("voice_ready", "built"):
                    row["status"] = "script_locked" if row["script_meta"]["locked"] else "editing_script"
            row["voice"][key] = value
    return _make_save(row)


def make_view(row: dict) -> dict:
    row = copy.deepcopy(row)
    beats = (row.get("script") or {}).get("beats") or []
    hashes = {b.get("id"): voice_hash(str(b.get("narration") or "")) for b in beats}
    row["script_stale"] = bool(row.get("script")) and row["script_meta"]["source_narration_hash"] != row["narration"]["hash"]
    row["voice_bad"] = [bid for bid, item in row["voice"]["items"].items()
                        if item.get("hash") != hashes.get(bid)]
    row["script_badge"] = "stale" if row["script_stale"] else ("locked" if row["script_meta"]["locked"] else "draft")
    row["voice_badge"] = "stale" if row["voice_bad"] else ("ready" if beats and not voice_missing(row) else "missing")
    return row


def makes_view() -> list:
    return [make_view(row) for row in reversed(config.load_video_makes())]


def voice_missing(row: dict) -> list:
    items = row["voice"]["items"]
    return [b["id"] for b in (row.get("script") or {}).get("beats", [])
            if items.get(b["id"], {}).get("hash") != voice_hash(str(b.get("narration") or ""))]


def make_del(mid: str) -> int:
    rows = config.load_video_makes()
    kept = [r for r in rows if r.get("id") != mid]
    config.save_video_makes(kept)
    if len(kept) != len(rows) and _safe_id(mid):
        for root in (voice_root(), assets_root()):
            shutil.rmtree(_safe_path(root, mid), ignore_errors=True)
    return len(rows) - len(kept)


def make_duplicate(mid: str) -> dict | None:
    row = make_get(mid)
    if not row:
        return None
    row = copy.deepcopy(row)
    row.update(id=_new_make_id(), title=row["title"] + " 副本", project_id="", created_at=_now())
    row.pop("last_build", None)
    row["script_meta"].update(locked=False, locked_at=None)
    row["status"] = "editing_script" if row["narration"]["locked"] and row["script"] else (
        "narration_locked" if row["narration"]["locked"] else "editing_narration")
    for root, field in ((voice_root(), "voice"), (assets_root(), "assets")):
        src, dst = _safe_path(root, mid), _safe_path(root, row["id"])
        try:
            if src.is_dir():
                shutil.copytree(src, dst)
            elif field == "voice":
                row["voice"]["items"] = {}
        except OSError:
            shutil.rmtree(dst, ignore_errors=True)
            if field == "voice":
                row["voice"]["items"] = {}
            else:
                row["assets"] = []
                row["video"]["beat_overrides"] = [o for o in row["video"]["beat_overrides"] if not o.get("asset_id")]
    return _make_save(row)


def lock_narration(mid: str):
    row = make_get(mid)
    if not row:
        return None, {"error": "make_not_found"}
    if _word_count(row["narration"]["text"]) < 40:
        return None, {"error": "too_short", "hint": "口播稿去空白至少 40 字"}
    row["narration"].update(locked=True, locked_at=_now(), hash=narration_hash(row["narration"]["text"]))
    row["status"] = "narration_locked"
    return _make_save(row), None


def unlock_narration(mid: str):
    row = make_get(mid)
    if not row:
        return None, {"error": "make_not_found"}
    row["narration"]["locked"] = False
    row["status"] = "editing_narration"
    return _make_save(row), None


def _storyboard_integrity(script, text: str) -> bool:
    beats = script.get("beats") if isinstance(script, dict) else None
    return (isinstance(beats, list) and bool(beats) and all(isinstance(b, dict) for b in beats)
            and re.sub(r"\s+", "", "".join(str(b.get("narration") or "") for b in beats))
            == re.sub(r"\s+", "", text))


def lock_script(mid: str):
    row = make_get(mid)
    if not row:
        return None, {"error": "make_not_found"}
    if not row["narration"]["locked"]:
        return None, {"error": "narration_not_locked", "hint": "先定稿口播稿"}
    if not _storyboard_integrity(row["script"], row["narration"]["text"]):
        return None, {"error": "integrity", "hint": "逐拍口播拼接必须与口播稿逐字一致（忽略空白）"}
    script = row["script"]
    warnings = script.get("warnings") if isinstance(script.get("warnings"), list) else []
    script["warnings"] = list(dict.fromkeys(warnings + validate_script(script, _STYLES.get(
        row["narration"]["style_id"], _STYLES["recap-ask-conclude"]))))
    row["script_meta"] = {"locked": True, "locked_at": _now(),
                          "hash": narration_hash("".join(b["narration"] for b in script["beats"])),
                          "source_narration_hash": row["narration"]["hash"]}
    row["status"] = "script_locked"
    return _make_save(row), None


def unlock_script(mid: str):
    row = make_get(mid)
    if not row:
        return None, {"error": "make_not_found"}
    row["script_meta"]["locked"] = False
    row["status"] = "editing_script"
    return _make_save(row), None


ASSET_EXTS = {"png", "jpg", "jpeg", "webp", "mp4", "webm"}


def asset_add(make_id: str, beat_id: str, orig_name: str, body: bytes):
    row = make_get(make_id)
    if not row:
        return None, {"error": "make_not_found"}
    ext = Path(orig_name).suffix.lower().lstrip(".")
    if ext not in ASSET_EXTS:
        return None, {"error": "bad_ext"}
    if not _safe_id(make_id):
        return None, {"error": "bad_id"}
    aid = _id("va")
    while any(a.get("asset_id") == aid for a in row["assets"]):
        time.sleep(0.001)
        aid = _id("va")
    path = _safe_path(assets_root(), make_id, f"{aid}.{ext}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    asset = {"asset_id": aid, "name": orig_name, "ext": ext, "size": len(body),
             "beat_id": beat_id, "created_at": _now()}
    row["assets"].append(asset)
    _make_save(row)
    return asset, None


def asset_find(asset_id: str, make_id: str = ""):
    if not _safe_id(asset_id) or (make_id and not _safe_id(make_id)):
        return None, make_id
    root = assets_root()
    paths = (_safe_path(root, make_id).glob(f"{asset_id}.*") if make_id
             else root.glob(f"*/{asset_id}.*"))
    for p in paths:
        if p.is_file() and root.resolve() in p.resolve().parents and p.suffix.lstrip(".") in ASSET_EXTS:
            return p, p.parent.name
    return None, make_id


def assets_list(make_id: str) -> list:
    return [{**a, "exists": asset_find(a["asset_id"], make_id)[0] is not None}
            for a in (make_get(make_id) or {}).get("assets", [])]


def asset_del(asset_id: str, make_id: str) -> int:
    path, make_id = asset_find(asset_id, make_id)
    row = make_get(make_id)
    if not row:
        return 0
    if path:
        path.unlink(missing_ok=True)
    row["assets"] = [a for a in row["assets"] if a.get("asset_id") != asset_id]
    old = row["video"].get("beat_overrides") or []
    row["video"]["beat_overrides"] = [o for o in old if o.get("asset_id") != asset_id]
    _make_save(row)
    return len(old) - len(row["video"]["beat_overrides"])


NARRATION_SYSTEM = r"""你是财经口播稿主编。输出且仅输出一个 ```json 代码块，不要解释。
输出 wb-narration/v1：
{"schema":"wb-narration/v1","title":"≤30字","format":"horizontal|vertical","paragraphs":[{"id":"p1","text":"..."}],"word_count":0,"warnings":[]}
写作前逐句扫描九类禁令：
①二元对比壳（不是A而是B）；②命令模板开头（别急着）；③伪洞察标记（真正、其实、本质上、说白了）；④冒号讲义腔；⑤模糊指代（这一点、它）；⑥时态错位（曾经…如今）；⑦没有参照物的空泛比较级（更、明显）；⑧抽象施压（很多人都没意识到）；⑨隐喻口号收尾（起航、破浪）。
数字写成可念形式，例如百分之十八。节拍短句，每5-8字一顿的口播节奏。
首句必须是“谁+做了什么+带张力的结果”，结尾悬念收束。paragraphs 3-8 段。
纯口播禁止 Markdown、角色前缀、镜头指示、元话语。"""

STORYBOARD_SYSTEM = r"""你是口播分镜编辑。输入是已定稿口播稿全文，只输出一个 ```json 代码块。
输出 wb-video-script/v1：
{"schema":"wb-video-script/v1","title":"≤30字","format":"horizontal|vertical","style_id":"make-storyboard","duration_est_s":0,"word_count":0,"hook":{"type":"事实recap","variants":[{"type":"事实recap","text":"首拍原文"},{"type":"替观众提问","text":"钩子"},{"type":"结论承诺","text":"钩子"}]},"beats":[{"id":"b1","role":"hook|setup|move|gives|payoff|cta","duration_est_s":0,"narration":"原文","on_screen":[],"visual_hint":"画面建议","subtitle":"字幕"}],"cta":{"action":"关注","line":"末拍原文"},"warnings":[]}
铁律：beats[].narration 按顺序拼接（去空白）必须等于口播稿全文（去空白），一字符不许改。
role 序列首 hook 尾 cta，中段 setup/move/gives/payoff。on_screen 每条≤6词。
visual_hint/subtitle 必填。hook.variants 恰好3条，type互异，variant[0].text 默认等于首 beat narration。
只切分并设计画面，不改写、删减或新增口播。"""


def run_narration(request: dict) -> tuple[dict, int]:
    style_id = request.get("style_id")
    style = _STYLES.get(style_id)
    if not style:
        return {"error": "bad_style"}, 4
    row = make_get(request.get("make_id")) if request.get("make_id") else None
    if request.get("make_id") and not row:
        return {"error": "make_not_found"}, 4
    if row and row["narration"]["locked"]:
        return {"error": "narration_locked", "hint": "先解锁口播稿再生成"}, 4
    material, err = _material_for_generate({**request, "pasted": request.get("ref_text") or request.get("pasted")})
    if err:
        return err, 4
    llm = _translate_cfg(config.load())
    if not llm:
        return {"error": "no_llm_config", "hint": "到设置页配置翻译模型"}, 4
    lo, hi = style["wc"]
    user = f"风格：{style['name']}；{style['prompt']}\n写作引导字数区间：{lo}—{hi} 字\n输入材料：\n{material}"
    tick("generate", "llm", 15, "生成口播稿中…")
    raw = chat_completions(*llm, [{"role": "system", "content": NARRATION_SYSTEM},
                                  {"role": "user", "content": user}], 0.5, 3500, 90)
    obj, _ = _parse_json_reply(raw or "")
    paragraphs = obj.get("paragraphs") if isinstance(obj, dict) else None
    if not isinstance(paragraphs, list) or not paragraphs or not all(
            isinstance(p, dict) and isinstance(p.get("text"), str) for p in paragraphs):
        return {"error": "llm_failed", "hint": "模型未返回有效口播稿 JSON"}, 3
    text = "\n\n".join(p["text"] for p in paragraphs)
    obj.update(schema="wb-narration/v1", title=str(obj.get("title") or "未命名口播稿")[:30],
               format=style["format"], text=text, word_count=_word_count(text))
    if row:
        current = make_get(row["id"])
        if not current or current["narration"]["locked"]:
            return {"error": "make_changed", "hint": "生成期间口播稿已定稿或项目已删除"}, 4
        current["narration"].update(source="llm", style_id=style_id,
                                    ref_text=str(request.get("ref_text") or "")[:2000],
                                    text=text, locked=False, locked_at=None, hash="")
        current["status"] = "editing_narration"
        _make_save(current)
    _set_job_result("generate", obj)
    return obj, 0


def _storyboard_fallback(text: str, title: str, fmt: str) -> dict:
    from . import vmake
    sentences = vmake._split_sentences(text)
    if len(sentences) < 3:
        sentences = vmake._split_clauses(text)
    # 单句/无标点输入也保留首尾角色，原文按字符切分且绝不改字。
    if len(sentences) < 2:
        pivot = max(1, len(text) // 2)
        sentences = [text[:pivot], text[pivot:]]
    beats = [{"id": f"b{i+1}", "role": "hook" if i == 0 else (
        "cta" if i == len(sentences)-1 else ("setup", "move", "gives", "payoff")[(i-1) % 4]),
        "duration_est_s": round(_word_count(s) / 4.2), "narration": s,
        "on_screen": [], "subtitle": s, "visual_hint": ""} for i, s in enumerate(sentences)]
    return {"schema": "wb-video-script/v1", "title": title[:30], "format": fmt,
            "style_id": "make-storyboard", "word_count": _word_count(text),
            "duration_est_s": round(_word_count(text) / 4.2), "beats": beats,
            "hook": {"type": "事实recap", "variants": [{"type": t, "text": sentences[0]}
                    for t in ("事实recap", "替观众提问", "结论承诺")]},
            "cta": {"action": "关注", "line": sentences[-1]},
            "warnings": ["LLM 生成失败/校验未过，已用确定性拆句兜底"]}


def run_storyboard(request: dict) -> tuple[dict, int]:
    row = make_get(request.get("make_id"))
    if not row or not row["narration"]["locked"]:
        return {"error": "narration_not_locked" if row else "make_not_found"}, 4
    if row["script_meta"]["locked"]:
        return {"error": "script_locked", "hint": "先解锁脚本再生成"}, 4
    text = row["narration"]["text"]
    fmt = "vertical" if row["video"]["aspect"] == "9:16" else "horizontal"
    llm = _translate_cfg(config.load())
    script = None
    user = ("口播稿全文（逐字冻结）：\n" + text
            + f"\n字数/时长参考：{_word_count(text)} 字，约 {round(_word_count(text)/4.2)} 秒")
    tick("generate", "llm", 15, "切分已定稿口播稿…")
    if llm:
        for attempt in range(2):
            try:
                raw = chat_completions(*llm, [{"role": "system", "content": STORYBOARD_SYSTEM},
                    {"role": "user", "content": user + ("\n上次校验失败，请逐字保留全文。" if attempt else "")}], 0.5, 3500, 90)
                candidate, _ = _parse_json_reply(raw or "")
            except Exception:
                candidate = None
            if not candidate:
                break
            if _storyboard_integrity(candidate, text):
                script = candidate
                break
    script = script or _storyboard_fallback(text, row["title"], fmt)
    script.update(schema="wb-video-script/v1", style_id="make-storyboard", format=fmt,
                  title=str(script.get("title") or row["title"])[:30],
                  word_count=_word_count(text), duration_est_s=round(_word_count(text)/4.2))
    warnings = script.get("warnings") if isinstance(script.get("warnings"), list) else []
    script["warnings"] = list(dict.fromkeys(warnings + validate_script(script, _STYLES.get(
        row["narration"]["style_id"], _STYLES["recap-ask-conclude"]))))
    current = make_get(row["id"])
    if (not current or current["narration"] != row["narration"] or current["script_meta"]["locked"]):
        return {"error": "make_changed", "hint": "生成期间定稿已变化，请重新生成"}, 4
    current["script"] = script
    current["script_meta"] = {"locked": False, "locked_at": None,
                              "hash": narration_hash(text), "source_narration_hash": row["narration"]["hash"]}
    current["status"] = "editing_script"
    _make_save(current)
    _set_job_result("generate", script)
    return script, 0


def run_narration_cli(args) -> int:
    report, code = {}, 3
    try:
        request = load_jobs()["generate"]["request"]
        tick("generate", "start", 1, "准备口播稿生成")
        report, code = run_narration(request) if request else ({"error": "no_request"}, 4)
    except Exception as e:
        report = {"error": type(e).__name__, "hint": str(e)[:200]}
    finally:
        finish_job("generate", code, report.get("error", ""), report.get("hint", ""))
        print(json.dumps(report, ensure_ascii=False))
    return code


def _tts_provider(provider_id: str, voice: str, allow_disabled: bool = False):
    provider = next((p for p in (config.load().get("tts") or {}).get("providers", [])
                     if p.get("id") == provider_id), None)
    if (not provider or not _safe_id(provider_id) or not _safe_id(voice)
            or (not allow_disabled and not provider.get("enabled"))
            or provider.get("engine") not in ("edge", "dashscope")
            or voice not in [v.get("id") for v in provider.get("voices", [])]):
        return None
    return provider


def _tts_node(scenes: list, out_dir: Path, provider: dict, voice: str, progress: bool = False):
    """CLI 专用。job/result 均留在工作台自有语音目录，Node 仅接受该目录。"""
    from . import vmake
    out_dir.mkdir(parents=True, exist_ok=True)
    job_json = out_dir / "_job.json"
    result_json = out_dir / "_result.json"
    result_json.unlink(missing_ok=True)   # 本次失败不能误读上次结果
    _atomic_json(job_json, {"scenes": scenes, "out_dir": str(out_dir.resolve()),
                           "provider": provider["engine"], "voice": voice})
    env = os.environ.copy()
    if provider["engine"] == "dashscope":
        if provider.get("api_key"):
            env["DASHSCOPE_API_KEY"] = provider["api_key"]
        if provider.get("base_url"):
            env["DASHSCOPE_BASE_URL"] = provider["base_url"]
    proc = subprocess.Popen(["node", "scripts/tts-scenes.mjs", str(job_json.resolve())],
                            cwd=str(vmake.VIDEO_DIR), env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    last, count = "", 0
    for line in proc.stdout or []:
        if line.strip():
            last = line.strip()
        if progress and "合成语音" in line:
            count += 1
            tick("voice", "tts", min(95, count * 90 // max(1, len(scenes))), f"合成语音 {count}")
    code = proc.wait()
    if proc.stdout:
        proc.stdout.close()
    if code:
        key = provider.get("api_key") or ""
        return None, (last.replace(key, "***") if key else last)[-200:] or "tts_failed"
    try:
        result = json.loads(result_json.read_text(encoding="utf-8"))
        if not isinstance(result.get("items"), dict):
            raise ValueError("bad items")
        return result["items"], None
    except (OSError, ValueError, AttributeError):
        return None, "tts_result_missing"


def _voice_file(mid: str, voice_key: str, file: str) -> Path | None:
    if not _safe_id(mid) or not _safe_id(voice_key) or not isinstance(file, str):
        return None
    try:
        root = _safe_path(voice_root(), mid, voice_key)
        path = _safe_path(root, file)
        return path if path.is_file() and path.suffix == ".mp3" else None
    except (ValueError, OSError):
        return None


def _run_voice(request: dict):
    row = make_get(request.get("make_id"))
    if not row or not row["script_meta"]["locked"]:
        return {"error": "script_not_locked" if row else "make_not_found"}, 4
    pid, voice = request.get("provider_id"), request.get("voice")
    provider = _tts_provider(pid, voice)
    if not provider:
        return {"error": "bad_provider", "hint": "检查供应商启用状态、引擎与音色"}, 4
    beats = row["script"].get("beats") or []
    scope = request.get("scope") or "all"
    scenes = [{"id": b["id"], "narration": b["narration"]} for b in beats
              if scope == "all" or b["id"] == scope]
    if not scenes or any(not _safe_id(s["id"]) for s in scenes):
        return {"error": "bad_scope"}, 4
    vkey = re.sub(r"[^\w-]", "", f"{pid}-{voice}")
    out_dir = _safe_path(voice_root(), row["id"], vkey)
    items, err = _tts_node(scenes, out_dir, provider, voice, progress=True)
    if err:
        return {"error": err}, 3
    warnings, valid = [], {}
    for scene in scenes:
        bid = scene["id"]
        item = items.get(bid)
        if not isinstance(item, dict) or item.get("hash") != voice_hash(scene["narration"]):
            warnings.append(f"场景 {bid} 语音哈希不符或结果缺失，已忽略")
        elif not _voice_file(row["id"], vkey, item.get("file")):
            warnings.append(f"场景 {bid} 语音文件缺失，已忽略")
        else:
            valid[bid] = item
    current = make_get(row["id"])
    if not current or current["script"] != row["script"] or not current["script_meta"]["locked"]:
        return {"error": "make_changed", "hint": "合成期间脚本变化，请重新合成"}, 4
    merged = dict(current["voice"]["items"]) if current["voice"]["voice_key"] == vkey else {}
    for scene in scenes:
        merged.pop(scene["id"], None)
    merged.update(valid)
    current["voice"].update(profile_id=pid, voice=voice, voice_key=vkey, items=merged)
    current["status"] = "voice_ready" if not voice_missing(current) else "script_locked"
    _make_save(current)
    result = {"make_id": row["id"], "voice_key": vkey, "items": merged, "warnings": warnings}
    _set_job_result("voice", result)
    return result, 0


def run_voice_cli(args) -> int:
    report, code = {}, 3
    try:
        request = load_jobs()["voice"]["request"]
        tick("voice", "start", 1, "准备合成语音")
        report, code = _run_voice(request) if request else ({"error": "no_request"}, 4)
    except Exception as e:
        report = {"error": type(e).__name__}
    finally:
        finish_job("voice", code, report.get("error", ""), report.get("hint", ""))
        print(json.dumps(report, ensure_ascii=False))
    return code


def run_test_tts_cli(args) -> int:
    provider = _tts_provider(args.provider, args.voice, allow_disabled=True)
    if not provider:
        print(json.dumps({"ok": False, "error": "bad_provider"}))
        return 4
    try:
        from . import vmake
        if (provider["engine"] == "dashscope" and not provider.get("api_key")
                and not os.environ.get("DASHSCOPE_API_KEY") and not vmake.dashscope_key_ok()):
            print(json.dumps({"ok": False, "error": "dashscope_key_missing"}))
            return 3
        narration = "各位好，这里是 AI 财经工作台语音合成自检，当前链路工作正常。"
        out_dir = _safe_path(voice_root(), "_probe", args.provider)
        # 探测目录按供应商共用，换音色不能命中上一音色的同文缓存。
        (out_dir / "probe.mp3").unlink(missing_ok=True)
        items, err = _tts_node([{"id": "probe", "narration": narration}], out_dir, provider, args.voice)
        item = (items or {}).get("probe") or {}
        if not err and (item.get("hash") != voice_hash(narration) or not (out_dir / "probe.mp3").is_file()):
            err = "tts_result_missing"
        report = {"ok": False, "error": err} if err else {
            "ok": True, "url": f"/wb-api/video-voice/_probe/{args.provider}/probe.mp3"}
    except Exception as e:
        report = {"ok": False, "error": type(e).__name__}
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 3


def pool_view() -> dict:
    rows = config.load_video_pool()
    videos = yt_track.load_store().get("videos") or {}
    analyses = _load_analyses().get("analyses") or {}
    items = []
    for row in rows:
        item = dict(row)
        video = videos.get(row.get("video_id")) or {}
        latest = (video.get("series") or [{}])[-1]
        item.update({"views": latest.get("v"),
                     "summary": (video.get("insight") or {}).get("summary"),
                     "duration_s": video.get("duration_s"), "is_short": video.get("is_short")})
        analysis = analyses.get(analysis_key_of(row.get("video_id") or "", row.get("url") or "")) or {}
        item.update({"analysis_status": analysis.get("status"),
                     "analysis_tier_used": analysis.get("tier_used")})
        items.append(item)
    return {"items": items,
            "meta": {"n": len(items),
                     "analyzed_n": sum(1 for i in items if i.get("analysis_status") in ("ok", "partial"))}}


def analyses_index() -> list:
    rows = [{k: record.get(k) for k in ("key", "title", "status", "tier_used", "updated_at")}
            for record in (_load_analyses().get("analyses") or {}).values()]
    return sorted(rows, key=lambda row: row.get("updated_at") or "", reverse=True)


def analysis_get(key: str) -> dict | None:
    return (_load_analyses().get("analyses") or {}).get(key)


def scripts_view() -> list:
    return sorted(config.load_video_scripts(), key=lambda row: row.get("updated_at") or "",
                  reverse=True)


def script_get(sid: str) -> dict | None:
    return next((row for row in config.load_video_scripts() if row.get("id") == sid), None)


def script_add(payload: dict) -> dict:
    now = _now()
    row = {"id": _id("vs"), "kind": payload.get("kind") or "generated",
           "title": payload.get("title") or "未命名脚本",
           "style_id": payload.get("style_id") or "", "reusable": False,
           "analysis_key": payload.get("analysis_key") or "",
           "draft_id": payload.get("draft_id") or "", "brief": payload.get("brief") or "",
           "script": payload.get("script"), "created_at": now, "updated_at": now}
    rows = config.load_video_scripts()
    rows.append(row)
    rows = sorted(rows, key=lambda item: item.get("updated_at") or "", reverse=True)[:MAX_SCRIPTS]
    config.save_video_scripts(rows)
    return row


def script_update(sid: str, patch: dict) -> dict | None:
    rows = config.load_video_scripts()
    for row in rows:
        if row.get("id") == sid:
            if "title" in patch:
                row["title"] = str(patch.get("title") or "")
            if "reusable" in patch:
                row["reusable"] = bool(patch.get("reusable"))
            row["updated_at"] = _now()
            config.save_video_scripts(rows)
            return row
    return None


def script_del(sid: str) -> int:
    rows = config.load_video_scripts()
    kept = [row for row in rows if row.get("id") != sid]
    if len(kept) != len(rows):
        config.save_video_scripts(kept)
        return 1
    return 0


def pool_add(payload: dict) -> tuple[dict | None, dict | None]:
    raw_id = str(payload.get("video_id") or "").strip()
    parsed = parse_video_input(raw_id) if raw_id else parse_video_input(str(payload.get("url") or ""))
    if not parsed:
        return None, {"error": "bad_input"}
    rows = config.load_video_pool()
    key = parsed["video_id"] or parsed["url"]
    if any((row.get("video_id") or row.get("url")) == key for row in rows):
        return None, {"error": "dup"}
    now = _now()
    meta = _yt_meta_of(parsed["video_id"])          # 入池即补热点库展示快照(标题/频道), 缺时留空
    row = {"id": _id("p"), "video_id": parsed["video_id"], "url": parsed["url"],
           "title": str(payload.get("title") or "") or meta.get("title", ""),
           "channel_title": str(payload.get("channel_title") or "") or meta.get("channel_title", ""),
           "thumb": str(payload.get("thumb") or ""),
           "source": payload.get("source") if payload.get("source") in ("hot", "manual") else "manual",
           "note": str(payload.get("note") or ""), "added_at": now}
    rows.append(row)
    rows = sorted(rows, key=lambda item: item.get("added_at") or "", reverse=True)[:MAX_POOL]
    config.save_video_pool(rows)
    return row, None


def pool_del(pid: str) -> int:
    rows = config.load_video_pool()
    kept = [row for row in rows if row.get("id") != pid]
    if len(kept) != len(rows):
        config.save_video_pool(kept)
        return 1
    return 0


def run_analyze_cli(args) -> int:
    request = dict((load_jobs().get("analyze") or {}).get("request") or {})
    if getattr(args, "url", None):
        request = {"url": args.url, "force": bool(getattr(args, "force", False))}
    elif request and getattr(args, "force", False):
        request["force"] = True
    if not request:
        print(json.dumps({"error": "no_request"}, ensure_ascii=False))
        return 4
    report, code = {}, 3
    try:
        tick("analyze", "start", 1, "准备分析")
        report, code = run_analyze(request)
        if report.get("key"):
            _set_job_result("analyze", report["key"])
        return code
    except Exception as e:
        report, code = {"error": type(e).__name__, "hint": str(e)[:200]}, 3
        return code
    finally:
        finish_job("analyze", code, str(report.get("error") or ""),
                   str(report.get("hint") or ""))
        print(json.dumps(report, ensure_ascii=False))


def run_generate_cli(args) -> int:
    request = dict((load_jobs().get("generate") or {}).get("request") or {})
    if not request:
        print(json.dumps({"error": "no_request"}, ensure_ascii=False))
        return 4
    report, code = {}, 3
    try:
        tick("generate", "start", 1, "准备生成")
        report, code = run_storyboard(request) if request.get("task") == "storyboard" else run_generate(request)
        return code
    except Exception as e:
        report, code = {"error": type(e).__name__, "hint": str(e)[:200]}, 3
        return code
    finally:
        finish_job("generate", code, str(report.get("error") or ""),
                   str(report.get("hint") or ""))
        print(json.dumps(report, ensure_ascii=False))


# ── 视频制作（build 槽）：转换 → 建项目 → node build.mjs 逐行跟进 ────────────

BUILD_TIMEOUT_S = 3600     # 总超时: 渲染分钟级, 1 小时保底杀树


def _gen_collage_image(prompt: str, dest: Path, timeout: int = 150) -> None:
    """seedream 生成一张纸拼贴海报 → 移动到 dest(项目 input/collage/)。
    arkcli 必须 cmd /c 调用(npm shim); 尺寸 1920x1920(Ark 最低像素门槛), 模板端 cover 裁切。
    生成失败抛 RuntimeError(调用方回退无图版式)。"""
    import shutil
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run(
            ["cmd", "/c", "arkcli", "+gen", "--modality", "image",
             "--model", "doubao-seedream-5.0-lite", "--size", "1920x1920", prompt],
            cwd=tmp, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout)
        out = (proc.stdout or "") + (proc.stderr or "")
        m = re.search(r'"local_path"\s*:\s*"([^"]+)"', out)
        if proc.returncode != 0 or not m:
            raise RuntimeError((out.strip() or "arkcli 无输出")[:200])
        src = Path(m.group(1).replace("\\\\", "\\"))
        if not src.is_file():
            raise RuntimeError("arkcli 报告生成但文件不存在")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))


def _fill_collage_images(project_id: str, story: dict, warnings: list) -> None:
    """paper-board 场景的拼贴图补齐(幂等: 已存在跳过, 失败场景回退无图)。仅 CLI 进程调用。"""
    from . import vmake                     # 局部导入: 与 run_build_cli 同纪律
    scenes = [s for s in story.get("scenes", [])
              if isinstance(s, dict) and s.get("template") == "paper-board"
              and isinstance(s.get("data"), dict) and s["data"].get("image_prompt")]
    todo = [s for s in scenes
            if not (vmake.VIDEOS_DIR / project_id / s["data"]["image"]).is_file()]
    if not scenes:
        return
    total = len(todo)
    for i, s in enumerate(todo):
        tick("build", "collage", 22 + int(26 * i / max(total, 1)),
             f"生成纸拼贴图 {i + 1}/{total}…(约 40 秒/张)")
        dest = vmake.VIDEOS_DIR / project_id / s["data"]["image"]
        try:
            _gen_collage_image(s["data"]["image_prompt"], dest)
        except Exception as e:
            s["data"]["image"] = None
            warnings.append(f"场景 {s.get('id')} 拼贴图生成失败, 已回退无图版式: {str(e)[:80]}")
    # 有回退时把 story.json 刷写回项目目录(模板据 image=null 走打字机大字)
    if any(s["data"].get("image") is None for s in todo):
        story_path = vmake.VIDEOS_DIR / project_id / "story.json"
        try:
            story_path.write_text(json.dumps(story, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass


def run_build_cli(args) -> int:
    """CLI 子进程入口：读 build.request → vmake 转换建项目 → 渲染跟进。

    进度映射：convert 5→15% / create 20% / prepare 25% / tts 30→60% /
    render 65% → 95% / done 100%。全部构建输出原文追加写
    data/workbench/video_builds/<project_id>.log（前端「查看日志」读同一文件）。
    """
    from . import vmake
    request = dict((load_jobs().get("build") or {}).get("request") or {})
    if not request:
        print(json.dumps({"error": "no_request"}, ensure_ascii=False))
        return 4
    project_id = str(request.get("project_id") or "")
    if request.get("make_id"):
        return _run_make_build_cli(request)
    mode = str(request.get("mode") or "build")
    script = request.get("script") if isinstance(request.get("script"), dict) else {}
    settings = request.get("settings") if isinstance(request.get("settings"), dict) else {}
    hook_index = request.get("hook_index")
    report, code, hint = {}, 3, ""
    try:
        tick("build", "convert", 5, "口播脚本转换为分镜…")
        story, warnings = vmake.script_to_story(script, settings, hook_index=hook_index)
        warnings = [str(w) for w in warnings]
        tick("build", "convert", 15, f"分镜就绪（{len(story['scenes'])} 场）")
        tick("build", "create", 20, "创建项目目录…")
        vmake.create_project(project_id, story, request)
        _fill_collage_images(project_id, story, warnings)   # paper-board 场景生图(幂等, 失败回退无图)
        cmd = ["node", "scripts/build.mjs", project_id] \
            + (["--estimate"] if mode == "estimate" else [])
        BUILD_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = BUILD_LOG_DIR / f"{project_id}.log"
        timeout_s = BUILD_TIMEOUT_S * (2 if vmake.normalize_fps(settings.get("fps")) == 60 else 1)
        code, hint = _run_build_process(cmd, project_id, log_path, timeout_s)
        # 收尾探测产物
        out_dir = vmake.VIDEOS_DIR / project_id / "out"
        mp4s = sorted(p.name for p in out_dir.glob("*.mp4")) if out_dir.is_dir() else []
        verify_warnings = []
        verify_file = out_dir / "verify.json"
        if verify_file.is_file():
            try:
                verify_warnings = [str(w) for w in
                                   (json.loads(verify_file.read_text(encoding="utf-8"))
                                    .get("warnings") or [])]
            except Exception:
                pass
        result = {"project_id": project_id,
                  "output": f"out/{mp4s[0]}" if mp4s else "",
                  "warnings": warnings + verify_warnings}
        _set_job_result("build", result)
        report = {"project_id": project_id, "exit": code, "output": result["output"],
                  "warnings": result["warnings"]}
        return code
    except Exception as e:
        code = 3
        report = {"error": type(e).__name__, "hint": str(e)[:200], "project_id": project_id}
        return code
    finally:
        error = str(report.get("error") or "") or (f"exit {code}" if code else "")
        if hint:
            report["hint"] = hint
        finish_job("build", code, error, hint or str(report.get("hint") or ""))
        print(json.dumps(report, ensure_ascii=False))


def _run_make_build_cli(request: dict) -> int:
    """四段式独立接线；旧直传 script/settings 渲染路径保持原样。"""
    from . import vmake
    row = make_get(request.get("make_id"))
    project_id = str(request.get("project_id") or "")
    mode = request.get("mode") or "build"
    report, code, started = {}, 3, False
    try:
        if not row or not row["script"] or not row["script_meta"]["locked"]:
            code = 4
            report = {"error": "script_not_locked" if row else "make_not_found"}
            return code
        if mode == "build" and voice_missing(row):
            code = 4
            report = {"error": "voice_missing", "hint": "、".join(voice_missing(row))}
            return code
        if not _safe_id(project_id):
            code, report = 4, {"error": "bad_project_id"}
            return code
        row.update(status="rendering", project_id=project_id)
        _make_save(row)
        started = True
        provider = next((p for p in (config.load().get("tts") or {}).get("providers", [])
                         if p.get("id") == row["voice"]["profile_id"]), {})
        settings = {k: row["video"].get(k) for k in ("aspect", "fps", "theme", "layout", "enrich")}
        settings.update(title=row["title"], voice=row["voice"]["voice"],
                        tts_provider=provider.get("engine") or "edge")
        warnings, overrides, materials = [], [], []
        for override in row["video"].get("beat_overrides") or []:
            override = dict(override)
            if override.get("method") in ("upload_image", "upload_video"):
                path, _ = asset_find(override.get("asset_id"), row["id"])
                if not path:
                    warnings.append(f"场景 {override.get('beat_id')} 素材缺失，回退模板")
                    continue
                override["file"] = path.name
                materials.append(path)
            overrides.append(override)
        # 先转换并创建目录，再复制素材，最后使用真实 materials_dir 验证覆盖。
        tick("build", "convert", 5, "口播脚本转换为分镜…")
        story, notes = vmake.script_to_story(row["script"], settings, row["video"].get("hook_index"))
        warnings.extend(notes)
        proj = vmake.create_project(project_id, story, {**request, "settings": settings})
        material_dir = proj / "input" / "materials"
        material_dir.mkdir(parents=True, exist_ok=True)
        for path in materials:
            shutil.copy2(path, material_dir / path.name)
        settings.update(beat_overrides=overrides, materials_dir=str(material_dir))
        # 覆盖层复用首次转换的结果，避免 enrich=llm 重复外呼。
        story, notes = vmake.apply_beat_overrides(story, row["script"], settings, [])
        warnings.extend(notes)
        if row["voice"]["voice"]:
            story["meta"]["voice"] = row["voice"]["voice"]
        if provider.get("engine") == "dashscope":
            story["meta"]["tts"] = {"provider": "dashscope", "voice": row["voice"]["voice"]}
        audio_dir = proj / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        manifest = {}
        for scene in story["scenes"]:
            item = row["voice"]["items"].get(scene["id"], {})
            if item.get("hash") != voice_hash(scene["narration"]):
                continue
            path = _voice_file(row["id"], row["voice"]["voice_key"], item.get("file"))
            if path and _safe_id(scene["id"]):
                shutil.copy2(path, audio_dir / f"{scene['id']}.mp3")
                manifest[scene["id"]] = item["hash"]
        _atomic_json(audio_dir / "manifest.json", manifest)
        _atomic_json(proj / "story.json", story)
        project = json.loads((proj / "project.json").read_text(encoding="utf-8"))
        project["settings"] = settings
        _atomic_json(proj / "project.json", project)
        _fill_collage_images(project_id, story, warnings)
        cmd = ["node", "scripts/build.mjs", project_id] + (["--estimate"] if mode == "estimate" else [])
        logs = config.DATA_DIR / "video_builds"
        logs.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        if provider.get("engine") == "dashscope":
            if provider.get("api_key"):
                env["DASHSCOPE_API_KEY"] = provider["api_key"]
            if provider.get("base_url"):
                env["DASHSCOPE_BASE_URL"] = provider["base_url"]
        timeout = BUILD_TIMEOUT_S * (2 if vmake.normalize_fps(settings.get("fps")) == 60 else 1)
        code, hint = _run_build_process(cmd, project_id, logs / f"{project_id}.log", timeout, env=env)
        mp4s = sorted((proj / "out").glob("*.mp4"))
        try:
            verify = json.loads((proj / "out" / "verify.json").read_text(encoding="utf-8"))
            warnings.extend(str(w) for w in verify.get("warnings", []))
        except (OSError, ValueError, AttributeError):
            pass
        report = {"project_id": project_id, "exit": code, "output": f"out/{mp4s[0].name}" if mp4s else "",
                  "warnings": warnings, "hint": hint}
        _set_job_result("build", report)
        return code
    except Exception as e:
        code = 3
        report = {"error": type(e).__name__, "hint": str(e)[:200], "project_id": project_id}
        return code
    finally:
        if started:
            current = make_get(row["id"])
            if current:
                current.update(status="built" if code == 0 else "voice_ready",
                               last_build={"project_id": project_id, "mode": mode, "at": _now()})
                _make_save(current)
        finish_job("build", code, report.get("error") or (f"exit {code}" if code else ""), report.get("hint", ""))
        print(json.dumps(report, ensure_ascii=False))


def _run_build_process(cmd: list, project_id: str, log_path: Path,
                       timeout_s: int = BUILD_TIMEOUT_S, env=None) -> tuple[int, str]:
    """跑 node build.mjs：逐行读输出跟进进度，原文落日志；总超时杀进程树。"""
    import threading
    hint = ""
    timed_out = threading.Event()

    def _kill_tree():
        timed_out.set()
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True)

    with open(log_path, "a", encoding="utf-8") as log, subprocess.Popen(
            cmd, cwd=str(Path(__file__).resolve().parents[2] / "ai-workflow" / "video"),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", **({"env": env} if env is not None else {})) as proc:
        tick("build", "prepare", 25, "build.mjs 启动…")
        watchdog = threading.Timer(timeout_s, _kill_tree)
        watchdog.start()
        tts_n = 0
        try:
            for line in proc.stdout or []:
                log.write(line)
                log.flush()
                if "合成语音" in line:
                    tts_n += 1
                    tick("build", "tts", min(60, 30 + tts_n * 3), f"合成语音 {tts_n}")
                elif ("开始渲染" in line) or ("Rendering" in line):
                    tick("build", "render", 65, "Remotion 渲染中…")
                elif ("✅" in line) or ("done" in line):
                    tick("build", "render", 95, "渲染收尾…")
            code = proc.wait()
        finally:
            watchdog.cancel()
    if timed_out.is_set():
        code = 3
        hint = f"渲染超时（超过 {timeout_s // 60} 分钟已终止）；可到项目目录清理 out/ 后重试"
    return code, hint


def build_presets() -> dict:
    """制作向导预设：音色清单（按 provider 分组）+ 能力探测（只读，不打印密钥内容）。"""
    from . import vmake
    tts = config.load().get("tts") or config.DEFAULTS["tts"]
    voices = [{"id": v["id"], "name": f"{v['name']}（{p['name']}）", "provider": p["id"],
               "engine": p["engine"]} for p in tts["providers"] if p.get("enabled") for v in p.get("voices", [])]
    swatches = {
        "terminal-dark": ["#070B16", "#76B900", "#4D9FFF"],
        "paper-light": ["#F7F4EC", "#2B2A26", "#C7392B"],
        "ocean-blue": ["#06182E", "#6FD3FF", "#EAF4FF"],
        "vox-collage": ["#E9DCC3", "#3E2F1D", "#B3352C"],
    }
    aspect_labels = {"16:9": "横版", "9:16": "竖版", "1:1": "方形", "4:5": "4:5 竖构图"}
    return {"voices": voices,
            "tts": {"default": tts["default"], "providers": [
                {k: p.get(k) for k in ("id", "name", "engine", "enabled", "voices")} for p in tts["providers"]]},
            "themes": [{"id": k, "name": v, "swatch": swatches[k],
                        **({"aspect_limit": "16:9"} if k == "vox-collage" else {})}
                       for k, v in vmake.THEMES.items()],
            "layouts": [{"id": k, "name": v} for k, v in vmake.LAYOUTS.items()],
            "aspects": [{"id": k, "label": aspect_labels[k], "dims": list(dims)}
                        for k, dims in vmake.ASPECTS.items()],
            "fps_options": [{"id": 30, "label": "30 fps（标准）"},
                            {"id": 60, "label": "60 fps（渲染约 2 倍时长）"}],
            "dashscope_key_ok": vmake.dashscope_key_ok(),
            "collage_ready": shutil_which("arkcli"),
            "llm_ready": bool(_translate_cfg(config.load())),
            "max_chars": 20000}


def shutil_which(cmd: str) -> bool:
    """只读探测外部命令是否在 PATH(arkcli 为 npm shim, shutil.which 走 PATHEXT)。"""
    import shutil
    return shutil.which(cmd) is not None
