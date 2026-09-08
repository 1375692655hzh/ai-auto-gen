"""四段式后端：存储统一 patch DATA_DIR，LLM/Node 全离线。"""
import copy
import hashlib
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import config, vstudio, vmake


class MakeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        p = patch.object(config, "DATA_DIR", self.tmp)
        p.start()
        self.addCleanup(p.stop)

    def make(self, locked=True):
        row = vstudio.make_upsert({"title": "测试", "narration": {
            "text": "市场公布最新消息引发交易变化。投资者开始重新评估风险因素。后续政策影响仍需持续关注。" * 2,
            "style_id": "event-fast"}})
        if locked:
            row, err = vstudio.lock_narration(row["id"])
            self.assertIsNone(err)
        return row

    def script_make(self):
        row = self.make()
        script = vstudio._storyboard_fallback(row["narration"]["text"], "测试", "horizontal")
        row = vstudio.make_upsert({"id": row["id"], "script": script})
        row, err = vstudio.lock_script(row["id"])
        self.assertIsNone(err)
        return row

    def test_hash_and_integrity(self):
        self.assertEqual(vstudio.narration_hash("旁白 一\n"), vstudio.narration_hash("旁白一"))
        self.assertEqual(vstudio.narration_hash("旁白一"), vstudio.narration_hash("旁白一"))
        self.assertNotEqual(vstudio.narration_hash("旁白二"), vstudio.narration_hash("旁白一"))
        manifest = {"b1": vstudio.voice_hash("旁白一")}
        self.assertEqual(manifest, {"b1": hashlib.sha1("旁白一".encode()).hexdigest()[:10]})
        self.assertNotEqual(vstudio.voice_hash("旁白一\n"), manifest["b1"])
        script = {"beats": [{"narration": "旁白 "}, {"narration": "一"}]}
        self.assertTrue(vstudio._storyboard_integrity(script, "旁白一"))
        self.assertFalse(vstudio._storyboard_integrity(script, "旁白一二"))
        self.assertFalse(vstudio._storyboard_integrity(script, "旁白"))

    def test_fallback_integrity_any_text(self):
        for text in ("", "字", "没有标点的完整口播稿" * 5, "第一句完整保留。第二句完整保留！第三句完整保留？", "空格\n 与标点，全部保留。"):
            script = vstudio._storyboard_fallback(text, "标题", "horizontal")
            self.assertTrue(vstudio._storyboard_integrity(script, text))
            self.assertEqual((script["beats"][0]["role"], script["beats"][-1]["role"]), ("hook", "cta"))
            self.assertTrue(script["warnings"])

    def test_storyboard_good_bad_json_and_retry(self):
        row = self.make()
        good = vstudio._storyboard_fallback(row["narration"]["text"], "LLM标题", "horizontal")
        good["warnings"] = []
        for replies, calls, fallback in ((["broken"], 1, True), ([json.dumps(good)], 1, False),
                                        ([json.dumps({"beats": [{"narration": "错"}]})] * 2, 2, True),
                                        ([json.dumps({"beats": [{"narration": "错"}]}), json.dumps(good)], 2, False)):
            with (patch.object(vstudio, "_translate_cfg", return_value=("x", "k", "m")),
                  patch.object(vstudio, "chat_completions", side_effect=replies) as chat):
                report, code = vstudio.run_storyboard({"make_id": row["id"]})
            self.assertEqual(code, 0, report)
            self.assertEqual(chat.call_count, calls)
            self.assertEqual(any("确定性拆句兜底" in w for w in report["warnings"]), fallback)
            self.assertTrue(vstudio._storyboard_integrity(report, row["narration"]["text"]))
            if not fallback:
                self.assertEqual(report["title"], "LLM标题")
        unlocked = self.make(False)
        self.assertEqual(vstudio.run_storyboard({"make_id": unlocked["id"]})[1], 4)

    def test_narration_flatten_and_lock_protection(self):
        row = self.make(False)
        result = {"schema": "wb-narration/v1", "paragraphs": [{"text": "第一段口播。"}, {"text": "第二段 口播。"}], "title": "口播"}
        with (patch.object(vstudio, "_translate_cfg", return_value=("x", "k", "m")),
              patch.object(vstudio, "chat_completions", return_value=json.dumps(result))):
            report, code = vstudio.run_narration({"make_id": row["id"], "style_id": "event-fast", "ref_text": "材料"})
        self.assertEqual(code, 0)
        self.assertEqual(report["text"], "第一段口播。\n\n第二段 口播。")
        self.assertEqual(report["word_count"], vstudio._word_count(report["text"]))
        saved = vstudio.make_get(row["id"])
        self.assertEqual(saved["narration"]["text"], report["text"])
        self.assertEqual(saved["narration"]["ref_text"], "材料")
        self.assertFalse(saved["narration"]["locked"])
        locked = self.make()
        self.assertEqual(vstudio.run_narration({"make_id": locked["id"], "style_id": "event-fast"})[1], 4)

    def test_tts_patch_and_public_mask(self):
        cfg = config.apply_patch({"tts": {"providers": [{"id": "dashscope", "api_key": "sk-old"}]}})
        cfg = config.apply_patch({"tts": {"providers": [
            {"id": "dashscope", "api_key": "", "enabled": True},
            {"id": "custom", "name": "新供应商", "api_key": "sk-new", "engine": "edge"}],
            "default": {"provider_id": "custom", "voice": "new-voice"}}})
        providers = {p["id"]: p for p in cfg["tts"]["providers"]}
        self.assertEqual(providers["dashscope"]["api_key"], "sk-old")
        self.assertTrue(providers["dashscope"]["enabled"])
        self.assertEqual(len(providers), 3)
        self.assertEqual(cfg["tts"]["default"], {"provider_id": "custom", "voice": "new-voice"})
        public = config.public_view(cfg)
        self.assertTrue(all(p["api_key"] == "" for p in public["tts"]["providers"]))
        self.assertEqual([p["has_key"] for p in public["tts"]["providers"]], [False, True, True])
        self.assertEqual(config.load()["tts"], cfg["tts"])
        self.assertTrue((self.tmp / "settings.json").is_file())
        with patch.object(vmake, "VIDEO_DIR", self.tmp):
            self.assertTrue(vmake.dashscope_key_ok())

        cfg = config.apply_patch({"tts": {"remove_ids": ["custom", "missing"],
                                          "providers": [{"id": "../bad"},
                                                        {"id": "dashscope", "enabled": False,
                                                         "voices": [{"id": "longanlufeng", "name": "陆锋"}]}]}})
        ids = [p["id"] for p in cfg["tts"]["providers"]]
        self.assertEqual(ids, ["edge", "dashscope"])
        self.assertNotIn("custom", ids)
        self.assertFalse(next(p["enabled"] for p in cfg["tts"]["providers"] if p["id"] == "dashscope"))
        self.assertEqual(cfg["tts"]["default"]["provider_id"], "edge")
        self.assertTrue(cfg["tts"]["default"]["voice"])
        self.assertTrue(all(set(p) <= {"id", "name", "engine", "enabled", "api_key", "base_url", "voices"}
                            for p in cfg["tts"]["providers"]))
        emptied = config.apply_patch({"tts": {"remove_ids": ids}})
        self.assertEqual(emptied["tts"]["providers"], [])
        self.assertEqual(emptied["tts"]["default"], {"provider_id": "", "voice": ""})

    def test_corrupt_makes_empty(self):
        for content in ("{broken", "{}", '["bad"]'):
            (self.tmp / "video_makes.json").write_text(content, encoding="utf-8")
            self.assertEqual(config.load_video_makes(), [])

    def test_staleness_and_duplicate_files(self):
        row = self.script_make()
        self.assertFalse(vstudio.make_view(row)["script_stale"])
        vstudio.unlock_narration(row["id"])
        vstudio.make_upsert({"id": row["id"], "narration": {"text": row["narration"]["text"] + "更新"}})
        changed, _ = vstudio.lock_narration(row["id"])
        self.assertTrue(vstudio.make_view(changed)["script_stale"])
        voice = self.tmp / "video_voice" / row["id"] / "edge-voice"
        voice.mkdir(parents=True)
        (voice / "b1.mp3").write_bytes(b"audio")
        changed["voice"].update(voice_key="edge-voice", items={"b1": {"file": "b1.mp3", "hash": "bad"}})
        vstudio._make_save(changed)
        self.assertEqual(vstudio.make_view(changed)["voice_bad"], ["b1"])
        duplicated = vstudio.make_duplicate(row["id"])
        self.assertNotEqual(duplicated["id"], row["id"])
        self.assertFalse(duplicated["script_meta"]["locked"])
        self.assertTrue((self.tmp / "video_voice" / duplicated["id"] / "edge-voice" / "b1.mp3").is_file())

    def mock_tts(self, scenes, out_dir, provider, voice, progress=False):
        out_dir.mkdir(parents=True, exist_ok=True)
        items = {}
        for s in scenes:
            (out_dir / f"{s['id']}.mp3").write_bytes(b"audio")
            items[s["id"]] = {"file": f"{s['id']}.mp3", "hash": vstudio.voice_hash(s["narration"]), "duration_s": 2}
        return items, None

    def test_voice_cli_all_single_and_failure(self):
        row = self.script_make()
        req = {"make_id": row["id"], "provider_id": "edge", "voice": "zh-CN-XiaoxiaoNeural", "scope": "all"}
        vstudio.begin_job("voice", req)
        with patch.object(vstudio, "_tts_node", side_effect=self.mock_tts), redirect_stdout(io.StringIO()):
            self.assertEqual(vstudio.run_voice_cli(None), 0)
        ready = vstudio.make_get(row["id"])
        self.assertEqual(ready["status"], "voice_ready")
        self.assertIsNotNone(vstudio.status_payload()["voice"]["result"])
        req["scope"] = "b1"
        with patch.object(vstudio, "_tts_node", side_effect=self.mock_tts):
            result, code = vstudio._run_voice(req)
        self.assertEqual(code, 0)
        self.assertEqual(result["items"], ready["voice"]["items"])
        with patch.object(vstudio, "_tts_node", return_value=(None, "failed")):
            self.assertEqual(vstudio._run_voice(req)[1], 3)
        self.assertEqual(vstudio._run_voice({**req, "voice": "invalid"})[1], 4)

    def test_node_job_environment_and_missing_result(self):
        scenes = [{"id": "b1", "narration": "旁白一"}]
        out = self.tmp / "video_voice" / "probe"
        provider = {"engine": "dashscope", "api_key": "secret", "base_url": "https://tts.invalid"}
        proc = MagicMock(stdout=io.StringIO("合成语音 b1\n完成\n"))
        def finish():
            (out / "_result.json").write_text(json.dumps({"items": {"b1": {"hash": "abc"}}}))
            return 0
        proc.wait.side_effect = finish
        with patch.object(vstudio.subprocess, "Popen", return_value=proc) as spawn:
            items, err = vstudio._tts_node(scenes, out, provider, "longanlufeng", True)
        self.assertIsNone(err)
        self.assertEqual(items["b1"]["hash"], "abc")
        job = json.loads((out / "_job.json").read_text())
        self.assertEqual(job["scenes"], scenes)
        self.assertTrue(Path(job["out_dir"]).is_absolute())
        self.assertEqual(spawn.call_args.kwargs["env"]["DASHSCOPE_API_KEY"], "secret")
        proc = MagicMock(stdout=io.StringIO(""))
        proc.wait.return_value = 0
        with patch.object(vstudio.subprocess, "Popen", return_value=proc):
            self.assertEqual(vstudio._tts_node(scenes, out, provider, "longanlufeng")[1], "tts_result_missing")

    def test_probe_disabled_provider_and_fresh_audio(self):
        config.apply_patch({"tts": {"providers": [{"id": "edge", "enabled": False}]}})
        out_dir = self.tmp / "video_voice" / "_probe" / "edge"
        out_dir.mkdir(parents=True)
        (out_dir / "probe.mp3").write_bytes(b"old voice")
        def probe(scenes, out_dir, provider, voice):
            self.assertFalse((out_dir / "probe.mp3").exists())
            return self.mock_tts(scenes, out_dir, provider, voice)
        with patch.object(vstudio, "_tts_node", side_effect=probe), redirect_stdout(io.StringIO()) as output:
            code = vstudio.run_test_tts_cli(SimpleNamespace(provider="edge", voice="zh-CN-XiaoxiaoNeural"))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["url"], "/wb-api/video-voice/_probe/edge/probe.mp3")
        with (patch.object(vmake, "dashscope_key_ok", return_value=False),
              patch.dict(vstudio.os.environ, {"DASHSCOPE_API_KEY": ""}), redirect_stdout(io.StringIO())):
            self.assertEqual(vstudio.run_test_tts_cli(SimpleNamespace(provider="dashscope", voice="longanlufeng")), 3)

    def test_invalid_voice_result_and_provider_switch(self):
        row = self.script_make()
        req = {"make_id": row["id"], "provider_id": "edge", "voice": "zh-CN-XiaoxiaoNeural"}
        with patch.object(vstudio, "_tts_node", side_effect=self.mock_tts):
            self.assertEqual(vstudio._run_voice(req)[1], 0)
        def bad_tts(scenes, out_dir, provider, voice, progress=False):
            items, err = self.mock_tts(scenes, out_dir, provider, voice, progress)
            items["b1"]["hash"] = "bad"
            return items, err
        with patch.object(vstudio, "_tts_node", side_effect=bad_tts):
            report, code = vstudio._run_voice({**req, "scope": "b1"})
        self.assertEqual(code, 0)
        self.assertNotIn("b1", report["items"])
        self.assertTrue(report["warnings"])
        self.assertEqual(vstudio.make_get(row["id"])["status"], "script_locked")
        changed = vstudio.make_upsert({"id": row["id"], "voice": {"voice": "zh-CN-YunxiNeural"}})
        self.assertEqual(changed["voice"]["items"], {})

    def test_presets_no_keys_and_default_replacement(self):
        config.apply_patch({"tts": {"providers": [{"id": "dashscope", "enabled": True, "api_key": "test-secret"}],
                                    "default": {"provider_id": "dashscope"}}})
        self.assertEqual(config.load()["tts"]["default"]["provider_id"], "dashscope")
        with patch.object(vstudio, "shutil_which", return_value=False):
            presets = vstudio.build_presets()
        self.assertEqual(len(presets["voices"]), 5)
        self.assertNotIn("test-secret", json.dumps(presets))
        self.assertTrue(all("engine" in v for v in presets["voices"]))

    def test_narration_cli_and_storyboard_dispatch(self):
        vstudio.begin_job("generate", {"task": "narration"})
        with patch.object(vstudio, "run_narration", return_value=({"error": "no_llm_config"}, 4)), redirect_stdout(io.StringIO()):
            self.assertEqual(vstudio.run_narration_cli(None), 4)
        self.assertFalse(vstudio.load_jobs()["generate"]["running"])
        vstudio.begin_job("generate", {"task": "storyboard", "make_id": "test"})
        with patch.object(vstudio, "run_storyboard", return_value=({}, 0)) as storyboard, redirect_stdout(io.StringIO()):
            self.assertEqual(vstudio.run_generate_cli(None), 0)
        storyboard.assert_called_once()

    def test_make_build_copies_materials_and_flat_manifest(self):
        row = self.script_make()
        req = {"make_id": row["id"], "provider_id": "edge", "voice": "zh-CN-XiaoxiaoNeural"}
        with patch.object(vstudio, "_tts_node", side_effect=self.mock_tts):
            self.assertEqual(vstudio._run_voice(req)[1], 0)
        asset, _ = vstudio.asset_add(row["id"], "b2", "image.png", b"image")
        vstudio.make_upsert({"id": row["id"], "video": {"beat_overrides": [
            {"beat_id": "b2", "method": "upload_image", "asset_id": asset["asset_id"]},
            {"beat_id": "b3", "method": "upload_image", "asset_id": "missing"}]}})
        for exit_code in (0, 3):
            pid = "offline" + str(exit_code)
            vstudio.begin_job("build", {"make_id": row["id"], "project_id": pid, "mode": "build"})
            with (patch.object(vmake, "VIDEOS_DIR", self.tmp / "projects"),
                  patch.object(vstudio, "_run_build_process", return_value=(exit_code, "")),
                  patch.object(vstudio, "_fill_collage_images"), redirect_stdout(io.StringIO())):
                self.assertEqual(vstudio.run_build_cli(None), exit_code)
            proj = self.tmp / "projects" / pid
            manifest = json.loads((proj / "audio" / "manifest.json").read_text())
            self.assertEqual(manifest, {b["id"]: vstudio.voice_hash(b["narration"]) for b in row["script"]["beats"]})
            story = json.loads((proj / "story.json").read_text(encoding="utf-8"))
            self.assertEqual(story["scenes"][1]["template"], "clip")
            self.assertTrue((proj / "input" / "materials" / (asset["asset_id"] + ".png")).is_file())
            self.assertIn("场景 b3 素材缺失，回退模板", vstudio.status_payload()["build"]["result"]["warnings"])
            saved = vstudio.make_get(row["id"])
            self.assertEqual(saved["status"], "built" if exit_code == 0 else "voice_ready")
            self.assertEqual(saved["last_build"]["project_id"], pid)


if __name__ == "__main__":
    unittest.main()
