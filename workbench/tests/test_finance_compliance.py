import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import config, finance_compliance as fc, views, vstudio


class FinanceTests(unittest.TestCase):
    def test_templates_and_windows(self):
        self.assertEqual(fc.disclaimer_for("法院判决"), fc.DISCLAIMERS["regulatory"])
        self.assertEqual(fc.disclaimer_for("新股申购"), fc.DISCLAIMERS["ipo"])
        self.assertEqual(fc.disclaimer_for("财报"), fc.DISCLAIMERS["industry"])
        for text, expected in [("申购截止", "过期勿发"), ("财报", "3 天"),
                               ("产业链", "1–2 周"), ("复盘", "长期")]:
            self.assertIn(expected, fc.publication_window(text))

    def test_actual_story_numbers_and_names(self):
        story = {"scenes": [{"id": "b1", "narration": "2026年9月9日，甲公司收入12.5亿元，增长35%，指数3万点，下调25个基点。"},
                            {"id": "b2", "narration": "NVDA增长百分之十五，收入一万一千七百亿美元。"}]}
        result = fc.review_markdown(story, Path("sample"), {"title": "测试", "style_id": "产业链"})
        for value in ["2026年9月9日", "12.5亿元", "35%", "3万点", "25个基点", "百分之十五", "一万一千七百亿美元", "NVDA"]:
            self.assertIn(value, result)
        self.assertIn("未经独立核实", result)
        self.assertIn("本期由确定性模板生成", result)

    def test_write_review_and_read_only_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "sample"
            (project / "out").mkdir(parents=True)
            (project / "story.json").write_text(json.dumps({"scenes": []}), encoding="utf-8")
            target = fc.write_review(project, {"disclaimer": "自定义声明"})
            self.assertIn("自定义声明", target.read_text(encoding="utf-8"))
            with patch.object(views, "VIDEOS", root):
                self.assertEqual(views.video_file("sample", "发布前核对.md"), target)
                self.assertIsNone(views.video_file("sample", "../settings.json"))
                self.assertTrue(views.videos()[0]["has_review"])

    def test_script_add_keeps_nested_and_top_level_disclaimer(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(config, "DATA_DIR", Path(tmp)):
            script = {"schema": "wb-video-script/v1", "disclaimer": "脚本声明"}
            row = vstudio.script_add({"script": script, "disclaimer": "外层声明"})
            self.assertEqual(row["script"]["disclaimer"], "脚本声明")
            self.assertEqual(row["disclaimer"], "外层声明")
            self.assertEqual(config.load_video_scripts()[0]["script"], script)


if __name__ == "__main__":
    unittest.main()
