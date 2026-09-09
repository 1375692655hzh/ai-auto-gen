"""视频删除端点离线测试，仅真实删除 wbdelete-test 废弃项目。"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.app import create_app
from server import views


class VideoDeleteTests(unittest.TestCase):
    def setUp(self):
        self.videos = Path(__file__).resolve().parents[2] / "ai-workflow" / "video" / "videos"
        self.project = self.videos / "wbdelete-test"
        self.assertEqual(self.project.resolve().parent, self.videos.resolve())
        # 不接管任何已有目录；清理只针对本次测试创建的目录。
        self.project.mkdir()
        self.addCleanup(self.cleanup_project)
        (self.project / "out").mkdir()
        (self.project / "project.json").write_text(
            json.dumps({"id": "wbdelete-test", "title": "删除测试"}), encoding="utf-8")
        self.client = TestClient(create_app())
        self.addCleanup(self.client.close)

    def cleanup_project(self):
        self.assertEqual(self.project.resolve(), self.videos.resolve() / "wbdelete-test")
        if self.project.exists():
            shutil.rmtree(self.project)

    def test_delete_real_cli(self):
        # Execute the real CLI with this test interpreter, independent of Windows
        # launcher registration. The fixed production argv has its own test below.
        real_run = subprocess.run
        def portable_python(argv, **kwargs):
            self.assertEqual(argv[:2], ["py", "-3.11"])
            return real_run([sys.executable, *argv[2:]], **kwargs)
        with patch("subprocess.run", side_effect=portable_python):
            response = self.client.delete("/wb-api/videos/wbdelete-test")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"removed": 1})
        deadline = time.monotonic() + 10
        while self.project.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertFalse(self.project.exists())

    def test_invalid_id(self):
        with patch("subprocess.run") as run:
            response = self.client.delete("/wb-api/videos/a%20b")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "bad_vid"})
        run.assert_not_called()

    def test_missing_project(self):
        self.assertFalse((self.videos / "wb-no-such-project-xyz").exists())
        response = self.client.delete("/wb-api/videos/wb-no-such-project-xyz")
        self.assertIn(response.status_code, (400, 404))

    def test_subprocess_errors_and_contract(self):
        for error, code in ((subprocess.TimeoutExpired("test", 60), 504), (OSError("test"), 500)):
            with self.subTest(code=code), patch("subprocess.run", side_effect=error):
                self.assertEqual(self.client.delete("/wb-api/videos/wbdelete-test").status_code, code)
        for stderr, stdout in (("e" * 250, "ignored"), ("", "o" * 250)):
            with patch("subprocess.run", return_value=SimpleNamespace(
                    returncode=3, stderr=stderr, stdout=stdout)) as run:
                response = self.client.delete("/wb-api/videos/wbdelete-test")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"error": "remove_failed", "hint": (stderr or stdout)[-200:]})
            run.assert_called_once_with(
                ["py", "-3.11", str(self.videos.parents[2] / "cli.py"), "video", "remove", "wbdelete-test"],
                capture_output=True, text=True, encoding="utf-8", timeout=60)

    def test_verify_summary(self):
        verify = self.project / "out" / "verify.json"
        original_is_file = Path.is_file
        original_read_text = Path.read_text
        cases = [(None, None, [], []), ("broken", None, [], []),
                 ("[]", None, [], []), ('{"mode": 3, "warnings": "bad", "errors": null}', None, [], []),
                 (json.dumps({"mode": "strict", "warnings": ["提示", 2], "errors": ["错误"]}),
                  "strict", ["提示", "2"], ["错误"])]
        for content, mode, warnings, errors in cases:
            with self.subTest(content=content):
                def is_file(path):
                    return content is not None if path == verify else original_is_file(path)

                def read_text(path, *args, **kwargs):
                    return content if path == verify else original_read_text(path, *args, **kwargs)

                with patch.object(Path, "is_file", is_file), patch.object(Path, "read_text", read_text):
                    project = next(p for p in views.videos() if p["id"] == "wbdelete-test")
                    self.assertIsNone(views.video_file("wbdelete-test", "verify.json"))
                self.assertEqual(project["title"], "删除测试")
                self.assertEqual(project["verify_mode"], mode)
                self.assertEqual(project["verify_warnings"], warnings)
                self.assertEqual(project["verify_errors"], errors)


if __name__ == "__main__":
    unittest.main()
