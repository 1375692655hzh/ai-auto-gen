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


if __name__ == "__main__":
    unittest.main()
