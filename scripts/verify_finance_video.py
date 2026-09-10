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


def check():
    from PIL import Image, ImageChops, ImageStat
    sys.path.insert(0, str(ROOT / "workbench"))
    from server.finance_compliance import NUMBER_FACT
    result = read(RUN / "narration/video_jobs.json")["generate"]["result"]
    text = result["text"]
    checks = {
        "disclaimer": "不构成投资建议" in result["disclaimer"] and "不构成投资建议" in text,
        "position": "重仓" not in text and any(t in text for t in ("承受能力", "自行判断", "参与比例")),
        "returns": "必涨" not in text and any(t in text for t in ("若", "如果", "条件")),
        "source": any(t in text for t in ("材料声称", "待核", "待核实", "尚待核实")),
        "living_person": all(t not in text for t in ("据前员工描述", "张某", "挪用")),
        "company_expectation": "有望受益" in text or "市场预期" in text,
        "fiction": "虚构" in text,
    }
    assert all(checks.values()), checks
    print("NARRATION", checks)
    compositor = VIDEO / "node_modules/@remotion/compositor-win32-x64-msvc"
    reports = []
    for pid in (SAMPLE_ID, "finance-short-0909"):
        project = VIDEO / "videos" / pid
        out = project / "out"
        qa, timeline, story = read(out / "verify.json"), read(out / "timeline.json"), read(project / "story.json")
        assert not qa["errors"], qa
        assert qa["stills"] == len(story["scenes"])
        frames, fps = timeline["frames"], timeline["fps"]
        assert all(f["durationInFrames"] >= 5.5 * fps for f in frames)
        assert all(f["alignmentMethod"] == "approximate-text-weight" for f in frames)
        for frame, scene in zip(frames, story["scenes"]):
            previous = 0
            for cue in frame["cues"]:
                assert cue["start"] >= previous and cue["end"] > cue["start"]
                previous = cue["end"]
            assert previous <= frame["durationInFrames"]
            assert "".join("".join(c["t"].split()) for c in frame["cues"]) == "".join(scene["narration"].split())
            assert (out / "keyframes" / (scene["id"] + ".png")).is_file()
        doc = (out / "发布前核对.md").read_text(encoding="utf-8")
        facts = [m.group() for s in story["scenes"] for m in NUMBER_FACT.finditer(s["narration"])]
        assert all(value in doc for value in facts)
        media = json.loads(subprocess.check_output([str(compositor / "ffprobe.exe"), "-v", "error", "-show_streams",
                                                   "-show_format", "-of", "json", str(out / "final.mp4")]))
        assert {s["codec_type"] for s in media["streams"]} >= {"video", "audio"}
        assert abs(float(media["format"]["duration"]) - qa["durationS"]) < .15
        subprocess.run([str(compositor / "ffmpeg.exe"), "-v", "error", "-i", str(out / "final.mp4"),
                        "-c:v", "rawvideo", "-c:a", "pcm_s16le", "-f", "null", "-"], check=True, capture_output=True)
        reports.append({"project": pid, "duration": qa["durationS"], "stills": qa["stills"], "errors": qa["errors"],
                        "min_scene_seconds": min(f["durationInFrames"] / fps for f in frames),
                        "caption_methods": qa["captionMethods"], "facts": facts, "decode": "PASS"})
        if pid == "finance-short-0909":
            first = frames[0]
            assert first["durationInFrames"] == 5.5 * fps > first["visualDurationInFrames"]
            def pixels(n):
                png = RUN / f"frozen-tail-{n}.png"
                subprocess.run([str(compositor / "ffmpeg.exe"), "-v", "error", "-y", "-i", str(out / "final.mp4"),
                    "-vf", f"trim=start_frame={n}:end_frame={n+1}", "-frames:v", "1", "-update", "1", str(png)], check=True)
                with Image.open(png) as image:
                    return image.convert("RGB")
            delta = ImageStat.Stat(ImageChops.difference(pixels(first["visualDurationInFrames"] - 1),
                                                       pixels(first["durationInFrames"] - 1))).mean
            assert max(delta) < 1, delta
            reports[-1]["frozen_tail_mean_pixel_difference"] = delta
    for origin in read(VIDEO / "videos" / SAMPLE_ID / "acceptance-origin.json")["audio"]:
        assert hashlib.sha256(Path(origin["source"]).read_bytes()).hexdigest() == origin["sha256"]
        assert hashlib.sha256(Path(origin["target"]).read_bytes()).hexdigest() == origin["sha256"]
    save(RUN / "checks.json", {"narration": checks, "videos": reports, "source_audio_unchanged": True,
                              "edge_live": "BLOCKED EACCES; no actual provider cues produced"})
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "prepare":
        prepare()
    elif action == "prepare-short":
        prepare_short()
    elif action == "check":
        check()
    else:
        sys.exit(run(action))
