"""图表缺口自动补全(发知乎等无图平台时用)

知乎图片常传不上, 文中"下表/下图/如图"等依赖图表的句子, 没图就读不通。
本模块: 检测这类句子, 用你配置的模型(见 llm.py / 网页「模型 API 设置」)
在该位置补一句文字说明(把图表关键信息文字化), 其余原文和格式完全不动。

只补"图表缺口", 不改写正文、不动风格、不动标题加粗。
没配模型 API 时优雅降级: 图表缺口处不补文字(图块直接丢弃), 不影响其余正文发布。
"""

import re

import llm

# 依赖图表的触发词(段落含这些 → 它后面大概率有图, 没图就断了)
_CHART_REF = re.compile(r"下表|下图|如下表|如下图|如图|见图|见下|上表|上图|换算到[^，。]{0,20}口径")


def _blocktext(blk):
    return "".join(r.get("text", "") for r in blk.get("runs", []))


def _call_model(prompt: str, timeout: int = 90) -> str:
    """调团队配置的模型 API(llm.complete)。未配置/失败返回空。"""
    return llm.complete(prompt, max_tokens=128, temperature=0.3, timeout=timeout)


def _rows_to_blocks(spec):
    """把一张表格图的转写(lead + rows)变成正文块: lead 段 + 每行一个列表项(环节名加粗)。"""
    import os as _os
    out = []
    lead = (spec or {}).get("lead", "").strip()
    if lead:
        out.append({"type": "paragraph",
                    "runs": [{"text": lead, "bold": False, "italic": False, "stock": None}]})
    for row in (spec or {}).get("rows", []):
        if not row:
            continue
        label = str(row[0]).strip()
        detail = str(row[1]).strip() if len(row) > 1 else ""
        runs = [{"text": label, "bold": True, "italic": False, "stock": None}]
        if detail:
            runs.append({"text": "：" + detail, "bold": False, "italic": False, "stock": None})
        out.append({"type": "list_item", "runs": runs})
    return out


def fill_chart_gaps(blocks, logger=None, transcriptions=None, only_transcribed=False):
    """返回新 blocks: 把图表图替换成文字。优先级:
    ① 有人工转写(transcriptions[basename]) → 用 _rows_to_blocks 完整文字化(表格数据全保留, 环节名加粗);
    ② 前文明确提到图表(下表/下图…) → Claude 补一句文字说明;
    ③ 否则视为装饰图 → 删除。
    原有正文/格式完全不动。transcriptions: {图片basename: {lead, rows}}。
    only_transcribed=True: 只把"有转写"的表格图换成文字, 其余图原样保留(给能正常显示图、但表格图传不上的平台用, 如东财)。
    """
    transcriptions = transcriptions or {}

    def log(m):
        if logger:
            logger.info(f"[chart_gap] {m}")

    import os as _os
    new = []
    n = len(blocks)
    filled = 0
    tabled = 0
    for i, blk in enumerate(blocks):
        if blk["type"] != "image":
            new.append(blk)
            continue
        # ① 人工转写优先(表格类图最可靠): 按图片文件名匹配
        base = _os.path.basename(blk.get("src", ""))
        if base in transcriptions:
            tb = _rows_to_blocks(transcriptions[base])
            new.extend(tb)
            tabled += 1
            log(f"表格图文字化: {base} → {len(tb)} 块")
            continue
        # only_transcribed: 没转写的图原样保留(交给平台上传), 不删不补
        if only_transcribed:
            new.append(blk)
            continue
        # image 块: 找它前面最近的非空文本段(图的说明上下文)
        ctx_before = ""
        for j in range(i - 1, max(-1, i - 4), -1):
            t = _blocktext(blocks[j]) if blocks[j].get("runs") else ""
            if t.strip():
                ctx_before = t
                break
        ctx_after = ""
        for j in range(i + 1, min(n, i + 3)):
            t = _blocktext(blocks[j]) if blocks[j].get("runs") else ""
            if t.strip():
                ctx_after = t
                break
        # 只对"前文明确提到图表"的图做文字补全; 否则直接丢弃图(纯装饰图无需文字)
        if not _CHART_REF.search(ctx_before):
            log(f"图块(前文无图表引用)→ 跳过/删除: {ctx_before[-20:]!r}")
            continue
        prompt = (
            "你是财经研报编辑。下面这段研报正文提到了一张图/表, 但发布平台显示不了图。"
            "请你用一句话(最多40字)把这张图/表大概会呈现的关键信息文字化, 接在正文后面, "
            "保持研报客观专业的语气, 不要加'如图''如下'等字样, 不要展开议论, 只陈述图表会显示的核心对比或数据。"
            "只输出这一句话, 不要任何前后缀。\n\n"
            f"【图前正文】{ctx_before}\n【图后正文】{ctx_after}")
        sent = _call_model(prompt)
        sent = re.sub(r"^[\"'「『]|[\"'」』]$", "", sent).strip()
        if sent and len(sent) < 120:
            # 作为普通段落插入(纯文字, 无加粗)
            new.append({"type": "paragraph",
                        "runs": [{"text": sent, "bold": False, "italic": False, "stock": None}]})
            filled += 1
            log(f"补全: {sent[:30]}...")
        else:
            log(f"补全失败/为空, 丢弃图块: {ctx_before[-20:]!r}")
    log(f"完成: 表格文字化 {tabled} 张, 补全 {filled} 处图表缺口")
    return new


def load_transcriptions(article_id, articles_dir="articles"):
    """按文章名加载表格转写 sidecar: articles/_tables/<文章名>.json。无则返回 {}。"""
    import json
    from pathlib import Path
    stem = Path(article_id).stem
    f = Path(articles_dir) / "_tables" / f"{stem}.json"
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception:
        return {}
