"""账号管理数据面(2026-09-18 用户裁决九列)离线测试:
- xpool_prefs: 启用/备注写口(原子写/幂等/空偏好不落孤儿键)
- xaccounts: 池字段回填映射(positioning/tags/followers) + manage_payload 合成
  (关注=账号追踪库, 备注覆盖层, 启用=池 ∧ 本机) + 停用对 load_accounts 生效
- app 契约外的 x_track 联动: set_follow 增删追踪库行(补池内名称)
全离线: 池 yaml/x_track 库/偏好文件全部 patch 到临时目录。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))    # 任意目录可跑
from workbench.server import config, x_track, xaccounts, xpool_prefs

_POOL_YAML = """defaults:
  per_account_limit: 50
accounts:
- handle: AlphaOne
  uid: '1'
  name: Alpha One
  markets:
  - 美国
  role: analyst
  positioning: 美股宏观快评
  tags:
  - 宏观
  - 美联储
  followers: 123456
  note: pool-note-alpha
- handle: beta_two
  uid: '2'
  name: Beta Two
  markets:
  - 日本
  role: kol
  note: pool-note-beta
"""


def _route(module, name, target):
    p = patch.object(module, name, target)
    p.start()
    return p


class XpoolPrefsTests(unittest.TestCase):
    def setUp(self):
        _t = tempfile.TemporaryDirectory()
        self.addCleanup(_t.cleanup)
        self.tmp = Path(_t.name)
        _route(config, "DATA_DIR", self.tmp)

    def test_set_enabled_toggle(self):
        self.assertEqual(xpool_prefs.disabled_handles(), set())
        out = xpool_prefs.set_enabled("Alpha", False)
        self.assertFalse(out["enabled"])
        self.assertEqual(xpool_prefs.disabled_handles(), {"alpha"})
        out = xpool_prefs.set_enabled("alpha", True)          # 恢复看=清标记
        self.assertTrue(out["enabled"])
        self.assertEqual(xpool_prefs.load().get("alpha"), None)   # 空偏好不落孤儿键

    def test_set_note_overlay_and_clear(self):
        xpool_prefs.set_note("Alpha", "  本机备注  ")
        self.assertEqual(xpool_prefs.note_overlay("alpha"), "本机备注")
        xpool_prefs.set_note("alpha", "x" * 300)
        self.assertEqual(len(xpool_prefs.note_overlay("alpha")), 200)   # 截断 200
        xpool_prefs.set_note("alpha", "")
        self.assertEqual(xpool_prefs.note_overlay("alpha"), "")

    def test_corrupt_file_is_empty(self):
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (config.DATA_DIR / "xpool_prefs.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(xpool_prefs.load(), {})
        self.assertEqual(xpool_prefs.disabled_handles(), set())


class XaccountsManageTests(unittest.TestCase):
    def setUp(self):
        _t = tempfile.TemporaryDirectory()
        self.addCleanup(_t.cleanup)
        self.tmp = Path(_t.name)
        _route(config, "DATA_DIR", self.tmp)
        _route(x_track, "DATA_DIR", self.tmp)
        pool = self.tmp / "twitter_pool.yaml"
        pool.write_text(_POOL_YAML, encoding="utf-8")
        _route(xaccounts, "POOL_FILE", pool)
        # x_track 常量在 import 时已定型, 库文件与锁同目录一起 patch 到临时盘
        # (不 patch TRACK_FILE 会有跨盘 os.replace WinError 17, 也绝不碰真实库)
        _route(x_track, "TRACK_FILE", self.tmp / "x_track.json")
        xaccounts.invalidate()
        self.addCleanup(xaccounts.invalidate)

    def test_acct_view_backfill_fields(self):
        m = xaccounts._role_positioning_map()
        a = xaccounts._acct_view(
            {"handle": "x1", "role": "analyst", "markets": ["美国"],
             "positioning": "一句话定位", "tags": ["宏观", " 美联储 ", ""], "followers": "7"},
            m)
        self.assertEqual(a["positioning"], "一句话定位")       # 池字段优先
        self.assertEqual(a["tags"], ["宏观", "美联储"])        # 去空白去空串
        self.assertEqual(a["followers"], 7)
        b = xaccounts._acct_view({"handle": "x2", "role": "media"}, m)
        self.assertEqual(b["positioning"], m.get("media", ""))  # 缺池字段回退 role 口径
        self.assertEqual(b["tags"], [])
        self.assertEqual(b["followers"], 0)

    def test_manage_payload_synthesis(self):
        x_track.add_account("alphaone", note="")
        profiles = {"beta_two": {"followers": 99, "verified": True, "bio": "b"}}
        with patch.object(x_profile_enricher_mod(), "load_cache",
                          return_value={"profiles": profiles, "enriched_at": None}):
            d = xaccounts.manage_payload()
        rows = {r["handle"]: r for r in d["accounts"]}
        self.assertEqual(d["count"], 2)
        self.assertTrue(rows["AlphaOne"]["follow"])           # 关注=在追踪库(键小写判)
        self.assertFalse(rows["beta_two"]["follow"])
        self.assertEqual(rows["AlphaOne"]["followers"], 123456)   # 池字段优先
        self.assertEqual(rows["beta_two"]["followers"], 99)       # 缺池字段回退档案缓存
        self.assertEqual(rows["beta_two"]["note_effective"], "pool-note-beta")
        xpool_prefs.set_note("beta_two", "本机覆盖")
        with patch.object(x_profile_enricher_mod(), "load_cache",
                          return_value={"profiles": profiles, "enriched_at": None}):
            d = xaccounts.manage_payload()
        row = next(r for r in d["accounts"] if r["handle"] == "beta_two")
        self.assertEqual(row["note_local"], "本机覆盖")
        self.assertEqual(row["note_effective"], "本机覆盖")    # 覆盖层生效

    def test_enabled_toggle_hides_from_views(self):
        xaccounts.set_enabled("beta_two", False)
        self.assertIn("beta_two", xaccounts.disabled_handles())
        self.assertNotIn("beta_two", xaccounts.load_accounts(force=True))
        d = xaccounts.manage_payload()
        row = next(r for r in d["accounts"] if r["handle"] == "beta_two")
        self.assertFalse(row["enabled"])                      # 管理页仍列出但标停用
        self.assertTrue(row["pool_enabled"])                  # 池侧原状态不变
        xaccounts.set_enabled("beta_two", True)
        self.assertIn("beta_two", xaccounts.load_accounts(force=True))

    def test_set_follow_add_remove_with_name(self):
        xaccounts.set_follow("AlphaOne", True)
        store = x_track.load_store()
        self.assertIn("alphaone", store["accounts"])
        self.assertEqual(store["accounts"]["alphaone"]["name"], "Alpha One")   # 补池名
        xaccounts.set_follow("alphaone", False)               # 大小写无关
        self.assertNotIn("alphaone", x_track.load_store()["accounts"])

    def test_follow_unknown_handle_raises(self):
        with self.assertRaises(KeyError):
            xaccounts.set_follow("nobody404", True)
        with self.assertRaises(KeyError):
            xaccounts.set_enabled("nobody404", True)


def x_profile_enricher_mod():
    from workbench.server import x_profile_enricher
    return x_profile_enricher


if __name__ == "__main__":
    unittest.main()
