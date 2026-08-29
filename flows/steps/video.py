"""视频步骤: daily 流程沿用 generator/video; morning-digest 从过稿口播稿出片(零 LLM)。

render_morning_video: 解析 口播稿-{date}.md(人工可能已改) → 复检机检 → story.json
→ Remotion 出片。音画一致构造保证: narration(去「第N条,」前缀) == rows body 逐字相等。
"""

import json
import re
import subprocess
import sys
from pathlib import Path

from flows.steps import step


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
    """口播稿 md → (intro, outro, [(kicker, headline, text)])。人可删段落/改正文。"""
    intro, outro, blocks = "", "", []
    zone, headline = None, ""
    for line in md.splitlines():
        m = re.match(r"^## (.+)", line)
        if m:
            head = m.group(1).strip()
            if head == "开场":
                zone, headline = "intro", ""
            elif head == "收尾":
                zone, headline = "outro", ""
            else:
                zone = "item"
                kicker, _, headline = head.partition("|")
                blocks.append([kicker.strip(), headline.strip(), ""])
            continue
        if line.startswith("#") or line.startswith("<!--"):
            continue
        t = line.strip()
        if not t:
            continue
        if zone == "intro":
            intro = (intro + t) if not intro else intro + t
        elif zone == "outro":
            outro = (outro or "") + t
        elif zone == "item" and blocks:
            blocks[-1][2] = (blocks[-1][2] + t) if blocks[-1][2] else t
    return intro, outro, [tuple(b) for b in blocks if b[2]]


def _build_story(intro, outro, blocks, date: str) -> dict:
    def _r(t, b=False):
        return [{"t": t, **({"b": True} if b else {})}]

    first_headline = blocks[0][1]
    vt = f"{_cut(first_headline, 22)}【财经早报】"
    scenes = [{
        "id": "opening", "template": "title",
        "narration": intro, "caption": vt,
        "data": {"kicker": "财经早报", "kickerColor": "blue",
                 "titlePre": vt.replace("【财经早报】", ""),
                 "subtitle1": _r(f"今日 {len(blocks)} 条要闻", True),
                 "subtitle2": _r(f"重点关注:{' / '.join(b[1] for b in blocks[:3])}")},
    }]
    for i, (kicker, headline, text) in enumerate(blocks, 1):
        scenes.append({
            "id": f"news-{i:02d}", "template": "rows",
            "narration": f"第{i}条,{text}",       # 前缀不入画面
            "caption": "",                        # 详情即字幕, 关底部条
            "data": {"kicker": kicker,
                     "headline": _r(headline, True),
                     "rows": [{"accent": "blue", "label": _r("详情", True), "body": _r(text)}]},
        })
    scenes.append({
        "id": "closing", "template": "conclusion",
        "narration": outro, "caption": "关注不迷路",
        "data": {"kicker": "免责声明",
                 "statements": [{"who": "风险提示", "body": _r("内容基于公开信息整理, 不构成任何投资建议")}],
                 "tagline": _r("每天几分钟, 看懂财经", True)},
    })
    return {"meta": {"title": vt, "voice": "zh-CN-XiaoxiaoNeural",
                     "fps": 30, "width": 1920, "height": 1080, "padSeconds": 0.8},
            "scenes": scenes}


def _assert_consistency(story: dict):
    """音画一致 + 板块词卫兵(构造性保证, 违反即停)。"""
    for s in story["scenes"]:
        if s["template"] != "rows":
            continue
        body = "".join(x["t"] for row in s["data"]["rows"] for x in row["body"])
        prefix = f"第{s['id'].split('-')[1].lstrip('0')}条,"
        assert s["narration"].replace(prefix, "", 1) == body, f"{s['id']} 音画不一致"
        k = s["data"]["kicker"]
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
