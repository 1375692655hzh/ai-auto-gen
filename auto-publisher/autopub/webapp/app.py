#!/usr/bin/env python3
"""auto-publisher 本地网页控制台

团队零门槛使用: 浏览器里上传文章、勾选平台、填模型 API、点发布看日志。
只在本机跑(发布要弹出真 Chrome 让你手动登录/过验证码),不要部署到公网。

启动:
    python3 webapp/app.py
然后浏览器打开 http://127.0.0.1:5001
"""

import sys
import subprocess
import threading
from pathlib import Path

from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml
import llm
import tdoc_client
from state import State
from publishers import REGISTRY

ARTICLES_DIR = ROOT / "articles"
LOG_DIR = ROOT / "logs"
RUN_LOG = LOG_DIR / "webrun.log"
ALLOWED_EXT = {".md", ".docx"}

# 平台清单动态生成, 不在这里维护第二份(内核加平台网页自动跟上):
#   清单  = publishers/REGISTRY(发布真正认的平台)
#   中文名+验证状态 = publish/targets.yaml
#   开关  = config.yaml platforms.<id>.enabled(与 publish_all.py 同语义)
TARGETS_YAML = ROOT.parent / "publish" / "targets.yaml"
VERIFIED_NOTE = {
    "published": "已真发验证",
    "draft": "草稿验证",
    "placeholder": "适配器占位",
    "disabled-需实名": "已停用: 需实名",
    "disabled-风控": "已停用: 账号风控",
}

app = Flask(__name__)

# 运行状态(单机单任务,够用)
_run = {"proc": None}
_lock = threading.Lock()


# ---------- 工具 ----------

def list_articles():
    out = []
    if ARTICLES_DIR.exists():
        for f in sorted(ARTICLES_DIR.glob("*.md")) + sorted(ARTICLES_DIR.glob("*.docx")):
            if f.name.startswith("~$"):
                continue
            out.append({"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1)})
    return out


def is_running():
    p = _run["proc"]
    return p is not None and p.poll() is None


def load_config():
    try:
        with open(ROOT / "config.yaml", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def list_platforms():
    """网页展示用的平台清单(单一事实来源聚合, 见顶部注释)。"""
    cfg = load_config().get("platforms") or {}
    meta = {}
    try:
        with open(TARGETS_YAML, encoding="utf-8") as f:
            meta = (yaml.safe_load(f) or {}).get("platforms") or {}
    except Exception:
        pass
    # targets.yaml 的顺序即展示顺序(验证过的在前); 它漏登记的注册平台兜底排最后
    ordered = [k for k, m in meta.items()
               if isinstance(m, dict) and m.get("engine") == "autopub" and k in REGISTRY]
    ordered += [k for k in REGISTRY if k not in ordered]
    out = []
    for k in ordered:
        m = meta.get(k) or {}
        note = VERIFIED_NOTE.get(m.get("verified", ""), m.get("verified") or "已注册")
        out.append({
            "key": k,
            "name": m.get("title") or k,
            "note": note,
            "enabled": bool((cfg.get(k) or {}).get("enabled")),
        })
    return out


# ---------- 页面 ----------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    """页面初始/轮询数据: 模型配置 + 文章列表 + 平台 + 运行态。"""
    state = State(ROOT / "state.json")
    arts = list_articles()
    platforms = list_platforms()
    # 每篇在各平台的发布状态(给页面打勾用)
    pub = {}
    for a in arts:
        pub[a["name"]] = {p["key"]: state.is_published(a["name"], p["key"]) for p in platforms}
    return jsonify({
        "model": llm.status(),
        "providers": list(llm.PRESET_BASE_URLS.keys()) + ["claude_cli"],
        "preset_urls": llm.PRESET_BASE_URLS,
        "platforms": platforms,
        "articles": arts,
        "published": pub,
        "running": is_running(),
    })


# ---------- 模型 API ----------

@app.route("/api/model/save", methods=["POST"])
def api_model_save():
    d = request.get_json(force=True)
    provider = (d.get("provider") or "openai_compatible").strip()
    llm.save_secret(
        provider=provider,
        api_key=d.get("api_key", ""),
        model=d.get("model", ""),
        base_url=d.get("base_url", ""),
    )
    return jsonify({"ok": True, "status": llm.status()})


@app.route("/api/model/test", methods=["POST"])
def api_model_test():
    ok, msg = llm.test_connection()
    return jsonify({"ok": ok, "message": msg})


# ---------- 腾讯文档授权 ----------

_tdoc_code = {"code": ""}       # 本会话的授权 code(auth_start 发起, auth_poll 轮询)


@app.route("/api/tdoc/status")
def api_tdoc_status():
    return jsonify({"authorized": bool(tdoc_client.load_token())})


@app.route("/api/tdoc/auth_start", methods=["POST"])
def api_tdoc_auth_start():
    code = tdoc_client.make_auth_code()
    _tdoc_code["code"] = code
    return jsonify({"ok": True, "url": tdoc_client.auth_url(code)})


@app.route("/api/tdoc/auth_poll")
def api_tdoc_auth_poll():
    code = _tdoc_code["code"]
    if not code:
        return jsonify({"done": False, "message": "请先点'去授权'"})
    st, val = tdoc_client.poll_token(code)
    if st == "ok":
        tdoc_client.save_token(val)
        return jsonify({"done": True, "message": "授权成功, 可以图文导入了"})
    if st == "error":
        return jsonify({"done": False, "error": val})
    return jsonify({"done": False, "message": "等待浏览器完成授权…"})


# ---------- 文章 ----------

@app.route("/api/upload", methods=["POST"])
def api_upload():
    files = request.files.getlist("files")
    saved, skipped = [], []
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    for f in files:
        if not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED_EXT:
            skipped.append(f.filename)
            continue
        # 保留中文文件名,只去掉路径分隔符等危险字符
        name = f.filename.replace("/", "_").replace("\\", "_").lstrip(".")
        f.save(str(ARTICLES_DIR / name))
        saved.append(name)
    return jsonify({"ok": True, "saved": saved, "skipped": skipped, "articles": list_articles()})


@app.route("/api/delete", methods=["POST"])
def api_delete():
    name = (request.get_json(force=True) or {}).get("name", "")
    f = ARTICLES_DIR / Path(name).name      # 防目录穿越
    if f.exists() and f.parent == ARTICLES_DIR:
        f.unlink()
    return jsonify({"ok": True, "articles": list_articles()})


@app.route("/api/import_doc", methods=["POST"])
def api_import_doc():
    """腾讯文档链接 → 导入待发队列。

    主路径: OpenAPI 导出 docx(图文+格式全保真, 需 mcporter 已授权)。
    降级路径: dop-api 拉纯文本存 md(仅"任何人可查看"的文档, 无图)。
    """
    url = (request.get_json(force=True) or {}).get("url", "").strip()
    if not url:
        return jsonify({"ok": False, "message": "请粘贴腾讯文档链接"}), 400
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    import import_tencent_doc
    r = import_tencent_doc.import_doc(url, ARTICLES_DIR)
    if r.get("ok"):
        return jsonify({"ok": True, "saved": r["saved"], "mode": "docx(图文)",
                        "bytes": r.get("bytes"),
                        "articles": list_articles()})
    # OpenAPI 不可用 → 退 dop-api 纯文本, 并如实告知差异
    import tencent_doc
    t = tencent_doc.fetch_doc(url)
    if t.get("ok"):
        name = (t.get("title") or "腾讯文档").replace("/", "_").replace("\\", "_") \
                                    .lstrip(".").strip()
        f = ARTICLES_DIR / f"{name}.md"
        if f.exists():      # 同名不覆盖, 加时间后缀
            from datetime import datetime
            f = ARTICLES_DIR / f"{name}-{datetime.now():%H%M%S}.md"
        f.write_text(f"{t['title']}\n\n{t.get('body') or ''}", encoding="utf-8")
        return jsonify({"ok": True, "saved": f.name, "mode": "纯文本(无图)",
                        "paragraphs": len(t.get("paragraphs") or []),
                        "articles": list_articles()})
    return jsonify({"ok": False, "message":
                    f"导入失败。图文导出: {r.get('error', '')}; "
                    f"纯文本降级: {t.get('error', '')}"}), 400


# ---------- 发布 ----------

@app.route("/api/run", methods=["POST"])
def api_run():
    with _lock:
        if is_running():
            return jsonify({"ok": False, "message": "已有发布任务在跑,请等它结束"}), 409
        d = request.get_json(force=True) or {}
        platforms = [p for p in d.get("platforms", []) if p]
        only_file = d.get("file") or None
        if not platforms:
            return jsonify({"ok": False, "message": "请至少勾选一个平台"}), 400
        # --platforms 显式点名会绕过 config 的 enabled 开关, 网页侧必须自己挡:
        # 勾了停用平台的明确拒绝, 不悄悄尝试发
        plat_info = {p["key"]: p for p in list_platforms()}
        disabled = [p for p in platforms if not plat_info.get(p, {}).get("enabled")]
        if disabled:
            names = ", ".join(plat_info[d]["name"] for d in disabled)
            return jsonify({"ok": False,
                            "message": f"平台已停用(见 config.yaml 开关): {names}"}), 400
        if not list_articles():
            return jsonify({"ok": False, "message": "articles/ 里没有文章,请先上传"}), 400

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        # -u 关闭输出缓冲,Windows 上日志才能实时刷到网页
        cmd = [sys.executable, "-u", str(ROOT / "publish_all.py"),
               "--platforms", ",".join(platforms)]
        if only_file:
            cmd += ["--file", only_file]
        logf = open(RUN_LOG, "w", encoding="utf-8")
        logf.write(f"$ {' '.join(cmd)}\n\n")
        logf.flush()
        _run["proc"] = subprocess.Popen(
            cmd, cwd=str(ROOT), stdout=logf, stderr=subprocess.STDOUT, text=True)
    return jsonify({"ok": True, "message": "已开始发布,注意弹出的 Chrome 窗口(首次需手动登录)"})


@app.route("/api/run/log")
def api_run_log():
    text = RUN_LOG.read_text(encoding="utf-8") if RUN_LOG.exists() else ""
    return jsonify({"running": is_running(), "log": text})


@app.route("/api/run/stop", methods=["POST"])
def api_run_stop():
    p = _run["proc"]
    if p and p.poll() is None:
        p.terminate()
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("auto-publisher 控制台: http://127.0.0.1:5001")
    app.run(host="127.0.0.1", port=5001, debug=False, threaded=True)
