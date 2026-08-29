"""视频步骤:调 generator 的 video 管线出片(TTS+渲染+封面); morning-digest 专用口播稿版本。"""

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
    """morning-digest: 文章条目(来龙去脉) + LLM 口播稿 → Remotion 出片。
    with: {top: 12}。画面: kicker=编号+板块词(无多空无AI字样), rows=原文详情;
    口播: 独立讲述体 80-120 字/条(不复读画面)。女声晓晓。产物 autopub/videos/早报视频-{date}.mp4。"""
    import daily
    from common import llm_complete, GEN_ROOT
    date = wf.date
    digest_p = ctx.get("image_digest_path")
    article_p = ctx.get("article_path") or ctx.get("tagged_path")
    if not digest_p or not Path(digest_p).exists():
        sys.exit("视频依赖长图存档 image-digest JSON: 需 --set with_image=true")
    if not article_p or not Path(article_p).exists():
        sys.exit("视频依赖文章产物")
    payload = json.loads(Path(digest_p).read_text(encoding="utf-8"))
    cards = payload.get("cards") or []
    article = Path(article_p).read_text(encoding="utf-8")

    from flows.steps.image import _index_with_tags
    items, _ = _index_with_tags(article)
    text_of = {it["n"]: it["text"] for it in items}
    # 卡片对齐文章原文(n 编号一致), 取 top 条做播报单位
    sel = [c for c in cards if c["n"] in text_of][: int(params.get("top", 12))]
    if len(sel) < 4:
        sys.exit(f"可播报条目过少({len(sel)}), 不值得出片")

    # ---- LLM 口播稿(讲述体, 复读画面是事故) ----
    feed = chr(10).join(
        f"{c['n']}|{(c.get('pill') not in (None, '', '-') and c['pill']) or c['tag']}|{text_of[c['n']]}"
        for c in sel)
    tpl = daily.load_prompt("morning_video_script")
    if not tpl:
        sys.exit("缺少提示词 morning_video_script.md")
    user = tpl.replace("<<DATE>>", date).replace("<<ITEMS>>", feed)
    system = "你是财经早报视频主持人, 只输出严格 JSON。"
    print(f"口播稿: {len(sel)} 条 / 送模型 {len(user)} 字 ...")
    narr, err = _parse_script(llm_complete(user, system=system, max_tokens=3500, temperature=0.3),
                             {c["n"]: text_of[c["n"]] for c in sel})
    if err:
        print(f"⚠ 口播稿校验失败({err}), 重试一次 ...")
        narr, err = _parse_script(llm_complete(user, system=system, max_tokens=3500, temperature=0.3),
                                  {c["n"]: text_of[c["n"]] for c in sel})
    if err:
        sys.exit(f"口播稿失败: {err}")

    video_root = GEN_ROOT.parent / "video"
    story = _build_story(sel, text_of, narr, date)
    proj_id = f"morning-{date.replace('-', '')}"
    proj_dir = video_root / "videos" / proj_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "story.json").write_text(
        json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
    (proj_dir / "project.json").write_text(
        json.dumps({"id": proj_id, "title": story["meta"]["title"], "status": "draft",
                    "created": date, "note": "由 morning-digest 自动生成"},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"视频项目: video/videos/{proj_id}/story.json ({len(sel)} 条 + 开场收尾)")
    print(f"视频标题: {story['meta']['title']}")

    r = subprocess.run(["node", "scripts/build.mjs", proj_id, "--force"], cwd=video_root)
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
    return {"video_path": str(out), "video_cards": len(sel)}


def _parse_script(raw: str, src: dict):
    """解析口播稿 JSON + 数字保真。返回 ({n: narration}, err)。"""
    m = re.search(r"\{[\s\S]*\}", raw or "")
    if not m:
        return None, "无 JSON"
    try:
        data = json.loads(m.group(0))
    except Exception as e:
        return None, f"解析失败: {e}"
    out = {}
    for o in data.get("items") or []:
        n = o.get("n")
        t = str(o.get("narration") or "").strip()
        if not isinstance(n, int) or n not in src or not t:
            continue
        for num in re.findall(r"\d+(?:\.\d+)?", t):
            if num not in src[n]:
                return None, f"#{n} 数字失真: {num}"
        if any(w in t for w in ("买入", "卖出", "建仓", "抄底", "目标价", "上车", "布局", "AI解读")):
            return None, f"#{n} 禁词"
        out[n] = t
    if len(out) < len(src) // 2:
        return None, f"有效条目过少({len(out)}/{len(src)})"
    return out, ""


def _cut(text: str, limit: int) -> str:
    """句读边界截断。"""
    t = text.strip()
    if len(t) <= limit:
        return t
    cut = t[:limit]
    for sep in ("。", "；", "，"):
        i = cut.rfind(sep)
        if i > limit // 2:
            return cut[:i + (1 if sep != "，" else 0)]
    return cut.rstrip("，,、") + "……"


def _build_story(sel: list, text_of: dict, narr: dict, date: str) -> dict:
    from datetime import datetime
    try:
        d = datetime.strptime(date, "%Y-%m-%d")
        date_cn = f"{d.month}月{d.day}日"
    except ValueError:
        date_cn = date
    vt = f"{_cut(sel[0]['title'], 22)}【财经早报】"
    n = len(sel)

    def _r(t, b=False):
        return [{"t": t, **({"b": True} if b else {})}]

    scenes = [{
        "id": "opening", "template": "title",
        "narration": f"早上好,今天是{date_cn},财经早报,今天重点事件:{sel[0]['title']}。",
        "caption": vt,
        "data": {"kicker": "财经早报", "kickerColor": "blue",
                 "titlePre": vt.replace("【财经早报】", ""),
                 "subtitle1": _r(f"今日 {n} 条要闻", True),
                 "subtitle2": _r(f"重点关注:{' / '.join(c['title'] for c in sel[:3])}")},
    }]
    for i, c in enumerate(sel, 1):
        pill = c.get("pill")
        pill = pill if pill not in (None, "", "-") else "要闻"
        body = _cut(text_of[c["n"]], 92)             # 画面详情 = 原文来龙去脉
        scenes.append({
            "id": f"news-{i:02d}", "template": "rows",
            "narration": f"第{i}条,{narr.get(c['n']) or body}",   # 口播稿缺失时退原文
            "caption": c["title"],
            "data": {"kicker": f"{i:02d} · {pill}",
                     "headline": _r(c["title"], True),
                     "rows": [{"accent": "blue", "label": _r("详情", True), "body": _r(body)}]},
        })
    scenes.append({
        "id": "closing", "template": "conclusion",
        "narration": "以上就是今天的财经早报,内容基于公开信息整理,不构成投资建议。关注我,每天几分钟看懂财经。",
        "caption": "关注不迷路",
        "data": {"kicker": "免责声明",
                 "statements": [{"who": "风险提示", "body": _r("内容基于公开信息整理, 不构成任何投资建议")}],
                 "tagline": _r("每天几分钟, 看懂财经", True)},
    })
    return {"meta": {"title": vt, "voice": "zh-CN-XiaoxiaoNeural",
                     "fps": 30, "width": 1920, "height": 1080, "padSeconds": 0.8},
            "scenes": scenes}
