"""早报长图渲染器(morning-digest 专用, 不碰 formats.render_long_image——那是 morning-paper 的活代码)。

输入: image-digest payload(见 flows/steps/image.py 生成) + 日期 + 输出路径。
版式: 1080 宽 | 深蓝头部(标题+副标+今日看点3行) | 分类节(色带标题条) | 白卡(左色条
+标签行+标题短语+要点一行+解读行▲板块) | 公告热度条 | 免责尾。
设计参数来自五方设计(gemini 版式表/kimi 文案规范), v1 精简版。
"""

import re
from pathlib import Path

from formats import _font, _wrap, _load_img_tmpl, CAT_COLORS, DEFAULT_COLOR

W, PAD = 1080, 40
CARD_PAD, CARD_GAP, CARD_R = 28, 16, 16
SECTION_GAP = 28
BG, HEAD = (245, 246, 250), (17, 34, 64)
CAT_LIGHT = {   # 分类浅底色(节标题条用), 对应 CAT_COLORS
    "宏观政策": (230, 238, 247), "公司动态": (226, 243, 235), "行业产业": (244, 230, 238),
    "海外市场": (246, 238, 222), "大宗商品": (240, 228, 220), "公司公告": (232, 236, 243),
}
DIR_MARK = {"利好": ("▲", (206, 52, 52)), "利空": ("▼", (30, 140, 68)),
            "中性": ("◆", (130, 130, 140)), "承压": ("▼", (140, 110, 50)),
            "关注": ("◆", (130, 130, 140))}


def _truncate(draw, text, font, max_w):
    """超宽截断加省略号。"""
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text + "…"


def render_digest_image(payload: dict, date: str, out_path: str):
    from PIL import Image, ImageDraw
    try:
        _font(28)                                    # 字体缺失在此显式暴露
    except OSError as e:
        raise RuntimeError(f"中文字体不可用, 长图渲染中止: {e}") from e

    tmpl = _load_img_tmpl()
    cards = payload["cards"]
    focus = payload.get("focus") or []
    ann = payload.get("ann_summary") or []

    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))

    # ---- 高度预算(probe 预量) ----
    head_h = 210 + len(focus) * 44
    sections = []                                    # [(cat, cards, sec_h)]
    for cat in ("宏观政策", "公司动态", "行业产业", "海外市场", "大宗商品", "公司公告"):
        cs = [c for c in cards if c["cat"] == cat]
        if not cs:
            continue
        h = 68                                       # 节标题条
        for c in cs:
            h += _card_h(c) + CARD_GAP
        sections.append((cat, cs, h))
    ann_h = 90 + len(ann) * 44 if ann else 0
    foot_h = 150
    H = head_h + sum(sh + SECTION_GAP for _, _, sh in sections) + ann_h + foot_h + PAD

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # ---- 头部 ----
    d.rectangle([0, 0, W, head_h], fill=HEAD)
    d.text((PAD, 46), tmpl["title"], font=_font(52, True), fill=(255, 255, 255))
    d.text((PAD, 122), tmpl["subtitle"].format(date=date, n=len(cards)),
           font=_font(30), fill=(185, 200, 225))
    d.line([PAD, 170, W - PAD, 170], fill=(60, 80, 110), width=1)
    d.text((PAD, 186), "今日焦点", font=_font(26, True), fill=(255, 215, 80))
    for i, f in enumerate(focus[:3]):
        d.text((PAD + 24, 222 + i * 44), _truncate(probe, f, _font(28), W - PAD * 2 - 24),
               font=_font(28), fill=(220, 230, 245))

    # ---- 分类节 + 卡片 ----
    y = head_h + PAD
    for cat, cs, _ in sections:
        color = CAT_COLORS.get(cat, DEFAULT_COLOR)
        light = CAT_LIGHT.get(cat, (238, 240, 244))
        d.rounded_rectangle([PAD, y, W - PAD, y + 56], radius=12, fill=light)
        d.rectangle([PAD, y + 10, PAD + 6, y + 46], fill=color)
        d.text((PAD + 22, y + 10), f"{cat}", font=_font(30, True), fill=color)
        d.text((W - PAD - 24 - probe.textlength(f"{len(cs)}条", font=_font(26)), y + 14),
               f"{len(cs)}条", font=_font(26), fill=(130, 130, 140))
        y += 68
        for c in cs:
            ch = _card_h(c)                          # 有解读行加高, 防绘制溢出被下卡覆盖
            top = y
            d.rounded_rectangle([PAD, top, W - PAD, top + ch], radius=CARD_R,
                                fill=(255, 255, 255))
            d.rectangle([PAD, top + 14, PAD + 4, top + ch - 14], fill=color)
            cy = top + 24
            d.text((PAD + CARD_PAD, cy), f"{c['tag']}", font=_font(26), fill=color)
            if c.get("hot"):
                hx = PAD + CARD_PAD + probe.textlength(c["tag"], font=_font(26)) + 16
                d.rounded_rectangle([hx, cy - 2, hx + 62, cy + 32], radius=6, fill=(206, 52, 52))
                d.text((hx + 10, cy + 1), "HOT", font=_font(22, True), fill=(255, 255, 255))
            cy += 36
            d.text((PAD + CARD_PAD, cy), _truncate(probe, c["title"], _font(40, True), W - PAD * 2 - CARD_PAD),
                   font=_font(40, True), fill=(20, 20, 24))
            cy += 52
            d.text((PAD + CARD_PAD, cy), _truncate(probe, c["point"], _font(30), W - PAD * 2 - CARD_PAD),
                   font=_font(30), fill=(80, 80, 90))
            # 解读行: ▲板块·板块(方向色; 中性默认隐藏)
            line = _dir_line(c)
            if line:
                cy += 42
                mark, mc = DIR_MARK.get(c["direction"], ("◆", (130, 130, 140)))
                d.text((PAD + CARD_PAD, cy), _truncate(probe, line, _font(28), W - PAD * 2 - CARD_PAD),
                       font=_font(28, True), fill=mc)
            y = top + ch + CARD_GAP
        y += SECTION_GAP

    # ---- 公告热度 ----
    if ann:
        d.text((PAD, y), "今日公告热度", font=_font(30, True), fill=(75, 85, 110))
        y += 44
        mx = max(n for _, n in ann) if ann else 1
        for name, cnt in ann[:8]:
            d.text((PAD, y), name, font=_font(28), fill=(60, 60, 67))
            bar_w = int(360 * cnt / mx)
            d.rounded_rectangle([PAD + 150, y + 6, PAD + 150 + bar_w, y + 24],
                                radius=4, fill=(75, 85, 110))
            d.text((PAD + 150 + bar_w + 12, y), f"{cnt}", font=_font(26), fill=(130, 130, 140))
            y += 44

    # ---- 尾部 ----
    d.text((PAD, H - foot_h + 24), tmpl["footer1"], font=_font(26), fill=(130, 130, 138))
    d.text((PAD, H - foot_h + 68), tmpl["footer2"], font=_font(28, True), fill=HEAD)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, quality=92)
    return out_path


def _card_h(c: dict) -> int:
    """卡高: 基础158, 带解读行198(标签34+标题52+要点40+解读42+上下留白)。"""
    return 198 if _dir_line(c) else 158


def _dir_line(c: dict) -> str:
    """解读行文案: ▲芯片·AI (方向色由渲染定; 中性默认隐藏省版面)。"""
    sectors = c.get("sectors") or []
    direction = c.get("direction") or ""
    if not sectors or not direction:
        return ""
    if direction == "中性":
        return ""                                    # 零信息不占版面
    return f"{DIR_MARK.get(direction, ('◆',))[0]}{'·'.join(sectors)}"
