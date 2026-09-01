"""blocks -> 微信公众号内联样式 HTML(参照 doocs/md 的排版经验, WTFPL)

微信编辑器会过滤外部 CSS/部分标签, 所以所有样式必须内联, 且:
  - hr 标签会被过滤 → 用带 border-top 的 section 模拟
  - ul/li 样式易丢   → 列表转成带前缀符号("•"/"1.")的段落
  - 外链图片会被屏蔽 → 本地图读成 base64 内联, 远程图下载后 base64
    (编辑器收到 data URI 图片会自动转存公众号素材库)
用法: render(blocks, art_dir) -> html 字符串(可直接注入编辑器)
"""

import base64
import html as _html
import mimetypes
from pathlib import Path

# 排版常量(参照 doocs/md 默认主题的观感)
INK = "#3f3f3f"          # 正文色
ACCENT = "#1e80ff"       # 主题蓝(标题点缀/加粗)
P_MARGIN = "10px 0"
LINE = "1.75"


def _esc(t: str) -> str:
    return _html.escape(t or "", quote=False)


def _img_to_data_uri(src: str, art_dir) -> str:
    """图片转 data URI; 本地找不到/下载失败返回 ""(调用方降级为占位文字)。"""
    try:
        p = Path(src)
        if not p.is_absolute() and art_dir:
            cand = Path(art_dir) / src
            if cand.exists():
                p = cand
        if p.exists():
            mime = mimetypes.guess_type(str(p))[0] or "image/png"
            return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()
        if src.startswith(("http://", "https://")):
            import requests
            r = requests.get(src, timeout=20)
            r.raise_for_status()
            mime = r.headers.get("Content-Type", "image/png").split(";")[0]
            if mime.startswith("image/"):
                return f"data:{mime};base64," + base64.b64encode(r.content).decode()
    except Exception:
        pass
    return ""


def _runs_html(runs: list) -> str:
    out = []
    for r in runs or []:
        t = _esc(r.get("text", ""))
        if not t:
            continue
        if r.get("italic"):
            t = f"<em style=\"font-style:italic\">{t}</em>"
        if r.get("bold"):
            t = f"<strong style=\"color:{ACCENT};font-weight:bold\">{t}</strong>"
        out.append(t)
    return "".join(out)


def _h(level: int, inner: str) -> str:
    size = {1: 20, 2: 17, 3: 16}.get(level, 15)
    style = (f"margin:{'28' if level == 1 else '22'}px 0 12px;font-size:{size}px;"
             f"font-weight:bold;color:{'inherit' if level == 1 else INK};line-height:1.4;")
    if level == 2:      # 二级标题加主题色竖条, doocs/md 经典样式
        style += f"border-left:4px solid {ACCENT};padding-left:10px;"
    return f"<h{level} style=\"{style}\">{inner}</h{level}>"


def render(blocks: list, art_dir=None) -> str:
    """结构化块 -> 公众号内联样式 HTML。"""
    parts, list_no = [], 0
    for b in blocks or []:
        typ = b.get("type")
        runs_html = _runs_html(b.get("runs"))
        if typ == "heading":
            parts.append(_h(int(b.get("level", 2)) or 2, runs_html or _esc(b.get("text", ""))))
            list_no = 0
        elif typ == "list_item":
            list_no = list_no + 1 if b.get("ordered") else 0
            prefix = f"{list_no}. " if b.get("ordered") else "• "
            parts.append(
                f"<p style=\"margin:{P_MARGIN};padding-left:1.2em;text-indent:-1.2em;"
                f"color:{INK};line-height:{LINE};font-size:15px;\">"
                f"<span style=\"color:{ACCENT}\">{prefix}</span>{runs_html}</p>")
        elif typ == "image":
            alt = _esc(b.get("alt") or "")
            uri = _img_to_data_uri(b.get("src", ""), art_dir)
            if uri:
                parts.append(
                    f"<img src=\"{uri}\" alt=\"{alt}\" style=\"width:100%;"
                    f"border-radius:4px;margin:12px 0;display:block;\">")
            else:
                parts.append(
                    f"<p style=\"margin:{P_MARGIN};color:#999;font-size:13px;"
                    f"line-height:{LINE};\">[图片未嵌入: {alt or b.get('src', '')}]</p>")
        elif typ == "hr":
            parts.append(
                f"<section style=\"border-top:1px dashed #e5e5e5;"
                f"margin:20px 0;font-size:0;line-height:0;\">&nbsp;</section>")
        else:           # paragraph / 未知类型一律按段落
            parts.append(
                f"<p style=\"margin:{P_MARGIN};color:{INK};line-height:{LINE};"
                f"letter-spacing:.4px;font-size:15px;\">{runs_html}</p>")
    return (
        f"<section style=\"font-size:15px;color:{INK};line-height:{LINE};"
        f"letter-spacing:.4px;word-break:break-word;text-align:justify;\">"
        + "".join(parts) + "</section>")
