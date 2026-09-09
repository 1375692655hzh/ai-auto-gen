"""视频分镜确定性转换的离线回归测试。"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import vmake


class StoryTests(unittest.TestCase):
    def script(self, fmt="horizontal"):
        return {"title": "测试", "format": fmt, "beats": [
            {"id": f"b{i + 1}", "role": role, "narration": f"旁白{i + 1}",
             "subtitle": "场景标题", "on_screen": ["上涨35%", "5800亿", "趋势延续", "保持关注"]}
            for i, role in enumerate(("hook", "setup", "move", "gives", "payoff", "cta"))]}

    def convert(self, script=None, **settings):
        return vmake.script_to_story(script or self.script(), {"enrich": "plain", **settings})

    def fast_cut_script(self, fmt="horizontal"):
        script = self.script(fmt)
        for beat in script["beats"][1:-1]:
            beat["narration"] = "供给洪流正在来袭。赤字已经接近两万亿。利息支出同比增加百分之十五。"
        return script

    def test_fast_cut_preserves_parent_beats(self):
        script = self.fast_cut_script()
        story, _ = self.convert(script, layout="fast-cut")
        self.assertEqual([s["id"] for s in story["scenes"]], [b["id"] for b in script["beats"]])
        self.assertEqual([s["narration"] for s in story["scenes"]], [b["narration"] for b in script["beats"]])
        self.assertTrue(all(s["template"] == "vox-fast-cut" for s in story["scenes"]))

    def test_fast_cut_whitespace_and_punctuation_retained(self):
        for text in ("市场震动。是的。赤字两万亿。利息支出同比增加百分之十五。", " 市场震动！\n是的？赤字两万亿； "):
            script = self.fast_cut_script()
            script["beats"][2]["narration"] = text
            story, _ = self.convert(script, layout="fast-cut")
            self.assertEqual(story["scenes"][2]["narration"], text)
            self.assertEqual(story["scenes"][2]["id"], "b3")

    def test_fast_cut_long_clause_retains_audio_identity(self):
        script = self.fast_cut_script()
        text = "供给，美国年度赤字接近两万亿美元、是的，利息支出同比增加百分之十五。"
        script["beats"][2]["narration"] = text
        story, _ = self.convert(script, layout="fast-cut")
        self.assertEqual(story["scenes"][2]["narration"], text)
        self.assertEqual(story["scenes"][2]["id"], "b3")

    def test_fast_cut_vertical_rejected(self):
        with self.assertRaisesRegex(ValueError, "仅支持 16:9"):
            self.convert(self.fast_cut_script("vertical"), layout="fast-cut")

    def test_fast_cut_single_sentence_beat_not_split(self):
        script = self.fast_cut_script()
        script["beats"][2]["narration"] = "利息支出同比增加百分之十五。"
        story, _ = self.convert(script, layout="fast-cut")
        scenes = [s for s in story["scenes"] if s["id"] == "b3" or s["id"].startswith("b3-s")]
        self.assertEqual(len(scenes), 1)
        self.assertEqual((scenes[0]["id"], scenes[0]["template"]), ("b3", "vox-fast-cut"))

    def test_fast_cut_hook_override_skips_llm(self):
        script = self.fast_cut_script()
        script["hook"] = {"variants": [{"text": "这是替换后的钩子。第二句话也不拆。"}]}
        script["cta"] = {"line": "关注后续解读"}
        with patch.object(vmake, "_llm_compose_scenes", side_effect=AssertionError("不得外呼")):
            story, warnings = vmake.script_to_story(
                script, {"layout": "fast-cut", "enrich": "llm", "pad_seconds": 0.3}, 0)
        narrations = [b["narration"] for b in script["beats"]]
        narrations[0] = script["hook"]["variants"][0]["text"]
        self.assertTrue(vmake._check_narration_integrity(script["beats"], story["scenes"], narrations))
        self.assertFalse(vmake._check_narration_integrity(script["beats"], story["scenes"]))
        self.assertEqual(story["scenes"][0]["id"], "b1")
        self.assertEqual(story["scenes"][-1]["narration"], script["beats"][-1]["narration"])
        self.assertEqual(story["meta"]["padSeconds"], 0.3)
        self.assertTrue(all(s["template"] == "vox-fast-cut" for s in story["scenes"]))

    def test_data_dense_preserves_absolute_labels(self):
        story, _ = self.convert(style_pack="data-dense")
        self.assertEqual(story["scenes"][2]["template"], "rows")
        self.assertIn("5800亿", str(story["scenes"][2]["data"]))
        data = vmake._data_for("bars", self.script()["beats"][2], "test", self.script(), "16:9")
        self.assertEqual(data["bars"], [{"name":"上涨35%", "pct":35, "tag":"上涨35%"}])
        self.assertNotIn(50, [b["pct"] for b in data["bars"]])

    def test_quote_big(self):
        story, _ = self.convert(style_pack="quote-big")
        self.assertEqual(story["scenes"][3]["template"], "versus")
        self.assertEqual(story["scenes"][4]["template"], "stacked")
        self.assertIn("bull", story["scenes"][3]["data"])
        self.assertIn("bear", story["scenes"][3]["data"])

    def test_default_unchanged(self):
        story, _ = self.convert()
        self.assertEqual([s["template"] for s in story["scenes"]],
                         ["title", "event", "stacked", "cards", "rows", "conclusion"])
        self.assertEqual([s["narration"] for s in story["scenes"]],
                         [b["narration"] for b in self.script()["beats"]])

    def test_vertical_ignores_pack(self):
        script = self.script("vertical")
        baseline, _ = self.convert(script)
        story, warnings = self.convert(script, style_pack="data-dense")
        self.assertEqual(story["scenes"], baseline["scenes"])
        self.assertEqual(story["meta"]["layout"], "data-dense")
        self.assertEqual(warnings, [])
        self.assertTrue(all(s["template"] in vmake.V_TEMPLATE_WHITELIST for s in story["scenes"]))

    def test_vertical_numeric_anchor(self):
        script = self.script("vertical")
        script["beats"][1]["on_screen"] = ["这是一段没有数字的长文本", "趋势延续"]
        story, warnings = self.convert(script)
        self.assertEqual(story["scenes"][1]["template"], "vpoints")
        self.assertIn("points", story["scenes"][1]["data"])
        self.assertIn("场景2无数字锚点已改用要点版式", warnings)
        self.assertEqual(story["scenes"][3]["template"], "vstat")

    def test_pack_normalization(self):
        for value in (None, "unknown", [], {}, 1):
            with self.subTest(value=value):
                self.assertEqual(vmake.normalize_style_pack(value), "auto")
        for value in vmake.LEGACY_PACK_MAP:
            self.assertEqual(vmake.normalize_style_pack(value), value)

    def test_aspect_fps_theme_matrix(self):
        for aspect, dims in vmake.ASPECTS.items():
            for fps in (30, 60):
                for theme in ("terminal-dark", "paper-light", "ocean-blue"):
                    with self.subTest(aspect=aspect, fps=fps, theme=theme):
                        story, _ = self.convert(aspect=aspect, fps=fps, theme=theme, layout="auto")
                        meta = story["meta"]
                        self.assertEqual(
                            tuple(meta[k] for k in ("format", "fps", "width", "height", "theme", "layout")),
                            (aspect, fps, *dims, theme, "auto"))
                        family = (vmake.V_TEMPLATE_WHITELIST if aspect == "9:16"
                                  else vmake.H_TEMPLATE_WHITELIST)
                        self.assertTrue(all(s["template"] in family for s in story["scenes"]))

    def test_legacy_and_precedence(self):
        cases = [
            ({"style_pack": "data-dense"}, ("16:9", 30, "terminal-dark", "data-dense")),
            ({}, ("16:9", 30, "terminal-dark", "auto")),
            ({"aspect": "3:2", "fps": 120}, ("16:9", 30, "terminal-dark", "auto")),
            ({"aspect": "1:1", "format": "vertical", "fps": "60"},
             ("1:1", 60, "terminal-dark", "auto")),
            ({"aspect": "3:2", "format": "vertical"}, ("9:16", 30, "terminal-dark", "auto")),
            ({"style_pack": "vox-collage", "theme": "paper-light", "layout": "quote-big"},
             ("16:9", 30, "paper-light", "quote-big")),
            ({"style_pack": "vox-collage", "theme": "bad", "layout": "bad"},
             ("16:9", 30, "terminal-dark", "auto")),
        ]
        for settings, expected in cases:
            with self.subTest(settings=settings):
                story, _ = self.convert(**settings)
                self.assertEqual(tuple(story["meta"][k] for k in ("format", "fps", "theme", "layout")),
                                 expected)
        story, _ = self.convert(self.script("vertical"), aspect="bad", format="bad")
        self.assertEqual(story["meta"]["format"], "9:16")

    def test_vox_theme(self):
        for aspect in vmake.ASPECTS:
            if aspect != "16:9":
                with self.assertRaisesRegex(ValueError, "仅支持 16:9"):
                    self.convert(aspect=aspect, theme="vox-collage")
            else:
                story, _ = self.convert(aspect=aspect, theme="vox-collage")
                self.assertTrue(all(s["template"] == "vox-fast-cut" for s in story["scenes"]))
                self.assertTrue(all(s["data"]["image_prompt"] for s in story["scenes"]))

    def test_vox_overrides_fast_cut(self):
        story, _ = self.convert(self.fast_cut_script(), theme="vox-collage", layout="fast-cut")
        self.assertEqual(len(story["scenes"]), 6)
        self.assertTrue(all(s["template"] == "vox-fast-cut" for s in story["scenes"]))

    def test_other_horizontal_family_fast_cut(self):
        for aspect in ("1:1", "4:5"):
            with self.assertRaisesRegex(ValueError, "仅支持 16:9"):
                self.convert(self.fast_cut_script(), aspect=aspect, layout="fast-cut", fps=60)

    def test_normalizers(self):
        for value in (None, [], {}, "bad", 120):
            self.assertEqual(vmake.normalize_aspect(value), "16:9")
            self.assertEqual(vmake.normalize_fps(value), 30)
            self.assertEqual(vmake.normalize_theme(value), "terminal-dark")
            self.assertEqual(vmake.normalize_layout(value), "auto")
        for value in (float("inf"), float("nan")):
            self.assertEqual(vmake.normalize_fps(value), 30)

    def test_empty_panels_and_number_only_bar(self):
        script = self.script()
        script["beats"][4]["on_screen"] = []
        script["beats"][2]["on_screen"] = ["35", "增长3.5%"]
        story, _ = self.convert(script, style_pack="data-dense")
        self.assertEqual(story["scenes"][2]["template"], "rows")
        self.assertIn("增长3.5%", str(story["scenes"][2]["data"]))
        data = story["scenes"][4]["data"]
        self.assertEqual(data["left"], {"title": [{"t": "观点A"}], "items": []})
        self.assertEqual(data["right"], {"title": [{"t": "观点B"}], "items": []})


if __name__ == "__main__":
    unittest.main()
