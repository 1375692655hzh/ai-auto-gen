"""三板块文件契约的只读视图(红线: 全程只读, 不写 run.json/state.json/任何三板块文件)。

只读扫描:
  flows 清单        ai-workflow/flows/*/workflow.yaml (正则取 title, 不 import flows 引擎)
  runs 状态机       data/runs/<流>/<日期>/run.json
  生成产物          ai-workflow/generator/output/
  待发队列          auto-publisher/autopub/articles/
  发布账本          auto-publisher/autopub/state.json  (只读!)
  视频项目          ai-workflow/video/videos/*/(project.json|out/)
触发类动作(flows run/publish)本期一律不做, 前端按钮是桩; 未来也只经 subprocess 调 cli.py。
"""

import json
import re
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]         # workbench/server/views.py → 仓库根
AIWF = REPO / "ai-workflow"
PUB = REPO / "auto-publisher"
RUNS = REPO / "data" / "runs"
OUTPUT = AIWF / "generator" / "output"
QUEUE = PUB / "autopub" / "articles"
LEDGER = PUB / "autopub" / "state.json"
VIDEOS = AIWF / "video" / "videos"


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _stat(p: Path) -> dict:
    st = p.stat()
    return {"size": st.st_size, "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))}


# ── flows / runs ────────────────────────────────────────────────────────────

def flows_list() -> list:
    """扫描 ai-workflow/flows/builtin|imports 下的工作流包(与 flows.engine.discover 同规则)。"""
    out = []
    for base in ("builtin", "imports"):
        root = AIWF / "flows" / base
        for wf in sorted(root.glob("*/workflow.yaml")) if root.exists() else []:
            title = ""
            try:
                m = re.search(r"^\s*title:\s*(.+?)\s*$", wf.read_text(encoding="utf-8"), re.M)
                title = m.group(1).strip("'\"") if m else ""
            except Exception:
                pass
            out.append({"name": wf.parent.name, "title": title or wf.parent.name,
                        "origin": base})
    return out


def runs_list(limit: int = 30) -> list:
    rows = []
    for flow_dir in sorted(RUNS.iterdir()) if RUNS.exists() else []:
        if not flow_dir.is_dir():
            continue
        for date_dir in sorted(flow_dir.iterdir(), reverse=True):
            rj = date_dir / "run.json"
            if not rj.exists():
                continue
            d = _read_json(rj, {})
            rows.append({"flow": flow_dir.name, "date": date_dir.name,
                         "status": d.get("status", "?"), "note": d.get("note", ""),
                         "steps": d.get("steps", {}), "artifacts": d.get("artifacts") or {},
                         **_stat(rj)})
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return rows[:limit]


# ── 生成产物 / 队列 / 账本 ───────────────────────────────────────────────────

def artifacts() -> dict:
    arts = []
    if OUTPUT.exists():
        for p in sorted(OUTPUT.rglob("*")):
            if p.is_file() and p.suffix.lower() in (".md", ".png", ".jpg", ".json", ".txt", ".mp3"):
                rel = p.relative_to(OUTPUT).as_posix()
                if any(seg.startswith(".") for seg in p.relative_to(OUTPUT).parts):
                    continue
                arts.append({"path": rel, "name": p.name, "kind": p.suffix.lstrip("."), **_stat(p)})
    arts.sort(key=lambda a: a["mtime"], reverse=True)
    queue = []
    if QUEUE.exists():
        for p in sorted(QUEUE.glob("*")):
            if p.suffix.lower() in (".md", ".docx") and p.is_file():
                queue.append({"name": p.name, **_stat(p)})
    return {"artifacts": arts[:200], "queue": queue}


def artifact_file(rel: str) -> Path | None:
    """产物文件回源(带路径逃逸防护, 只允许 output/ 之内)。"""
    p = (OUTPUT / rel).resolve()
    if not str(p).startswith(str(OUTPUT.resolve())) or not p.is_file():
        return None
    return p


def ledger_rows(limit: int = 200) -> dict:
    data = _read_json(LEDGER, {})
    rows = []
    for aid, plats in (data.items() if isinstance(data, dict) else []):
        for plat, rec in (plats or {}).items():
            rows.append({"article": aid, "platform": plat,
                         "status": rec.get("status", "?"), "time": rec.get("time", ""),
                         "url": rec.get("url", "")})
    rows.sort(key=lambda r: r["time"], reverse=True)
    published = [r for r in rows if r["status"] == "published" and r["url"]]
    return {"rows": rows[:limit], "published": published[:limit],
            "stats": {"records": len(rows),
                      "published": sum(1 for r in rows if r["status"] == "published"),
                      "failed": sum(1 for r in rows if r["status"] == "failed"),
                      "uncertain": sum(1 for r in rows if r["status"] == "uncertain")}}


# ── 视频项目 ────────────────────────────────────────────────────────────────

def videos() -> list:
    out = []
    for d in sorted(VIDEOS.iterdir()) if VIDEOS.exists() else []:
        if not d.is_dir() or d.name.startswith(("_", ".")):
            continue
        proj = _read_json(d / "project.json", {})
        story = _read_json(d / "story.json", {})
        mp4s = sorted(p.name for p in (d / "out").glob("*.mp4")) if (d / "out").exists() else []
        cover = (d / "out" / "cover.png").exists() or (d / "cover.png").exists()
        out.append({"id": d.name,
                    "title": proj.get("title") or story.get("title") or d.name,
                    "status": proj.get("status", "draft"),
                    "date": proj.get("date") or story.get("date") or "",
                    "mp4": mp4s, "cover": cover,
                    "scenes": len(story.get("scenes", [])) if isinstance(story, dict) else 0})
    out.sort(key=lambda v: (v["date"], v["id"]), reverse=True)
    return out


def video_file(vid: str, name: str) -> Path | None:
    if not re.fullmatch(r"[\w\-.]+", vid) or not re.fullmatch(r"[\w\-.]+", name):
        return None
    for base in (VIDEOS / vid / "out", VIDEOS / vid):
        p = base / name
        if p.is_file() and p.suffix.lower() in (".mp4", ".png", ".jpg", ".srt"):
            return p
    return None


# ── 环境自检(设置页"环境体检"卡片) ───────────────────────────────────────────

def selfcheck() -> dict:
    def n_ledger():
        d = _read_json(LEDGER, {})
        return sum(len(v) for v in d.values()) if isinstance(d, dict) else 0
    return {
        "flows_count": len(flows_list()),
        "queue_count": len(artifacts()["queue"]),
        "ledger_records": n_ledger(),
        "video_projects": len(videos()),
        "runs_count": len(runs_list(1000)),
        "paths": {
            "runs": str(RUNS), "output": str(OUTPUT), "queue": str(QUEUE),
            "ledger": str(LEDGER), "videos": str(VIDEOS),
        },
    }
