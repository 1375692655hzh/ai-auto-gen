"""腾讯文档 → 本地 docx 导入(图文全保真)

走腾讯文档 OpenAPI(底层是 mcporter CLI + 本机已授权的 Token):
  URL 的 padID → query_file_info 拿 file_id → export_file 发起导出
  → export_progress 轮询(4s 间隔) → 带签名 URL 下载 docx → 存 articles/

docx 直接进待发队列即可: content.load_article 原生解析 docx(标题+段落+图片,
图片随每次加载解压, 各平台适配器照常上传), 格式保真度最高。

Token 授权(一次): 见 tencent-docs skill 的 references/auth.md。
OpenAPI 不可用(mcporter 未装/未授权)时, webapp 侧退 dop-api 纯文本导入。

用法:
  py import_tencent_doc.py --url https://docs.qq.com/doc/DXXXX [--out-dir articles]
  from import_tencent_doc import import_doc
"""

import argparse
import json
import re
import subprocess
import shutil
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"


def _mcporter() -> str:
    exe = shutil.which("mcporter")
    if not exe:
        raise RuntimeError("mcporter 未安装(腾讯文档 OpenAPI CLI, 见 tencent-docs skill 的 auth.md)")
    return exe


def _call(exe: str, tool: str, args: dict) -> dict:
    r = subprocess.run([exe, "call", "tencent-docs", tool, "--args",
                        json.dumps(args, ensure_ascii=False)],
                       capture_output=True, text=True, timeout=60,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"mcporter {tool} 退出码 {r.returncode}: {r.stderr[:200]}")
    try:
        d = json.loads(r.stdout)
    except Exception:
        raise RuntimeError(f"mcporter {tool} 输出非 JSON: {r.stdout[:200]}")
    if d.get("error"):
        raise RuntimeError(f"{tool}: {d['error']}")
    return d


def import_doc(url: str, out_dir=None) -> dict:
    """腾讯文档链接 → docx 落盘。返回 {ok, saved, title, bytes} 或 {ok:False, error}。"""
    try:
        out_dir = Path(out_dir or (ROOT / "articles"))
        m = re.search(r"docs\.qq\.com/(?:doc|word)/([A-Za-z0-9]+)", url or "")
        if not m:
            return {"ok": False, "error": f"不是腾讯文档(Word类)链接: {url}"}
        exe = _mcporter()
        info = _call(exe, "manage.query_file_info", {"file_id": m.group(1)})
        if info.get("is_folder") or info.get("type") not in ("doc",):
            return {"ok": False, "error": f"仅支持 Word 类文档, 该文档类型: {info.get('type')}"}
        fid, title = info["file_id"], info.get("title") or "腾讯文档"

        task = _call(exe, "manage.export_file", {"file_id": fid})
        tid = task.get("task_id")
        if not tid:
            return {"ok": False, "error": f"导出任务未建立: {task}"}
        for _ in range(30):                       # 4s×30 = 最长约 2 分钟
            time.sleep(4)
            p = _call(exe, "manage.export_progress", {"task_id": tid})
            if p.get("progress") == 100 and p.get("file_url"):
                break
        else:
            return {"ok": False, "error": "导出超时(2 分钟未完成)"}

        out_dir.mkdir(parents=True, exist_ok=True)
        name = title.replace("/", "_").replace("\\", "_").lstrip(".").strip()
        f = out_dir / f"{name}.docx"
        if f.exists():
            f = out_dir / f"{name}-{time.strftime('%H%M%S')}.docx"
        req = urllib.request.Request(p["file_url"], headers={"User-Agent": _UA})
        data = urllib.request.urlopen(req, timeout=120).read()
        f.write_bytes(data)
        return {"ok": True, "saved": f.name, "title": title, "bytes": len(data)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--out-dir", default=str(ROOT / "articles"))
    a = ap.parse_args()
    print(json.dumps(import_doc(a.url, a.out_dir), ensure_ascii=False))
