"""视频步骤:调 generator 的 video 管线出片(TTS+渲染+封面)。"""

import sys
from pathlib import Path

from flows.steps import step


@step("render_video")
def render_video(ctx, wf, params):
    """依赖 assemble 的 daily JSON。with: {estimate: bool}(无声预览)。"""
    import video as video_mod
    out = video_mod.run(date=wf.date, force=True, estimate=bool(params.get("estimate")))
    return {"video_path": str(out)}


@step("render_morning_video")
def render_morning_video(ctx, wf, params):
    """morning-digest: image-digest 卡片 → 口播 story → Remotion 出片。
    with: {top: 14}。口播稿 = 长图同款精简卡(title+point+解读), 每条约10秒, ≈3分钟。
    女声 zh-CN-XiaoxiaoNeural(edge 引擎免费)。产物 autopub/videos/早报视频-{date}.mp4。"""
    import json
    import subprocess
    date = wf.date
    digest_p = ctx.get("image_digest_path")
    if not digest_p or not Path(digest_p).exists():
        sys.exit("视频依赖长图存档 image-digest JSON: 需 --set with_image=true")
    payload = json.loads(Path(digest_p).read_text(encoding="utf-8"))
    cards = (payload.get("cards") or [])[: int(params.get("top", 14))]
    if len(cards) < 4:
        sys.exit(f"卡片过少({len(cards)}), 不值得出片")

    from common import GEN_ROOT
    video_root = GEN_ROOT.parent / "video"
    if not (video_root / "scripts" / "build.mjs").exists():
        sys.exit(f"缺少 Remotion 项目: {video_root}")

    story = _build_story(cards, date)
    proj_id = f"morning-{date.replace('-', '')}"
    proj_dir = video_root / "videos" / proj_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "story.json").write_text(
        json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
    (proj_dir / "project.json").write_text(
        json.dumps({"id": proj_id, "title": story["meta"]["title"], "status": "draft",
                    "created": date, "note": "由 morning-digest 自动生成"},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"视频项目: video/videos/{proj_id}/story.json ({len(cards)} 条 + 开场收尾)")
    print(f"视频标题: {story['meta']['title']}")

    r = subprocess.run(["node", "scripts/build.mjs", proj_id, "--force"],
                       cwd=video_root)
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
    return {"video_path": str(out), "video_cards": len(cards)}


def _narr_direction(c: dict) -> str:
    """解读行 → 口播句(中性零信息跳过)。"""
    sectors = c.get("sectors") or []
    direction = c.get("direction") or ""
    if not sectors or direction in ("", "中性"):
        return ""
    d = {"利好": "利好", "利空": "利空", "承压": "短期承压", "关注": "值得关注"}.get(direction, direction)
    return f"板块上看,{d}{'、'.join(sectors[:3])}。"


def _build_story(cards: list, date: str) -> dict:
    from datetime import datetime
    try:
        d = datetime.strptime(date, "%Y-%m-%d")
        date_cn = f"{d.month}月{d.day}日"
    except ValueError:
        date_cn = date
    vt = f"{cards[0]['title'][:24]}【财经早报】"
    n = len(cards)

    def _r(t, b=False):
        return [{"t": t, **({"b": True} if b else {})}]

    scenes = [{
        "id": "opening", "template": "title",
        "narration": f"早上好,今天是{date_cn},财经早报,{n}条要闻。今天重点事件:{cards[0]['title']}。",
        "caption": vt,
        "data": {"kicker": "财经早报", "kickerColor": "blue",
                 "titlePre": vt.replace("【财经早报】", ""),
                 "subtitle1": _r(f"今日 {n} 条要闻", True),
                 "subtitle2": _r(f"重点关注:{' / '.join(c['title'] for c in cards[:3])}")},
    }]
    for i, c in enumerate(cards, 1):
        pill = c.get("pill") or ""
        if pill in ("-", ""):
            pill = c.get("cat", "财经")
        narr = f"第{i}条,{c['title']}。{c['point']}。{_narr_direction(c)}"
        scenes.append({
            "id": f"news-{i:02d}", "template": "rows",
            "narration": narr, "caption": c["title"],
            "data": {"kicker": f"{i:02d} · {pill}",
                     "headline": _r(c["title"], True),
                     "rows": [{"accent": "blue", "label": _r("详情", True), "body": _r(c["point"])}],
                     **({"footnote": [{"t": f"AI解读|{c['direction']}:{'/'.join(c['sectors'][:3])}", "b": True}]}
                        if c.get("direction") and c["direction"] != "中性" and c.get("sectors") else {})},
        })
    scenes.append({
        "id": "closing", "template": "conclusion",
        "narration": "以上就是今天的财经早报,内容基于公开信息整理,不构成投资建议。关注我,每天几分钟看懂财经。",
        "caption": "关注不迷路",
        "data": {"kicker": "免责声明",
                 "statements": [{"who": "风险提示", "body": _r("内容基于公开信息由 AI 整理,不构成任何投资建议")}],
                 "tagline": _r("每天几分钟,看懂财经", True)},
    })
    return {"meta": {"title": vt, "voice": "zh-CN-XiaoxiaoNeural",
                     "fps": 30, "width": 1920, "height": 1080, "padSeconds": 0.8},
            "scenes": scenes}
