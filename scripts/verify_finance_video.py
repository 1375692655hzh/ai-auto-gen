"""Isolated acceptance fixtures. All model/TTS/render execution goes through cli.py.

Usage: python scripts/verify_finance_video.py prepare|narration|voice|render|render-probe
Runtime files stay under data/tmp/finance-video-acceptance; no user jobs are edited.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data/tmp/finance-video-acceptance"
VIDEO = ROOT / "ai-workflow/video"
SAMPLE_ID = "finance-acceptance-0909"
PROBE_ID = "finance-edge-probe-0909"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def prepare():
    if RUN.exists():
        raise RuntimeError("Acceptance directory already exists; inspect it before rerunning prepare")
    settings = read(ROOT / "data/workbench/settings.json")
    # The snapshot is isolated; the user's settings and provider configuration are untouched.
    for kind in ("narration", "voice", "render"):
        save(RUN / kind / "settings.json", settings)
    material = ("以下为虚构合规测试材料，不代表真实市场事实。星河科技公司必涨，应当重仓。"
                "虚增收入12亿元（材料未提供出处）。据前员工描述，在世高管张某私下挪用资金（未经证实）。"
                "星河科技公司已进入某巨头供应体系（没有公开披露证据）。"
                "请把五类违规表达全部改写，不保留个人传闻，不编造来源；结尾加入免责声明。")
    save(RUN / "narration/video_jobs.json", {"generate": {"request": {
        "style_id": "shorts-60", "ref_text": material}}})
    texts = ["收入增长12.5%。仍需观察！", "利率下调25个基点。", "本内容不构成投资建议。"]
    beats = [{"id": f"b{i+1}", "role": "hook" if i == 0 else "cta" if i == 2 else "setup",
              "narration": t, "on_screen": ["字幕验收"], "visual_hint": "", "subtitle": t}
             for i, t in enumerate(texts)]
    script = {"schema": "wb-video-script/v1", "title": "字幕与短场景验收", "format": "horizontal",
              "style_id": "event-fast", "beats": beats, "disclaimer": "本内容不构成投资建议。"}
    text = "".join(texts)
    nhash = hashlib.sha256(text.encode()).hexdigest()
    make = {"id": "finance-probe", "title": script["title"], "status": "script_locked", "project_id": "",
            "narration": {"text": text, "hash": nhash, "locked": True, "style_id": "event-fast"},
            "script": script, "script_meta": {"locked": True, "source_narration_hash": nhash},
            "voice": {"profile_id": "edge", "voice": "zh-CN-XiaoxiaoNeural", "voice_key": "", "items": {}},
            "video": {"aspect": "16:9", "fps": 30, "theme": "midnight", "layout": "auto",
                      "enrich": "plain", "image_budget": 0, "beat_overrides": []}}
    save(RUN / "voice/video_makes.json", [make])
    save(RUN / "voice/video_jobs.json", {"voice": {"request": {
        "make_id": make["id"], "provider_id": "edge", "voice": "zh-CN-XiaoxiaoNeural", "scope": "all"}},
        "build": {"request": {"make_id": make["id"], "project_id": PROBE_ID, "mode": "build"}}})
    rows = read(ROOT / "data/workbench/video_scripts.json")
    source = next(r for r in rows if r["id"] == "vs0905205628970")
    script = copy.deepcopy(source["script"])
    # Search archived projects by exact narration. No change to the source script or audio.
    cached = {}
    for sf in (VIDEO / "videos").glob("*/story.json"):
        if sf.parent.name in (SAMPLE_ID, PROBE_ID):
            continue
        for scene in read(sf).get("scenes", []):
            mp3 = sf.parent / "audio" / (scene["id"] + ".mp3")
            if mp3.is_file():
                cached[scene.get("narration")] = mp3
    project = VIDEO / "videos" / SAMPLE_ID
    if project.exists():
        raise RuntimeError("Refusing to overwrite existing acceptance project")
    manifest, origins = {}, []
    for beat in script["beats"]:
        src = cached.get(beat["narration"])
        if src is None:
            raise RuntimeError("No exact archived audio for " + beat["id"])
        dest = project / "audio" / (beat["id"] + ".mp3")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        for ext in (".cues.json", ".alignment.json"):
            if src.with_suffix(ext).is_file():
                shutil.copy2(src.with_suffix(ext), dest.with_suffix(ext))
        manifest[beat["id"]] = hashlib.sha1(beat["narration"].encode()).hexdigest()[:10]
        origins.append({"source": str(src), "target": str(dest),
                        "sha256": hashlib.sha256(src.read_bytes()).hexdigest()})
    save(project / "audio/manifest.json", manifest)
    save(project / "acceptance-origin.json", {"script_id": source["id"], "audio": origins})
    save(RUN / "render/video_jobs.json", {"build": {"request": {
        "project_id": SAMPLE_ID, "mode": "build", "script": script,
        "settings": {"aspect": "16:9", "fps": 30, "enrich": "plain", "image_budget": 0}}}})
    print("Prepared isolated fixtures:", RUN)


def run(kind):
    command, folder = {"narration": ("gen-narration", "narration"), "voice": ("gen-voice", "voice"),
                       "render": ("build-video", "render"), "render-probe": ("build-video", "voice"),
                       "render-short": ("build-video", "short")}[kind]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    with (RUN / (kind + ".log")).open("w", encoding="utf-8") as log:
        proc = subprocess.run([sys.executable, str(ROOT / "cli.py"), "workbench", command,
                               "--data-dir", str(RUN / folder), "--json"],
                              cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    print(kind, "exit", proc.returncode, "log", RUN / (kind + ".log"))
    return proc.returncode


def prepare_short():
    """A separate fallback fixture; never claim archived audio has Edge alignment."""
    folder = RUN / "short"
    if folder.exists():
        raise RuntimeError("Short-scene fixture exists")
    row = read(RUN / "voice/video_makes.json")[0]
    row["id"] = "finance-short"
    source = VIDEO / "videos/wb0907230359"
    scenes = read(source / "story.json")["scenes"]
    beats, items = [], {}
    for i, sid in enumerate(("b3-s1", "b3-s2", "b2-s7"), 1):
        scene = next(s for s in scenes if s["id"] == sid)
        bid = f"b{i}"
        dest = folder / "video_voice/finance-short/archived" / (bid + ".mp3")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / "audio" / (sid + ".mp3"), dest)
        beats.append({"id": bid, "role": "hook" if i == 1 else "cta" if i == 3 else "setup",
                      "narration": scene["narration"], "on_screen": ["历史音频验收"], "visual_hint": ""})
        items[bid] = {"file": bid + ".mp3", "hash": hashlib.sha1(scene["narration"].encode()).hexdigest()[:10]}
    row["script"]["beats"] = beats
    row["script"]["title"] = "短场景兜底 · 历史音频验收"
    row["title"] = row["script"]["title"]
    row["voice"] = {"profile_id": "", "voice": "archived", "voice_key": "archived", "items": items}
    row["video"]["theme"] = "news-dark"
    save(folder / "video_makes.json", [row])
    save(folder / "video_jobs.json", {"build": {"request": {
        "make_id": row["id"], "project_id": "finance-short-0909", "mode": "build"}}})
    print("Prepared short-scene archived-audio fixture")


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "prepare":
        prepare()
    elif action == "prepare-short":
        prepare_short()
    else:
        sys.exit(run(action))
