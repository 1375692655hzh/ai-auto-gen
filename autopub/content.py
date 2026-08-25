"""文章读取 + 内容处理(从 stock-media-v2 的 flatten.py 抽出的纯 Python 版)

一篇文章 = 一个 .md 文件:
  - 第一行非空行 = 标题
  - 其余 = 正文

提供:
  load_article(path)              -> {id, path, title, body, raw}
  flatten(text)                   -> 扁平化(去 markdown 语法,community 编辑器直接可读)
  strip_stock_tags(text)          -> $名字(SH600000)$ / $600000$ -> 纯文本(微博/股吧用)
  keep_stock_tags(text)           -> 原样保留(雪球/老虎用)

纯正则实现,不依赖 claude;表格用简单规则转成 "A / B / C" 行。
"""

import re
from pathlib import Path


# ---------- 读文章 ----------

def load_article(path) -> dict:
    """读单篇文章(.md 或 .docx),统一返回 title + blocks(+ 纯文本 body)。

    blocks: 结构化块(heading/paragraph/list_item/image/hr),行内保留 加粗/斜体/股票。
    body:   纯文本(给不支持富文本的平台用)。
    """
    p = Path(path)
    if p.suffix.lower() == ".docx":
        title, blocks = load_docx(p)
        return {
            "id": p.name, "path": p, "dir": p.parent,
            "title": title, "blocks": blocks,
            "body": blocks_to_plain(blocks), "raw": "",
        }
    # markdown / 纯文本
    raw = p.read_text(encoding="utf-8")
    body_text = _strip_frontmatter(_strip_html_comments(raw))
    lines = body_text.splitlines()
    title = ""
    body_start = 0
    for i, ln in enumerate(lines):
        if ln.strip():
            title = _clean_title(ln.strip())
            body_start = i + 1
            break
    body = "\n".join(lines[body_start:]).lstrip("\n")
    return {
        "id": p.name, "path": p, "dir": p.parent,
        "title": title, "blocks": parse_markdown(body),
        "body": body, "raw": raw,
    }


def _strip_frontmatter(md: str) -> str:
    """剥掉开头的 YAML frontmatter (--- ... ---)。"""
    m = re.match(r"^\s*---\n.*?\n---\n", md, flags=re.S)
    return md[m.end():] if m else md


def _clean_title(line: str) -> str:
    """标题清洗:去 markdown # 标题语法 / **加粗**,纯文本。"""
    line = re.sub(r"^#{1,6}\s*", "", line)
    line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
    return line.strip()


# ---------- 扁平化 ----------

def _strip_html_comments(md: str) -> str:
    """剥掉 HTML 注释(否则会被当正文发出去)。"""
    return re.sub(r"<!--.*?-->", "", md, flags=re.S).strip()


_TABLE_RE = re.compile(
    r"^\|[^\n]*\|[ \t]*\n"
    r"^\|[\s:|\-]+\|[ \t]*\n"
    r"(?:^\|[^\n]*\|[ \t]*\n?)+",
    re.MULTILINE,
)


def _table_to_text(m) -> str:
    """markdown 表格 -> 每行 "单元格1 / 单元格2 / ..." 的纯文本段。"""
    out = []
    for ln in m.group(0).splitlines():
        if not ln.strip():
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        # 跳过分隔行 |---|:--|
        if all(re.fullmatch(r"[:\-\s]*", c) for c in cells):
            continue
        out.append(" / ".join(c for c in cells if c))
    return "\n".join(out)


def flatten(text: str) -> str:
    """把 markdown 扁平化成 community 编辑器可直接输入的纯文本。

    - 去 HTML 注释
    - 表格 -> "A / B / C" 行
    - # 标题 -> 【标题】
    - **加粗** -> 文字(community 编辑器多数不渲染 markdown 粗体)
    - 行首 * / - 列表前缀去掉
    - 单星号 *斜体* 去掉星号
    """
    text = _strip_html_comments(text)
    text = _TABLE_RE.sub(_table_to_text, text)
    # # 标题 -> 【标题】
    text = re.sub(r"^#{1,6}\s*(.+?)\s*$", r"【\1】", text, flags=re.MULTILINE)
    # **加粗** -> 文字
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    # 行首列表前缀
    text = re.sub(r"^[*\-]\s+", "", text, flags=re.MULTILINE)
    # 残留单星号斜体
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)
    return text.strip()


# ---------- 股票标签 ----------

def strip_stock_tags(text: str) -> str:
    """转纯文本(不识别雪球 chip 的平台:微博/股吧/同花顺)。
      $名字(SH600000)$ -> 名字
      $SH600000$ / $600000$ -> 600000
    """
    text = re.sub(r"\$([^\$()]+?)\((?:SH|SZ)?\d{6}\)\$", r"\1", text)
    text = re.sub(r"\$(?:SH|SZ)?(\d{6})\$", r"\1", text)
    return text


def keep_stock_tags(text: str) -> str:
    """原样保留(雪球/老虎会渲染 $...$ 为标签)。"""
    return text


def apply_stock_tags(text: str, mode: str) -> str:
    return strip_stock_tags(text) if mode == "strip" else keep_stock_tags(text)


# ---------- 雪球 cashtag 链接化(参考 stock-media v2.2 normalize 思路)----------

# 文中"名字 (代码)"/"名字（代码）": 代码=6位A股 或 1-6位美股字母
# 名字允许英文内部空格(Astera Labs)
_MENTION_RE = re.compile(
    r"([一-龥A-Za-z][一-龥A-Za-z0-9·\- ]{1,24}?)\s*[（(]\s*([A-Z]{1,6}|\d{6})\s*[)）]")
# 非股票的概念/缩写, 不转 cashtag
_CONCEPT_DENY = {
    "AI", "CPO", "IOT", "IOX", "AEC", "UQD", "GPU", "CPU", "TPU", "ASIC", "SOC",
    "HBM", "PCB", "PCIE", "RTX", "PC", "AR", "VR", "XR", "ROE", "ROA", "PE", "PB",
    "GDP", "CES", "API", "SAAS", "IPO", "ETF", "QDII", "OEM", "ODM", "BMS", "BBU",
    "UPS", "DDR", "LPDDR", "NPU", "DPU", "DCU", "VRM", "LLM", "AIGC", "RAG", "TSV",
    "EDA", "FAB", "EUV", "MCU", "FPGA", "SSD", "HDD", "DRAM", "NAND", "GW", "TW",
}


def _ashare_exchange(code: str) -> str:
    c = code[0]
    if c == "6" or c == "9":
        return "SH"
    if c in ("0", "3"):
        return "SZ"
    if c in ("4", "8"):
        return "BJ"
    return "SH"


# 分组多代码: (AVGO、MRVL、TSM) / (VRT/英维克) 这类纯代码罗列(2个以上)
_GROUP_RE = re.compile(r"[（(]\s*([A-Z]{1,6}(?:\s*[、,，/]\s*[A-Z]{1,6})+)\s*[)）]")


def tag_stock_mentions(blocks):
    """把 blocks 里 run 文本中的"名字(代码)"识别成股票 run(供富文本平台插 cashtag chip)。
    返回新 blocks(不改原始)。代码: A股6位(去交易所前缀, 搜索用纯码)/美股字母; 概念缩写跳过。
    """
    def _ok_code(c):
        c = c.strip()
        return bool(c) and (c.isdigit() or c.upper() not in _CONCEPT_DENY)

    def split_run(r):
        if r.get("stock") or not r.get("text"):
            return [r]
        text, b, i = r["text"], r.get("bold", False), r.get("italic", False)
        # 收集事件: (start, end, [(code,name),...], 是否分组)
        events = []
        for m in _MENTION_RE.finditer(text):
            name, code = m.group(1).strip(" ·-"), m.group(2)
            if name and _ok_code(code):
                events.append((m.start(), m.end(), [(code, name)], False))
        for m in _GROUP_RE.finditer(text):
            codes = [c.strip() for c in re.split(r"[、,，/]", m.group(1)) if _ok_code(c)]
            if len(codes) >= 2:
                events.append((m.start(), m.end(), [(c, c) for c in codes], True))
        if not events:
            return [r]
        events.sort()
        out, pos = [], 0
        for start, end, stocks, grouped in events:
            if start < pos:           # 重叠(单码与分组), 跳过后者
                continue
            if start > pos:
                out.append({"text": text[pos:start], "bold": b, "italic": i, "stock": None})
            if grouped:
                out.append({"text": "(", "bold": b, "italic": i, "stock": None})
                for j, (code, name) in enumerate(stocks):
                    if j > 0:
                        out.append({"text": "、", "bold": b, "italic": i, "stock": None})
                    out.append({"text": "", "bold": b, "italic": i, "stock": (code, name)})
                out.append({"text": ")", "bold": b, "italic": i, "stock": None})
            else:
                code, name = stocks[0]
                out.append({"text": "", "bold": b, "italic": i, "stock": (code, name)})
            pos = end
        if pos < len(text):
            out.append({"text": text[pos:], "bold": b, "italic": i, "stock": None})
        return out

    new = []
    for blk in blocks:
        if "runs" not in blk:
            new.append(blk)
            continue
        nb = dict(blk)
        runs = []
        for r in blk["runs"]:
            runs.extend(split_run(r))
        nb["runs"] = runs
        new.append(nb)
    return new


def add_xueqiu_cashtags(text: str) -> str:
    """把"名字(代码)"转成雪球可点 cashtag $名字(交易所代码)$。
    A股补 SH/SZ/BJ; 美股字母码原样; 概念缩写(AI/CPO/AEC...)跳过; 已是 $...$ 的不动。
    """
    def repl(m):
        name, code = m.group(1).strip(" ·-"), m.group(2)
        if not name:
            return m.group(0)
        if code.isdigit():
            full = f"{_ashare_exchange(code)}{code}"
        else:
            if code.upper() in _CONCEPT_DENY:
                return m.group(0)            # 概念缩写, 不转
            full = code.upper()
        return f"${name}({full})$"

    out, i = [], 0
    # 跳过已有的 $...$ 段, 只处理其余文本
    for m in re.finditer(r"\$[^$\n]{1,40}\$", text):
        out.append(_MENTION_RE.sub(repl, text[i:m.start()]))
        out.append(m.group(0))
        i = m.end()
    out.append(_MENTION_RE.sub(repl, text[i:]))
    return "".join(out)


# ============================================================
# 富文本解析(保留格式: 标题/加粗/斜体/列表/图/股票卡片)
# ============================================================

# 股票标签两种写法都要兼容:
#   $贵州茅台(SH600519)$   (A股, 有结尾 $)
#   $英伟达(NVDA.O)        (美股平头哥格式, 无结尾 $)
#   $600519$ / $NVDA$      (纯代码)
STOCK_RE = re.compile(
    r"\$([^$\n]*?\((?:SH|SZ)?[A-Z0-9.]{1,8}\))\$?"   # $名字(代码)$ 或 $名字(代码)
    r"|\$((?:SH|SZ)?[A-Z0-9]{2,8})\$"                 # $代码$
)


def parse_stock_key(inner: str):
    """从标签内部解析 (老虎搜索用代码, 显示名)。
    "英伟达(NVDA.O)" -> ("NVDA","英伟达"); "贵州茅台(SH600519)" -> ("600519","贵州茅台")
    "NVDA"/"SH600519" -> 自身/去前缀
    """
    m = re.search(r"\(([^()]+)\)", inner)
    if m:
        code, name = m.group(1).strip(), inner[:m.start()].strip()
    else:
        code = name = inner.strip()
    code = re.sub(r"^(?:SH|SZ|sh|sz)", "", code)        # 去 A 股前缀
    code = re.sub(r"\.(?:O|N|US|HK|SH|SZ|OQ)$", "", code, flags=re.I)  # 去美/港后缀
    return code.strip(), (name or code).strip()


def _inline_runs(text: str):
    """把一行拆成 runs: {text, bold, italic, stock:(code,name)|None}。
    处理 **加粗** / *斜体* / 股票标签。
    """
    runs = []
    # 先按股票标签切, 标签段单独成 run; 其余文本再解析 加粗/斜体
    pos = 0
    for m in STOCK_RE.finditer(text):
        if m.start() > pos:
            runs.extend(_emph_runs(text[pos:m.start()]))
        inner = m.group(1) or m.group(2)
        runs.append({"text": "", "bold": False, "italic": False,
                     "stock": parse_stock_key(inner)})
        pos = m.end()
    if pos < len(text):
        runs.extend(_emph_runs(text[pos:]))
    return runs


_EMPH_RE = re.compile(r"\*\*(.+?)\*\*|(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")


def _emph_runs(text: str):
    """处理 **加粗** 和 *斜体*, 返回 runs(无股票)。"""
    runs = []
    pos = 0
    for m in _EMPH_RE.finditer(text):
        if m.start() > pos:
            runs.append({"text": text[pos:m.start()], "bold": False,
                         "italic": False, "stock": None})
        if m.group(1) is not None:
            runs.append({"text": m.group(1), "bold": True,
                         "italic": False, "stock": None})
        else:
            runs.append({"text": m.group(2), "bold": False,
                         "italic": True, "stock": None})
        pos = m.end()
    if pos < len(text):
        runs.append({"text": text[pos:], "bold": False,
                     "italic": False, "stock": None})
    return [r for r in runs if r["text"] or r["stock"]]


def _runs_from_text(text: str, bold: bool, italic: bool):
    """把一段(统一 bold/italic 的)文本按股票标签切成 runs。"""
    runs = []
    pos = 0
    for m in STOCK_RE.finditer(text):
        if m.start() > pos:
            runs.append({"text": text[pos:m.start()], "bold": bold,
                         "italic": italic, "stock": None})
        inner = m.group(1) or m.group(2)
        runs.append({"text": "", "bold": bold, "italic": italic,
                     "stock": parse_stock_key(inner)})
        pos = m.end()
    if pos < len(text):
        runs.append({"text": text[pos:], "bold": bold, "italic": italic, "stock": None})
    return [r for r in runs if r["text"] or r["stock"]]


def _docx_para_image_paths(d, p, tmpdir, counter):
    """抽取一个段落里内嵌的图片 → 写到 tmpdir, 返回文件路径列表(保持文档顺序)。"""
    from docx.oxml.ns import qn
    paths = []
    for blip in p._p.iter(qn("a:blip")):
        rid = blip.get(qn("r:embed")) or blip.get(qn("r:link"))
        if not rid:
            continue
        try:
            part = d.part.related_parts[rid]
            blob = part.blob
            ct = (part.content_type or "").lower()
            ext = ".png" if "png" in ct else (".jpg" if "jp" in ct else
                  (".gif" if "gif" in ct else ".png"))
            counter[0] += 1
            fp = Path(tmpdir) / f"img_{counter[0]:03d}{ext}"
            fp.write_bytes(blob)
            paths.append(str(fp))
        except Exception:
            continue
    return paths


def load_docx(path):
    """读 Word(.docx) → (title, blocks)。块结构与 parse_markdown 一致。
    标题层级取自 Word 样式 Heading 1/2/3;加粗/斜体取 run 级;股票标签按 $名字(代码)$ 识别;
    内嵌图片抽到临时目录, 作为 image 块(src=绝对路径)。
    """
    import docx, tempfile
    d = docx.Document(str(path))
    tmpdir = tempfile.mkdtemp(prefix="autopub_img_")
    img_counter = [0]
    title = ""
    blocks = []
    for p in d.paragraphs:
        # 先抽本段内嵌图(图可能在空文本段里, 必须在 text 判空之前处理)
        for fp in _docx_para_image_paths(d, p, tmpdir, img_counter):
            blocks.append({"type": "image", "src": fp, "alt": ""})
        text = p.text.strip()
        if not text:
            continue
        try:
            style = p.style.name or ""
        except Exception:
            style = ""
        if not title:                       # 首个非空文本段 = 标题
            title = _clean_title(text)
            continue
        # 合并连续同格式 run, 再切股票标签
        segs = []
        for r in p.runs:
            if not r.text:
                continue
            b, i = bool(r.bold), bool(r.italic)
            if segs and segs[-1][1] == b and segs[-1][2] == i:
                segs[-1] = [segs[-1][0] + r.text, b, i]
            else:
                segs.append([r.text, b, i])
        if not segs:                        # 无 run(罕见), 用纯文本
            segs = [[text, False, False]]
        runs = []
        for t, b, i in segs:
            runs.extend(_runs_from_text(t, b, i))
        runs = [r for r in runs if r["text"].strip() or r["stock"]]
        if not runs:
            continue
        m = re.match(r"Heading\s+(\d)", style)
        if m:
            blocks.append({"type": "heading", "level": int(m.group(1)), "runs": runs})
        elif "List" in style:
            blocks.append({"type": "list_item", "ordered": False, "runs": runs})
        else:
            blocks.append({"type": "paragraph", "runs": runs})
    return title, blocks


def clean_spaces(text: str) -> str:
    """清除多余空格: 连续空格→单个; 中文字符之间的空格去掉; 去行首尾空格。
    (保留英文/数字单词内部及之间的单个空格)
    """
    if not text:
        return text
    text = text.replace("　", " ")              # 全角空格→半角
    text = re.sub(r"[ \t]{2,}", " ", text)           # 连续空格→1个
    # 中文字符之间/中文与标点之间的空格去掉(英文数字之间保留)
    text = re.sub(r"(?<=[一-鿿，。、；：！？）】」》])\s+(?=[一-鿿，。、；：！？（【「《])", "", text)
    text = re.sub(r"(?<=[一-鿿])\s+(?=[一-鿿])", "", text)
    return text.strip()


def blocks_to_plain(blocks, stock_fmt="name") -> str:
    """块 → 纯文本(给不支持富文本的平台用)。
    stock_fmt: "name"=股票转显示名; "tag"=转 $名字(代码)$(雪球会渲染成 chip)。
    标题→【】, 列表→·, 加粗/斜体丢弃, 图跳过。
    """
    out = []
    for b in blocks:
        if b["type"] == "hr":
            out.append("———")
            continue
        if b["type"] == "image":
            continue
        txt = ""
        for r in b.get("runs", []):
            if r["stock"]:
                code, name = r["stock"]
                txt += f"${name}({code})$" if stock_fmt == "tag" else name
            else:
                txt += r["text"]
        if b["type"] == "heading":
            txt = f"【{txt}】"
        elif b["type"] == "list_item":
            txt = "· " + txt
        out.append(txt)
    return "\n".join(out).strip()


def parse_markdown(body: str):
    """把正文 markdown 解析成块列表(保留格式)。
    块类型: heading(level,runs) / paragraph(runs) / list_item(ordered,runs)
            / image(src,alt) / hr
    """
    body = _strip_frontmatter(_strip_html_comments(body))
    blocks = []
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        s = line.strip()
        if not s:
            continue
        # 分隔线
        if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", s):
            blocks.append({"type": "hr"})
            continue
        # 图片 ![alt](src)
        mi = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", s)
        if mi:
            blocks.append({"type": "image", "alt": mi.group(1), "src": mi.group(2)})
            continue
        # 标题
        mh = re.match(r"(#{1,6})\s+(.*)", s)
        if mh:
            blocks.append({"type": "heading", "level": len(mh.group(1)),
                           "runs": _inline_runs(mh.group(2).strip())})
            continue
        # 列表项(有序/无序)
        ml = re.match(r"(?:[-*]|\d+[.、])\s+(.*)", s)
        if ml:
            ordered = bool(re.match(r"\d", s))
            blocks.append({"type": "list_item", "ordered": ordered,
                           "runs": _inline_runs(ml.group(1).strip())})
            continue
        # 普通段落
        blocks.append({"type": "paragraph", "runs": _inline_runs(s)})
    return blocks
