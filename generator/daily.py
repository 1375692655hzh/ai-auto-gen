"""AI 财经日报(逐条详情模式,对标"一条条消息看过去"的视频早报格式)。

流水线: 抓取(复用 sources) → 规则粗筛 → LLM 精排(打分/分类/配额)
  → 逐条二次抓取原文+同行早报背景 → LLM 扩写详情+AI分析(受控概念词表)
  → 数字防幻觉校验 → 图文 MD(进 autopub 待发) + 口播稿(逐条) + 结构化 JSON
"""

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from common import (load_cfg, out_dir, today, now_str, save_text,
                    llm_complete, parse_llm_list, safe_filename)
import sources

CATEGORIES = ["宏观政策", "公司动态", "行业产业", "海外市场", "大宗商品"]

# P0 静态候选概念词表(LLM 只能从这里选;P1 换成东财板块库自动构建)
CONCEPT_POOL = [
    "银行", "证券", "保险", "房地产", "基建", "钢铁", "有色", "煤炭", "石油石化",
    "电力", "光伏", "风电", "储能", "锂电池", "新能源车", "汽车", "汽车零部件",
    "军工", "半导体", "消费电子", "折叠屏", "AI算力", "CPO", "光模块", "服务器",
    "软件", "信创", "传媒", "游戏", "白酒", "食品饮料", "医药", "创新药", "医疗器械",
    "农业", "养殖", "化工", "机械设备", "机器人", "人形机器人", "低空经济",
    "卫星互联网", "固态电池", "跨境电商", "港口航运", "黄金", "白银", "稀土",
    "氢能", "核电", "算力租赁", "数据中心", "云计算", "网络安全", "智能驾驶",
    "家电", "纺织服装", "旅游酒店", "零售", "物流", "环保", "数字货币", "跨境支付",
    "央企改革", "并购重组", "半年报业绩", "存储芯片", "面板", "工业金属", "贵金属",
]

NOISE_RE = re.compile(r"招标公告|中标公示|申购代码|中签率|配号|解除质押|质押式回购|大宗交易公告|董事辞职")


# ---------- 第 1 步:粗筛 ----------

def coarse_filter(items: list) -> list:
    """规则粗筛:去噪 + 跨源命中统计(多源同报=高关注,作排序加成)。"""
    kept = [it for it in items if not NOISE_RE.search(it["text"])]
    # 跨源命中:同一事件被多个来源报道,关注度程序化统计(不花 token)
    for it in kept:
        it["cross_hits"] = 1
    n = len(kept)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = kept[i], kept[j]
            if a["source"] == b["source"]:
                continue
            # 快速判断:前40字里有>=12字的公共子串即视为同事件
            sa, sb = a["text"][:40], b["text"][:40]
            m = re.search(f"({'|'.join(map(re.escape, _ngrams(sa, 12)))})", sb) if _ngrams(sa, 12) else None
            if m:
                a["cross_hits"] += 1
                b["cross_hits"] += 1
    return kept


def _ngrams(s: str, size: int, step: int = 4):
    return [s[i:i + size] for i in range(0, max(1, len(s) - size + 1), step)]


# ---------- 提示词外置(P3): flows/prompts/<名>.md 或工作流包内 prompts/<名>.md 可覆盖 ----------

PROMPTS = {}          # 显式注入优先(工作流包在运行前注入)
from pathlib import Path as _P
PROMPT_DIR = _P(__file__).resolve().parent.parent / "flows" / "prompts"


def load_prompt(name: str, default: str = "") -> str:
    if name in PROMPTS:
        return PROMPTS[name]
    f = PROMPT_DIR / f"{name}.md"
    if f.exists():
        return f.read_text(encoding="utf-8")
    return default


# ---------- 第 2 步:LLM 精选 ----------

def rank_items(items: list, want: int) -> list:
    feed = "\n".join(f"#{i} [{it['time']}](x{it['cross_hits']}) {it['text'][:120]}"
                     for i, it in enumerate(items))
    tpl = load_prompt("rank_user")
    if tpl:
        user = (tpl.replace("<<DATE>>", today()).replace("<<FEED>>", feed)
                .replace("<<WANT>>", str(want)))
    else:
        user = f"今天是 {today()}。以下是从快讯池粗筛后的条目((xN)表示有几个来源同时报道):\n\n{feed}\n\n"
        f"请选出最重要的 {want} 条,输出 JSON 数组,每项:\n"
        '{{"id": 编号, "score": 0-10重要性, "category": "宏观政策|公司动态|行业产业|海外市场|大宗商品", '
        '"title": "一行式标题(≤22字)", "reason": "入选理由一句话"}}\n'
        "筛选标准:影响面大(全市场/行业级优先)、主体量级大(权重股/巨头/部委优先)、"
        "关注度高(多源报道优先)、与A股关联紧密、有详情可展开。"
        f"配额约束:宏观政策≥2条、海外市场≥2条、同一行业相关≤4条。排序按 score 降序。"
    raw = llm_complete(
        user,
        system=load_prompt("rank_system", "你是财经内容主编,只输出 JSON 数组,不加解释。"),
        max_tokens=3000,
    )
    ranked = parse_llm_list(raw)
    if not ranked:
        sys.exit(f"精排输出无法解析:\n{raw[:400]}")
    by_id = {i: it for i, it in enumerate(items)}
    out = []
    for r in sorted(ranked, key=lambda x: -float(x.get("score", 0))):
        it = by_id.get(r.get("id"))
        if it is None:
            continue
        it["rank_title"] = r.get("title", it["text"][:20])
        it["category"] = r.get("category", "行业产业")
        it["rank_reason"] = r.get("reason", "")
        it["score"] = r.get("score", 0)
        out.append(it)
        if len(out) >= want:
            break
    return out


# ---------- 第 3 步:证据收集(二次抓取 + 同行早报背景) ----------

def collect_evidence(item: dict, refs: list) -> dict:
    """为单条快讯收集扩写证据:豆包搜索(最新网络信息) + 东财同题新闻正文 + 同行早报相关段落。"""
    import search as search_mod
    ev = {"raw": item["text"], "web": "", "news_body": "", "peer": "", "urls": []}
    # ① 豆包搜索:当天最新网络报道(摘要 500-1000 字,最适合供详情与解读)
    try:
        hits = search_mod.search_safe(search_mod.make_query(item), count=3)
        if hits:
            ev["web"] = "\n".join(f"[{h['time']} {h['site']}] {h['text']}" for h in hits)[:4000]
            ev["urls"].append({"name": hits[0]["site"] or "网络报道", "url": hits[0]["url"]})
    except Exception:
        pass
    # ② 东财同题新闻正文
    kw = re.sub(r"[【】\[\]()（）:：,，.。]", " ", item["text"][:24]).split()
    keyword = "".join(kw)[:16] if kw else item["text"][:16]
    try:
        arts = sources._em_search_articles(keyword, page_size=2)
        if arts:
            body = sources._fetch_em_article_body(arts[0]["url"]) or arts[0].get("text", "")
            if body:
                ev["news_body"] = body[:2000]
                ev["urls"].append({"name": arts[0].get("mediaName", "东财报道"), "url": arts[0]["url"]})
    except Exception:
        pass
    # ③ 同行早报段落召回:与快讯共享≥2个长片段的段落
    best, best_hits = "", 0
    for r in refs:
        for para in re.split(r"[。；\n]", r.get("text", "")):
            para = para.strip()
            if len(para) < 20:
                continue
            hits = sum(1 for g in _ngrams(item["text"], 6, 3) if g and g in para)
            if hits > best_hits:
                best, best_hits = para, hits
    if best_hits >= 2:
        ev["peer"] = best
    return ev


# ---------- 第 4 步:扩写 + AI 分析 ----------

SYS_EXPAND = (
    "你是财经编辑。严格遵守:详情中所有数字、时间、公司名、金额必须逐字来自给定材料,"
    "禁止编造或推算材料外的数字;材料不足就少写,不凑段数。"
    "解读句基于材料给出一句话判断(利好/利空/中性+板块+情绪/预期逻辑),"
    "优先利用【网络搜索】材料里最新的信息与背景,禁止给出任何买卖建议。"
    "只输出 JSON,不加解释。"
)


def expand_item(item: dict, ev: dict) -> dict:
    concept_list = "、".join(CONCEPT_POOL)
    material = (f"【快讯原文】[{item['time']}] {ev['raw']}\n"
                f"【网络搜索(最新报道)】{ev['web'] or '(无)'}\n"
                f"【同题新闻正文】{ev['news_body'] or '(无)'}\n"
                f"【同行早报相关段落】{ev['peer'] or '(无)'}")
    raw = llm_complete(
        f"{material}\n\n"
        "基于以上材料为这条财经消息产出结构化内容,输出 JSON 对象:\n"
        '{"title": "一行式标题(≤22字)", "summary": "一句话摘要(≤40字)",\n'
        ' "detail_paragraphs": ["3-5段详情,每段40-120字:第一段发生了什么(含关键数字),'
        "后面讲背景/最新进展/后续安排(优先用网络搜索材料里的最新信息),只能重组材料内事实\"],\n"
        ' "sectors": ["从候选里选0-3个"], "concepts": ["从候选里选0-3个"],\n'
        ' "direction": "利好|利空|中性", "impact": "一句话解读(≤40字,如:利好固态电池产业链短期情绪)"}\n'
        f"候选板块/概念(只能从中选,没有合适的给空数组):{concept_list}",
        system=load_prompt("expand", SYS_EXPAND), max_tokens=3000,
    )
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError("扩写输出非 JSON")
    d = json.loads(m.group(0))
    d["needs_review"] = not numbers_verified(d.get("detail_paragraphs", []), ev)
    return d


def numbers_verified(paragraphs: list, ev: dict) -> bool:
    """数字防幻觉校验:详情中每个数字都必须出现在证据材料里。"""
    evidence = ev["raw"] + ev["web"] + ev["news_body"] + ev["peer"]
    ev_nums = set(re.findall(r"\d+(?:\.\d+)?", evidence.replace(",", "").replace("，", "")))
    for p in paragraphs:
        for num in re.findall(r"\d+(?:\.\d+)?", p.replace(",", "").replace("，", "")):
            if num not in ev_nums:
                return False
    return True


# ---------- 第 5 步:口播稿(逐条) ----------

SYS_VOICE = (
    "你是财经短视频口播撰稿人,口语化、短句、有节奏。"
    "每条口播词固定结构:串场词(4-8字,如'再看下一条')+标题句+关键事实1-2句(保留最有感的数字)"
    "+影响句。禁止书面语(据悉/公告显示),禁止买卖建议。只输出 JSON,不加解释。"
)


def gen_voiceovers(entries: list) -> None:
    lines = []
    for i, e in enumerate(entries):
        lines.append(json.dumps({
            "id": i + 1, "title": e["title"], "summary": e["summary"],
            "key_detail": e["detail_paragraphs"][0] if e.get("detail_paragraphs") else "",
            "impact": e.get("impact", ""), "category": e["category"],
        }, ensure_ascii=False))
    raw = llm_complete(
        f"今天是 {today()},共 {len(entries)} 条。逐条口播词 60-90 字(约15秒/条):\n"
        + "\n".join(lines)
        + '\n\n输出 JSON 数组:[{"id": 1, "text": "口播词"}]。串场词要有变化,分类切换时用"接下来看海外市场"这类过渡。',
        system=load_prompt("voice", SYS_VOICE), max_tokens=4000,
    )
    vo = {v.get("id"): v.get("text", "") for v in parse_llm_list(raw)}
    for i, e in enumerate(entries):
        e["voiceover"] = vo.get(i + 1, "")
    # 开场与收尾
    top3 = "、".join(e["title"] for e in entries[:3])
    entries.insert(0, {"category": "开场", "voiceover":
        f"早上好,今天是{today()},AI财经日报,{len(entries)}条要闻。今天最值得盯的:{top3}。"})
    entries.append({"category": "收尾", "voiceover":
        "以上就是今天的财经日报,内容基于公开信息整理,不构成投资建议。关注我,每天几分钟看懂财经。"})


# ---------- 第 6 步:组装输出 ----------

def build_md(entries: list, refs: list, date: str | None = None) -> str:
    L = [f"# AI财经日报 | {date or today()}", "", "## 今日概览", ""]
    for i, e in enumerate(entries, 1):
        L.append(f"{i}. **[{e['category']}]** {e['title']}")
    L.append("\n---\n")
    for i, e in enumerate(entries, 1):
        L.append(f"## {i}. {e['title']}")
        L.append(f"*{e['category']} · {e['time']} · 来源:{e['source_name']}*")
        L.append("")
        L.append(f"> {e['summary']}")
        L.append("")
        for p in e.get("detail_paragraphs", []):
            L.append(p)
            L.append("")
        seen_tags = []
        for t in e.get("sectors", []) + e.get("concepts", []):
            if t and t not in seen_tags:
                seen_tags.append(t)
        tags = "/".join(seen_tags) or "综合"
        L.append(f"**📌 AI解读|关联:{tags} · {e.get('direction', '中性')} —— {e.get('impact', '')}**")
        if e.get("urls"):
            L.append("\n" + " · ".join(f"[{u['name']}]({u['url']})" for u in e["urls"]))
        L.append("\n---\n")
    L.append("> 内容基于公开信息由 AI 整理,不构成投资建议。")
    return "\n".join(L)


def build_voice_md(entries_with_vo: list) -> str:
    L = [f"# AI财经日报-{today()} 口播稿(逐条)", ""]
    total = sum(len(e.get("voiceover", "")) for e in entries_with_vo)
    L.append(f"*预计总时长约 {round(total / 4.5)} 秒(按 4.5 字/秒)*\n")
    for e in entries_with_vo:
        tag = f"[{e['category']}]" if e.get("category") else ""
        L.append(f"{tag} {e.get('voiceover', '')}\n")
    return "\n".join(L)


# ---------- 总控 ----------

def run(want: int = 15, with_voice: bool = True) -> dict:
    from common import llm_require_config
    llm_require_config()
    cfg = load_cfg().get("daily", {})
    want = want or int(cfg.get("items", 15))

    items, failed = sources.gather()
    refs, ref_failed = sources.gather_refs()
    if failed or ref_failed:
        print(f"⚠ 不可用来源: {', '.join(failed + ref_failed)}")
    if not items:
        sys.exit("没有抓到快讯")

    coarse = coarse_filter(items)
    print(f"粗筛: {len(items)} → {len(coarse)} 条")

    ranked = rank_items(coarse, want)
    print(f"精排入选 {len(ranked)} 条: " + " | ".join(f"{it['rank_title'][:18]}" for it in ranked))

    def work(it):
        ev = collect_evidence(it, refs)
        try:
            d = expand_item(it, ev)
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
    with ThreadPoolExecutor(max_workers=2) as pool:  # 并发过高易触发方舟限流
        futs = {pool.submit(work, it): it for it in ranked}
        for f in as_completed(futs):
            it = f.result()
            entries.append(it)
    entries.sort(key=lambda x: -float(x.get("score", 0)))
    # 按分类聚类排序(宏观→行业→公司→海外→大宗)
    order = {c: i for i, c in enumerate(CATEGORIES)}
    entries.sort(key=lambda x: order.get(x["category"], 9))
    flagged = [e["title"] for e in entries if e.get("needs_review")]
    if flagged:
        print(f"⚠ {len(flagged)} 条数字校验未过(已保留,建议人工复核): {'; '.join(flagged[:5])}")

    md = build_md(entries, refs)
    md_path = save_text(out_dir("articles_dir") / f"AI财经日报-{today()}.md", md)

    voice_path = None
    if with_voice:
        gen_voiceovers(entries)
        voice_path = save_text(out_dir("scripts_dir") / f"AI财经日报-{today()}-口播.md",
                               build_voice_md(entries))

    data_path = out_dir("research_dir").parent / "daily" / f"daily-{today()}.json"
    data_path.parent.mkdir(parents=True, exist_ok=True)
    clean = []
    for i, e in enumerate(entries):
        if e.get("category") in ("开场", "收尾"):  # 口播插入的条目不进数据文件
            continue
        clean.append({"id": len(clean) + 1, "category": e["category"], "time": e.get("time", ""),
                      "title": e["title"], "summary": e["summary"],
                      "detail_paragraphs": e.get("detail_paragraphs", []),
                      "analysis": {"sectors": e.get("sectors", []), "concepts": e.get("concepts", []),
                                   "direction": e.get("direction"), "impact": e.get("impact")},
                      "needs_review": e.get("needs_review", False),
                      "evidence_urls": e.get("evidence_urls", []),
                      "voiceover": e.get("voiceover", "")})
    data_path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n图文日报: {md_path}")
    if voice_path:
        print(f"口播稿:   {voice_path}")
    print(f"结构化:   {data_path}")
    print(f"共 {len(entries)} 条 | 开场/收尾口播已加 | 图文已进 autopub 待发目录")
    return {"md": md_path, "voice": voice_path, "data": data_path, "entries": clean}
