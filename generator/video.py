"""日报 → 视频桥:把 generator 的 daily JSON 转成 video/(Remotion)的 story.json,并一键制作。

场景映射:
  开场   → title 模板    (日期 + 今日 N 条 + 三大看点)
  逐条   → event 模板    (kicker=编号+分类, headline=标题, chips=板块/概念, quote=AI影响分析)
  收尾   → conclusion 模板 (免责声明 + 关注引导)

用法:
  python generator/main.py video                  # 用今天的 daily JSON 建项目并出片(跳过审核门禁)
  python generator/main.py video --date 2026-08-27
  python generator/main.py video --estimate       # 无声预览(不耗 TTS/不出正式片)
  python generator/main.py video --no-render      # 只生成 story.json,用 remotion studio 手动预览
"""

import json
import subprocess
import sys
from pathlib import Path

from common import GEN_ROOT, today

VIDEO_ROOT = GEN_ROOT.parent / "video"


def _rich(text: str, bold=False):
    return [{"t": text, **({"b": True} if bold else {})}]


def _first_sentences(paragraph: str, limit: int = 80) -> str:
    """取段落前 1-2 句并截到 limit 字内(句号/分号边界优先)。"""
    text = paragraph.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in ("。", "；", ";", "，"):
        i = cut.rfind(sep)
        if i > limit // 2:
            return cut[:i + (1 if sep != "，" else 0)]
    return cut.rstrip("，,、") + "……"


def build_story(entries: list) -> dict:
    scenes = []
    n = len(entries)
    top3 = " / ".join(e["title"] for e in entries[:3])
    scenes.append({
        "id": "opening",
        "template": "title",
        "narration": f"早上好,今天是{today()},AI财经日报,{n}条要闻。今天最值得盯的:{'、'.join(e['title'] for e in entries[:3])}。",
        "caption": f"AI财经日报 {today()}",
        "data": {
            "kicker": "AI 财经日报",
            "kickerColor": "blue",
            "titlePre": today(),
            "subtitle1": _rich(f"今日 {n} 条要闻", True),
            "subtitle2": _rich(f"重点关注:{top3}"),
        },
    })
    for i, e in enumerate(entries, 1):
        a = e.get("analysis") or {}
        tags = (a.get("sectors", []) + a.get("concepts", []))[:4]
        # 详情细节 → rows 模板(每段压成一句,画面中间不再是空的)
        labels = ["事件", "详情", "进展", "背景", "影响"]
        accents = ["blue", "green", "amber", "purple", "red"]
        rows = []
        for j, p in enumerate(e.get("detail_paragraphs", [])[:4]):
            body = _first_sentences(p, limit=80)
            if body:
                rows.append({"accent": accents[j % len(accents)],
                             "label": _rich(labels[j % len(labels)], True),
                             "body": _rich(body)})
        scenes.append({
            "id": f"news-{i:02d}",
            "template": "rows",
            "narration": e.get("voiceover") or e.get("summary", ""),
            "caption": e["title"],
            "data": {
                "kicker": f"{i:02d} · {e.get('category', '财经')}",
                "headline": _rich(e["title"], True),
                "rows": rows or [{"accent": "blue", "label": _rich("要点", True),
                                  "body": _rich(e.get("summary", ""))}],
                **({"footnote": [{"t": f"AI解读|关联:{'/'.join(tags)} · {a.get('direction', '中性')} —— {a.get('impact', '')}",
                                  "b": True}]}
                   if a.get("impact") else {}),
            },
        })
    scenes.append({
        "id": "closing",
        "template": "conclusion",
        "narration": "以上就是今天的财经日报,内容基于公开信息整理,不构成投资建议。关注我,每天几分钟看懂财经。",
        "caption": "关注不迷路",
        "data": {
            "kicker": "免责声明",
            "statements": [{"who": "风险提示", "body": _rich("内容基于公开信息由 AI 整理,不构成任何投资建议")}],
            "tagline": _rich("每天几分钟,看懂财经", True),
        },
    })
    return {
        "meta": {"title": f"AI财经日报 {today()}", "voice": "zh-CN-YunxiNeural",
                 "fps": 30, "width": 1920, "height": 1080, "padSeconds": 0.8},
        "scenes": scenes,
    }


def run(date: str | None = None, estimate: bool = False, no_render: bool = False, force: bool = True) -> Path:
    date = date or today()
    data_file = GEN_ROOT / "output" / "daily" / f"daily-{date}.json"
    if not data_file.exists():
        sys.exit(f"未找到 {data_file}\n请先运行: python generator/main.py daily")
    entries = json.loads(data_file.read_text(encoding="utf-8"))
    if not entries:
        sys.exit("daily JSON 为空")

    proj_id = f"daily-{date.replace('-', '')}"
    proj_dir = VIDEO_ROOT / "videos" / proj_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "story.json").write_text(
        json.dumps(build_story(entries), ensure_ascii=False, indent=2), encoding="utf-8")
    (proj_dir / "project.json").write_text(
        json.dumps({"id": proj_id, "title": f"AI财经日报 {date}", "status": "draft",
                    "created": date, "note": "由 generator daily 自动生成"},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成 video/videos/{proj_id}/story.json ({len(entries)} 条 + 开场收尾)")

    cmd = ["node", "scripts/build.mjs", proj_id]
    if estimate:
        cmd.append("--estimate")
    elif force:
        cmd.append("--force")
    if no_render:
        cmd.append("--no-render")
    if not (estimate or no_render or force):
        pass  # 无 flag 时尊重审核门禁(status=draft 会被拒,提示人工审核)
    print("执行:", " ".join(cmd), "(cwd=video/)")
    r = subprocess.run(cmd, cwd=VIDEO_ROOT)
    if r.returncode != 0:
        sys.exit(f"视频制作失败(exit {r.returncode});首次使用请先在 video/ 下执行 npm install")
    out = proj_dir / "out" / ("preview-silent.mp4" if estimate else "final.mp4")
    print(f"\n✅ 视频输出: {out}")
    return out
