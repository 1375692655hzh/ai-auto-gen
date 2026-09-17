"""音频路线(上传录音→mimo 转写→whisper 钉词→切原声)离线单测: HTTP/Node 全 mock。"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import config, vstudio


class AudioRouteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        p = patch.object(config, "DATA_DIR", self.tmp)
        p.start()
        self.addCleanup(p.stop)

    def test_config_asr_section_and_masking(self):
        cfg = config.load()
        self.assertIn("asr", cfg)
        self.assertEqual(cfg["asr"]["language"], "zh")
        view = config.public_view(cfg)
        self.assertEqual(view["asr"]["api_key"], "")
        self.assertFalse(view["asr"]["has_key"])
        cfg2 = config.apply_patch({"asr": {"api_key": "tp-test123", "language": "en",
                                           "base_url": "https://x/v1", "model": "m"}})
        self.assertEqual(cfg2["asr"]["api_key"], "tp-test123")
        self.assertEqual(cfg2["asr"]["language"], "en")
        view2 = config.public_view(cfg2)
        self.assertEqual(view2["asr"]["api_key"], "")
        self.assertTrue(view2["asr"]["has_key"])
        self.assertEqual(view2["asr"]["key_tail"], "t123")
        # 空 key 留空=保持不变(与其他凭据段同语义)
        cfg3 = config.apply_patch({"asr": {"api_key": "", "language": "zh"}})
        self.assertEqual(cfg3["asr"]["api_key"], "tp-test123")
        self.assertEqual(cfg3["asr"]["language"], "zh")

    def test_make_upsert_route_and_audio_binding(self):
        row = vstudio.make_upsert({"route": "audio", "title": "音频测试"})
        self.assertEqual(row["route"], "audio")
        self.assertIsNone(row["audio"])
        # 绑定音频; 未锁定时换音频=转写/脚本全重置
        row = vstudio.make_upsert({"id": row["id"], "audio": {"asset_id": "va123"}})
        self.assertEqual(row["audio"]["asset_id"], "va123")
        row["narration"].update(text="x" * 50)
        vstudio._make_save(row)
        row = vstudio.make_upsert({"id": row["id"], "audio": {"asset_id": "va456"}})
        self.assertEqual(row["audio"]["asset_id"], "va456")
        self.assertEqual(row["narration"]["text"], "")
        self.assertIsNone(row["script"])
        # 已锁定时拒绝静默换音频
        vstudio.make_upsert({"id": row["id"], "narration": {"text": "y" * 50}})
        vstudio.lock_narration(row["id"])
        row = vstudio.make_upsert({"id": row["id"], "audio": {"asset_id": "va789"}})
        self.assertEqual(row["audio"]["asset_id"], "va456")

    def test_audio_route_voice_protected_from_provider_backfill(self):
        """0917 e2e 实证: 前端给音频路线单回填默认 TTS 供应商不得清已切原声。"""
        row = vstudio.make_upsert({"route": "audio", "title": "音频单"})
        row["voice"].update(profile_id="", voice="", voice_key="asr-abcd1234",
                            items={"b1": {"file": "b1.mp3", "hash": "h", "duration_s": 5}})
        row["status"] = "voice_ready"
        vstudio._make_save(row)
        row = vstudio.make_upsert({"id": row["id"], "voice": {"profile_id": "edge", "voice": "zh-CN-XiaoxiaoNeural"}})
        self.assertEqual(row["voice"]["voice_key"], "asr-abcd1234")
        self.assertEqual(row["voice"]["items"]["b1"]["hash"], "h")
        self.assertEqual(row["status"], "voice_ready")

    def test_assign_phrases_atomic_allocation(self):
        phrases = [
            {"id": 0, "text": "第一句话。", "start": 0.5, "end": 2.1},
            {"id": 1, "text": "第二句来了，", "start": 2.1, "end": 4.0},
            {"id": 2, "text": "第三句收尾。", "start": 4.0, "end": 6.2},
        ]
        beats = [{"id": "b1", "narration": "第一句话。"},
                 {"id": "b2", "narration": "第二句来了，第三句收尾。"}]
        groups = vstudio._assign_phrases(beats, phrases)
        self.assertEqual([p["id"] for p in groups[0]], [0])
        self.assertEqual([p["id"] for p in groups[1]], [1, 2])
        # beat 边界切在句中 → 整句归前幕(切点永远句边界)
        beats2 = [{"id": "b1", "narration": "第一句话。第二句来了，"},
                  {"id": "b2", "narration": "第三句收尾。"}]
        groups2 = vstudio._assign_phrases(beats2, phrases)
        self.assertEqual([p["id"] for p in groups2[0]], [0, 1])
        self.assertEqual([p["id"] for p in groups2[1]], [2])

    def test_vasr_payload_shape(self):
        """官方协议: 单条 input_audio, 禁 text; language 透传 asr_options。"""
        import server.vasr as vasr
        from types import SimpleNamespace
        audio = self.tmp / "a.mp3"
        audio.write_bytes(b"fake-mp3")
        captured = {}
        def fake_urlopen(req, timeout=None):
            captured["payload"] = json.loads(req.data.decode())
            captured["url"] = req.full_url
            return SimpleNamespace(read=lambda: json.dumps(
                {"choices": [{"message": {"content": "转写文本"}}],
                 "usage": {"seconds": 8, "prompt_tokens_details": {"audio_tokens": 44}}}).encode(),
                close=lambda: None)
        config.apply_patch({"asr": {"base_url": "https://token-plan-cn.xiaomimimo.com/v1",
                                    "api_key": "tp-x", "language": "zh"}})
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            out = vasr.transcribe_file(audio)
        self.assertEqual(out["text"], "转写文本")
        self.assertEqual(out["seconds"], 8)
        payload = captured["payload"]
        self.assertEqual(payload["model"], "mimo-v2.5-asr")
        self.assertEqual(payload["asr_options"], {"language": "zh"})
        content = payload["messages"][0]["content"]
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0]["type"], "input_audio")       # 禁带 text part(带上 400)
        self.assertTrue(content[0]["input_audio"]["data"].startswith("data:audio/mpeg;base64,"))
        self.assertTrue(captured["url"].endswith("/chat/completions"))

    def test_vasr_error_classification(self):
        import server.vasr as vasr
        import urllib.error
        audio = self.tmp / "a.mp3"
        audio.write_bytes(b"x")
        config.apply_patch({"asr": {"api_key": ""}})
        with self.assertRaises(vasr.AsrError) as ctx:
            vasr.transcribe_file(audio)
        self.assertEqual(ctx.exception.kind, "no_key")
        config.apply_patch({"asr": {"api_key": "tp-x"}})
        def raise_401(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 401, "unauth", {}, io.BytesIO(b"{}"))
        with patch("urllib.request.urlopen", side_effect=raise_401):
            with self.assertRaises(vasr.AsrError) as ctx2:
                vasr.transcribe_file(audio)
        self.assertEqual(ctx2.exception.kind, "http_401")

    def test_run_asr_cli_route_gate(self):
        """非音频路线/无音频 → exit 4; 不真调 mimo。"""
        row = vstudio.make_upsert({"route": "script", "title": "文案单"})
        vstudio.begin_job("asr", {"make_id": row["id"]})
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(vstudio.run_asr_cli(None), 4)
        self.assertEqual(json.loads(out.getvalue())["error"], "bad_make")

    def test_extract_audio_command_and_errors(self):
        """视频抽音轨: ffmpeg 解析(系统优先) + libmp3lame 命令行 + lame 缺失给安装指引。"""
        from types import SimpleNamespace
        src = self.tmp / "clip.mp4"
        src.write_bytes(b"fake-mp4")
        dest = self.tmp / "out.mp3"
        calls = {}
        def fake_run(argv, **kw):
            calls["argv"] = argv
            if "libmp3lame" in argv:
                dest.write_bytes(b"mp3" * 1000)     # 模拟成功产物
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        with (patch("shutil.which", return_value="C:/ffmpeg/ffmpeg.exe"),
              patch.object(vstudio.subprocess, "run", side_effect=fake_run)):
            self.assertEqual(vstudio._extract_audio(src, dest), "")
        argv = calls["argv"]
        self.assertEqual(argv[0], "C:/ffmpeg/ffmpeg.exe")
        for flag in ("-vn", "-c:a", "libmp3lame", "-q:a", "2"):
            self.assertIn(flag, argv)
        self.assertNotIn("-ar", argv)                    # 出片档保持原采样率
        self.assertIn(str(src), argv)
        # 压缩档(转写副本): 16k 单声道
        calls.clear()
        dest2 = self.tmp / "out16k.mp3"
        def fake_run2(argv, **kw):
            calls["argv"] = argv
            if "libmp3lame" in argv:
                dest2.write_bytes(b"mp3" * 1000)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        with (patch("shutil.which", return_value="C:/ffmpeg/ffmpeg.exe"),
              patch.object(vstudio.subprocess, "run", side_effect=fake_run2)):
            self.assertEqual(vstudio._extract_audio(src, dest2, voice_grade=False), "")
        for flag in ("-ar", "16000", "-ac", "1"):
            self.assertIn(flag, calls["argv"])
        # lame 缺失 → 指引文案(不透传裸 stderr)
        def lame_fail(argv, **kw):
            return SimpleNamespace(returncode=1, stdout="",
                                   stderr="Unknown encoder 'libmp3lame'")
        with (patch("shutil.which", return_value="C:/ffmpeg/ffmpeg.exe"),
              patch.object(vstudio.subprocess, "run", side_effect=lame_fail)):
            err = vstudio._extract_audio(src, self.tmp / "out2.mp3")
        self.assertIn("libmp3lame", err)
        self.assertIn("完整版 ffmpeg", err)
        # 无任何 ffmpeg → 指引(直接桩解析结果, 不 patch Path 方法)
        with patch.object(vstudio, "_resolve_ffmpeg", return_value=""):
            err2 = vstudio._extract_audio(src, self.tmp / "out3.mp3")
        self.assertIn("ffmpeg", err2)

    def test_estimate_phrases_silence_allocation(self):
        """长音频 whisper 幻觉降级: 语音区+字数比例分配, 句界落在语音区内且单调。"""
        from types import SimpleNamespace
        src = self.tmp / "long.mp3"
        src.write_bytes(b"f")
        fake_log = ("Duration: 00:01:00.00\n"
                    "silence_start: 9.0\nsilence_end: 11.0\n"
                    "silence_start: 19.0\nsilence_end: 21.5\n")
        # 语音区=[0,9],[11,19],[21.5,60] 共 55.5s; 三句各 10 字 → 每句 55.5/3=18.5s? 不: 按字数
        narration = "第一句十个字第一句十个字。第二句十个字第二句十个字！第三句十个字第三句十个字？"
        with (patch.object(vstudio, "_resolve_ffmpeg", return_value="ff"),
              patch.object(vstudio.subprocess, "run", return_value=SimpleNamespace(
                  returncode=0, stdout="", stderr=fake_log))):
            phrases, err = vstudio._estimate_phrases(src, narration)
        self.assertEqual(err, "")
        self.assertEqual(len(phrases), 3)
        self.assertAlmostEqual(phrases[0]["start"], 0.0, places=2)
        # 20 字/55.5s → 每句 ~18.5 平铺秒; 第一句末≈18.5 映射回真实: 跨过 [9,11] 静音 → 真实≈20.5
        self.assertGreater(phrases[0]["end"], 11.0)
        for a, b in zip(phrases, phrases[1:]):
            self.assertGreaterEqual(b["start"], a["start"])
            self.assertLessEqual(a["end"], 60.0 + 0.01)
        # 静音探测不可用 → 报错不产出
        with (patch.object(vstudio, "_resolve_ffmpeg", return_value="ff"),
              patch.object(vstudio.subprocess, "run", return_value=SimpleNamespace(
                  returncode=0, stdout="", stderr="Duration: 00:01:00.00\n"))):
            phrases2, err2 = vstudio._estimate_phrases(src, narration)
        self.assertEqual(phrases2, [])
        self.assertTrue(err2)

    def test_make_upsert_script_text_semantics(self):
        """参考稿(2026-09-17): 独立可写(不动状态机) + 换绑音频重置 + 截断保护。"""
        row = vstudio.make_upsert({"route": "audio", "title": "参考稿单"})
        row = vstudio.make_upsert({"id": row["id"], "audio": {"asset_id": "va1"}})
        # 独立写入(无 asset_id): 不触发换绑重置
        row["narration"]["text"] = "t" * 50
        vstudio._make_save(row)
        row = vstudio.make_upsert({"id": row["id"],
                                   "audio": {"script_text": "原稿内容。", "script_name": "稿.txt"}})
        self.assertEqual(row["audio"]["asset_id"], "va1")
        self.assertEqual(row["audio"]["script_text"], "原稿内容。")
        self.assertEqual(row["narration"]["text"], "t" * 50)
        # 超长截断(100k 上限) + 空稿清名字
        row = vstudio.make_upsert({"id": row["id"], "audio": {
            "script_text": "x" * 150000, "script_name": "n" * 500}})
        self.assertEqual(len(row["audio"]["script_text"]), 100000)
        self.assertEqual(len(row["audio"]["script_name"]), 200)
        row = vstudio.make_upsert({"id": row["id"], "audio": {"script_text": ""}})
        self.assertEqual(row["audio"]["script_text"], "")
        self.assertEqual(row["audio"]["script_name"], "")
        # 换绑音频: 旧稿作废(重置后 payload 不带 script_text 即不保留)
        row = vstudio.make_upsert({"id": row["id"], "audio": {"asset_id": "va2"}})
        self.assertEqual(row["audio"]["asset_id"], "va2")
        self.assertNotIn("script_text", row["audio"])
        # 换绑+新稿同 payload: 重置后写入新稿
        row = vstudio.make_upsert({"id": row["id"],
                                   "audio": {"asset_id": "va3", "script_text": "新稿。"}})
        self.assertEqual(row["audio"]["asset_id"], "va3")
        self.assertEqual(row["audio"]["script_text"], "新稿。")

    def test_plan_asr_segments(self):
        """mimo 分段转写段规划: ≤160s 单段 / 超限按静音中点切 / 无静音硬切锚点。"""
        from types import SimpleNamespace

        def fake_ff(log_text):
            def run(argv, **kw):
                return SimpleNamespace(returncode=0, stdout="", stderr=log_text)
            return run

        src = self.tmp / "a.mp3"
        src.write_bytes(b"x" * 100)
        # 短音频(120s, 无静音行) → 单段直传
        with (patch.object(vstudio, "_resolve_ffmpeg", return_value="ff"),
              patch.object(vstudio.subprocess, "run",
                           side_effect=fake_ff("Duration: 00:02:00.00\n"))):
            segs, err = vstudio._plan_asr_segments(src)
        self.assertEqual(err, "")
        self.assertEqual(segs, [(0.0, 120.0)])
        # 长音频(400s): 静音区 [118,122] 与 [238,242] → 段界取静音中点 120/240
        log = ("Duration: 00:06:40.00\nsilence_start: 118\nsilence_end: 122\n"
               "silence_start: 238\nsilence_end: 242\n")
        with (patch.object(vstudio, "_resolve_ffmpeg", return_value="ff"),
              patch.object(vstudio.subprocess, "run", side_effect=fake_ff(log))):
            segs, err = vstudio._plan_asr_segments(src)
        self.assertEqual(err, "")
        self.assertEqual([round(s, 1) for s, _ in segs], [0.0, 120.0, 240.0])
        self.assertEqual(round(segs[-1][1], 1), 400.0)
        # 无静音 → 硬切在锚点(120s 间隔, 300s 只需 2 刀)
        with (patch.object(vstudio, "_resolve_ffmpeg", return_value="ff"),
              patch.object(vstudio.subprocess, "run",
                           side_effect=fake_ff("Duration: 00:05:00.00\n"))):
            segs, err = vstudio._plan_asr_segments(src)
        self.assertEqual([round(s, 1) for s, _ in segs], [0.0, 120.0, 240.0])
        self.assertEqual(round(segs[-1][1], 1), 300.0)   # 尾段 240→300(60s ≤160)
        # 尾段静音无 silence_end → 补时长不崩
        with (patch.object(vstudio, "_resolve_ffmpeg", return_value="ff"),
              patch.object(vstudio.subprocess, "run",
                           side_effect=fake_ff("Duration: 00:04:00.00\nsilence_start: 300\n"))):
            segs, err = vstudio._plan_asr_segments(src)
        self.assertEqual(err, "")
        self.assertEqual(round(segs[-1][1], 1), 240.0)

    def test_extract_audio_range_args(self):
        """分段转写截取: -ss/-t 位于 -i 前(输入侧快进), 16k 单声道压缩档。"""
        from types import SimpleNamespace
        src = self.tmp / "s.mp3"
        src.write_bytes(b"x" * 100)
        dest = self.tmp / "seg0.mp3"
        calls = {}

        def fake_run(argv, **kw):
            calls["argv"] = argv
            dest.write_bytes(b"mp3" * 1000)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with (patch("shutil.which", return_value="C:/ff/ffmpeg.exe"),
              patch.object(vstudio.subprocess, "run", side_effect=fake_run)):
            self.assertEqual(
                vstudio._extract_audio(src, dest, voice_grade=False, start_s=12.5, duration_s=98.3), "")
        argv = calls["argv"]
        i_ss, i_in = argv.index("-ss"), argv.index("-i")
        self.assertLess(i_ss, i_in)                    # 输入侧快进
        self.assertEqual(argv[i_ss + 1], "12.500")
        self.assertEqual(argv[argv.index("-t") + 1], "98.300")
        for flag in ("-ar", "16000", "-ac", "1"):
            self.assertIn(flag, argv)


if __name__ == "__main__":
    unittest.main()
