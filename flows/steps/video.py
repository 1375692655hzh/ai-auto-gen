"""视频步骤: daily 流程沿用 generator/video; morning-digest 从过稿口播稿出片(零 LLM)。

render_morning_video: 解析 口播稿-{date}.md(人工可能已改, 含 [概括]/[指标]/[背景] 标签行)
→ 模块化 story(EnrichedRowsTpl) → Remotion 出片。
音画一致构造断言: narration(去「第N条,」前缀) == 概括+各行文本拼接(标签不入音)。
"""

import json
import re
import subprocess
import sys
from pathlib import Path

from flows.steps import step

FPS = 30
SPEED = 4.2          # 与 script.py/build.mjs 同口径
LEAD_S = 0.7         # 音频前置静默: 语音开始时动画已展开(与 build.mjs 一致)
ROW_ACCENTS = {"背景": "blue", "进展": "green", "影响": "amber", "展望": "purple",
               "详情": "blue", "指标": "red"}


def _cues(text: str) -> list:
    """口播正文 → 同步字幕轨(按句切, 起止帧按字数比例, +前置静默偏移)。"""
    parts = [p for p in re.split(r"(?<=[。；！？])", text) if p.strip()]
    cues, cum, lead = [], 0, int(LEAD_S * FPS)
    for p in parts:
        start = lead + int(cum / SPEED * FPS)
        cum += len(p)
        cues.append({"t": p, "start": start, "end": lead + int(cum / SPEED * FPS)})
    return cues


@step("render_video")
def render_video(ctx, wf, params):
    """daily 流程: 依赖 assemble 的 daily JSON。with: {estimate: bool}(无声预览)。"""
    import video as video_mod
    out = video_mod.run(date=wf.date, force=True, estimate=bool(params.get("estimate")))
    return {"video_path": str(out)}


@step("render_morning_video")
def render_morning_video(ctx, wf, params):
    """过稿口播稿 md → Remotion 出片(零 LLM)。改稿后 --from video 只重出片。"""
    date = wf.date
    script_p = ctx.get("script_path")
    if not script_p:
        sp = wf.run_dir / f"口播稿-{date}.md"
        script_p = str(sp) if sp.exists() else None
    if not script_p or not Path(script_p).exists():
        sys.exit("视频依赖过稿口播稿: 需先跑 script 步骤(--set with_video=true)")
    md = Path(script_p).read_text(encoding="utf-8")
    intro, outro, blocks = _parse_script_md(md)
    if len(blocks) < 3:
        sys.exit(f"口播稿条目过少({len(blocks)}), 疑似格式损坏")

    from common import GEN_ROOT
    video_root = GEN_ROOT.parent / "video"
    story = _build_story(intro, outro, blocks, date)
    _assert_consistency(story)                       # 音画一致构造断言

    proj_id = f"morning-{date.replace('-', '')}"
    proj_dir = video_root / "videos" / proj_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "story.json").write_text(
        json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
    (proj_dir / "project.json").write_text(
        json.dumps({"id": proj_id, "title": story["meta"]["title"], "status": "reviewed",
                    "created": date, "note": "口播稿已过 flow 审核点, 免 build 门禁"},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"视频项目: video/videos/{proj_id}/story.json ({len(blocks)} 条 + 开场收尾)")
    print(f"视频标题: {story['meta']['title']}")

    r = subprocess.run(["node", "scripts/build.mjs", proj_id], cwd=video_root)
    if r.returncode != 0:
        sys.exit(f"Remotion 出片失败(exit {r.returncode}); 首次使用先在 video/ 下 npm install")
    src = proj_dir / "out" / "final.mp4"
    if not src.exists():
        sys.exit(f"出片产物缺失: {src}")
    out_dir = GEN_ROOT.parent / "autopub" / "videos"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"早报视频-{date}.mp4"
    out.write_bytes(src.read_bytes())
    print(f"早报视频: {out} ({out.stat().st_size // 1024}KB)")
    return {"video_path": str(out), "video_cards": len(blocks)}


def _parse_script_md(md: str):
    """口播稿 md → (intro, outro, [block])。block={"kicker","headline","summary","stat","lines"}。
    人可删段落/改正文/删行; 无标签行则整段进 lines[详情]。"""
    intro, outro, blocks = "", "", []

    def _new_block(kicker, headline):
        blocks.append({"kicker": kicker, "headline": headline,
                       "summary": "", "stat": None, "lines": []})

    zone = None
    for line in md.splitlines():
        m = re.match(r"^## (.+)", line)
        if m:
            head = m.group(1).strip()
            if head == "开场":
                zone = "intro"
            elif head == "收尾":
                zone = "outro"
            else:
                zone = "item"
                kicker, _, headline = head.partition("|")
                _new_block(kicker.strip(), headline.strip())
            continue
        if line.startswith("#") or line.startswith("<!--") or not line.strip():
            continue
        t = line.strip()
        if zone == "intro":
            intro += t
        elif zone == "outro":
            outro += t
        elif zone == "item" and blocks:
            b = blocks[-1]
            lm = re.match(r"^\[([^|\]]+)(?:\|([^\]]+))?\]\s*(.+)$", t)
            if lm:
                label, tail, text = lm.group(1).strip(), lm.group(2), lm.group(3).strip()
                if label == "概括":
                    b["summary"] = text
                elif label == "指标":
                    # [指标] 1188亿美元（贸易逆差） → stat 值+单位+标签
                    sm = re.match(r"^([\d.]+)([^（\s]*)(?:（([^）]*)）)?$", text)
                    b["stat"] = {"value": sm.group(1), "unit": sm.group(2) or "",
                                 "label": sm.group(3) or ""} if sm else None
                else:
                    b["lines"].append({"label": label, "text": text})
            else:
                # 无标签行: 并入上一行或作为详情行
                if b["lines"] and not b["summary"] and len(b["lines"]) == 1:
                    b["lines"][0]["text"] += t
                elif b["summary"] and not b["lines"]:
                    b["summary"] += t
                elif b["lines"]:
                    b["lines"][-1]["text"] += t
                else:
                    b["lines"].append({"label": "详情", "text": t})
    return intro, outro, [b for b in blocks if b["summary"] or b["lines"]]


def _build_story(intro, outro, blocks, date: str) -> dict:
    def _r(t, b=False):
        return [{"t": t, **({"b": True} if b else {})}]

    vt = f"{_cut(blocks[0]['headline'], 22)}【财经早报】"
    scenes = [{
        "id": "opening", "template": "title",
        "narration": intro, "caption": "", "captions": _cues(intro),
        "data": {"kicker": "财经早报", "kickerColor": "blue",
                 "titlePre": vt.replace("【财经早报】", ""),
                 "subtitle1": _r(f"今日 {len(blocks)} 条要闻", True),
                 "subtitle2": _r(f"重点关注:{' / '.join(b['headline'] for b in blocks[:3])}")},
    }]
    for i, b in enumerate(blocks, 1):
        rows = []
        for l in b["lines"]:
            rows.append({"accent": ROW_ACCENTS.get(l["label"], "blue"),
                         "label": _r(l["label"], True), "body": _r(l["text"])})
        narr = f"第{i}条,{b['summary']}{''.join(l['text'] for l in b['lines'])}"
        # 动画全部在前置静默(0.7s=21帧)内展开: 语音起播时画面已就位
        ent = {"summary": 4, "stat": 6}
        for j in range(len(rows)):
            ent[f"row{j}"] = 7 + int(j * 1.2)
        ent["tags"] = 9 + int(len(rows) * 1.2)
        scenes.append({
            "id": f"news-{i:02d}", "template": "rows",
            "narration": narr,
            "caption": "",
            "captions": _cues(narr),
            "data": {"kicker": b["kicker"], "headline": _r(b["headline"], True),
                     "summary": _r(b["summary"]) if b["summary"] else None,
                     "stat": b["stat"], "tags": b.get("sectors") or [],
                     "rows": rows, "entrances": ent},
        })
    scenes.append({
        "id": "closing", "template": "conclusion",
        "narration": outro, "caption": "", "captions": _cues(outro),
        "data": {"kicker": "免责声明",
                 "statements": [{"who": "风险提示", "body": _r("内容基于公开信息整理, 不构成任何投资建议")}],
                 "tagline": _r("每天几分钟, 看懂财经", True)},
    })
    return {"meta": {"title": vt, "voice": "zh-CN-XiaoxiaoNeural",
                     "fps": FPS, "width": 1920, "height": 1080, "padSeconds": 0.8},
            "scenes": scenes}


def _assert_consistency(story: dict):
    """音画一致 + 板块词卫兵(构造性保证, 违反即停)。"""
    for s in story["scenes"]:
        if s["template"] != "rows":
            continue
        d = s["data"]
        shown = "".join(x["t"] for x in (d.get("summary") or [])) + \
                "".join(x["t"] for row in d["rows"] for x in row["body"])
        prefix = f"第{s['id'].split('-')[1].lstrip('0')}条,"
        assert s["narration"].replace(prefix, "", 1) == shown, f"{s['id']} 音画不一致"
        k = d["kicker"]
        assert not re.search(r"利好|利空|承压|看多|看空|AI解读|AI整理|AI生成|AI播报", k), \
            f"{s['id']} kicker 违规: {k}"


def _cut(text: str, limit: int) -> str:
    t = text.strip()
    if len(t) <= limit:
        return t
    cut = t[:limit]
    for sep in ("。", "；", "，"):
        i = cut.rfind(sep)
        if i > limit // 2:
            return cut[:i]
    return cut.rstrip("，,、")
