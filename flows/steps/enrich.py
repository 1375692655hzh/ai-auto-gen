"""enrich 步骤: 素材+文章选中条 → LLM 结构化口播内容(summary/stat/lines) → 条目级数字保真。

口播文本源定案(2026-08-29 用户拍板): 文章 58 字是图文扫读黄金长度, 视频要 130-200 字——
双轨解耦, 视频口播稿由本步从素材层找补, 不动文章层。单条失败降级回文章原文。
"""

import json
import re
import sys
from pathlib import Path

from flows.steps import step

BAN_WORDS = ("买入", "卖出", "建仓", "加仓", "减仓", "抄底", "止盈", "止损",
             "清仓", "满仓", "目标价", "上车", "下车", "布局", "梭哈")
_JUDGE = re.compile(r"利好.{0,6}(板块|概念|方向)|利空.{0,6}(板块|概念|方向)|"
                    r"值得关注.{0,8}(板块|概念)|建议关注")


@step("enrich_video_details")
def enrich_video_details(ctx, wf, params):
    """image 选条 + 素材 → enriched JSON。with: {top: 10, model: ""}。"""
    import daily
    from common import llm_complete
    date = wf.date
    digest_p = ctx.get("image_digest_path")
    article_p = ctx.get("article_path") or ctx.get("tagged_path")
    material_p = ctx.get("material_path")
    if not digest_p or not Path(digest_p).exists():
        sys.exit("enrich 依赖长图存档: 需 --set with_image=true")
    if not article_p or not Path(article_p).exists():
        sys.exit("enrich 依赖文章产物")
    if not material_p or not Path(material_p).exists():
        sys.exit("enrich 依赖素材产物")

    payload = json.loads(Path(digest_p).read_text(encoding="utf-8"))
    cards = payload.get("cards") or []
    article = Path(article_p).read_text(encoding="utf-8")
    material = Path(material_p).read_text(encoding="utf-8")

    from flows.steps.image import _index_with_tags
    items, _ = _index_with_tags(article)
    text_of = {it["n"]: it["text"] for it in items}
    # 选中 top+2 缓冲条
    sel = [c for c in cards if c["n"] in text_of][: int(params.get("top", 10)) + 2]
    if len(sel) < 4:
        sys.exit(f"可扩写条目过少({len(sel)})")

    feed = chr(10).join(
        f"{c['n']}|{(c.get('pill') not in (None, '', '-') and c['pill']) or c['tag']}|{text_of[c['n']]}"
        for c in sel)
    tpl = daily.load_prompt("morning_video_enrich")
    if not tpl:
        sys.exit("缺少提示词 morning_video_enrich.md")
    user = (tpl.replace("<<DATE>>", date).replace("<<ITEMS>>", feed)
               .replace("<<MATERIAL>>", material[:14000]))
    system = "你是财经视频编导, 只输出严格 JSON。"
    print(f"enrich: {len(sel)} 条 / 送模型 {len(user)} 字 ...")

    def _call():
        from common import gen_llm
        return gen_llm(str(params.get("model", "")), user, system, 4000, 0.2)

    art_nums = {c["n"]: set(re.findall(r"\d+(?:\.\d+)?", text_of[c["n"]])) for c in sel}
    mat_nums = set(re.findall(r"\d+(?:\.\d+)?", material))
    enriched, err = _parse_enrich(_call(), art_nums, mat_nums)
    if err:
        print(f"⚠ enrich 校验失败({err}), 重试一次 ...")
        enriched, err = _parse_enrich(_call(), art_nums, mat_nums)

    out = wf.run_dir / f"enriched-{date}.json"
    if enriched is None:
        print(f"⚠ enrich 失败({err}), 全部条目降级文章原文")
        enriched = {}
    ok = {n: r for n, r in (enriched or {}).items() if r}
    out.write_text(json.dumps({"date": date, "items": ok}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"enrich: {len(ok)}/{len(sel)} 条扩写成功 → {out}")
    return {"enriched_path": str(out), "enriched_items": len(ok)}


def _parse_enrich(raw: str, art_nums: dict, mat_nums: set):
    """解析 enrich JSON + 条目级数字保真(原文∪素材并集)。返回 ({n: rec}, err)。"""
    m = re.search(r"\{[\s\S]*\}", (raw or "").strip())
    if not m:
        return None, "无 JSON"
    try:
        data = json.loads(m.group(0))
    except Exception as e:
        return None, f"解析失败: {e}"
    out = {}
    for o in data.get("items") or []:
        n = o.get("n")
        if not isinstance(n, int) or n not in art_nums:
            continue
        summary = str(o.get("summary") or "").strip()
        lines = [l for l in (o.get("lines") or [])
                 if isinstance(l, dict) and str(l.get("label", "")).strip() and str(l.get("text", "")).strip()]
        if not summary or not lines:
            continue
        all_text = summary + "".join(l["text"] for l in lines)
        stat = o.get("stat") if isinstance(o.get("stat"), dict) else None
        if stat and stat.get("value"):
            all_text += str(stat["value"]) + str(stat.get("unit", ""))
        # 条目级数字保真: 口播数字 ⊆ 原文 ∪ 素材
        allowed = art_nums[n] | mat_nums
        bad = [num for num in re.findall(r"\d+(?:\.\d+)?", all_text) if num not in allowed]
        if bad:
            print(f"  ⚠ #{n} 数字失真{bad[:3]}, 该条降级文章原文")
            continue
        if any(w in all_text for w in BAN_WORDS) or _JUDGE.search(all_text):
            print(f"  ⚠ #{n} 禁词/判断句, 该条降级")
            continue
        if stat and (not stat.get("value") or len(str(stat.get("value"))) > 12):
            stat = None
        out[n] = {"summary": summary, "stat": stat, "lines": lines[:3]}
    if not out:
        return None, "无有效条目"
    return out, ""
