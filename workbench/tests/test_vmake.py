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

    def test_fast_cut_splits_sentences(self):
        script = self.fast_cut_script()
        beats = script["beats"]
        narrations = [str(b.get("narration") or "") for b in beats]
        story, warnings = self.convert(script, layout="fast-cut")
        scenes = story["scenes"]
        self.assertGreater(len(scenes), len(beats))
        self.assertTrue(vmake._check_narration_integrity(beats, scenes, narrations))
        self.assertTrue(all(a["template"] != b["template"] for a, b in zip(scenes, scenes[1:])))
        self.assertEqual((scenes[0]["id"], scenes[0]["template"]), ("b1", "title"))
        self.assertEqual((scenes[-1]["id"], scenes[-1]["template"]), ("b6", "conclusion"))
        self.assertTrue(all(s["template"] in vmake.H_TEMPLATE_WHITELIST for s in scenes))
        self.assertEqual(story["meta"]["padSeconds"], 0.5)
        self.assertEqual(len(warnings), 4)
        self.assertTrue(all(s["caption"] == s["narration"] for s in scenes if "-s" in s["id"]))
        self.assertEqual(scenes[2]["data"]["bars"][0], {"name": "亿", "pct": 5800})
        self.assertEqual(beats[1]["on_screen"][0], "上涨35%")

    def test_fast_cut_short_fragment_merges(self):
        for text in ("市场震动。是的。赤字两万亿。利息支出同比增加百分之十五。",
                     "利息支出同比增加百分之十五。是的。赤字已经接近两万亿。",
                     " 市场震动！\n是的？赤字两万亿；利息支出同比增加百分之十五。 "):
            with self.subTest(text=text):
                script = self.fast_cut_script()
                script["beats"][2]["narration"] = text
                story, _ = self.convert(script, layout="fast-cut")
                micro = [s for s in story["scenes"] if s["id"].startswith("b3-s")]
                self.assertGreaterEqual(len(micro), 2)
                self.assertTrue(all(len("".join(s["narration"].split())) >= 8 for s in micro))
                self.assertEqual("".join(s["narration"] for s in micro), text)
                self.assertTrue(vmake._check_narration_integrity(script["beats"], story["scenes"]))

    def test_fast_cut_clause_fallback(self):
        for narration in (
            "推手是供给洪流，美国年度赤字接近两万亿美元，利息支出同比增加百分之十五。",
            " 供给，\n美国年度赤字接近两万亿美元、是的，利息支出同比增加百分之十五。 ",
        ):
            with self.subTest(narration=narration):
                script = self.script()
                script["beats"][2]["narration"] = narration
                self.assertEqual(len(vmake._split_sentences(narration)), 1)
                story, warnings = self.convert(script, layout="fast-cut")
                micro = [s for s in story["scenes"] if s["id"].startswith("b3-s")]
                self.assertGreaterEqual(len(micro), 2)
                self.assertTrue(vmake._check_narration_integrity(script["beats"], story["scenes"]))
                self.assertEqual("".join("".join(s["narration"].split()) for s in micro),
                                 "".join(narration.split()))
                self.assertEqual("".join(vmake._split_clauses(narration)), narration)
                self.assertTrue(all(len("".join(s["narration"].split())) >= 8 for s in micro))
                self.assertIn(f"快切：b3 按语逗拆为 {len(micro)} 个微场景", warnings)
        self.assertEqual(vmake._split_clauses("供给，美国年度赤字接近两万亿美元、是的，利息支出同比增加百分之十五。"),
                         ["供给，美国年度赤字接近两万亿美元、是的，", "利息支出同比增加百分之十五。"])

    def test_fast_cut_vertical_ignored(self):
        script = self.fast_cut_script("vertical")
        baseline, _ = self.convert(script)
        story, warnings = self.convert(script, layout="fast-cut")
        self.assertEqual(story, baseline)
        self.assertTrue(any("9:16 竖版不支持快切编排" in w for w in warnings))

    def test_fast_cut_single_sentence_beat_not_split(self):
        script = self.fast_cut_script()
        script["beats"][2]["narration"] = "利息支出同比增加百分之十五。"
        story, _ = self.convert(script, layout="fast-cut")
        scenes = [s for s in story["scenes"] if s["id"] == "b3" or s["id"].startswith("b3-s")]
        self.assertEqual(len(scenes), 1)
        self.assertEqual((scenes[0]["id"], scenes[0]["template"]), ("b3", "stacked"))

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
        self.assertEqual(story["scenes"][-1]["data"]["tagline"], [{"t": "关注后续解读"}])
        self.assertEqual(story["meta"]["padSeconds"], 0.3)
        self.assertTrue(any("快切路径暂用确定性版式" in w for w in warnings))

    def test_data_dense(self):
        story, warnings = self.convert(style_pack="data-dense")
        scenes = story["scenes"]
        self.assertEqual([s["template"] for s in scenes],
                         ["title", "event", "bars", "rows", "compare", "conclusion"])
        self.assertTrue(all(s["template"] in vmake.H_TEMPLATE_WHITELIST for s in scenes))
        bars = scenes[2]["data"]["bars"]
        self.assertTrue(bars)
        self.assertTrue(all("name" in b and "pct" in b for b in bars))
        self.assertEqual(bars, [{"name": "上涨%", "pct": 35}, {"name": "亿", "pct": 5800},
                                {"name": "趋势延续", "pct": 50}, {"name": "保持关注", "pct": 50}])
        self.assertEqual(scenes[4]["data"]["left"],
                         {"title": [{"t": "上涨35%"}], "items": [[{"t": "5800亿"}]]})
        self.assertIn("right", scenes[4]["data"])
        self.assertEqual(warnings, [])

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
            ({"format": "vertical", "style_pack": "vox-collage"},
             ("9:16", 30, "vox-collage", "auto")),
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
            with self.subTest(aspect=aspect), patch.object(
                    vmake, "_llm_compose_scenes", side_effect=AssertionError("不得外呼")):
                story, warnings = self.convert(
                    aspect=aspect, theme="vox-collage",
                    enrich="llm" if aspect == "16:9" else "plain")
                if aspect == "16:9":
                    self.assertTrue(all(s["template"] == "paper-board" for s in story["scenes"]))
                    self.assertTrue(all(s["data"]["image"] and s["data"]["image_prompt"]
                                        for s in story["scenes"]))
                    self.assertFalse(any("已忽略拼贴版式" in w for w in warnings))
                else:
                    self.assertTrue(any("已忽略拼贴版式" in w for w in warnings))
                    family = (vmake.V_TEMPLATE_WHITELIST if aspect == "9:16"
                              else vmake.H_TEMPLATE_WHITELIST)
                    self.assertTrue(all(s["template"] in family for s in story["scenes"]))

    def test_vox_overrides_fast_cut(self):
        story, _ = self.convert(self.fast_cut_script(), theme="vox-collage", layout="fast-cut")
        self.assertEqual(len(story["scenes"]), 6)
        self.assertTrue(all(s["template"] == "paper-board" for s in story["scenes"]))

    def test_other_horizontal_family_fast_cut(self):
        for aspect in ("1:1", "4:5"):
            story, _ = self.convert(self.fast_cut_script(), aspect=aspect, layout="fast-cut", fps=60)
            self.assertGreater(len(story["scenes"]), 6)
            self.assertEqual(story["meta"]["format"], aspect)
            self.assertEqual(story["meta"]["fps"], 60)

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
        self.assertEqual(story["scenes"][2]["data"]["bars"],
                         [{"name": "35", "pct": 35}, {"name": "增长%", "pct": 3.5}])
        data = story["scenes"][4]["data"]
        self.assertEqual(data["left"], {"title": [{"t": "观点A"}], "items": []})
        self.assertEqual(data["right"], {"title": [{"t": "观点B"}], "items": []})


if __name__ == "__main__":
    unittest.main()
