"""全局素材库与模板偏好离线契约，文件写入临时目录。"""
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import config, vmake, vstudio
from server.app import create_app


class VideoLibraryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        for p in (patch.object(config, "DATA_DIR", self.tmp),
                  patch.object(vstudio, "_MIGRATED", False)):
            p.start()
            self.addCleanup(p.stop)

    def client(self):
        client = TestClient(create_app())
        self.addCleanup(client.close)
        return client

    def add(self, name="image.png", duration_s=None):
        asset, error = vstudio.asset_add(name, b"media", duration_s)
        self.assertIsNone(error)
        return asset

    def test_global_crud_and_kinds(self):
        for ext, kind in vstudio.ASSET_KIND.items():
            with self.subTest(ext=ext):
                asset = self.add("media." + ext, 1.5)
                self.assertEqual(asset["kind"], kind)
                self.assertEqual(asset["size"], 5)
                self.assertEqual(asset["duration_s"], 1.5)
                self.assertTrue({"asset_id", "name", "ext", "kind", "size", "duration_s",
                                 "created_at", "updated_at"} <= asset.keys())
                path = self.tmp / "video_assets" / f"{asset['asset_id']}.{ext}"
                self.assertEqual(path.read_bytes(), b"media")
                self.assertEqual(vstudio.asset_find(asset["asset_id"]), (path, kind))
        self.assertEqual(len(config.load_video_assets()), len(vstudio.ASSET_KIND))
        self.assertTrue(all(a["exists"] and a["refs"] == [] for a in vstudio.assets_list()))
        self.assertIsNone(self.add()["duration_s"])
        self.assertEqual(vstudio.asset_add("x.svg", b"x"), (None, {"error": "bad_ext"}))
        self.assertEqual(vstudio.asset_find("../bad"), (None, None))
        path.unlink()
        self.assertFalse(next(a for a in vstudio.assets_list() if a["asset_id"] == asset["asset_id"])["exists"])

    def test_capacity_and_corrupt_store(self):
        store = self.tmp / "video_assets.json"
        for raw in ("broken", "{}", '[1, {}]'):
            store.write_text(raw, encoding="utf-8")
            self.assertEqual(config.load_video_assets(), [])
        with patch.object(vstudio, "MAX_ASSETS", 1):
            asset = self.add()
            self.assertEqual(vstudio.asset_add("x.mp3", b"audio")[1]["error"], "capacity_limit")
            self.assertEqual(config.load_video_assets(), [asset])
            response = self.client().put("/wb-api/video-assets", params={"name": "x.png"}, content=b"x")
            self.assertEqual((response.status_code, response.json()["error"]), (400, "capacity_limit"))

    def test_references_force_and_make_lifecycle(self):
        asset = self.add()
        aid = asset["asset_id"]
        override = {"beat_id": "b1", "asset_id": aid, "method": "upload_image", "prompt": "保留",
                    "kenburns": "in", "credit": "作者", "start": 1, "end": 2}
        first = vstudio.make_upsert({"title": "原作", "video": {"beat_overrides": [override]}})
        second = vstudio.make_duplicate(first["id"])
        self.assertEqual(second["video"]["beat_overrides"], [override])
        self.assertFalse((vstudio.assets_root() / second["id"]).exists())
        self.assertEqual({r["make_id"] for r in vstudio.asset_refs(aid)}, {first["id"], second["id"]})
        self.assertFalse(vstudio.asset_del(aid)["ok"])
        self.assertEqual(len(vstudio.assets_list()[0]["refs"]), 2)
        client = self.client()
        response = client.delete(f"/wb-api/video-assets/{aid}")
        self.assertEqual(response.status_code, 409)
        self.assertIn("被 2 个制作引用", response.json()["hint"])
        with patch.object(config, "save_video_makes", wraps=config.save_video_makes) as save:
            self.assertEqual(vstudio.asset_del(aid, force=True), {"ok": True, "cleared_overrides": 2, "refs": []})
            save.assert_called_once()
        expected = {k: v for k, v in override.items() if k != "asset_id"}
        for row in config.load_video_makes():
            self.assertEqual(row["video"]["beat_overrides"], [expected])
        self.assertEqual(vstudio.asset_find(aid), (None, None))
        self.assertEqual(config.load_video_assets(), [])
        self.assertEqual(vstudio.asset_del(aid), {"ok": True, "cleared_overrides": 0, "refs": []})
        other = self.add()
        legacy = vstudio.assets_root() / first["id"]
        legacy.mkdir()
        (legacy / "old.png").write_bytes(b"old")
        vstudio.make_del(first["id"])
        self.assertTrue(legacy.exists())
        self.assertIsNotNone(vstudio.asset_find(other["asset_id"])[0])

    def test_rename_and_audio_endpoints(self):
        client = self.client()
        for ext, mime in (("mp3", "audio/mpeg"), ("wav", "audio/wav"), ("m4a", "audio/mp4")):
            response = client.put("/wb-api/video-assets", params={"name": "song." + ext,
                                  "make_id": "missing", "beat_id": "b1", "duration_s": "2.5"}, content=b"audio")
            self.assertEqual(response.status_code, 200)
            asset = response.json()["asset"]
            self.assertEqual(asset["duration_s"], 2.5)
            url = f"/wb-api/video-assets/{asset['asset_id']}"
            response = client.get(url + "/file")
            self.assertEqual(response.headers["content-type"], mime)
            self.assertEqual(response.content, b"audio")
        path, _ = vstudio.asset_find(asset["asset_id"])
        before = path.stat().st_mtime_ns
        response = client.post(url + "/rename", json={"name": " " + "名" * 100 + " "})
        self.assertEqual(response.json()["asset"]["name"], "名" * 80)
        self.assertEqual(path.stat().st_mtime_ns, before)
        self.assertEqual(path.read_bytes(), b"audio")
        for name in ("", "  ", None, 12):
            self.assertEqual(client.post(url + "/rename", json={"name": name}).status_code, 400)
        self.assertEqual(client.post("/wb-api/video-assets/missing/rename", json={"name": "新"}).status_code, 404)
        for duration in ("bad", "NaN", "inf"):
            response = client.put("/wb-api/video-assets", params={"name": "x.png", "duration_s": duration}, content=b"x")
            self.assertIsNone(response.json()["asset"]["duration_s"])

    def test_legacy_migration_and_idempotence(self):
        row = vstudio.make_upsert({"title": "旧制作"})
        folder = vstudio.assets_root() / row["id"]
        folder.mkdir(parents=True)
        path = folder / "vaold.png"
        path.write_bytes(b"old")
        stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        row["assets"] = [{"asset_id": "vaold", "name": "旧名"}]
        config.save_video_makes([row])
        self.assertEqual(vstudio.asset_find("vaold"), (path, "image"))
        self.assertEqual(vstudio.migrate_legacy_assets(), 1)
        self.assertEqual((vstudio.assets_root() / "vaold.png").read_bytes(), b"old")
        asset = config.load_video_assets()[0]
        self.assertEqual((asset["name"], asset["created_at"], asset["duration_s"]), ("vaold.png", stamp, None))
        self.assertEqual(vstudio.make_get(row["id"])["assets"], [])
        self.assertFalse(folder.exists())
        self.assertEqual(vstudio.migrate_legacy_assets(), 0)
        with patch.object(vstudio, "_MIGRATED", False):
            self.assertEqual(vstudio.migrate_legacy_assets(), 0)

    def test_migration_collision_and_file_error(self):
        folder = vstudio.assets_root() / "vmold"
        folder.mkdir(parents=True)
        (folder / "vaone.png").write_bytes(b"old")
        (vstudio.assets_root() / "vaone.png").write_bytes(b"new")
        (folder / "vatwo.mp3").write_bytes(b"audio")
        with patch.object(vstudio.shutil, "move", side_effect=OSError("failed")):
            self.assertEqual(vstudio.migrate_legacy_assets(), 0)
        self.assertEqual((vstudio.assets_root() / "vaone.png").read_bytes(), b"new")
        self.assertTrue((folder / "vatwo.mp3").exists())

    def test_new_make_defaults(self):
        for vs, expected in (({"default_theme": "paper-light", "default_layout": "quote-big",
                              "default_generation_method": "template"}, ("paper-light", "quote-big", "template")),
                             ({"default_theme": [], "default_layout": "wrong", "default_generation_method": {}},
                              ("terminal-dark", "auto", "inherit")), ({}, ("terminal-dark", "auto", "inherit"))):
            with patch.object(config, "load", return_value={"video_studio": vs}):
                row = vstudio.make_upsert({})
            self.assertEqual(tuple(row["video"][k] for k in ("theme", "layout", "generation_method")), expected)

    def test_catalog_and_engine_templates(self):
        with patch.object(vstudio, "_translate_cfg", side_effect=AssertionError("不应探测外呼配置")):
            catalog = self.client().get("/wb-api/video-templates").json()
        cards = catalog["cards"]
        methods = {m["id"] for m in vmake.GENERATION_METHODS} - {"inherit", "upload_image", "upload_video", "ai_image"}
        for kind, ids in (("theme", set(vmake.THEMES)), ("layout", set(vmake.LAYOUTS)), ("method", methods)):
            self.assertEqual({c["id"] for c in cards if c["kind"] == kind}, ids)
        for card in cards:
            self.assertTrue(all(card[k] for k in ("key", "kind", "id", "name", "blurb", "aspects", "cost", "source")))
            self.assertEqual(card["key"], f"{card['kind']}:{card['id']}")
            if card["kind"] != "method":
                self.assertEqual(card["cost"], "跟随生成方式")
            self.assertEqual("swatch" in card, card["kind"] == "theme")
        self.assertEqual(catalog["defaults"]["favorites"], [])
        presets = vstudio.build_presets()
        self.assertTrue(all(x["desc"] for k in ("themes", "layouts", "generation_methods") for x in presets[k]))
        self.assertIn("title", presets["engine_templates"]["ids"])
        self.assertIn("vtitle", presets["engine_templates"]["vertical_ids"])
        for kwargs in ({"side_effect": OSError()}, {"return_value": "broken"}):
            with patch.object(Path, "read_text", **kwargs):
                self.assertEqual(vstudio._engine_templates(), {"ids": [], "vertical_ids": []})

    def test_style_validation_and_atomic_patch(self):
        client = self.client()
        for payload in ({"default_theme": "wrong"}, {"default_layout": []},
                        {"default_generation_method": "wrong"}, {"favorite": None},
                        {"favorite": {"key": "theme:ocean-blue", "on": "true"}},
                        *({"favorite": {"key": "method:" + x, "on": True}}
                          for x in ("inherit", "upload_image", "upload_video", "ai_image"))):
            with patch.object(config, "apply_patch") as save:
                response = client.post("/wb-api/video-style", json=payload)
                self.assertEqual(response.status_code, 400, payload)
                self.assertTrue(response.json()["error"].startswith("bad_"))
                save.assert_not_called()
        config.apply_patch({"video_studio": {"custom": "保留", "favorites": ["theme:ocean-blue"]}})
        payload = {"default_theme": "paper-light", "default_layout": "quote-big",
                   "default_generation_method": "template", "favorite": {"key": "method:template", "on": True}}
        for _ in range(2):
            response = client.post("/wb-api/video-style", json=payload)
            self.assertEqual(response.status_code, 200)
        saved = response.json()["video_studio"]
        self.assertEqual(saved["custom"], "保留")
        self.assertEqual(saved["favorites"], ["theme:ocean-blue", "method:template"])
        self.assertEqual(config.load()["video_studio"], saved)
        self.assertEqual(client.get("/wb-api/video-templates").json()["defaults"]["default_theme"], "paper-light")
        response = client.post("/wb-api/video-style", json={"favorite": {"key": "method:template", "on": False}})
        self.assertEqual(response.json()["video_studio"]["favorites"], ["theme:ocean-blue"])


if __name__ == "__main__":
    unittest.main()
