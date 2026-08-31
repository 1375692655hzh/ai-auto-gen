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
from state import State

ARTICLES_DIR = ROOT / "articles"
LOG_DIR = ROOT / "logs"
RUN_LOG = LOG_DIR / "webrun.log"
ALLOWED_EXT = {".md", ".docx"}

# publish_all.py 里 ORDER 支持的平台 + 中文名
PLATFORMS = [
    {"key": "laohu",     "name": "老虎社区",   "note": "已验证"},
    {"key": "eastmoney", "name": "东方财富股吧", "note": "已验证"},
    {"key": "xueqiu",    "name": "雪球",       "note": "已验证"},
    {"key": "zhihu",     "name": "知乎",       "note": "已验证(图表转文字需模型 API)"},
]

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


# ---------- 页面 ----------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    """页面初始/轮询数据: 模型配置 + 文章列表 + 平台 + 运行态。"""
    state = State(ROOT / "state.json")
    arts = list_articles()
    # 每篇在各平台的发布状态(给页面打勾用)
    pub = {}
    for a in arts:
        pub[a["name"]] = {p["key"]: state.is_published(a["name"], p["key"]) for p in PLATFORMS}
    return jsonify({
        "model": llm.status(),
        "providers": list(llm.PRESET_BASE_URLS.keys()) + ["claude_cli"],
        "preset_urls": llm.PRESET_BASE_URLS,
        "platforms": PLATFORMS,
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
