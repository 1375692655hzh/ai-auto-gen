"""腾讯文档 → 本地 docx 导入(图文全保真)

传输优先级:
  1) tdoc_client 直连(项目自带, Token 存 secret.local.json —— 推荐, 零外部依赖)
  2) mcporter CLI(兼容老环境; 需 npm i -g mcporter 且已 config add tencent-docs)

链路: URL 的 padID → query_file_info 拿 file_id → export_file 发起导出
  → export_progress 轮询(4s 间隔) → 带签名 URL 下载 docx → 存 articles/

docx 直接进待发队列即可: content.load_article 原生解析 docx(标题+段落+图片,
图片随每次加载解压, 各平台适配器照常上传), 格式保真度最高。

授权(一次, 之后长期有效): py tdoc_client.py auth   (浏览器 QQ/微信扫码)

用法:
  py import_tencent_doc.py --url https://docs.qq.com/doc/DXXXX [--out-dir articles]
  from import_tencent_doc import import_doc
"""

import argparse
import json
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import tdoc_client

ROOT = Path(__file__).resolve().parent
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"


# ---------- 传输层: 优先直连, 退 mcporter ----------

def _call(tool: str, args: dict) -> dict:
    tok = tdoc_client.load_token()
    if tok:
        return tdoc_client.TDocClient(tok).call(tool, args)
    exe = shutil.which("mcporter")
    if exe:
        r = subprocess.run([exe, "call", "tencent-docs", tool, "--args",
                            json.dumps(args, ensure_ascii=False)],
                           capture_output=True, text=True, timeout=60,
                           encoding="utf-8", errors="replace")
        if r.returncode == 0:
            try:
                d = json.loads(r.stdout)
                if not d.get("error"):
                    return d
            except Exception:
                pass
    raise tdoc_client.TDocError(
        "腾讯文档未授权(直连无 Token, mcporter 不可用)。"
        "请运行: py tdoc_client.py auth 完成一次扫码授权")


def import_doc(url: str, out_dir=None) -> dict:
    """腾讯文档链接 → docx 落盘。返回 {ok, saved, title, bytes} 或 {ok:False, error}。"""
    try:
        out_dir = Path(out_dir or (ROOT / "articles"))
        m = re.search(r"docs\.qq\.com/(?:doc|word)/([A-Za-z0-9]+)", url or "")
        if not m:
            return {"ok": False, "error": f"不是腾讯文档(Word类)链接: {url}"}
        info = _call("manage.query_file_info", {"file_id": m.group(1)})
        if info.get("is_folder") or info.get("type") not in ("doc",):
            return {"ok": False, "error": f"仅支持 Word 类文档, 该文档类型: {info.get('type')}"}
        fid, title = info["file_id"], info.get("title") or "腾讯文档"

        task = _call("manage.export_file", {"file_id": fid})
        tid = task.get("task_id")
        if not tid:
            return {"ok": False, "error": f"导出任务未建立: {task}"}
        for _ in range(30):                       # 4s×30 = 最长约 2 分钟
            time.sleep(4)
            p = _call("manage.export_progress", {"task_id": tid})
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
