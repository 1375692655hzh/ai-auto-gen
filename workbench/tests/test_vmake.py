"""视频分镜确定性转换的离线回归测试。"""
from pathlib import Path
import sys
import unittest

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
        self.assertEqual(story, baseline)
        self.assertTrue(any("竖版不支持风格包" in w for w in warnings))
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
        for value in vmake.STYLE_PACKS:
            self.assertEqual(vmake.normalize_style_pack(value), value)

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
