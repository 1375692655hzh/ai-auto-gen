"""源启停写内核(单一事实源): cli `sources enable` 与 serve 写端点共用。

config.local.yaml 是用户手维护的模板(key/翻译链等), 只做行级编辑保留注释;
原子写(tempfile+replace)防半写。路径与 sources._cfg_section 同源:
ai-workflow/generator/config.local.yaml, 缺板块二时退 global-news-sources/。
"""

import os
import re
import tempfile
from pathlib import Path

from . import _GEN_CFG, list_sources


def yaml_set_enabled(text: str, sid: str, on: bool) -> str:
    """行级编辑 sources.<sid>.enabled, 保留注释与其他段; 不整文件 safe_dump
    重写(会丢注释)。原子写由调用方负责。"""
    val = "true" if on else "false"
    lines = text.splitlines(keepends=True) if text else []
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    src_i = next((i for i, l in enumerate(lines)
                  if re.match(r"^sources:\s*(#.*)?$", l.rstrip("\n"))), None)
    if src_i is None:                       # 无 sources 段: 文件尾新开一段
        if not text:
            lines.append("# 本机覆盖(gitignored, 不入库) — sources 启停由 cli/sources enable 端点维护\n")
        elif lines and lines[-1] != "\n":
            lines.append("\n")
        lines += ["sources:\n", f"  {sid}:\n", f"    enabled: {val}\n"]
        return "".join(lines)
    j, sid_i = src_i + 1, None
    while j < len(lines):
        l = lines[j].rstrip("\n")
        if l.strip() and not l[0].isspace():
            break                           # 下一个顶层键: sources 段结束
        if re.match(r"^  " + re.escape(sid) + r":\s*(#.*)?$", l):
            sid_i = j
            break
        j += 1
    if sid_i is None:                       # 段内无该源: 紧跟 sources: 后插入
        lines.insert(src_i + 1, f"  {sid}:\n    enabled: {val}\n")
        return "".join(lines)
    k, en_i = sid_i + 1, None
    while k < len(lines):
        l = lines[k].rstrip("\n")
        if l.strip() and (not l[0].isspace() or len(l) - len(l.lstrip()) <= 2):
            break                           # 顶层键或 sources 下别的子键: sid 块结束
        if re.match(r"^ {4}enabled:", l):
            en_i = k
            break
        k += 1
    if en_i is None:
        lines.insert(sid_i + 1, f"    enabled: {val}\n")
    else:
        lines[en_i] = re.sub(r"(enabled:)\s*(true|false)?", rf"\1 {val}", lines[en_i])
    return "".join(lines)


def set_enabled(sid: str, on: bool | None = None) -> dict:
    """启停(或 on=None 翻转)一个源。KeyError=未知源; ok=False=写后状态未如预期。
    返回 {"id", "enabled", "ok", "file"}。"""
    cur = next((m["enabled"] for m in list_sources() if m["id"] == sid), None)
    if cur is None:
        raise KeyError(sid)
    target = (not cur) if on is None else bool(on)
    loc = _GEN_CFG.with_name("config.local.yaml")
    new_text = yaml_set_enabled(loc.read_text(encoding="utf-8") if loc.exists() else "",
                                sid, target)
    loc.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(loc.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(new_text)
    os.replace(tmp, loc)
    now = next((m["enabled"] for m in list_sources() if m["id"] == sid), None)
    return {"id": sid, "enabled": now, "ok": (now == target), "file": str(loc)}
