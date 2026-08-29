"""口播稿步骤: 文章来龙去脉 → 口播稿(单一文本源, 零 LLM) → 机检 → 人工过稿。

四家设计共识(codex/grok/gemini/kimi-k3 独立方案汇总裁决):
- 口播正文 = 文章条目原文逐字(音画一致靠构造保证, 不靠提示词自觉)
- 口播稿是视频的源头文案: review 审核点过稿后才出片; 人直接改 md, 续跑生效
- 板块词只进画面 kicker, 绝不进口播; 正则机检拦板块判断句
"""

import re
import sys
from pathlib import Path

from flows.steps import step

SPEED = 4.2          # 晓晓实测语速(字/秒, 与 build.mjs estimate 同口径)
MAX_SECONDS = 330    # 总时长硬顶(5.5 分钟)

BAN_WORDS = ("买入", "卖出", "建仓", "加仓", "减仓", "抄底", "止盈", "止损",
             "清仓", "满仓", "目标价", "上车", "下车", "布局", "梭哈",
             "AI解读", "AI整理", "AI生成", "AI播报", "由AI", "人工智能生成")
# 口播禁板块判断句(方向词×板块词共现 / 建议式表述)
_JUDGE_PATTERNS = [
    r"(利好|利空|看多|看空|承压)[了的是]?.{0,6}(板块|概念|方向|个股|行情)",
    r"(板块|概念|方向|行情).{0,8}(利好|利空|机会|风险|受益|受损|值得)",
    r"(值得关注|可关注|建议关注|重点关注).{0,10}(板块|概念|个股|方向)",
]


@step("render_morning_script")
def render_morning_script(ctx, wf, params):
    """文章+图卡 → 口播稿 md(人看人改正本)。with: {top: 10}。零 LLM。"""
    date = wf.date
    digest_p = ctx.get("image_digest_path")
    article_p = ctx.get("article_path") or ctx.get("tagged_path")
    if not digest_p or not Path(digest_p).exists():
        sys.exit("口播稿依赖长图存档: 需 --set with_image=true")
    if not article_p or not Path(article_p).exists():
        sys.exit("口播稿依赖文章产物")
    import json
    payload = json.loads(Path(digest_p).read_text(encoding="utf-8"))
    cards = payload.get("cards") or []
    article = Path(article_p).read_text(encoding="utf-8")

    from flows.steps.image import _index_with_tags
    items, _ = _index_with_tags(article)
    text_of = {it["n"]: it["text"] for it in items}
    sel = [c for c in cards if c["n"] in text_of][: int(params.get("top", 10))]
    if len(sel) < 4:
        sys.exit(f"可播报条目过少({len(sel)})")

    from datetime import datetime
    try:
        d = datetime.strptime(date, "%Y-%m-%d")
        date_cn = f"{d.month}月{d.day}日"
    except ValueError:
        date_cn = date

    intro = (f"早上好,今天是{date_cn},财经早报,今天共{len(sel)}条要闻,"
             f"先看头版:{sel[0]['title']}。")
    outro = "以上就是今天的财经早报,内容基于公开信息整理,不构成投资建议。关注我,每天几分钟看懂财经。"

    blocks = []                       # [(kicker, headline, text, n)]
    for i, c in enumerate(sel, 1):
        pill = c.get("pill")
        pill = pill if pill not in (None, "", "-") else "要闻"
        blocks.append((f"{i:02d}·{pill}", c["title"], text_of[c["n"]].strip(), c["n"]))

    # ---- 机检(过稿前拦截) ----
    report = _lint_script(intro, outro, blocks, text_of)
    total_chars = len(intro) + len(outro) + sum(len(b[2]) for b in blocks) + 2 * len(blocks)
    est = total_chars / SPEED + (len(blocks) + 2) * 0.8
    if est > MAX_SECONDS:
        sys.exit(f"口播稿预估 {est:.0f}s 超 {MAX_SECONDS}s 硬顶, 请降 video_top 后重跑")

    md = _render_md(date, intro, outro, blocks, est, report)
    out = wf.run_dir / f"口播稿-{date}.md"
    out.write_text(md, encoding="utf-8")
    print(f"口播稿: {out} ({len(blocks)}条, 正文{total_chars}字, 预估{est:.0f}s ≈ {est/60:.1f}分钟)")
    if report["fail"]:
        print(f"⚠ 机检未过: {report['fail']}")
    else:
        print(f"机检: 通过{'(警告' + str(len(report['warn'])) + '条)' if report['warn'] else ''}")
    print("过稿: 直接编辑该 md 保存后, 重跑同一命令续跑出片; 重新生成用 --from script")
    if report["fail"]:
        sys.exit(f"口播稿机检未过: {report['fail']}")
    return {"script_path": str(out), "script_items": len(blocks),
            "script_seconds": round(est)}


def _lint_script(intro, outro, blocks, text_of):
    """数字保真/禁词/板块判断句。fail=阻断, warn=提示人工。"""
    fail, warn = [], []
    all_text = intro + outro + "".join(b[2] for b in blocks)
    for w in BAN_WORDS:
        if w in all_text:
            fail.append(f"禁词「{w}」")
    for pat in _JUDGE_PATTERNS:
        for m in re.finditer(pat, all_text):
            fail.append(f"板块判断句「{m.group(0)}」")
    for i, (_, _, text, n) in enumerate(blocks, 1):
        src = text_of.get(n) or ""
        for num in re.findall(r"\d+(?:\.\d+)?", text):
            if not re.search(rf"(?<!\d){re.escape(num)}(?!\d)", src):
                fail.append(f"#{i} 数字失真: {num}")
        if len(text) > 130:
            warn.append(f"#{i} 正文{len(text)}字偏长")
        if re.search(r"据报|被曝|消息人士", src) and not re.search(r"据报|被曝|消息人士|援引|知情人士", text):
            warn.append(f"#{i} 传闻限定词缺失")
    if "投资建议" not in outro:
        fail.append("收尾缺免责")
    return {"fail": fail, "warn": warn}


def _render_md(date, intro, outro, blocks, est, report):
    from datetime import datetime
    try:
        wd = "一二三四五六日"[datetime.strptime(date, '%Y-%m-%d').weekday()]
    except ValueError:
        wd = ""
    lines = [
        f"# 早报口播稿 {date} 周{wd}",
        f"<!-- 预估 {est/60:.1f} 分钟 | {len(blocks)} 条 | 机检: "
        f"{'通过' if not report['fail'] else '未过'}"
        f"{' / 警告' + str(len(report['warn'])) + '条' if report['warn'] else ''} -->",
        "<!-- 本稿 = 画面详情 = 语音(单一文本源)。过稿: 直接改正文保存, 重跑命令续跑出片;",
        "     整条删除可直接删段落(自动重编号); 重新生成用 --from script(会覆盖人工修改) -->",
        "",
        "## 开场",
        intro,
        "",
    ]
    for k, headline, text, _n in blocks:
        lines += [f"## {k} | {headline}", text, ""]
    lines += ["## 收尾", outro, ""]
    return "\n".join(lines)
