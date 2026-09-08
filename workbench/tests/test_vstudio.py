"""视频制作向导离线回归：模型、任务写入和渲染均使用 mock。"""
import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, mock_open, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import vstudio, vmake, views


class GenerateTests(unittest.TestCase):
    def script(self):
        return {
            "schema": "wb-video-script/v1", "title": "离线脚本",
            "hook": {"variants": [{"type": t, "text": t} for t in ("提问", "数字", "反差")]},
            "beats": [{"id": f"b{i}", "role": role, "narration": "字" * 125,
                       "on_screen": ["要点"], "subtitle": "字幕", "visual_hint": "画面"}
                      for i, role in enumerate(("hook", "setup", "payoff", "cta"), 1)],
            "cta": {"action": "关注", "line": "关注后续"},
        }

    def test_generate_duration_and_prompt(self):
        # 500 字低于财经盘后参考区间，旧夹紧公式会错误抬高时长。
        with (patch.object(vstudio, "chat_completions", return_value=json.dumps(
                self.script(), ensure_ascii=False)) as chat,
                patch.object(vstudio, "_translate_cfg", return_value=("http://x", "k", "m")),
                patch.object(vstudio.config, "load", return_value={}),
                patch.object(vstudio, "tick"), patch.object(vstudio, "finish_job") as finish,
                patch.object(vstudio, "_set_job_result") as result):
            report, code = vstudio.run_generate(
                {"style_id": "recap-ask-conclude", "brief": "离线测试材料"})
        self.assertEqual(code, 0, report)
        self.assertEqual(result.call_args.args[0], "generate")
        script = result.call_args.args[1]
        self.assertEqual(script["word_count"], 500)
        self.assertEqual(script["duration_est_s"], 119)
        finish.assert_called_once_with("generate", 0, "")
        user = next(m["content"] for m in chat.call_args.args[3] if m["role"] == "user")
        self.assertNotIn("目标时长", user)
        self.assertIn("写作引导字数区间：700—900 字", user)

    def test_word_count_warning(self):
        warnings = vstudio.validate_script(self.script(), vstudio._STYLES["recap-ask-conclude"])
        self.assertEqual(warnings, [
            "口播 500 字，与该风格写作参考区间 700—900 有偏差（仅写作提示，不影响制作时长）"])
        self.assertEqual(vstudio.validate_script(self.script(), {"format": "horizontal", "wc": (500, 600)}), [])


class BuildPresetsTests(unittest.TestCase):
    def test_presets(self):
        with (patch.object(vmake, "dashscope_key_ok", return_value=False),
                patch.object(vstudio, "shutil_which", return_value=True),
                patch.object(vstudio.config, "load", return_value={}),
                patch.object(vstudio, "_translate_cfg", return_value=None)):
            presets = vstudio.build_presets()
        self.assertNotIn("packs", presets)
        self.assertEqual([t["id"] for t in presets["themes"]], list(vmake.THEMES))
        self.assertEqual([t["swatch"] for t in presets["themes"]], [
            ["#070B16", "#76B900", "#4D9FFF"], ["#F7F4EC", "#2B2A26", "#C7392B"],
            ["#06182E", "#6FD3FF", "#EAF4FF"], ["#E9DCC3", "#3E2F1D", "#B3352C"]])
        self.assertEqual(presets["themes"][-1]["aspect_limit"], "16:9")
        self.assertTrue(all("aspect_limit" not in t for t in presets["themes"][:-1]))
        self.assertEqual([a["dims"] for a in presets["aspects"]],
                         [list(d) for d in vmake.ASPECTS.values()])
        self.assertEqual([x["id"] for x in presets["fps_options"]], [30, 60])
        self.assertEqual([x["id"] for x in presets["layouts"]], list(vmake.LAYOUTS))
        self.assertEqual(presets["max_chars"], 20000)
        self.assertFalse(presets["dashscope_key_ok"])
        self.assertTrue(presets["collage_ready"])
        self.assertFalse(presets["llm_ready"])


class BuildTests(unittest.TestCase):
    def test_cli_timeout_selection(self):
        for fps, expected in ((30, 3600), (60, 7200), ("60", 7200), (120, 3600)):
            request = {"project_id": "offline", "script": {}, "settings": {"fps": fps}}
            videos = MagicMock()
            (videos / "offline" / "out").is_dir.return_value = False
            (videos / "offline" / "out" / "verify.json").is_file.return_value = False
            with (
                self.subTest(fps=fps),
                patch.object(vstudio, "load_jobs", return_value={"build": {"request": request}}),
                patch.object(vmake, "script_to_story", return_value=({"scenes": []}, [])),
                patch.object(vmake, "create_project"),
                patch.object(vmake, "VIDEOS_DIR", videos),
                patch.object(vstudio, "_fill_collage_images"),
                patch.object(vstudio, "BUILD_LOG_DIR", MagicMock()),
                patch.object(vstudio, "tick"), patch.object(vstudio, "_set_job_result"),
                patch.object(vstudio, "finish_job"),
                patch.object(vstudio, "_run_build_process", return_value=(0, "")) as run,
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(vstudio.run_build_cli(None), 0)
                self.assertEqual(run.call_args.args[3], expected)

    def test_watchdog_uses_timeout_and_message(self):
        for timeout in (3600, 7200):
            with (
                self.subTest(timeout=timeout),
                patch("builtins.open", mock_open()),
                patch.object(vstudio.subprocess, "Popen") as popen,
                patch.object(vstudio.subprocess, "run") as kill,
                patch.object(vstudio, "tick"),
                patch("threading.Timer") as timer,
            ):
                proc = popen.return_value.__enter__.return_value
                proc.stdout = []
                proc.wait.return_value = 0
                timer.side_effect = lambda seconds, callback: MagicMock(start=callback)
                code, hint = vstudio._run_build_process(["node"], "offline", Path("unused.log"), timeout)
                self.assertEqual(code, 3)
                self.assertIn(f"超过 {timeout // 60} 分钟已终止", hint)
                self.assertEqual(timer.call_args.args[0], timeout)
                kill.assert_called_once()

    def test_endpoint_settings(self):
        from fastapi.testclient import TestClient
        from server.app import create_app
        cases = [
            ({"aspect": "4:5", "format": "vertical", "fps": 60,
              "theme": "paper-light", "layout": "quote-big", "style_pack": "vox-collage"},
             ("4:5", 60, "paper-light", "quote-big")),
            ({"format": "vertical", "style_pack": "vox-collage"},
             ("9:16", 30, "vox-collage", "auto")),
            ({"aspect": [], "format": {}, "fps": 120, "theme": [], "layout": {}},
             ("16:9", 30, "terminal-dark", "auto")),
            ({"theme": "bad", "layout": "bad", "style_pack": "data-dense"},
             ("16:9", 30, "terminal-dark", "data-dense")),
        ]
        with TestClient(create_app()) as client:
            for body, expected in cases:
                with (
                    self.subTest(body=body),
                    patch.object(vstudio, "job_running", return_value=False),
                    patch.object(vstudio, "begin_job") as begin,
                    patch("subprocess.Popen") as spawn,
                ):
                    response = client.post("/wb-api/video-build", json={
                        "script": {"format": "vertical", "beats": [{"narration": "测试"}]}, **body})
                    self.assertEqual(response.status_code, 200, response.text)
                    settings = begin.call_args.args[1]["settings"]
                    self.assertEqual(set(settings), {
                        "aspect", "fps", "theme", "layout", "voice", "tts_provider", "enrich", "title"})
                    self.assertEqual(tuple(settings[k] for k in ("aspect", "fps", "theme", "layout")),
                                     expected)
                    spawn.assert_called_once()

    def test_verify_duration(self):
        root = MagicMock()
        project = root.iterdir.return_value = [MagicMock()]
        project = project[0]
        project.name = "offline"
        project.is_dir.return_value = True
        for value, expected in ((119, 119), (119.5, 119.5), ("119", None), (None, None), (True, None)):
            with (
                self.subTest(value=value),
                patch.object(views, "VIDEOS", root),
                patch.object(views, "_read_json", side_effect=[{}, {}, {"durationS": value}]),
            ):
                self.assertEqual(views.videos()[0]["verify_duration_s"], expected)


if __name__ == "__main__":
    unittest.main()
