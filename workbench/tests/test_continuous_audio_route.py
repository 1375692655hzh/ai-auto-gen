# 音频路线·原音连续主轨(0917 用户裁决)回归: 不切音频, 只规划画面时间轴; gate/handoff 走 master。
# 语义: 成片唯一音轨=用户上传原始音频比特流(ffmpeg -c:a copy remux), 画面按绝对时间轴排布。
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workbench.server import config, vstudio


def _mk_asset(ext: str, body: bytes) -> str:
    aid = "va" + ext.ljust(6, "0")[:8]
    root = vstudio.assets_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{aid}.{ext}").write_bytes(body)
    return aid


def _audio_make(narration="第一句话在这里。第二句话也来了。", beats=None, asset_id=None):
    row = vstudio.make_upsert({"route": "audio", "title": "连续主轨测试"})
    if asset_id:
        row["audio"] = {"asset_id": asset_id, "src_ext": "mp3", "seconds": 800.9}
    row["narration"].update(text=narration, locked=True)
    row["script"] = {"beats": beats or [
        {"id": "b1", "narration": "第一句话在这里。"},
        {"id": "b2", "narration": "第二句话也来了。"}]}
    row["script_meta"] = {"locked": True, "locked_at": "x", "hash": "h",
                          "source_narration_hash": "h"}
    vstudio._make_save(row)
    return row


class ContinuousMasterTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        p = patch.object(config, "DATA_DIR", self.tmp)
        p.start()
        self.addCleanup(p.stop)

    def test_ensure_master_m4a_byte_copy(self):
        """m4a 上传: master=原始字节直拷, delivery=stream-copy, 不转码。"""
        body = b"FAKE-M4A-BYTES-" + bytes(range(64))
        aid = _mk_asset("m4a", body)
        row = _audio_make(asset_id=aid)
        master, err = vstudio._ensure_master(row)
        self.assertFalse(err)
        self.assertEqual(master["delivery"], "stream-copy")
        self.assertEqual(master["ext"], "m4a")
        mfile = vstudio._safe_path(vstudio.voice_root(), row["id"], master["file"])
        self.assertEqual(mfile.read_bytes(), body)          # 字节级=用户上传原文件
        self.assertAlmostEqual(master["duration_s"], 800.9)  # ffprobe 失败回退 seconds

    def test_ensure_master_video_stream_copy_then_fallback(self):
        """视频上传: -map 0:a:0 -c:a copy 抽轨; copy 失败一次性 aac 转码并标记 normalized。"""
        aid = _mk_asset("mp4", b"FAKE-MP4")
        row = _audio_make(asset_id=aid)
        calls = []

        def fake_run(argv, **kw):
            calls.append(argv)

            class P:
                returncode = 0
                stdout, stderr = "", ""
            Path(argv[-1]).write_bytes(b"EXTRACTED-AAC" + b"\0" * 4096)
            return P()

        with patch.object(vstudio.subprocess, "run", fake_run), \
                patch.object(vstudio, "_probe_duration", lambda p: 123.4):
            master, err = vstudio._ensure_master(row)
        self.assertFalse(err)
        self.assertEqual(master["delivery"], "stream-copy")
        flat = [a for argv in calls for a in argv]
        self.assertIn("0:a:0", flat)
        self.assertIn("copy", flat)
        # 失败回退: copy 返回非 0 → aac 转码
        calls.clear()

        def bad_run(argv, **kw):
            calls.append(argv)

            class P:
                returncode = 0
                stdout, stderr = "", ""
            if "aac" in argv:                     # 第二次(转码)成功
                Path(argv[-1]).write_bytes(b"AAC-TRANSCODED" + b"\0" * 4096)
            else:
                P.returncode = 1
                P.stderr = "boom"
            return P()

        mfile = vstudio._safe_path(vstudio.voice_root(), row["id"], "master.m4a")
        mfile.unlink(missing_ok=True)
        with patch.object(vstudio.subprocess, "run", bad_run), \
                patch.object(vstudio, "_probe_duration", lambda p: 123.4):
            master, err = vstudio._ensure_master(row)
        self.assertFalse(err)
        self.assertEqual(master["delivery"], "normalized-aac")
        self.assertIn("aac", calls[-1])

    def test_run_slice_plans_timeline_without_cutting(self):
        """核心: _run_slice 不再调 cut-audio.mjs, 产出全轨连续时间轴(首0末满/相邻相接)。"""
        aid = _mk_asset("m4a", b"M4A-BYTES")
        row = _audio_make(narration="第一句话在这里。第二句话也来了。",
                          beats=[{"id": "b1", "narration": "第一句话在这里。"},
                                 {"id": "b2", "narration": "第二句话也来了。"}],
                          asset_id=aid)
        # source.mp3(钉词工作输入)须存在
        src = vstudio._asr_source_path(row["id"], ".mp3")
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"MP3-SOURCE")
        phrases = [{"id": 0, "text": "第一句话在这里。", "start": 1.0, "end": 3.0},
                   {"id": 1, "text": "第二句话也来了。", "start": 3.4, "end": 5.6}]
        mfile = vstudio._safe_path(vstudio.voice_root(), row["id"], "master.m4a")
        mfile.write_bytes(b"M4A-BYTES")
        fake_master = {"file": "master.m4a", "ext": "m4a", "asset_id": aid,
                       "hash": vstudio._file_hash8(mfile), "duration_s": 5.9,
                       "delivery": "stream-copy"}
        node_calls = []

        def fake_node(argv, **kw):
            node_calls.append(argv)
            raise AssertionError("连续主轨模式不得调用 node 切片链")

        with patch.object(vstudio, "_asr_pin",
                          return_value=(phrases, "", {"match_rate": 1.0})), \
                patch.object(vstudio, "_ensure_master", return_value=(fake_master, "")), \
                patch.object(vstudio.subprocess, "run", fake_node):
            result, code = vstudio._run_slice({"make_id": row["id"]})
        self.assertEqual(code, 0, result)
        current = vstudio.make_get(row["id"])
        self.assertEqual(current["status"], "voice_ready")
        self.assertEqual(current["voice"]["items"], {})            # 不再有逐幕切片
        self.assertEqual(current["voice"]["voice_key"], "")
        tl_file = vstudio._safe_path(vstudio.voice_root(), row["id"], "master.timeline.json")
        tl = json.loads(tl_file.read_text(encoding="utf-8"))
        self.assertEqual(tl["schema"], "wb-original-continuous-timeline/v1")
        self.assertEqual(tl["audio_hash"], fake_master["hash"])
        self.assertEqual(len(tl["beats"]), 2)
        self.assertEqual(tl["beats"][0]["start_s"], 0.0)           # 首幕从 0(保留片头)
        self.assertEqual(tl["beats"][-1]["end_s"], 5.9)            # 末幕到 EOF(保留片尾)
        self.assertEqual(tl["beats"][0]["end_s"], tl["beats"][1]["start_s"])   # 相邻相接无洞
        # 中点边界: (3.0+3.4)/2=3.2
        self.assertAlmostEqual(tl["beats"][0]["end_s"], 3.2, places=2)
        self.assertFalse(node_calls)
        # audio 元数据: master+timeline 注册, cuts 仅 UI 展示
        self.assertEqual(current["audio"]["master"]["hash"], fake_master["hash"])
        self.assertEqual(current["audio"]["timeline"]["beats"], 2)
        self.assertEqual(current["audio"]["cuts"][0]["cut_mode"], "continuous")

    def test_run_slice_degenerate_beat_rejected(self):
        """量化后分不到画面时间的幕 → 明确报错, 不悄悄产出近 0 长区间。"""
        aid = _mk_asset("m4a", b"M4A-BYTES")
        row = _audio_make(narration="只有一句话。",
                          beats=[{"id": "b1", "narration": "只有"},
                                 {"id": "b2", "narration": "一句话。"}],
                          asset_id=aid)
        src = vstudio._asr_source_path(row["id"], ".mp3")
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"MP3")
        # 边界中点 0.02s → b1 画面区间不足 0.05s
        phrases = [{"id": 0, "text": "只有", "start": 0.0, "end": 0.02},
                   {"id": 1, "text": "一句话。", "start": 0.02, "end": 2.0}]
        mfile = vstudio._safe_path(vstudio.voice_root(), row["id"], "master.m4a")
        mfile.write_bytes(b"M4A")
        fake_master = {"file": "master.m4a", "ext": "m4a", "asset_id": aid,
                       "hash": vstudio._file_hash8(mfile), "duration_s": 2.0,
                       "delivery": "stream-copy"}
        with patch.object(vstudio, "_asr_pin",
                          return_value=(phrases, "", {"match_rate": 1.0})), \
                patch.object(vstudio, "_ensure_master", return_value=(fake_master, "")):
            result, code = vstudio._run_slice({"make_id": row["id"]})
        self.assertEqual(code, 3)
        self.assertEqual(result["error"], "timeline_degenerate")

    def test_master_gate_and_route_awareness(self):
        """audio 路线 gate 查主轨+时间轴; script 路线维持逐幕 take 校验。"""
        row = _audio_make()
        # 无 master/timeline → 拦
        missing = vstudio.master_audio_missing(row)
        self.assertTrue(any("主轨" in m for m in missing))
        # 齐备 → 放行
        mfile = vstudio._safe_path(vstudio.voice_root(), row["id"], "master.m4a")
        mfile.parent.mkdir(parents=True, exist_ok=True)
        mfile.write_bytes(b"M4A")
        row["audio"] = {"asset_id": "va1", "src_ext": "mp3",
                        "master": {"file": "master.m4a", "hash": vstudio._file_hash8(mfile),
                                   "duration_s": 5.9},
                        "timeline": {"file": "master.timeline.json", "beats": 2,
                                     "narration_hash": vstudio.voice_hash(row["narration"]["text"])}}
        tl_file = vstudio._safe_path(vstudio.voice_root(), row["id"], "master.timeline.json")
        tl_file.write_text("{}", encoding="utf-8")
        self.assertEqual(vstudio.master_audio_missing(row), [])
        self.assertEqual(vstudio._audio_gate_missing(row), [])
        # 文稿改动 → 时间轴过期拦
        row["narration"]["text"] += "新增句"
        self.assertTrue(any("过期" in m for m in vstudio.master_audio_missing(row)))
        # script 路线不受影响: 仍走逐幕 take
        srow = vstudio.make_upsert({"route": "script", "title": "文案单"})
        srow["script"] = {"beats": [{"id": "b1", "narration": "x"}]}
        vstudio._make_save(srow)
        self.assertEqual(vstudio._audio_gate_missing(srow), ["b1"])   # voice_missing 语义原样

    def test_audio_bind_needs_route_in_same_payload(self):
        """0917 分发用户案回归: 前端历史上传不带 route, 服务端对 route!=audio 的单
        静默丢 audio → 用户"传完没反应"。规则=route 与 audio 必须同载荷; 绑定保留 asset_name。"""
        aid = _mk_asset("mp3", b"FAKE-MP3-" + bytes(range(32)))
        # 新单(默认路线)只发 audio → 被丢弃(契约: 音频绑定只属于音频路线)
        row = vstudio.make_upsert({"title": "路线未带"})
        self.assertIsNone(vstudio.make_upsert({"id": row["id"], "audio": {"asset_id": aid}}).get("audio"))
        # route+audio 同载荷 → 绑定成功且 asset_name 回显
        row2 = vstudio.make_upsert({"id": row["id"], "route": "audio",
                                    "audio": {"asset_id": aid, "asset_name": "晨会录音.mp3"}})
        self.assertEqual(row2["route"], "audio")
        self.assertEqual(row2["audio"]["asset_id"], aid)
        self.assertEqual(row2["audio"]["asset_name"], "晨会录音.mp3")

    def test_video_env_summary_reports_ffmpeg_flag(self):
        """presets.video_env 必须带 ffmpeg_ok: 前端靠它在第 1 步拦下无 ffmpeg 的视频上传。"""
        env = vstudio.video_env_summary()
        self.assertIn("ok", env)
        self.assertIn("err", env)
        self.assertIsInstance(env["ffmpeg_ok"], bool)

    def test_run_slice_node_env_fast_fail(self):
        """裸机缺 Node: 第 4 步快败给环境指引, 不误报'校对改写幅度过大'让用户去改稿(0917 分发审计)。"""
        row = _audio_make()
        # 主轨+转写源在位(前置校验全过, 直达钉词前的环境检查)
        vdir = vstudio._safe_path(vstudio.voice_root(), row["id"])
        vdir.mkdir(parents=True, exist_ok=True)
        mfile = vdir / "master.m4a"
        mfile.write_bytes(b"M4A")
        row["audio"] = {"asset_id": "va1"}
        row["audio"].update(master={"file": "master.m4a", "hash": vstudio._file_hash8(mfile),
                                    "duration_s": 5.9}, src_ext="mp3")
        (vdir / "source.mp3").write_bytes(b"MP3")
        vstudio._make_save(row)
        with patch.object(vstudio, "node_env_check",
                          return_value=(False, "未检测到 Node.js：视频功能需 Node ≥ 20")):
            report, code = vstudio._run_slice({"make_id": row["id"]})
        self.assertEqual(code, 3)
        self.assertEqual(report["error"], "node_env")
        self.assertIn("Node", report["hint"])

    def test_run_asr_wav_src_ext_real_suffix(self):
        """wav 转写回写 src_ext=wav(0917 cursor 复审 P1: 旧写死 mp3, 第 4 步找不到 source.wav)。"""
        from workbench.server import vasr
        aid = _mk_asset("wav", b"FAKE-WAV-" + bytes(range(16)))
        row = vstudio.make_upsert({"route": "audio", "audio": {"asset_id": aid}, "title": "wav案"})
        with patch.object(vstudio, "_asr_pin", return_value=(
                [{"id": "s1", "text": "第一句话在这里。", "start": 0.0, "end": 2.0}], "", {})), \
             patch.object(vstudio, "_ensure_master", return_value=(
                {"file": "master.wav", "hash": "x", "duration_s": 2.0,
                 "delivery": "stream-copy", "ext": "wav"}, "")), \
             patch.object(vasr, "transcribe_file",
                          return_value={"text": "第一句话在这里。", "seconds": 2.0}), \
             patch.object(vstudio, "_plan_asr_segments", return_value=([(0.0, 0.0)], "")):
            report, code = vstudio._run_asr({"make_id": row["id"]})
        self.assertEqual(code, 0, report)
        cur = vstudio.make_get(row["id"])
        self.assertEqual(cur["audio"]["src_ext"], "wav")
        self.assertTrue(vstudio._safe_path(vstudio.voice_root(), row["id"], "source.wav").is_file())

    def test_run_asr_short_mp3_without_ffmpeg_single_segment(self):
        """无 ffmpeg 裸机: ≤7MB mp3/wav 跳过静音分段直传(官方引导"没 ffmpeg 传 mp3"不再自相矛盾)。"""
        from workbench.server import vasr
        aid = _mk_asset("mp3", b"FAKE-MP3-SHORT-" + bytes(range(16)))
        row = vstudio.make_upsert({"route": "audio", "audio": {"asset_id": aid}, "title": "裸机mp3"})
        with patch.object(vstudio, "_resolve_ffmpeg", return_value=""), \
             patch.object(vstudio, "_plan_asr_segments",
                          side_effect=AssertionError("无 ffmpeg 短音频不应走静音分段")), \
             patch.object(vstudio, "_asr_pin", return_value=([], "whisper 不可用", {})), \
             patch.object(vstudio, "_estimate_phrases", return_value=([], "no ffmpeg")), \
             patch.object(vstudio, "_ensure_master", return_value=({}, "skip")), \
             patch.object(vasr, "transcribe_file",
                          return_value={"text": "转写文本在这里。", "seconds": 3.0}):
            report, code = vstudio._run_asr({"make_id": row["id"]})
        self.assertEqual(code, 0, report)
        cur = vstudio.make_get(row["id"])
        self.assertEqual(cur["narration"]["text"], "转写文本在这里。")
        self.assertEqual(cur["audio"]["src_ext"], "mp3")

    def test_make_view_timeline_current(self):
        """时间轴时效(0917 cursor 复审 P2): 文稿哈希/beat id 序列任一变化即 timeline_current=False。"""
        row = _audio_make()
        vdir = vstudio._safe_path(vstudio.voice_root(), row["id"])
        vdir.mkdir(parents=True, exist_ok=True)
        mfile = vdir / "master.m4a"
        mfile.write_bytes(b"M4A")
        row["audio"] = {"asset_id": "va1",
                        "master": {"file": "master.m4a", "hash": vstudio._file_hash8(mfile),
                                   "duration_s": 5.9},
                        "timeline": {"file": "master.timeline.json", "beats": 2,
                                     "narration_hash": vstudio.voice_hash(row["narration"]["text"]),
                                     "ids": ["b1", "b2"]}}
        (vdir / "master.timeline.json").write_text("{}", encoding="utf-8")
        vstudio._make_save(row)
        view = vstudio.make_view(row)
        self.assertTrue(view["audio"]["timeline_current"])
        view["narration"]["text"] += "改稿"
        self.assertFalse(vstudio.make_view(view)["audio"]["timeline_current"])
        view2 = vstudio.make_view(vstudio.make_get(row["id"]))
        view2["audio"]["timeline"]["ids"] = ["b1", "b9"]
        self.assertFalse(vstudio.make_view(view2)["audio"]["timeline_current"])


if __name__ == "__main__":
    unittest.main()
