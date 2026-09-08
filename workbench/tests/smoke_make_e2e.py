# 四段式视频制作 真渲染冒烟（手工脚本，非单测；跑完自清）
# 用法: py -3.11 workbench/tests/smoke_make_e2e.py
# 流程: 直接输入口播稿 → 定稿 → AI 分镜(允许 LLM 失败走兜底) → 定稿 →
#       edge 晓晓真合成语音 → 1拍上传小png + 1拍 AI 生图(真调一次 seedream) + 其余模板 →
#       estimate 无声预览 → build 正式成片 → 校验 verify/log → 删除项目与 make
import json
import struct
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "workbench"))
from fastapi.testclient import TestClient          # noqa: E402
from server.app import create_app                  # noqa: E402

c = TestClient(create_app())
STEP = ""


def fail(msg):
    print(f"SMOKE-FAIL [{STEP}] {msg}")
    sys.exit(1)


def poll_job(kind, timeout_s):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        jobs = c.get("/wb-api/video-jobs").json()
        job = jobs.get(kind) or {}
        if not job.get("running"):
            return job
        time.sleep(3)
    fail(f"任务 {kind} 超时 {timeout_s}s")


def tiny_png(path: Path):
    """320x180 纯色 PNG，零依赖。"""
    w, h = 320, 180
    raw = b"".join(b"\x00" + b"\x33\x66\x99" * w for _ in range(h))
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


make_id, project_id = None, None
try:
    STEP = "create"
    text = ("美联储刚刚宣布维持利率不变，市场却在十分钟内回吐了全天涨幅。"
            "鲍威尔在发布会上暗示，缩表节奏可能比预期更早调整。"
            "过去三十年里，类似的信号只出现过四次，每次都伴随着剧烈的风格切换。"
            "真正的风险藏在哪里，我们下期接着拆。")
    r = c.post("/wb-api/video-makes", json={
        "title": "冒烟测试", "narration": {"text": text, "source": "manual"}})
    if r.status_code != 200:
        fail(r.text)
    make_id = r.json()["make"]["id"]
    print(f"[create] make_id={make_id}")

    STEP = "lock-narration"
    r = c.post(f"/wb-api/video-makes/{make_id}/lock-narration")
    if r.status_code != 200:
        fail(r.text)
    print(f"[lock-narration] hash={r.json()['make']['narration']['hash']}")

    STEP = "storyboard"
    r = c.post("/wb-api/video-storyboard/generate", json={"make_id": make_id})
    if r.status_code != 200:
        fail(r.text)
    job = poll_job("generate", 240)
    if job.get("exit") != 0:
        fail(f"storyboard exit={job.get('exit')} {job.get('error')} {job.get('hint')}")
    make = c.get(f"/wb-api/video-makes/{make_id}").json()["make"]
    beats = make["script"]["beats"]
    warnings = make["script"].get("warnings") or []
    print(f"[storyboard] beats={len(beats)} roles={[b['role'] for b in beats]} warnings={warnings}")

    STEP = "lock-script"
    r = c.post(f"/wb-api/video-makes/{make_id}/lock-script")
    if r.status_code != 200:
        fail(r.text)
    print("[lock-script] ok")

    STEP = "voice"
    r = c.post("/wb-api/video-voice/generate", json={
        "make_id": make_id, "provider_id": "edge",
        "voice": "zh-CN-XiaoxiaoNeural", "scope": "all"})
    if r.status_code != 200:
        fail(r.text)
    job = poll_job("voice", 600)
    if job.get("exit") != 0:
        fail(f"voice exit={job.get('exit')} {job.get('error')}")
    make = c.get(f"/wb-api/video-makes/{make_id}").json()["make"]
    items = make["voice"]["items"]
    if len(items) != len(beats) or make.get("voice_bad"):
        fail(f"voice 覆盖不全 items={list(items)} voice_bad={make.get('voice_bad')}")
    print(f"[voice] voice_key={make['voice']['voice_key']} items="
          f"{ {k: round(v['duration_s'],1) for k,v in items.items()} }")

    STEP = "asset-upload"
    png = ROOT / "data" / "workbench" / "_smoke_px.png"
    tiny_png(png)
    r = c.put(f"/wb-api/video-assets?name=px.png&make_id={make_id}&beat_id={beats[0]['id']}",
              content=png.read_bytes())
    if r.status_code != 200:
        fail(r.text)
    asset_id = r.json()["asset"]["asset_id"]
    print(f"[asset] {asset_id} {r.json()['asset']['size']}B")

    STEP = "overrides"
    overrides = [{"beat_id": beats[0]["id"], "method": "upload_image", "asset_id": asset_id,
                  "kenburns": "in", "credit": "smoke"}]
    if len(beats) > 1:
        overrides.append({"beat_id": beats[1]["id"], "method": "ai_image",
                          "prompt": "美联储议息会议现场的编辑风纸拼贴海报"})
    r = c.post("/wb-api/video-makes", json={
        "id": make_id,
        "video": {"mode": "edit", "aspect": "16:9", "fps": 30, "theme": "terminal-dark",
                  "layout": "auto", "enrich": "plain", "hook_index": 0,
                  "beat_overrides": overrides}})
    if r.status_code != 200:
        fail(r.text)
    print(f"[overrides] {[(o['beat_id'], o['method']) for o in overrides]}")

    for mode, expect in (("estimate", "preview-silent.mp4"), ("build", "final.mp4")):
        STEP = f"video-build-{mode}"
        r = c.post("/wb-api/video-build", json={"make_id": make_id, "mode": mode})
        if r.status_code != 200:
            fail(r.text)
        project_id = r.json()["project_id"]
        job = poll_job("build", 1500 if mode == "build" else 600)
        if job.get("exit") != 0:
            fail(f"build exit={job.get('exit')} {job.get('error')} {job.get('hint')}")
        out = ROOT / "ai-workflow" / "video" / "videos" / project_id / "out"
        verify = json.loads((out / "verify.json").read_text(encoding="utf-8"))
        if verify.get("errors"):
            fail(f"verify errors={verify['errors']}")
        if not (out / expect).is_file():
            fail(f"产物缺失 {expect}")
        log = (ROOT / "data" / "workbench" / "video_builds" / f"{project_id}.log") \
            .read_text(encoding="utf-8", errors="replace")
        tts_skip = "语音已全部存在" in log
        print(f"[{mode}] project={project_id} {expect}={((out/expect).stat().st_size)//1024}KB "
              f"verify_duration={round(verify.get('durationS', 0), 1)}s "
              f"warnings={verify.get('warnings')} tts_skip={tts_skip}")
        if mode == "build" and not tts_skip:
            fail("build 日志未见『语音已全部存在』——预拷贝语音未命中")

    print("SMOKE-OK")
finally:
    # 清理前等本项目相关任务收尾，避免删除后孤儿进程回写
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        jobs = c.get("/wb-api/video-jobs").json()
        busy = [k for k in ("generate", "voice", "build")
                if (jobs.get(k) or {}).get("running")
                and (jobs[k].get("request") or {}).get("make_id") in (make_id, None)
                and (k != "build" or (jobs[k].get("request") or {}).get("project_id") == project_id)]
        if not busy:
            break
        time.sleep(3)
    if project_id:
        r = c.delete(f"/wb-api/videos/{project_id}")
        print(f"[cleanup] project {project_id} -> {r.status_code}")
    if make_id:
        r = c.delete(f"/wb-api/video-makes/{make_id}")
        print(f"[cleanup] make {make_id} -> {r.status_code}")
    p = ROOT / "data" / "workbench" / "_smoke_px.png"
    p.unlink(missing_ok=True)
