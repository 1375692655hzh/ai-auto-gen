"""AI 财经早报工作流:生成系统的第一大关。

步骤(存档断点,重跑不重复花钱):
  1 fetch     抓取快讯+同行早报(免 LLM)
  2 rank      LLM 精排选条(打分/分类/配额)
  3 expand    逐条联网取证(豆包搜索)+扩写详情+AI解读+数字校验(并行,最贵的一步)
  4 assemble  组装图文日报(进 autopub 待发)+逐条口播稿+结构化 JSON   ← 审核点
  5 video     (可选,--with-video)一键成片

用法:
  python generator/main.py run morning-paper                # 标准跑,assemble 后暂停审核
  python generator/main.py run morning-paper --auto        # 全自动
  python generator/main.py run morning-paper --from expand # 从 expand 步重跑
  python generator/main.py run morning-paper --items 10    # 条数
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from workflows.base import WorkflowBase
from common import load_cfg, out_dir, save_text, GEN_ROOT
import sources
import daily


class MorningPaperWorkflow(WorkflowBase):
    name = "morning-paper"
    title = "AI财经早报"
    description = "抓取→粗筛→精排→联网取证→扩写解读→数字校验→图文日报+口播稿(+视频)"

    def __init__(self, date=None, items=0, with_video=False, no_voice=False):
        super().__init__(date)
        self.want = items or int(load_cfg().get("daily", {}).get("items", 15))
        self.with_video = with_video
        self.no_voice = no_voice

    def steps(self):
        return [
            ("fetch", self.step_fetch, False),
            ("rank", self.step_rank, False),
            ("expand", self.step_expand, False),
            ("assemble", self.step_assemble, True),   # 审核点:出稿后人工过目
            ("video", self.step_video, False),
        ]

    # ---- 各步骤 ----

    def step_fetch(self, ctx):
        items, failed = sources.gather()
        refs, ref_failed = sources.gather_refs()
        if failed or ref_failed:
            print(f"⚠ 不可用来源: {', '.join(failed + ref_failed)}")
        if not items:
            sys.exit("没有抓到快讯")
        print(f"抓取: 快讯 {len(items)} 条 + 同行早报 {len(refs)} 篇")
        return {"items": items, "refs": refs}

    def step_rank(self, ctx):
        coarse = daily.coarse_filter(ctx["items"])
        print(f"粗筛: {len(ctx['items'])} → {len(coarse)} 条")
        ranked = daily.rank_items(coarse, self.want)
        print(f"精排入选 {len(ranked)} 条")
        return {"coarse_count": len(coarse), "ranked": ranked}

    def step_expand(self, ctx):
        ranked, refs = ctx["ranked"], ctx["refs"]

        def work(it):
            ev = daily.collect_evidence(it, refs)
            try:
                d = daily.expand_item(it, ev)
            except Exception as ex:
                print(f"  ⚠ 「{it['rank_title'][:16]}」扩写失败({type(ex).__name__}),降级为仅摘要")
                d = {"title": it["rank_title"], "summary": it["text"][:60],
                     "detail_paragraphs": [], "sectors": [], "concepts": [],
                     "direction": "中性", "impact": "", "needs_review": False}
            it.update(d)
            it["evidence_urls"] = ev["urls"]
            it["source_name"] = it["source"]
            return it

        entries = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            futs = {pool.submit(work, it): it for it in ranked}
            for f in as_completed(futs):
                entries.append(f.result())
        order = {c: i for i, c in enumerate(daily.CATEGORIES)}
        entries.sort(key=lambda x: order.get(x["category"], 9))
        flagged = sum(1 for e in entries if e.get("needs_review"))
        if flagged:
            print(f"⚠ {flagged} 条数字校验未过(已保留待人工复核)")
        return {"entries": entries}

    def step_assemble(self, ctx):
        entries = ctx["entries"]
        md = daily.build_md(entries, ctx.get("refs", []))
        md_path = save_text(out_dir("articles_dir") / f"AI财经日报-{self.date}.md", md)

        voice_path = None
        if not self.no_voice:
            daily.gen_voiceovers(entries)
            voice_path = save_text(out_dir("scripts_dir") / f"AI财经日报-{self.date}-口播.md",
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
        data_path = GEN_ROOT / "output" / "daily" / f"daily-{self.date}.json"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        data_path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"图文: {md_path}\n口播: {voice_path}\nJSON: {data_path}")
        return {"md_path": str(md_path), "voice_path": str(voice_path), "data_path": str(data_path)}

    def step_video(self, ctx):
        if not self.with_video:
            print("未启用视频步骤(加 --with-video)")
            return {}
        import video as video_mod
        out = video_mod.run(date=self.date, force=True)
        return {"video_path": str(out)}
