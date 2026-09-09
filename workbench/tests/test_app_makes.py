"""制作端点离线契约：临时 DATA_DIR，所有外部进程均 mock。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import config, vstudio
from server.app import create_app


class AppMakesTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        for p in (patch.object(config, "DATA_DIR", self.tmp), patch("subprocess.Popen")):
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(create_app())
        self.addCleanup(self.client.close)

    def create(self):
        response = self.client.post("/wb-api/video-makes", json={"title": "测试"})
        self.assertEqual(response.status_code, 200)
        return response.json()["make"]

    def lock(self, row):
        text = "最新消息推动交易变化。投资者关注接下来的政策动向。后续走势仍需继续观察。" * 3
        self.client.post("/wb-api/video-makes", json={"id": row["id"], "narration": {"text": text}})
        base = "/wb-api/video-makes/" + row["id"]
        self.assertEqual(self.client.post(base + "/lock-narration").status_code, 200)
        script = vstudio._storyboard_fallback(text, "测试", "horizontal")
        self.client.post("/wb-api/video-makes", json={"id": row["id"], "script": script})
        response = self.client.post(base + "/lock-script")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["make"]

    def test_crud_and_lock_gates(self):
        row = self.create()
        base = "/wb-api/video-makes/" + row["id"]
        short = self.client.post(base + "/lock-narration")
        self.assertEqual(short.status_code, 400)
        self.assertEqual(short.json()["error"], "too_short")
        locked = self.lock(row)
        self.assertEqual(locked["status"], "script_locked")
        self.assertEqual(self.client.get(base).json()["make"]["script_badge"], "locked")
        self.assertEqual(len(self.client.get("/wb-api/video-makes").json()["makes"]), 1)
        self.client.post(base + "/unlock-script")
        self.client.post("/wb-api/video-makes", json={"id": row["id"], "script": {"beats": [{"narration": "错"}]}})
        bad = self.client.post(base + "/lock-script")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.json()["error"], "integrity")
        self.assertEqual(self.client.post(base + "/unlock-narration").status_code, 200)
        self.assertEqual(self.client.delete(base).json(), {"removed": 1})
        self.assertEqual(self.client.get(base).status_code, 404)

    def test_upload_download_delete_and_limits(self):
        row = self.create()
        params = {"make_id": row["id"], "beat_id": "b1"}
        for ext in ("svg", "mov", "txt"):
            self.assertEqual(self.client.put("/wb-api/video-assets", params={**params, "name": "x." + ext}, content=b"x").status_code, 400)
        response = self.client.put("/wb-api/video-assets", params={**params, "name": "x.png"}, content=b"png")
        self.assertEqual(response.status_code, 200, response.text)
        asset = response.json()["asset"]
        path = self.tmp / "video_assets" / (asset["asset_id"] + ".png")
        self.assertEqual(path.read_bytes(), b"png")
        file_url = "/wb-api/video-assets/" + asset["asset_id"]
        self.assertEqual(self.client.get(file_url + "/file", params=params).content, b"png")
        self.assertTrue(self.client.get("/wb-api/video-assets", params=params).json()["assets"][0]["exists"])
        for ext, limit in (("png", 15), ("mp4", 100), ("mp3", 30)):
            response = self.client.put("/wb-api/video-assets", params={**params, "name": "x." + ext},
                                       content=b"x", headers={"Content-Length": str(limit * 1024 * 1024 + 1)})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["error"], "too_large")
        for ext in ("wav", "m4a"):
            self.assertEqual(self.client.put("/wb-api/video-assets", params={"name": "x." + ext}, content=b"audio").status_code, 200)
        vstudio.make_upsert({"id": row["id"], "video": {"beat_overrides": [
            {"beat_id": "b1", "asset_id": asset["asset_id"], "method": "upload_image", "prompt": "保留"}]}})
        response = self.client.delete(file_url, params=params)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], "asset_in_use")
        self.assertEqual(response.json()["refs"][0]["make_id"], row["id"])
        self.assertEqual(self.client.delete(file_url, params={"force": "1"}).json(), {"removed": 1, "cleared_overrides": 1})
        self.assertFalse(path.exists())
        self.assertEqual(vstudio.make_get(row["id"])["video"]["beat_overrides"], [
            {"beat_id": "b1", "method": "upload_image", "prompt": "保留"}])

    def test_voice_file_and_path_guard(self):
        url = "/wb-api/video-voice/vmtest/edge-voice/b1.mp3"
        self.assertEqual(self.client.get(url).status_code, 404)
        path = self.tmp / "video_voice" / "vmtest" / "edge-voice" / "b1.mp3"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"audio")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "audio/mpeg")
        self.assertEqual(response.content, b"audio")
        self.assertEqual(self.client.get(url.replace("b1.mp3", "a%20b.mp3")).status_code, 404)

    def test_build_error_branches_and_estimate(self):
        url = "/wb-api/video-build"
        response = self.client.post(url, json={"make_id": "missing"})
        self.assertEqual((response.status_code, response.json()["error"]), (400, "make_not_found"))
        row = self.create()
        response = self.client.post(url, json={"make_id": row["id"]})
        self.assertEqual((response.status_code, response.json()["error"]), (400, "script_not_locked"))
        self.lock(row)
        response = self.client.post(url, json={"make_id": row["id"]})
        self.assertEqual((response.status_code, response.json()["error"]), (400, "voice_missing"))
        self.assertIn("b1", response.json()["hint"])
        response = self.client.post(url, json={"make_id": row["id"], "mode": "estimate"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(vstudio.load_jobs()["build"]["request"]["make_id"], row["id"])

    def test_job_busy_and_routes(self):
        row = self.lock(self.create())
        for route, kind, command in (("narration", "generate", "gen-narration"),
                                     ("storyboard", "generate", "gen-script"),
                                     ("voice", "voice", "gen-voice")):
            body = {"make_id": row["id"], "style_id": "event-fast", "brief": "测试",
                    "provider_id": "edge", "voice": "zh-CN-XiaoxiaoNeural"}
            vstudio.begin_job(kind, {})
            self.assertEqual(self.client.post(f"/wb-api/video-{route}/generate", json=body).status_code, 409)
            vstudio.finish_job(kind, 0, "")
            with patch("subprocess.Popen") as spawn:
                response = self.client.post(f"/wb-api/video-{route}/generate", json=body)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn(command, spawn.call_args.args[0])
            vstudio.finish_job(kind, 0, "")

    def test_duplicate_and_delete_dirs(self):
        row = self.create()
        original = self.tmp / "video_voice" / row["id"]
        original.mkdir(parents=True)
        response = self.client.post(f"/wb-api/video-makes/{row['id']}/duplicate")
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json()["make"]["id"], row["id"])
        self.client.delete(f"/wb-api/video-makes/{row['id']}")
        self.assertFalse(original.exists())

    def test_test_tts_contract(self):
        for code, expected in ((0, 200), (4, 400), (3, 502)):
            out = {"ok": code == 0, "url": "/audio", "error": "failed"}
            with patch("subprocess.run", return_value=SimpleNamespace(returncode=code, stdout="progress\n" + json.dumps(out))) as run:
                response = self.client.post("/wb-api/test-tts", json={"provider_id": "edge", "voice": "voice"})
            self.assertEqual(response.status_code, expected)
            self.assertEqual(run.call_args.kwargs["timeout"], 120)
        for error, expected in ((subprocess.TimeoutExpired("tts", 120), 504), (OSError(), 500)):
            with patch("subprocess.run", side_effect=error):
                self.assertEqual(self.client.post("/wb-api/test-tts", json={}).status_code, expected)


if __name__ == "__main__":
    unittest.main()
