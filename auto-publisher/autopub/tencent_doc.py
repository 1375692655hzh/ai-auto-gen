"""腾讯文档(docs.qq.com)只读文档正文抓取

原理: 文档页背后的 dop-api 接口返回 JSON, 其中
clientVars.collab_client_vars.initialAttributedText.text[0] 是 base64 的
etherpad 风格 attributed-text: 前半段是 UTF-8 正文(段落以 \r 分隔),
后半段是属性二进制。按 \r 切开后过滤掉二进制段即得正文段落。

用法:
  from tencent_doc import fetch_doc
  doc = fetch_doc("https://docs.qq.com/doc/DQWdockZyYk9SUXBY")
  # -> {"title": str, "paragraphs": [str...], "body": str, "ok": bool, "error": str}

限制: 只读文档(任何人可查看)才行; 需登录/加密的文档会拿不到正文。
图片(图表)不在纯文本里, 不抓取。
"""

import base64
import json
import re
import urllib.request

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# 段内容必须"大部分是可读文本"才算正文段(滤掉 protobuf 二进制尾巴)
_READABLE = re.compile(r"[\u4e00-\u9fa5A-Za-z0-9，。：；、！？%．.\-—…“”‘’（）()\[\]《》\s/"


                       r"·＋+＊*＝=｜|＃#＠@￥$～~、；：""'']")


def _extract(doc_id: str) -> dict:
    url = ("https://docs.qq.com/dop-api/opendoc?u=&id=" + doc_id +
           "&normal=1&outformat=1&noEscape=1&commandsFormat=1"
           "&doc_chunk_version=3&preview_token=&doc_chunk_flag=1")
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Referer": f"https://docs.qq.com/doc/{doc_id}",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        d = json.loads(resp.read().decode("utf-8"))
    txt = ((d.get("clientVars") or {}).get("collab_client_vars")
           or {}).get("initialAttributedText", {}).get("text") or []
    if not txt:
        return {"ok": False, "error": "接口未返回正文(可能需要登录/权限)"}
    raw = base64.b64decode(txt[0]).decode("utf-8", errors="ignore")
    paras = []
    for seg in raw.split("\r"):
        seg = seg.strip("\n").strip()
        if not seg:
            continue
        readable = len(_READABLE.findall(seg)) / max(len(seg), 1)
        if readable > 0.85 and len(seg) >= 2:
            paras.append(seg)
        if paras and readable <= 0.85:
            break        # 正文结束, 后面是属性二进制
    if not paras:
        return {"ok": False, "error": "正文解析为空"}
    title = (d.get("clientVars") or {}).get("title") or paras[0]
    if paras[0] == title:
        paras = paras[1:]      # 正文首段与标题重复时去掉
    body = "\n\n".join(paras)
    return {"ok": True, "title": title, "paragraphs": paras, "body": body}


def fetch_doc(url: str) -> dict:
    """抓取腾讯文档。url 形如 https://docs.qq.com/doc/DQWdockZyYk9SUXBY[...]"""
    m = re.search(r"docs\.qq\.com/(?:doc|sheet|slide)/([A-Za-z0-9]+)", url)
    if not m:
        return {"ok": False, "error": f"不是腾讯文档链接: {url}"}
    try:
        return _extract(m.group(1))
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    import sys
    r = fetch_doc(sys.argv[1] if len(sys.argv) > 1
                  else "https://docs.qq.com/doc/DQWdockZyYk9SUXBY")
    print(json.dumps(r, ensure_ascii=False, indent=2)[:2000])
