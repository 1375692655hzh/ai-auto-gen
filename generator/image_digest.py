"""早报长图渲染器 v2 紧凑版(morning-digest 专用, 不碰 formats.render_long_image)。

输入: image-digest payload(见 flows/steps/image.py) + 日期 + 输出路径。
v2(手机优先, 4574→约2780, 约2.4屏):
- 标签降级为标题行行首彩色胶囊; 解读右置标题行行尾(红▲/绿▼信号灯轨道)
- 条目等高 112px 列表式(节容器白底圆角+左缘色条, 节内 1px 细线分隔)
- 字阶收敛三级: 40 标题 / 28 要点·节名 / 24 标签·解读·计数·热度·免责
设计: codex+kimi 独立方案综合裁决(kimi 右置解读 / codex 溢出防御与字阶底线)。
"""

import re
from pathlib import Path

from formats import _font, _wrap, _load_img_tmpl, CAT_COLORS, DEFAULT_COLOR

W, M = 1080, 32                       # 画布宽 / 页边距
CW = W - M * 2                        # 内容宽 1016
ITEM_H, HEAD_H, SEC_HEAD, SEC_GAP = 112, 164, 56, 14
BG, HEAD = (245, 246, 250), (17, 34, 64)
LINE_GREY, TXT_GREY, CNT_GREY = (228, 230, 235), (92, 100, 112), (138, 144, 153)
DIR_MARK = {"利好": ("▲", (216, 64, 52)), "利空": ("▼", (30, 158, 90)),
            "中性": ("◆", (130, 130, 140)), "承压": ("▼", (150, 118, 52)),
            "关注": ("◆", (130, 130, 140))}


def _truncate(draw, text, font, max_w):
    """超宽截断加省略号。"""
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text + "…"


def _dir_line(c: dict) -> str:
    """解读文案(右置短版): ▲AI·软件。中性零信息不占位。"""
    sectors = c.get("sectors") or []
    direction = c.get("direction") or ""
    if not sectors or not direction or direction == "中性":
        return ""
    return f"{DIR_MARK.get(direction, ('◆',))[0]}{'·'.join(sectors[:3])}"


def _pill(draw, x, y, text, color, probe):
    """彩色胶囊标签, 返回右端 x。"""
    f = _font(24, True)
    w = probe.textlength(text, font=f) + 20
    draw.rounded_rectangle([x, y, x + w, y + 34], radius=6, fill=color)
    draw.text((x + 10, y + 5), text, font=f, fill=(255, 255, 255))
    return x + w


def render_digest_image(payload: dict, date: str, out_path: str):
    from PIL import Image, ImageDraw
    try:
        _font(28)                                    # 字体缺失在此显式暴露
    except OSError as e:
        raise RuntimeError(f"中文字体不可用, 长图渲染中止: {e}") from e

    tmpl = _load_img_tmpl()
    cards = payload["cards"]
    focus = (payload.get("focus") or [])[:2]         # 头部只留最强 2 条钩子
    ann = payload.get("ann_summary") or []

    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))

    # ---- 高度预算(两段式: 先 measure 再建画布) ----
    cats = ("宏观政策", "公司动态", "行业产业", "海外市场", "大宗商品", "公司公告")
    sections = [(cat, [c for c in cards if c["cat"] == cat]) for cat in cats]
    sections = [(cat, cs) for cat, cs in sections if cs]
    focus_h = len(focus) * 34
    head_h = 20 + 56 + 8 + focus_h + 14 + 16
    body = sum(SEC_HEAD + len(cs) * ITEM_H + 10 for _, cs in sections)
    gaps = SEC_GAP * max(0, len(sections) - 1)
    ann_rows = (min(len(ann), 8) + 1) // 2
    ann_h = SEC_HEAD + ann_rows * 38 + 14 if ann else 0
    foot_h = 100
    H = head_h + 16 + body + gaps + (ann_h + 14 if ann else 0) + foot_h

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # ---- 头部: 主标+右侧日期条数 / 金线 / 今日焦点(标签内联) ----
    d.rectangle([0, 0, W, head_h], fill=HEAD)
    d.text((M, 20), tmpl["title"], font=_font(46, True), fill=(255, 255, 255))
    sub = f"{date} · {len(cards)}条"
    d.text((W - M - probe.textlength(sub, font=_font(24)), 34),
           sub, font=_font(24), fill=(150, 168, 196))
    fy = 20 + 56 + 8
    d.text((M, fy), "今日焦点", font=_font(24, True), fill=(255, 215, 80))
    fx = M + probe.textlength("今日焦点", font=_font(24, True)) + 14
    for i, f in enumerate(focus):
        d.text((fx if i == 0 else M, fy + i * 34),
               _truncate(probe, f, _font(24), W - M - (fx if i == 0 else M)),
               font=_font(24), fill=(214, 224, 240))

    # ---- 分类节容器 + 等高条目 ----
    y = head_h + 16
    for cat, cs in sections:
        color = CAT_COLORS.get(cat, DEFAULT_COLOR)
        sh = SEC_HEAD + len(cs) * ITEM_H + 10
        d.rounded_rectangle([M, y, W - M, y + sh], radius=12, fill=(255, 255, 255))
        d.rectangle([M + 4, y + 14, M + 8, y + sh - 14], fill=color)
        d.text((M + 24, y + 10), cat, font=_font(28, True), fill=color)
        cnt = f"{len(cs)}条"
        d.text((W - M - 20 - probe.textlength(cnt, font=_font(24)), y + 13),
               cnt, font=_font(24), fill=CNT_GREY)
        d.line([M + 24 + probe.textlength(cat, font=_font(28, True)) + 14,
                y + 28, W - M - 20 - probe.textlength(cnt, font=_font(24)) - 14, y + 28],
               fill=LINE_GREY, width=1)
        iy = y + SEC_HEAD
        for k, c in enumerate(cs):
            top = iy + k * ITEM_H
            _draw_item(d, probe, c, color, top)
            if k < len(cs) - 1:
                d.line([M + 24, top + ITEM_H, W - M - 20, top + ITEM_H],
                       fill=LINE_GREY, width=1)
        y += sh + SEC_GAP

    # ---- 公告热度: 两列网格 ----
    if ann:
        y -= SEC_GAP
        d.rounded_rectangle([M, y, W - M, y + ann_h], radius=12, fill=(255, 255, 255))
        d.text((M + 24, y + 10), "今日公告热度", font=_font(26, True), fill=(75, 85, 110))
        mx = max(n for _, n in ann)
        shown = ann[:8]
        for i, (name, cnt) in enumerate(shown):
            col, row = i % 2, i // 2
            x0 = M + 24 + col * 496
            ry = y + SEC_HEAD + row * 38
            d.text((x0, ry), _truncate(probe, name, _font(24), 130),
                   font=_font(24), fill=(63, 70, 80))
            bar_w = max(16, int(130 * cnt / mx)) if mx else 16
            d.rounded_rectangle([x0 + 140, ry + 8, x0 + 140 + 130, ry + 16],
                                radius=4, fill=(238, 241, 244))      # 基座
            d.rounded_rectangle([x0 + 140, ry + 8, x0 + 140 + bar_w, ry + 16],
                                radius=4, fill=(75, 85, 110))
            d.text((x0 + 140 + 130 + 10, ry), f"{cnt}", font=_font(24), fill=CNT_GREY)
        y += ann_h

    # ---- 尾部 ----
    d.line([M, H - foot_h + 6, W - M, H - foot_h + 6], fill=LINE_GREY, width=1)
    d.text((M, H - foot_h + 22), tmpl["footer1"], font=_font(24), fill=(150, 156, 164))
    d.text((M, H - foot_h + 56), tmpl["footer2"], font=_font(24, True), fill=HEAD)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, quality=92)
    return out_path


def _draw_item(d, probe, c: dict, color, top: int):
    """单条目(等高 112px): 行1 = 标签胶囊+标题+HOT+右置解读 / 行2 = 要点。"""
    left = M + 24
    right = W - M - 20
    r1y = top + 11                                 # 行1 基准 y
    dirline = _dir_line(c)
    dir_w = probe.textlength(dirline, font=_font(24, True)) + 14 if dirline else 0
    hot = bool(c.get("hot"))
    hot_w = 66 if hot else 0
    # 标签胶囊
    tag_end = _pill(d, left, r1y + 7, c["tag"], color, probe)
    tx = tag_end + 12
    # 右置解读(先画, 标题据此截断)
    if dirline:
        _, mc = DIR_MARK.get(c["direction"], ("◆", (130, 130, 140)))
        d.text((right - dir_w + 14, r1y + 8), dirline, font=_font(24, True), fill=mc)
    # HOT 小胶囊(解读左侧)
    if hot:
        hx = right - dir_w - hot_w
        d.rounded_rectangle([hx, r1y + 7, hx + hot_w - 10, r1y + 41], radius=6,
                            fill=(206, 52, 52))
        d.text((hx + 10, r1y + 12), "HOT", font=_font(22, True), fill=(255, 255, 255))
    # 标题(40px 唯一大字锚点)
    max_w = right - dir_w - hot_w - 16 - tx
    d.text((tx, r1y), _truncate(probe, c["title"], _font(40, True), max_w),
           font=_font(40, True), fill=(20, 20, 24))
    # 行2 要点
    d.text((left, top + 66), _truncate(probe, c["point"], _font(28), right - left),
           font=_font(28), fill=TXT_GREY)
