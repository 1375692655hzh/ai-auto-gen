"""早报的多形态产出:①长图卡片 ②群发模板 ③同行式早报文章。(视频由 video 子系统负责)

输入:daily JSON 的 entries(工作流 expand 步骤的产物)。
"""

import json
import re
import textwrap
from pathlib import Path

from common import GEN_ROOT, today, out_dir, save_text

FONT_REG = r"C:\Windows\Fonts\msyh.ttc"
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"

CAT_COLORS = {  # 分类主题色(RGB)
    "宏观政策": (31, 78, 121), "公司动态": (0, 122, 87), "行业产业": (153, 68, 100),
    "海外市场": (140, 94, 15), "大宗商品": (122, 63, 42),
}
DEFAULT_COLOR = (60, 60, 67)


# ---------- ② 群发模板(固定格式,直接可发微信群/QQ群) ----------

def build_group_msg(entries: list, date: str | None = None) -> str:
    date = date or today()
    L = [f"🌅 AI财经早报 | {date}", "━━━━━━━━━━━━━━"]
    for i, e in enumerate(entries, 1):
        a = e.get("analysis") or {}
        L.append(f"{i}. [{e['category']}] {e['title']}")
        if a.get("impact"):
            L.append(f"   💡 {a['direction']}:{a['impact']}")
    L.append("━━━━━━━━━━━━━━")
    L.append(f"📌 今日看点:{';'.join(e['title'] for e in entries[:3])}")
    L.append("⚠️ 内容基于公开信息AI整理,不构成投资建议")
    return "\n".join(L)


# ---------- ③ 同行式早报文章(板块固定,简洁条目体) ----------

SECTION_ORDER = ["宏观政策", "行业产业", "公司动态", "海外市场", "大宗商品"]
SECTION_TITLES = {"宏观政策": "一、宏观与政策", "行业产业": "二、行业与产业",
                  "公司动态": "三、公司动态", "海外市场": "四、海外市场",
                  "大宗商品": "五、大宗商品"}


def build_morning_article(entries: list, date: str | None = None) -> str:
    date = date or today()
    L = [f"# AI财经早报 | {date}", ""]
    L.append(f"**【导读】**今日共 {len(entries)} 条要闻:"
             + ";".join(e["title"] for e in entries[:3]) + " 等。")
    L.append("")
    for sec in SECTION_ORDER:
        sec_entries = [e for e in entries if e.get("category") == sec]
        if not sec_entries:
            continue
        L.append(f"## {SECTION_TITLES[sec]}")
        L.append("")
        for e in sec_entries:
            a = e.get("analysis") or {}
            tags = "/".join(filter(None, (a.get("sectors") or []) + (a.get("concepts") or [])))
            detail = (e.get("detail_paragraphs") or [""])[0]
            L.append(f"**{e['title']}**")
            if detail:
                L.append(detail.strip())
            if tags or a.get("impact"):
                note = f"〔关联:{tags}·{a.get('direction','中性')}" + (f"——{a['impact']}" if a.get("impact") else "") + "〕"
                L.append(note)
            L.append("")
    L.append("---")
    L.append("> 内容基于公开信息由 AI 整理,不构成投资建议。")
    return "\n".join(L)


# ---------- ① 长图卡片(Pillow 渲染,1080 宽,一条一卡) ----------

def _font(size, bold=False):
    from PIL import ImageFont
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)


def _wrap(draw, text, font, max_w):
    lines, line = [], ""
    for ch in text:
        if draw.textlength(line + ch, font=font) <= max_w:
            line += ch
        else:
            lines.append(line)
            line = ch
    if line:
        lines.append(line)
    return lines


def render_long_image(entries: list, date: str | None = None,
                      out_path: Path | None = None) -> Path:
    from PIL import Image, ImageDraw
    date = date or today()
    W, PAD, CARD_PAD = 1080, 40, 36
    out_path = out_path or (GEN_ROOT / "output" / "daily" / f"早报长图-{date}.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 先用画布测文字,再算每张卡高度
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    f_title, f_body, f_tag = _font(44, True), _font(32), _font(30, True)
    inner_w = W - PAD * 2 - CARD_PAD * 2
    DIR_COLORS = {"利好": (200, 30, 40), "利空": (0, 130, 80), "中性": (110, 110, 120)}

    cards = []
    for e in entries:
        a = e.get("analysis") or {}
        title_lines = _wrap(probe, e["title"], f_title, inner_w)[:2]
        detail = (e.get("detail_paragraphs") or [""])[0].strip()
        body_lines = _wrap(probe, detail[:120], f_body, inner_w)[:3]
        tags = "/".join(filter(None, (a.get("sectors") or []) + (a.get("concepts") or [])))
        impact = a.get("impact", "")
        direction = a.get("direction", "中性")
        tag_line = f"解读 | 关联:{tags} · {direction} —— {impact}" if (tags or impact) else ""
        tag_lines = _wrap(probe, tag_line, f_tag, inner_w)[:2] if tag_line else []
        h = (CARD_PAD * 2 + 46 + len(title_lines) * 58 + 14
             + len(body_lines) * 44 + 14 + len(tag_lines) * 42)
        cards.append((e, title_lines, body_lines, tag_lines, h, direction))

    # 头部高度按"今日看点"实际行数动态计算,避免截断
    top3_lines = _wrap(probe, "今日看点:" + " / ".join(e["title"] for e in entries[:3]),
                       _font(30), W - PAD * 2)[:2]
    head_h = 300 + len(top3_lines) * 44
    foot_h = 150
    H = head_h + sum(c[4] + 24 for c in cards) + foot_h + PAD
    img = Image.new("RGB", (W, H), (244, 245, 247))
    d = ImageDraw.Draw(img)

    # 头部
    d.rectangle([0, 0, W, head_h], fill=(17, 34, 64))
    d.text((PAD, 56), "AI 财经早报", font=_font(64, True), fill=(255, 255, 255))
    d.text((PAD, 152), f"{date} · 今日 {len(entries)} 条要闻", font=_font(36), fill=(185, 200, 225))
    for i, ln in enumerate(top3_lines):
        d.text((PAD, 240 + i * 44), ln, font=_font(30), fill=(150, 172, 205))

    # 卡片
    y = head_h + PAD
    for e, title_lines, body_lines, tag_lines, h, direction in cards:
        color = CAT_COLORS.get(e.get("category"), DEFAULT_COLOR)
        d.rounded_rectangle([PAD, y, W - PAD, y + h], radius=20, fill=(255, 255, 255))
        d.rectangle([PAD, y + 20, PAD + 10, y + h - 20], fill=color)
        cy = y + CARD_PAD
        d.text((PAD + CARD_PAD, cy), f"{e.get('category','')} · {e.get('time','')[5:] if e.get('time') else ''}",
               font=f_tag, fill=color)
        cy += 46
        for ln in title_lines:
            d.text((PAD + CARD_PAD, cy), ln, font=f_title, fill=(20, 20, 24))
            cy += 58
        cy += 8
        for ln in body_lines:
            d.text((PAD + CARD_PAD, cy), ln, font=f_body, fill=(90, 90, 98))
            cy += 44
        cy += 14
        for ln in tag_lines:
            d.text((PAD + CARD_PAD, cy), ln, font=f_tag, fill=DIR_COLORS.get(direction, (110, 110, 120)))
            cy += 42
        y += h + 24

    # 尾部
    d.text((PAD, H - foot_h + 30), "内容基于公开信息由 AI 整理,不构成投资建议",
           font=_font(28), fill=(130, 130, 138))
    d.text((PAD, H - foot_h + 80), "AI财经日报 · 每天几分钟看懂财经",
           font=_font(28, True), fill=(17, 34, 64))
    img.save(out_path)
    return out_path


def run_all(date: str | None = None) -> dict:
    """从 daily JSON 生成三形态产物。"""
    date = date or today()
    data_file = GEN_ROOT / "output" / "daily" / f"daily-{date}.json"
    entries = json.loads(data_file.read_text(encoding="utf-8"))

    group = out_dir("research_dir").parent / "daily" / f"群发模板-{date}.txt"
    group.parent.mkdir(parents=True, exist_ok=True)
    group.write_text(build_group_msg(entries, date), encoding="utf-8")

    article = save_text(out_dir("articles_dir") / f"AI财经早报-{date}.md",
                        build_morning_article(entries, date))
    img = render_long_image(entries, date)
    return {"group": group, "article": article, "image": img}


if __name__ == "__main__":
    import sys
    for k, p in run_all(sys.argv[1] if len(sys.argv) > 1 else None).items():
        print(k, "->", p)
