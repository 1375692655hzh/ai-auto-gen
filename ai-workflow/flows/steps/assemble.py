"""组装步骤:图文日报(进待发目录) + 口播稿 + 结构化 daily JSON。← 通常设为审核点"""

import json

from flows.steps import step


@step("assemble_daily")
def assemble_daily(ctx, wf, params):
    """with: {no_voice: bool}。产物路径(md_path/voice_path/data_path)并入 ctx。"""
    import daily
    from common import out_dir, save_text, GEN_ROOT
    entries, date = ctx["entries"], wf.date
    md = daily.build_md(entries, ctx.get("refs", []), date=date)
    md_path = save_text(out_dir("articles_dir") / f"AI财经日报-{date}.md", md)

    voice_path = None
    if not params.get("no_voice"):
        daily.gen_voiceovers(entries)
        voice_path = save_text(out_dir("scripts_dir") / f"AI财经日报-{date}-口播.md",
                               daily.build_voice_md(entries))

    clean = []
    for e in entries:
        if e.get("category") in ("开场", "收尾"):
            continue
        clean.append({"id": len(clean) + 1, "category": e["category"], "time": e.get("time", ""),
                      "title": e["title"], "summary": e["summary"],
                      "detail_paragraphs": e.get("detail_paragraphs", []),
                      "analysis": {"sectors": e.get("sectors", []), "concepts": e.get("concepts", []),
                                   "direction": e.get("direction"), "impact": e.get("impact")},
                      "needs_review": e.get("needs_review", False),
                      "evidence_urls": e.get("evidence_urls", []),
                      "voiceover": e.get("voiceover", "")})
    data_path = GEN_ROOT / "output" / "daily" / f"daily-{date}.json"
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"图文: {md_path}\n口播: {voice_path}\nJSON: {data_path}")
    return {"md_path": str(md_path), "voice_path": str(voice_path), "data_path": str(data_path)}
