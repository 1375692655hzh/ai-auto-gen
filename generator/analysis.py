"""分析文章四步流程:选题 → 锁定最新信息 → 确定大纲 → 生成文章和口播稿。

每一步的中间产物都落盘(output/research/),可追溯、可复用:
  - 选题候选 / 相关快照 JSON
  - 大纲文本
交互模式下每步可确认或重来;--yes 全自动跑通。
"""

import json
import re
import sys

from common import (load_cfg, out_dir, today, now_str, save_text,
                    llm_complete, parse_llm_list, confirm)
import sources

SYS_TOPIC = "你是财经内容策划,擅长从零散快讯里发现值得深度分析的主题。只输出要求的内容,不加解释。"
SYS_RESEARCH = "你是严谨的财经研究员,只依据给定材料工作,不编造。只输出要求的内容。"
SYS_OUTLINE = "你是资深财经专栏作者。大纲要言之有物:每个小节写清这节要论证什么、用什么材料支撑。只输出 Markdown 大纲。"
SYS_ARTICLE = (
    "你是资深财经分析作者,写给关注市场的普通投资者。观点鲜明但论据扎实,"
    "所有事实性信息只能来自提供的材料,材料之外只允许常识性推理并明确标注推断。"
    "输出纯 Markdown,第一行一级标题。"
)
SYS_SCRIPT = (
    "你是财经短视频口播撰稿人。口语化、有节奏、短句为主。"
    "开头3秒抛出核心冲突,结尾一句引导关注。只输出口播正文,不要小标题和 Markdown 记号。"
)


def step1_topic(topic: str | None, auto: bool) -> str:
    """选题:给了 --topic 直接用;否则从最新快讯里让模型提 3 个候选。"""
    if topic:
        print(f"主题(手动指定): {topic}")
        return topic

    items, failed = sources.gather(limit=60)
    if failed:
        print(f"⚠ 部分信息源不可用: {', '.join(failed)}")
    if not items:
        sys.exit("没有抓到快讯,无法自动选题;请用 --topic 手动指定主题")

    raw = llm_complete(
        f"以下是最新财经快讯:\n\n{sources.render_items(items)}\n\n"
        "从中提炼 3 个值得写深度分析文章的主题(题材热点/产业趋势/重大事件),"
        '输出 JSON 数组:[{"topic": "主题名", "reason": "为什么现在值得写", "angle": "建议切入角度"}]',
        system=SYS_TOPIC, max_tokens=1200,
    )
    cands = parse_llm_list(raw)
    if not cands:
        sys.exit(f"模型选题输出无法解析,原始回复:\n{raw[:500]}")

    print(f"\n===== 第 1 步:选题(来自 {len(items)} 条最新快讯) =====")
    for i, c in enumerate(cands[:3], 1):
        print(f"\n[{i}] {c.get('topic', '?')}\n    理由: {c.get('reason', '')}\n    角度: {c.get('angle', '')}")

    if auto:
        pick = cands[0].get("topic", "")
        print(f"\n自动模式选择: [1] {pick}")
        return pick
    while True:
        ans = input("\n选择主题编号(1-3,r=重新生成,d=直接输入主题): ").strip().lower()
        if ans in ("1", "2", "3") and int(ans) <= len(cands):
            return cands[int(ans) - 1].get("topic", "")
        if ans == "d":
            return input("输入主题: ").strip()
        if ans == "r":
            return step1_topic(None, auto)


def step2_research(topic: str) -> list:
    """锁定最新信息:全量快讯里筛出与主题相关的条目,快照落盘。"""
    cfg = load_cfg().get("analysis", {})
    max_items = int(cfg.get("max_items", 80))
    items, failed = sources.gather(limit=max_items)
    if failed:
        print(f"⚠ 部分信息源不可用: {', '.join(failed)}")

    raw = llm_complete(
        f"主题:{topic}\n\n以下是最新财经快讯:\n\n{sources.render_items(items)}\n\n"
        '从中挑出与该主题直接相关的条目,输出 JSON 数组:'
        '[{"time": "原时间", "text": "原条目(保留原文)", "why": "相关性一句话"}],'
        "严格保留原文,不要改写;没有相关条目就输出 []",
        system=SYS_RESEARCH, max_tokens=3000,
    )
    related = parse_llm_list(raw)
    if not related:
        sys.exit(f"未锁定到与「{topic}」相关的快讯。模型回复:\n{raw[:500]}\n"
                 "建议换主题,或等热点发酵后再试。")

    snap = out_dir("research_dir") / f"{topic}-{today()}.json"
    snap.write_text(json.dumps({"topic": topic, "locked_at": now_str(),
                                "items": related}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(f"\n===== 第 2 步:锁定信息({len(related)} 条相关) =====")
    for r in related[:8]:
        print(f"  [{r.get('time', '')}] {str(r.get('text', ''))[:60]}")
    if len(related) > 8:
        print(f"  ...(共 {len(related)} 条,快照已存 {snap})")
    if len(related) < int(cfg.get("min_related_items", 3)):
        print(f"⚠ 相关素材偏少({len(related)} 条),成文深度可能受限。")
    return related


def step3_outline(topic: str, related: list, auto: bool) -> str:
    """大纲:基于锁定信息生成,交互确认/重生成。"""
    material = "\n".join(f"- [{r.get('time', '')}] {r.get('text', '')}" for r in related)
    hint = load_cfg().get("analysis", {}).get("article_hint", "")

    def gen():
        return llm_complete(
            f"主题:{topic}\n当前时间:{now_str()}\n\n已锁定的素材:\n{material}\n\n"
            f"请为这篇分析文章拟大纲(文章要求:{hint})。"
            "格式:一级标题(含主题、有信息量的标题,别用《深度解析》这类空话)+ "
            "各二级小节标题,每小节下列 2-3 条要点(写清论什么、用哪条素材)。",
            system=SYS_OUTLINE, max_tokens=2000,
        )

    outline = gen()
    while True:
        print(f"\n===== 第 3 步:大纲 =====\n\n{outline}\n")
        if auto:
            return outline
        ans = input("确认大纲?(回车=确认 r=重新生成)").strip().lower()
        if ans != "r":
            return outline
        outline = gen()


def step4_write(topic: str, outline: str, related: list) -> dict:
    """成文:文章 + 口播稿,文章落发布目录,口播稿落 output/。"""
    cfg = load_cfg().get("analysis", {})
    secs = int(cfg.get("script_seconds", 120))
    words = round(secs / 60 * 260)
    hint = cfg.get("article_hint", "")
    material = "\n".join(f"- [{r.get('time', '')}] {r.get('text', '')}" for r in related)

    article = llm_complete(
        f"主题:{topic}\n当前时间:{now_str()}\n大纲:\n{outline}\n\n素材(事实只能用这些):\n{material}\n\n"
        f"按大纲写全文,要求:{hint}。引用素材中的事实保留时间感(如「昨日」「今早」)。",
        system=SYS_ARTICLE, max_tokens=8000,
    )
    script = llm_complete(
        f"以下是成稿的分析文章:\n\n{article}\n\n请压缩改写成约 {words} 字(约 {secs} 秒)的口播稿,"
        "保留最核心的观点冲突和结论。",
        system=SYS_SCRIPT, max_tokens=1800,
    )

    from common import safe_filename
    stem = f"分析-{safe_filename(topic)}-{today()}"
    a_path = save_text(out_dir("articles_dir") / f"{stem}.md", article)
    s_path = save_text(out_dir("scripts_dir") / f"{stem}-口播.md",
                       f"# {stem} 口播稿(约{secs}秒)\n\n{script}\n")
    return {"article": a_path, "script": s_path}


def run(topic: str | None = None, auto: bool = False) -> dict:
    from common import llm_require_config
    llm_require_config()  # 先确认模型可用,再进入流程
    t = step1_topic(topic, auto)
    related = step2_research(t)
    outline = step3_outline(t, related, auto)
    print("\n===== 第 4 步:生成文章与口播稿 =====")
    r = step4_write(t, outline, related)
    print(f"文章: {r['article']}\n口播: {r['script']}")
    print("\n提示:文章已进入 autopub 待发目录;建议先 `python autopub/publish.py --platform zhihu --draft` 单平台试发。")
    return r
