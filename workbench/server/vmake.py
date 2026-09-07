"""wb-video-script/v1 口播脚本 → Remotion story.json 转换器（纯函数为主）。

职责：把视频工坊生成的口播脚本确定性转成 story.json（旁白逐字冻结，模板/on_screen
按角色确定性映射）；可选 LLM 编排增强（settings.enrich=="llm" 且翻译模型已配），
LLM 输出不过闸门（逐场景 narration 与输入逐字一致 + 模板白名单）即整单回退骨架。
架构红线：本模块只被 CLI 子进程调用（vstudio.run_build_cli），app.py 端点不得直呼；
_llm_compose_scenes 是本文件唯一外呼点。
"""

import json
import re
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]          # workbench/server/vmake.py → 仓库根
VIDEO_DIR = REPO / "ai-workflow" / "video"
VIDEOS_DIR = VIDEO_DIR / "videos"

FPS = 30
PAD_SECONDS = 0.8
DIMS = {"horizontal": (1920, 1080), "vertical": (1080, 1920)}
DEFAULT_EDGE_VOICE = "zh-CN-XiaoxiaoNeural"
DEFAULT_DASHSCOPE_VOICE = "longanlufeng"

H_TEMPLATE_WHITELIST = ("title", "event", "bars", "compare", "cards", "rows",
                        "stacked", "versus", "checklist", "conclusion")
V_TEMPLATE_WHITELIST = ("vtitle", "vstat", "vpoints")
TEMPLATE_WHITELIST = H_TEMPLATE_WHITELIST + V_TEMPLATE_WHITELIST

# 横版：role → 模板 确定性映射
H_TEMPLATE_BY_ROLE = {"hook": "title", "setup": "event", "move": "stacked",
                      "gives": "cards", "payoff": "rows", "cta": "conclusion"}
# 竖版：hook→vtitle，中段 vstat/vpoints 交替，cta→vpoints
V_TEMPLATE_MIDDLE = ("vstat", "vpoints")

STYLE_PACKS = {
    "auto": "AI 自动（LLM 按内容选型）",
    "data-dense": "数据密集（move/gives 优先 bars/compare/rows 类数据版式）",
    "quote-big": "金句大字（payoff/cta 优先 stacked/versus 大字对照，弱化罗列）",
}
H_TEMPLATE_BY_PACK = {
    "data-dense": {"hook": "title", "setup": "event", "move": "bars",
                   "gives": "rows", "payoff": "compare", "cta": "conclusion"},
    "quote-big": {"hook": "title", "setup": "event", "move": "stacked",
                  "gives": "versus", "payoff": "stacked", "cta": "conclusion"},
}


def normalize_style_pack(value) -> str:
    return value if isinstance(value, str) and value in STYLE_PACKS else "auto"


def dashscope_key_ok() -> bool:
    """只读探测 ai-workflow/video/.env 是否配置了非空 DASHSCOPE_API_KEY（不回显内容）。"""
    env = VIDEO_DIR / ".env"
    try:
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"^\s*DASHSCOPE_API_KEY\s*=\s*(.+?)\s*$", line)
            if m and m.group(1).strip("\"'"):
                return True
    except Exception:
        pass
    return False


def _rich(s) -> list:
    """字符串 → 富文本 [{t}]（None/空 → 空数组，模板侧 Rich(parts=[]) 安全）。"""
    s = str(s or "").strip()
    return [{"t": s}] if s else []


def _on_screen(beat: dict) -> list:
    out = []
    for x in (beat.get("on_screen") or []):
        s = str(x or "").strip()
        if s:
            out.append(s)
    return out


def _fallback_head(beat: dict, narration: str) -> str:
    """on_screen 缺失时的兜底文案：字幕 → 旁白截断。"""
    s = str(beat.get("subtitle") or "").strip()
    return s or (narration or "").strip()[:14]


def _build_meta(script: dict, settings: dict, fmt: str) -> dict:
    width, height = DIMS.get(fmt, DIMS["horizontal"])
    title = str(settings.get("title") or script.get("title") or "未命名视频").strip()[:30]
    provider = str(settings.get("tts_provider") or "edge")
    use_dash = provider == "dashscope" and dashscope_key_ok()
    if use_dash:
        voice = settings.get("voice") or DEFAULT_DASHSCOPE_VOICE
        meta_voice = voice if str(voice).startswith("longan") else DEFAULT_DASHSCOPE_VOICE
        tts = {"provider": "dashscope", "voice": meta_voice}
    else:
        # edge 引擎：只认 zh-CN-* 音色，dashscope 音色名落进来会整批失败，兜底回默认
        voice = settings.get("voice") or DEFAULT_EDGE_VOICE
        meta_voice = voice if str(voice).startswith("zh-CN") else DEFAULT_EDGE_VOICE
        tts = None
    meta = {"title": title, "voice": meta_voice, "fps": FPS,
            "width": width, "height": height, "format": fmt,
            "padSeconds": PAD_SECONDS}
    if tts:
        meta["tts"] = tts
    return meta


def _data_for(template: str, beat: dict, narration: str, script: dict,
              fmt: str) -> dict:
    """on_screen → 模板 data 的确定性派生。"""
    os_items = _on_screen(beat)
    head = _fallback_head(beat, narration)
    cta = script.get("cta") if isinstance(script.get("cta"), dict) else {}
    cta_line = str(cta.get("line") or "").strip() or narration
    if fmt == "vertical":
        if template == "vtitle":
            return {"title": _rich(os_items[0] if os_items else head or script.get("title")),
                    **({"sub": _rich(os_items[1])} if len(os_items) > 1 else {})}
        if template == "vstat":
            digits = [t for t in os_items if re.search(r"\d", t)]
            value = digits[0] if digits else (os_items[0] if os_items else head)
            rest = [t for t in os_items if t != value]
            label = rest[0] if rest else head
            return {"value": value, "label": _rich(label)}
        # vpoints（含 cta 场）：要点来自 on_screen，CTA 场保底把 CTA 原句收进最后一条
        pts = [{"text": _rich(t)} for t in os_items[:4]]
        if template == "vpoints" and not pts:
            pts = [{"text": _rich(head)}]
        if beat.get("role") == "cta":
            pts = (pts or [])[:3]
            pts.append({"text": _rich(cta_line)})
        return {"points": pts}
    if template == "title":
        data = {}
        if os_items:
            data["subtitle1"] = _rich(os_items[0])
            if len(os_items) > 1:
                data["subtitle2"] = _rich(os_items[1])
        else:
            data["subtitle1"] = _rich(head)
        return data
    if template == "event":
        return {"headline": _rich(os_items[0] if os_items else head),
                "chips": os_items[1:7]}
    if template == "bars":
        bars = []
        for item in os_items[:5]:
            number = re.search(r"\d+(?:\.\d+)?", item)
            name = (item[:number.start()] + item[number.end():]).strip() if number else item
            bars.append({"name": name or item,
                         "pct": float(number.group()) if number else 50})
        return {"headline": _rich(head), "bars": bars}
    if template in ("compare", "versus"):
        middle = len(os_items) // 2
        panels = []
        for items, fallback in ((os_items[:middle], "观点A"), (os_items[middle:], "观点B")):
            panels.append({"title": _rich(items[0] if items else fallback),
                           "items": [_rich(x) for x in items[1:]]})
        left, right = ("left", "right") if template == "compare" else ("bull", "bear")
        return {"headline": _rich(head), left: panels[0], right: panels[1]}
    if template == "stacked":
        panels = [{"title": _rich(t), "body": _rich(os_items[i + 2] if len(os_items) > i + 2 else "")}
                  for i, t in enumerate(os_items[1:3])]
        if not panels:
            panels = [{"title": _rich("要点"), "body": _rich(head)}]
        return {"headline": _rich(os_items[0] if os_items else head), "panels": panels}
    if template == "cards":
        cards = [{"icon": "◆", "title": t} for t in os_items[:4]]
        if not cards:
            cards = [{"icon": "◆", "title": head}]
        return {"headline": _rich(head), "cards": cards}
    if template == "rows":
        rows = [{"label": _rich(t), "body": _rich("")} for t in os_items[:6]]
        if not rows:
            rows = [{"label": _rich(head), "body": _rich("")}]
        return {"headline": _rich(head), "rows": rows}
    if template == "conclusion":
        return {"statements": [], "tagline": _rich(cta_line)}
    # 其余横版模板不在确定性映射里（仅 LLM 白名单可达），保底给 headline 防崩
    return {"headline": _rich(head)}


def _template_for(beat: dict, middle_i: int, fmt: str, pack: str = "auto") -> str:
    role = str(beat.get("role") or "")
    if fmt == "vertical":
        if role == "hook":
            return "vtitle"
        if role == "cta":
            return "vpoints"
        return V_TEMPLATE_MIDDLE[middle_i % 2]
    return H_TEMPLATE_BY_PACK.get(pack, H_TEMPLATE_BY_ROLE).get(role, "event")


def _deterministic_story(script: dict, settings: dict, beats: list,
                         narrations: list, fmt: str, pack: str = "auto") -> tuple:
    scenes = []
    warnings = []
    for i, beat in enumerate(beats):
        template = _template_for(beat, max(0, i - 1), fmt, pack)   # 中段从 vstat 起交替
        if fmt == "vertical" and template == "vstat" and not any(
                re.search(r"\d", item) for item in _on_screen(beat)):
            template = "vpoints"
            warnings.append(f"场景{i + 1}无数字锚点已改用要点版式")
        narration = narrations[i]
        scenes.append({
            "id": str(beat.get("id") or f"b{i + 1}"),
            "template": template,
            "narration": narration,
            "caption": str(beat.get("subtitle") or "").strip() or narration,
            "data": _data_for(template, beat, narration, script, fmt),
        })
    return {"meta": _build_meta(script, settings, fmt), "scenes": scenes}, warnings


COMPOSE_SYSTEM = r"""你是财经短视频分镜排版师。只输出一个 ```json 代码块，不要解释。
任务：为给定 beats 逐场选择模板并设计 data。铁律：
1. scenes 数量必须等于 beats 数量，顺序一一对应。
2. 每个场景的 narration 必须【逐字复制】输入 beat 的 narration，一个字都不能改。
3. template 只能用白名单：横版 title/event/bars/compare/cards/rows/stacked/versus/checklist/conclusion；
   竖版 vtitle/vstat/vpoints。vertical 项目只允许竖版模板。
4. data 最小 schema：
   title: {kicker?, titlePre?, ticker?, titlePost?, subtitle1?, subtitle2?}
   event: {headline, chips?, stat?{value,decimals?,prefix?,suffix?,label}}
   bars: {headline, bars:[{name,pct,tag?}]}
   compare: {headline, left:Panel, right:Panel, arrow?}   Panel={accent?,title,sub?,items?,chips?,footer?}
   cards: {headline, cards:[{icon?,title}]}               （2-4 张）
   rows: {headline, rows:[{accent?,label,body}]}
   stacked: {headline, transform?{from,to}, panels:[{accent?,title,body}]}
   versus: {headline, bull:Panel, bear:Panel}
   checklist: {headline, items:[{tag,body}]}
   conclusion: {statements:[{who,color?,body}], tagline}
   vtitle: {title, sub?}
   vstat: {value:"可ticker数字串如 3.2% 或 5800亿", label, source?}
   vpoints: {points:[{text}]}                             （2-4 条）
5. 富文本一律 [{t:"文字"}?]，可加 c(red/green/amber/blue/purple/nvidia/sub) 与 b:true。
6. 版式纪律：一场最多两种语义色；元素随旁白分批出现勿一次堆屏；标题 ≤18 字；
   禁紫蓝渐变/emoji/连续三场同版式；相邻场次更换空间组织（分栏/堆叠/中心舞台轮换）。
输出形状：{"scenes":[{"id":"与beat一致","template":"模板名","narration":"逐字旁白",
"caption":"一句话字幕","data":{…}}]}"""


def _llm_compose_scenes(script: dict, settings: dict, beats: list,
                        narrations: list, fmt: str, pack: str = "auto"):
    """LLM 编排增强；返回 (story|None, warnings)。任何闸门不过 → (None, 回退警告)。"""
    warnings = []
    from . import config, vstudio           # 延迟导入: 纯函数场景不背 LLM 依赖
    translate = vstudio._translate_cfg(config.load())
    if not translate:
        return None, ["AI 编排跳过：翻译模型未配置，使用确定性版式"]
    base, key, model = translate
    whitelist = "、".join(H_TEMPLATE_WHITELIST) + "（横版）/ " + "、".join(V_TEMPLATE_WHITELIST) + "（竖版）"
    beats_payload = [{"id": b.get("id"), "role": b.get("role"),
                      "narration": narrations[i],
                      "on_screen": _on_screen(b),
                      "visual_hint": str(b.get("visual_hint") or "")[:80]}
                     for i, b in enumerate(beats)]
    user = (f"项目画幅：{fmt}（模板白名单：{whitelist}）\n"
            f"脚本标题：{script.get('title') or ''}\n"
            f"beats 全量（narration 逐字冻结，visual_hint 仅作画面参考）：\n"
            + json.dumps(beats_payload, ensure_ascii=False))
    if pack == "data-dense":
        user += "\n视觉风格包：数据密集——中段 move/gives 场景优先选用 bars/compare/rows 类数据版式。"
    elif pack == "quote-big":
        user += "\n视觉风格包：金句大字——payoff/cta 场景优先 stacked/versus 大字对照，弱化罗列版式。"
    raw = vstudio.chat_completions(base, key, model,
                                   [{"role": "system", "content": COMPOSE_SYSTEM},
                                    {"role": "user", "content": user}], 0.3, 6000, 180)
    if not raw:
        return None, ["AI 编排回退：模型未返回内容，使用确定性版式"]
    parsed, _ = vstudio._parse_json_reply(raw)
    scenes = parsed.get("scenes") if isinstance(parsed, dict) else None
    if not isinstance(scenes, list) or len(scenes) != len(beats):
        return None, ["AI 编排回退：scenes 缺失或数量与 beats 不一致，使用确定性版式"]
    whitelist_fmt = V_TEMPLATE_WHITELIST if fmt == "vertical" else H_TEMPLATE_WHITELIST
    for i, sc in enumerate(scenes):
        sc = sc if isinstance(sc, dict) else {}
        if str(sc.get("narration") or "") != narrations[i]:
            return None, [f"AI 编排回退：场景 {i + 1} narration 被改写（要求逐字冻结），使用确定性版式"]
        if sc.get("template") not in whitelist_fmt:
            return None, [f"AI 编排回退：场景 {i + 1} 模板 {sc.get('template')!r} 不在白名单，使用确定性版式"]
    meta = _build_meta(script, settings, fmt)
    out_scenes = []
    for i, sc in enumerate(scenes):
        data = sc.get("data") if isinstance(sc.get("data"), dict) else {}
        out_scenes.append({
            "id": str(beats[i].get("id") or f"b{i + 1}"),   # id 强制回写 beat id，防重复/缺失
            "template": sc.get("template"),
            "narration": narrations[i],
            "caption": str(sc.get("caption") or "").strip() or narrations[i],
            "data": data,
        })
    warnings.append("AI 编排通过校验闸门（narration 逐字一致 + 模板白名单）")
    return {"meta": meta, "scenes": out_scenes}, warnings


def script_to_story(script, settings, hook_index=None):
    """wb-video-script/v1 → story.json。返回 (story, warnings)。

    - 旁白逐字冻结：narration ← beat.narration；hook 场在给出 hook_index 时用
      hook.variants[hook_index].text 覆盖（用户在预览页亲手选的变体）。
    - settings: {format?, voice?, tts_provider?, enrich?, title?}
    """
    warnings = []
    script = script if isinstance(script, dict) else {}
    settings = settings if isinstance(settings, dict) else {}
    beats = [b for b in (script.get("beats") or []) if isinstance(b, dict)]
    if not beats:
        raise ValueError("script.beats 为空，无法转换为 story")
    fmt = str(settings.get("format") or script.get("format") or "horizontal")
    if fmt not in DIMS:
        fmt = "horizontal"
    pack = normalize_style_pack(settings.get("style_pack"))
    if fmt == "vertical" and pack != "auto":
        warnings.append("竖版不支持风格包，已忽略")
        pack = "auto"
    # hook 变体覆盖
    hook = script.get("hook") if isinstance(script.get("hook"), dict) else {}
    variants = hook.get("variants") if isinstance(hook.get("variants"), list) else []
    hook_text = ""
    if isinstance(hook_index, int) and 0 <= hook_index < len(variants):
        v = variants[hook_index]
        hook_text = str((v.get("text") if isinstance(v, dict) else v) or "").strip()
    narrations = []
    for b in beats:
        n = str(b.get("narration") or "")
        if b.get("role") == "hook" and hook_text:
            n = hook_text
        narrations.append(n)
    if hook_text:
        warnings.append(f"hook 已切换为变体 #{hook_index + 1}")
    if settings.get("enrich") == "llm":
        story, llm_warnings = _llm_compose_scenes(script, settings, beats, narrations, fmt, pack)
        warnings.extend(llm_warnings)
        if story is not None:
            return story, warnings
    story, deterministic_warnings = _deterministic_story(script, settings, beats, narrations, fmt, pack)
    warnings.extend(deterministic_warnings)
    return story, warnings


def create_project(project_id, story, request=None) -> Path:
    """落盘 videos/<id>/ 项目目录；只能被 CLI 子进程调用（vstudio.run_build_cli）。"""
    request = request if isinstance(request, dict) else {}
    if not re.fullmatch(r"[\w\-]+", str(project_id)):
        raise ValueError(f"非法项目 id: {project_id!r}")
    proj = (VIDEOS_DIR / project_id).resolve()
    if VIDEOS_DIR.resolve() not in proj.parents:
        raise ValueError(f"项目目录越界: {proj}")
    (proj / "input").mkdir(parents=True, exist_ok=True)
    (proj / "out").mkdir(exist_ok=True)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    day = now[:10]
    project = {"id": project_id,
               "title": (story.get("meta") or {}).get("title") or project_id,
               "status": "reviewed",
               "note": "向导确认即审核（workbench 创建）；draft=待审 reviewed=可制作 built=已出片",
               "created": day, "date": day,
               "origin": "workbench",
               "settings": request.get("settings") if isinstance(request.get("settings"), dict) else {}}
    (proj / "project.json").write_text(
        json.dumps(project, ensure_ascii=False, indent="\t"), encoding="utf-8")
    (proj / "story.json").write_text(
        json.dumps(story, ensure_ascii=False, indent="\t"), encoding="utf-8")
    text = str(request.get("text") or "")
    if text.strip():
        (proj / "input" / "article.md").write_text(text, encoding="utf-8")
    return proj
