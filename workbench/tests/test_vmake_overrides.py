"""逐拍素材覆盖离线回归，不读写运行时目录。"""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import vmake


class OverrideTests(unittest.TestCase):
    def script(self):
        return {"title": "素材测试", "format": "horizontal", "beats": [
            {"id": f"b{i}", "role": role, "narration": "旁白原文", "subtitle": "字幕",
             "on_screen": ["要点"], "visual_hint": "市场档案"}
            for i, role in enumerate(("hook", "setup", "cta"), 1)]}

    def test_three_methods_and_original_fields(self):
        for method, file in (("upload_image", "x.png"), ("upload_video", "x.mp4"), ("ai_image", "")):
            with self.subTest(method=method):
                script = self.script()
                baseline, _ = vmake.script_to_story(script, {})
                story, _ = vmake.script_to_story(script, {"beat_overrides": [
                    {"beat_id": "b2", "method": method, "file": file, "start": 0, "end": 5}]})
                scene = story["scenes"][1]
                self.assertEqual({k: scene[k] for k in ("narration", "caption", "id")},
                                 {k: baseline["scenes"][1][k] for k in ("narration", "caption", "id")})
                if method == "ai_image":
                    self.assertEqual(scene["template"], "paper-board")
                    self.assertEqual(scene["data"]["image"], "input/collage/b2.jpeg")
                    self.assertTrue(scene["data"]["image_prompt"])
                else:
                    self.assertEqual(scene["template"], "clip")
                    self.assertEqual(scene["data"]["src"], f"materials/{file}")
                    self.assertEqual(scene["data"]["kind"], "image" if method == "upload_image" else "video")
                    if method == "upload_video":
                        self.assertEqual((scene["data"]["start"], scene["data"]["end"]), (0, 5))
                        self.assertNotIn("kenburns", scene["data"])
                    else:
                        self.assertEqual(scene["data"]["kenburns"], "in")
                        self.assertNotIn("start", scene["data"])

    def test_missing_and_unsafe_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for file in ("missing.png", "../outside.png", r"C:\outside.png"):
                with self.assertRaisesRegex(ValueError, "素材缺失或路径非法"):
                    vmake.script_to_story(self.script(), {"materials_dir": tmp,
                        "beat_overrides": [{"beat_id": "b2", "method": "upload_image", "file": file}]})

    def test_legacy_style_pack(self):
        for pack, theme, layout in (("vox-collage", "vox-collage", "auto"),
                                    ("fast-cut", "terminal-dark", "fast-cut"),
                                    ("bad", "terminal-dark", "auto")):
            story, _ = vmake.script_to_story(self.script(), {"style_pack": pack})
            self.assertEqual((story["meta"]["theme"], story["meta"]["layout"]), (theme, layout))

    def test_non_horizontal_rejected(self):
        for aspect in ("9:16", "1:1", "4:5"):
            with self.assertRaisesRegex(ValueError, "不支持画幅"):
                vmake.script_to_story(self.script(), {"aspect": aspect,
                    "beat_overrides": [{"beat_id": "b2", "method": "ai_image"}]})

    def test_parent_override_and_unknown_rejected(self):
        script = self.script()
        script["beats"][1]["narration"] = "第一句长旁白完整保留。第二句长旁白继续保留。"
        story, _ = vmake.script_to_story(script, {"layout": "fast-cut", "beat_overrides": [
            {"beat_id": "b2", "method": "ai_image"}]})
        self.assertEqual(story["scenes"][1]["template"], "paper-board")
        self.assertEqual(story["scenes"][1]["narration"], script["beats"][1]["narration"])
        with self.assertRaisesRegex(ValueError, "不存在"):
            vmake.script_to_story(script, {"beat_overrides": [{"beat_id":"missing", "method":"ai_image"}]})


if __name__ == "__main__":
    unittest.main()
