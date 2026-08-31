"""早报的多形态产出:①长图卡片 ②群发模板 ③同行式早报文章。(视频由 video 子系统负责)

输入:daily JSON 的 entries(工作流 expand 步骤的产物)。
"""

import json
import re
import textwrap
from pathlib import Path

from common import GEN_ROOT, today, out_dir, save_text, load_cfg


def _resolve_font(kind: str) -> str:
    """中文字体路径: config.yaml fonts 段可覆盖; 否则按平台候选表探测。"""
    try:
        cfg = (load_cfg().get("fonts") or {})
        if cfg.get(kind):
            return cfg[kind]
    except Exception:
        pass
    cands = {
        "regular": [r"C:\Windows\Fonts\msyh.ttc",
                    "/System/Library/Fonts/PingFang.ttc",
                    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"],
        "bold": [r"C:\Windows\Fonts\msyhbd.ttc",
                 "/System/Library/Fonts/PingFang.ttc",
                 "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                 "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"],
    }[kind]
    for c in cands:
        if Path(c).exists():
            return c
    return cands[0]


FONT_REG = _resolve_font("regular")
FONT_BOLD = _resolve_font("bold")

CAT_COLORS = {  # 分类主题色(RGB)
    "宏观政策": (31, 78, 121), "公司动态": (0, 122, 87), "行业产业": (153, 68, 100),
    "海外市场": (140, 94, 15), "大宗商品": (122, 63, 42),
}
DEFAULT_COLOR = (60, 60, 67)

# ---------- 图片模板外置(P3): flows/templates/image/morning-card.yaml 或工作流包注入 ----------
IMG_TMPL = {}          # 工作流包运行前注入(优先)
_TMPL_FILE = Path(__file__).resolve().parent.parent / "flows" / "templates" / "image" / "morning-card.yaml"


def _load_img_tmpl() -> dict:
    """图片版式参数: title/subtitle/footer/cat_colors。包注入 > 模板文件 > 内置默认。"""
    t = dict(IMG_TMPL)
    if not t and _TMPL_FILE.exists():
        try:
            import yaml
            t = yaml.safe_load(_TMPL_FILE.read_text(encoding="utf-8")) or {}
        except Exception:
            t = {}
    t.setdefault("title", "AI 财经早报")
    t.setdefault("subtitle", "{date} · 今日 {n} 条要闻")
    t.setdefault("footer1", "内容基于公开信息由 AI 整理，不构成投资建议")
    t.setdefault("footer2", "AI财经日报 · 每天几分钟看懂财经")
    colors = t.get("cat_colors") or {}
    out_colors = {}
    for k, v in colors.items():
        if isinstance(v, (list, tuple)) and len(v) == 3:
            out_colors[k] = tuple(v)
    t["_colors"] = out_colors
    return t


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


def build_morning_article(entries: list, date: str | None = None, extras: dict | None = None) -> str:
    extras = extras or {}
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
    # 固定尾部板块:外围市场(倒数第三) → 事件日历(倒数第二) → 上市公司公告(最后)
    if extras.get("markets"):
        L.append("## 六、外围市场")
        L.append("")
        L.append(" · ".join(f"{m['name']} {m['price']}({m['chg_pct'] or '—'})"
                            for m in extras["markets"]))
        L.append("")
    if extras.get("calendar"):
        L.append("## 七、今日事件日历")
        L.append("")
        for c in extras["calendar"][:10]:
            star = "★" * min(c.get("importance", 2), 4)
            L.append(f"- {c['time']} [{c['country']}] {c['event']} {star}")
        L.append("")
    if extras.get("announcements"):
        L.append("## 八、上市公司公告")
        L.append("")
        for a in extras["announcements"][:10]:
            L.append(f"- **{a['company']}**:{a['title']}")
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


def render_long_image(entries: list, date: str | None = None, extras: dict | None = None,
                      out_path: Path | None = None) -> Path:
    from PIL import Image, ImageDraw
    extras = extras or {}
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

    # 尾部固定板块:外围市场(倒数第三) → 事件日历(倒数第二) → 上市公司公告(最后)
    SPECIALS = []  # (标题, 色块色, [(左文本, 右文本, 右色)])
    if extras.get("markets"):
        rows = [(m["name"], f"{m['price']}  {m['chg_pct'] or ''}".strip(),
                 (200, 30, 40) if m.get("chg_pct", "").startswith("+")
                 else (0, 130, 80) if m.get("chg_pct", "").startswith("-") else (110, 110, 120))
                for m in extras["markets"]]
        SPECIALS.append(("外围市场 · 隔夜涨跌", (31, 78, 121), rows))
    if extras.get("calendar"):
        rows = [(f"{c['time']} [{c['country']}]", f"{'★' * min(c.get('importance', 2), 4)} {c['event']}"[:46],
                 (60, 60, 67)) for c in extras["calendar"][:12]]
        SPECIALS.append(("今日事件日历", (153, 68, 100), rows))
    if extras.get("announcements"):
        rows = [(a["company"], a["title"][:44], (60, 60, 67))
                for a in extras["announcements"][:12]]
        SPECIALS.append(("上市公司公告", (122, 63, 42), rows))
    f_spec_l, f_spec_r = _font(34, True), _font(30)
    special_cards = []
    for title, color, rows in SPECIALS:
        row_lines = []
        for lt, rt, rc in rows:
            rl = _wrap(probe, rt, f_spec_r, inner_w - 260)[:2]
            row_lines.append((lt, rl, rc))
        h = CARD_PAD * 2 + 56 + sum(16 + len(rl) * 42 for _, rl, _ in row_lines)
        special_cards.append((title, color, row_lines, h))

    H = head_h + sum(c[4] + 24 for c in cards) + sum(sc[3] + 24 for sc in special_cards) + foot_h + PAD
    img = Image.new("RGB", (W, H), (244, 245, 247))
    d = ImageDraw.Draw(img)

    # 头部
    d.rectangle([0, 0, W, head_h], fill=(17, 34, 64))
    _tmpl = _load_img_tmpl()
    if _tmpl["_colors"]:
        CAT_COLORS.update(_tmpl["_colors"])
    d.text((PAD, 56), _tmpl["title"], font=_font(64, True), fill=(255, 255, 255))
    d.text((PAD, 152), _tmpl["subtitle"].format(date=date, n=len(entries)),
           font=_font(36), fill=(185, 200, 225))
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

    # 尾部固定板块卡片
    for title, color, row_lines, h in special_cards:
        d.rounded_rectangle([PAD, y, W - PAD, y + h], radius=20, fill=(255, 255, 255))
        d.rectangle([PAD, y + 20, PAD + 10, y + h - 20], fill=color)
        d.text((PAD + CARD_PAD, y + CARD_PAD), title, font=_font(40, True), fill=color)
        cy = y + CARD_PAD + 56
        for lt, rl, rc in row_lines:
            d.text((PAD + CARD_PAD, cy), lt, font=f_spec_l, fill=(30, 30, 36))
            for ln in rl:
                d.text((PAD + CARD_PAD + 240, cy), ln, font=f_spec_r, fill=rc)
                cy += 42
            cy += 16
        y += h + 24

    # 尾部
    d.text((PAD, H - foot_h + 30), _tmpl["footer1"], font=_font(28), fill=(130, 130, 138))
    d.text((PAD, H - foot_h + 80), _tmpl["footer2"], font=_font(28, True), fill=(17, 34, 64))
    img.save(out_path)
    return out_path


def run_all(date: str | None = None, extras: dict | None = None) -> dict:
    """从 daily JSON 生成三形态产物(extras 提供日历/外围市场/公告板块数据)。"""
    date = date or today()
    extras = extras or {}
    data_file = GEN_ROOT / "output" / "daily" / f"daily-{date}.json"
    entries = json.loads(data_file.read_text(encoding="utf-8"))

    group = out_dir("research_dir").parent / "daily" / f"群发模板-{date}.txt"
    group.parent.mkdir(parents=True, exist_ok=True)
    group.write_text(build_group_msg(entries, date), encoding="utf-8")

    article = save_text(out_dir("articles_dir") / f"AI财经早报-{date}.md",
                        build_morning_article(entries, date, extras))
    img = render_long_image(entries, date, extras)
    return {"group": group, "article": article, "image": img}


if __name__ == "__main__":
    import sys
    for k, p in run_all(sys.argv[1] if len(sys.argv) > 1 else None).items():
        print(k, "->", p)
