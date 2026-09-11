"""种子升级合并: 存量用户吃得到开发者新增清单, 本地状态/删除不被破坏。全离线。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workbench.server import config


def _row(cid, value=None, enabled=True):
    return {"id": "y" + cid[-6:], "input": cid, "kind": "channel_id", "value": value or cid,
            "channel_id": cid, "title": "频道" + cid[-4:], "enabled": enabled,
            "resolve_status": "resolved", "subs": None, "uploads_pid": "",
            "added_at": "2026-09-11 00:00:00"}


class SeedMergeTests(unittest.TestCase):
    def setUp(self):
        _t = tempfile.TemporaryDirectory()
        self.addCleanup(_t.cleanup)
        self.tmp = Path(_t.name)
        self.seed = self.tmp / "seed"
        self.seed.mkdir()
        # seed_if_missing / seed_merge 读模块级 DATA_DIR/SEED_DIR, 全部 patch 到临时目录
        for p in (patch.object(config, "DATA_DIR", self.tmp / "data"),
                  patch.object(config, "SEED_DIR", self.seed)):
            p.start(); self.addCleanup(p.stop)
        (self.tmp / "data").mkdir()

    def _write_seed(self, rows):
        (self.seed / "yt_channels.json").write_text(
            json.dumps(rows, ensure_ascii=False), encoding="utf-8")

    def _local(self):
        return json.loads((config.DATA_DIR / "yt_channels.json").read_text(encoding="utf-8"))

    def test_first_run_copies_seed(self):
        self._write_seed([_row("UC1"), _row("UC2")])
        self.assertTrue(config.seed_if_missing("yt_channels.json"))
        self.assertEqual(len(self._local()), 2)

    def test_merge_adds_only_missing_for_existing_user(self):
        # 分布式老用户: 本地 23 个(含自有启停状态), 种子升级带 2 个新频道
        old = [_row(f"UC{i}", enabled=(i % 2 == 0)) for i in range(1, 24)]
        (config.DATA_DIR / "yt_channels.json").write_text(
            json.dumps(old, ensure_ascii=False), encoding="utf-8")
        self._write_seed(old[:21] + [_row("UCnew1"), _row("UCnew2")])
        rep = config.seed_merge_if_updated("yt_channels.json")
        self.assertEqual(rep["added"], 2)
        rows = self._local()
        self.assertEqual(len(rows), 25)
        # 原有行原样未动(启停状态保留)
        self.assertEqual(next(r for r in rows if r["channel_id"] == "UC2")["enabled"], True)
        self.assertEqual(next(r for r in rows if r["channel_id"] == "UC3")["enabled"], False)

    def test_same_version_runs_once(self):
        self._write_seed([_row("UC1")])
        (config.DATA_DIR / "yt_channels.json").write_text(json.dumps([_row("UC1")]), encoding="utf-8")
        self.assertEqual(config.seed_merge_if_updated("yt_channels.json").get("added"), 0)
        self.assertEqual(config.seed_merge_if_updated("yt_channels.json").get("skipped"),
                         "same_version")

    def test_tombstoned_row_never_revives(self):
        # 用户已删除 UC1(本地无此行, 墓碑在案); 种子里仍有 → 合并不复活
        local = [_row("UC9")]
        (config.DATA_DIR / "yt_channels.json").write_text(json.dumps(local), encoding="utf-8")
        config.seed_tombstone("yt_channels.json", _row("UC1"))
        self._write_seed([_row("UC1"), _row("UC2")])
        rep = config.seed_merge_if_updated("yt_channels.json")
        self.assertEqual(rep["added"], 1)
        ids = {r["channel_id"] for r in self._local()}
        self.assertNotIn("UC1", ids)
        self.assertIn("UC2", ids)

    def test_seed_row_without_keys_skipped(self):
        (config.DATA_DIR / "yt_channels.json").write_text(json.dumps([_row("UC1")]), encoding="utf-8")
        self._write_seed([_row("UC2"), {"id": "y-bad", "note": "无键脏行"}])
        rep = config.seed_merge_if_updated("yt_channels.json")
        self.assertEqual(rep["added"], 1)
        self.assertEqual(len(self._local()), 2)


if __name__ == "__main__":
    unittest.main()
