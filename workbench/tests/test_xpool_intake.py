"""xpool_intake(2026-09-20 固化)离线单测: 清单解析/正则校验/去重/预分类/写池。
覆盖 2026-09-17/19 四类事故的防复发逻辑: 非法 handle(含空格)退回不猜、清单内大小写去重、
池 handle/uid 查重、404 进失败清单、文本级写池+写后自查+幂等。
全离线: FxTwitter 验号 patch 掉, 池文件落临时目录。裸克隆可跑:
py -3.11 -m pytest workbench/tests/test_xpool_intake.py"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import xpool_intake as xi

_POOL_TEXT = """defaults:
  per_account_limit: 50
accounts:
- handle: dotey
  uid: '3178231'
  name: Dotey
  markets:
  - 全球
  role: kol
  lang: zh
  priority: medium
  risk: medium
  replies: false
- handle: HAOHONG_CFA
  uid: '41902408'
  name: Hong Hao
  markets:
  - 全球
  role: analyst
  lang: en
  priority: medium
  risk: low
  replies: false
filters:
  include_keywords:
  - stocks
  exclude_keywords:
  - giveaway
"""


def _mktmp():
    _t = tempfile.TemporaryDirectory()
    return _t


class ExtractTests(unittest.TestCase):
    def test_mixed_formats(self):
        text = ("\n"
                "cnfinancewatch\n"
                "@TraderS18\n"
                "王下一半@WangNextDoor2\n"
                "https://x.com/dotey\n"
                "https://www.twitter.com/Saylor?s=09\n"
                "1. qinbafrank\n"
                "2、fxtrader,\n"
                "- tj\n"
                "* okok_9\n"
                "# 注释跳过\n"
                "＠full＠width_handle\n"
                "| table_handle | 其他 |\n")
        cands, fails, skipped = xi.extract_handles(text)
        got = [h for h, _no in cands]
        self.assertEqual(got, ["cnfinancewatch", "TraderS18", "WangNextDoor2", "dotey",
                               "Saylor", "qinbafrank", "fxtrader", "tj", "okok_9",
                               "width_handle", "table_handle"])
        self.assertEqual(fails, [])
        self.assertEqual([s["cand"] for s in skipped], ["其他"])   # 中文名列跳过不报失败

    def test_illegal_space_not_guessed(self):
        """事故3: 名字@handle 混排带空格 → 失败清单原样退回, 绝不猜。"""
        cands, fails, _sk = xi.extract_handles("Jack Kellogg@Jackaroo Trades\n")
        self.assertEqual(cands, [])
        self.assertEqual(len(fails), 1)
        self.assertEqual(fails[0]["cand"], "Jackaroo Trades")
        self.assertIn("空格", fails[0]["reason"])
        self.assertIn("Jack Kellogg@Jackaroo Trades", fails[0]["raw"])

    def test_status_link_rejected(self):
        cands, fails, _sk = xi.extract_handles("https://x.com/dotey/status/123456\n")
        self.assertEqual(cands, [])
        self.assertEqual(fails[0]["cand"], "dotey")
        self.assertIn("帖子链接", fails[0]["reason"])

    def test_illegal_chars_and_length(self):
        cands, fails, _sk = xi.extract_handles("abc-def\n" + "A" * 16 + "\n@@\n")
        self.assertEqual(cands, [])
        reasons = [f["reason"] for f in fails]
        self.assertTrue(any("仅允许" in r for r in reasons))
        self.assertTrue(any("超 15 位" in r for r in reasons))
        self.assertTrue(any("空候选" in r for r in reasons))

    def test_table_placeholders_skipped(self):
        cands, fails, skipped = xi.extract_handles("| handle | --- | — | 无 | 其他 |\n| real_one | x |\n")
        self.assertEqual([h for h, _ in cands], ["real_one", "x"])   # 单字母 x 是合法 handle
        self.assertEqual(fails, [])
        self.assertEqual([s["cand"] for s in skipped], ["其他"])


class DedupInListTests(unittest.TestCase):
    def test_case_insensitive_keep_first(self):
        """事故4: 清单内部重复(TJ_Research×2 + 大小写变体) → 保留首次。"""
        kept, dupes = xi.dedup_in_list([("TJ_Research", 1), ("TJ_Research", 5),
                                        ("tj_research", 9), ("Other", 2)])
        self.assertEqual([h for h, _ in kept], ["TJ_Research", "Other"])
        self.assertEqual([(h, no, first) for h, no, first in dupes],
                         [("TJ_Research", 5, 1), ("tj_research", 9, 1)])


class DetectLangTests(unittest.TestCase):
    def test_zh_en_ja_ko_tr(self):
        self.assertEqual(xi.detect_lang("专注美股产业链分析，跟踪财报与政策", []), "zh")
        self.assertEqual(xi.detect_lang("Macro strategist. Fed, yields, tariffs.", []), "en")
        self.assertEqual(xi.detect_lang("米国株と日本株の情報発信", ["決算キータンです"]), "ja")
        self.assertEqual(xi.detect_lang("한국 증시 분석", []), "ko")
        self.assertEqual(xi.detect_lang("BIST hisse analiz, hedef fiyat ve teknik",
                                        ["bilanço açıkladı"]), "tr")

    def test_empty_is_en(self):
        self.assertEqual(xi.detect_lang("", []), "en")


class CardTests(unittest.TestCase):
    def test_build_card_defaults(self):
        prof = {"uid": "58560480", "name": "Michael Dell", "followers": 8170000,
                "bio": "Founder, Chairman and CEO", "posts": ["Dell earnings today"]}
        c = xi.build_card("MichaelDell", prof, "同事收集批次", "2026-09-17")
        self.assertEqual(c["uid"], "58560480")            # uid 字符串
        self.assertEqual(c["role"], "kol")
        self.assertEqual(c["markets"], ["全球"])
        self.assertEqual(c["priority"], "medium")
        self.assertEqual(c["risk"], "medium")
        self.assertFalse(c["replies"])
        self.assertEqual(c["homepage"], "https://x.com/MichaelDell")
        self.assertTrue(c["note"].startswith("同事收集批次(2026-09-17); 粉丝817万; bio: "))

    def test_card_yaml_lines_roundtrip_and_style(self):
        c = xi.build_card("dotey2", {"uid": "1", "name": "D", "followers": 10000,
                                     "bio": "x: y", "posts": []}, "b", "2026-09-20")
        lines = xi.card_yaml_lines(c)
        self.assertTrue(lines[0].startswith("- handle:"))
        self.assertTrue(lines[1].startswith("  uid:"))
        self.assertIn("  - 全球", lines)                   # 列表块风格与池一致
        parsed = yaml.safe_load("\n".join(lines))
        self.assertEqual(parsed[0], c)                     # 整卡可无损还原


class PoolIndexTests(unittest.TestCase):
    def test_lower_and_uid_map(self):
        pool = yaml.safe_load(_POOL_TEXT)
        hs, uids = xi.pool_index(pool)
        self.assertEqual(hs["haohong_cfa"], "HAOHONG_CFA")   # 大小写不敏感键
        self.assertEqual(uids["3178231"], "dotey")


class InsertCardsTests(unittest.TestCase):
    def test_insert_before_filters_and_roundtrip(self):
        cards = [xi.build_card("NewOne", {"uid": "111", "name": "N1", "followers": 20000,
                                          "bio": "", "posts": []}, "b", "2026-09-20"),
                 xi.build_card("NewTwo", {"uid": "222", "name": "N2", "followers": None,
                                          "bio": "bio2", "posts": []}, "b", "2026-09-20")]
        out = xi.insert_cards(_POOL_TEXT, cards)
        pool = yaml.safe_load(out)                          # 写后自查前提: 仍是合法 yaml
        hs = [a["handle"] for a in pool["accounts"]]
        self.assertEqual(hs[-2:], ["NewOne", "NewTwo"])     # 块尾追加
        self.assertEqual(hs[0], "dotey")                    # 旧账号原样在前
        self.assertIn("stocks", pool["filters"]["include_keywords"])   # filters 完好
        self.assertEqual(pool["defaults"]["per_account_limit"], 50)


class VerifyOneTests(unittest.TestCase):
    def _payload(self, author, texts=("post one", "post two")):
        return {"results": [{"author": author, "text": t} for t in texts]}

    def test_verify_normal(self):
        au = {"id": 123, "screen_name": "NewGuy", "name": "New Guy",
              "followers": 150000, "description": "宏观 分析"}
        with patch.object(xi, "_get", return_value=self._payload(au)):
            prof = xi.verify_one("NewGuy")
        self.assertEqual(prof["uid"], "123")
        self.assertEqual(prof["followers"], 150000)
        self.assertEqual(prof["name"], "New Guy")
        self.assertTrue(prof["posts"])

    def test_verify_retweet_trap(self):
        """转推陷阱: 条目 author 是原作者, 本人身份在 reposted_by → 仍能按 handle 匹配。"""
        item = {"author": {"id": 999, "screen_name": "SomeoneElse"},
                "reposted_by": {"id": 555, "screen_name": "RealOwner"},
                "text": "rt content"}
        with patch.object(xi, "_get", return_value={"results": [item]}):
            prof = xi.verify_one("RealOwner")
        self.assertEqual(prof["uid"], "555")

    def test_verify_enrich_from_profile_endpoint(self):
        """statuses 的 author 缺 followers/description → 用 /2/profile 佐证补全。"""
        statuses = {"results": [{"author": {"id": 7, "screen_name": "PoorMeta",
                                            "name": "PoorMeta"}, "text": "hi"}]}
        profile = {"user": {"followers": 4321, "description": "宏观 美股",
                            "name": "Rich Meta"}}
        with patch.object(xi, "_get", side_effect=[statuses, profile]):
            prof = xi.verify_one("PoorMeta")
        self.assertEqual(prof["uid"], "7")
        self.assertEqual(prof["followers"], 4321)
        self.assertEqual(prof["bio"], "宏观 美股")
        self.assertEqual(prof["name"], "Rich Meta")

    def test_verify_mismatch_not_guessed(self):
        """首页匹配不上本人(全转推/改名冲突) → 失败, 绝不取首条凑数。"""
        au = {"id": 999, "screen_name": "SomeoneElse"}
        with patch.object(xi, "_get", return_value=self._payload(au)):
            with self.assertRaises(RuntimeError) as cm:
                xi.verify_one("GhostHandle")
        self.assertIn("author_mismatch", str(cm.exception))

    def test_verify_404_and_500(self):
        with patch.object(xi, "_get", side_effect=RuntimeError("http_404")):
            with self.assertRaises(xi.NotFound):
                xi.verify_one("MichealDell")
        with patch.object(xi, "_get", side_effect=RuntimeError("http_500")):
            with self.assertRaises(RuntimeError) as cm:
                xi.verify_one("SecretGuy")
        self.assertIn("http_500", str(cm.exception))


class MainE2ETests(unittest.TestCase):
    """main 全流程离线跑: 清单→报告→(可选)写池→幂等。"""

    def setUp(self):
        _t = _mktmp()
        self.addCleanup(_t.cleanup)
        self.tmp = Path(_t.name)
        self.pool = self.tmp / "twitter_pool.yaml"
        self.pool.write_text(_POOL_TEXT, encoding="utf-8")
        self.list = self.tmp / "list.txt"
        self.list.write_text("dotey\n"                       # 池 handle 重复
                             "TJ_Research\nTJ_Research\n"    # 清单内重复
                             "Jack Kellogg@Jackaroo Trades\n"  # 非法 handle(事故3)
                             "MichealDell\n"                 # 404(事故2)
                             "@NewGuy\n",                    # 验号通过 → 新号
                             encoding="utf-8")

        def fake_verify(h):
            if h == "MichealDell":
                raise xi.NotFound(h)
            if h == "UidClash":
                return {"uid": "3178231", "name": "Clash", "followers": 1000,
                        "bio": "", "posts": []}              # 撞 dotey 的 uid
            if h == "TJ_Research":
                return {"uid": "777", "name": "TJ Research", "followers": 90000,
                        "bio": "投资研究", "posts": ["研究"]}
            return {"uid": "991", "name": "New Guy", "followers": 250000,
                    "bio": "美股 宏观", "posts": ["hi"]}

        p = patch.object(xi, "verify_one", side_effect=fake_verify)
        p.start()
        self.addCleanup(p.stop)
        sp = patch.object(xi, "FETCH_SLEEP", 0)
        sp.start()
        self.addCleanup(sp.stop)

    def test_dry_run_no_write_and_exit2(self):
        rc = xi.main([str(self.list), "--pool", str(self.pool)])
        self.assertEqual(rc, 2)                             # 失败清单非空 → 交用户核实
        self.assertEqual(self.pool.read_text(encoding="utf-8"), _POOL_TEXT)   # 未写

    def test_apply_writes_and_idempotent(self):
        rc = xi.main([str(self.list), "--pool", str(self.pool),
                      "--apply", "--batch", "同事收集批次"])
        self.assertEqual(rc, 2)
        pool = yaml.safe_load(self.pool.read_text(encoding="utf-8"))
        accs = {a["handle"]: a for a in pool["accounts"]}
        self.assertEqual(len(accs), 4)                      # 旧 2 + 新 2(TJ_Research/NewGuy)
        new = accs["NewGuy"]
        self.assertEqual(new["uid"], "991")
        self.assertEqual(new["role"], "kol")
        self.assertTrue(new["note"].startswith("同事收集批次(2026-"))
        self.assertEqual(accs["TJ_Research"]["uid"], "777")
        before = self.pool.read_text(encoding="utf-8")
        # 幂等: 重跑全部命中重复, 池文件字节不变
        rc2 = xi.main([str(self.list), "--pool", str(self.pool), "--apply"])
        self.assertEqual(rc2, 2)
        self.assertEqual(self.pool.read_text(encoding="utf-8"), before)
        self.assertIn("stocks", pool["filters"]["include_keywords"])   # filters 完好

    def test_uid_clash_rejected(self):
        """红线: uid 撞车拒绝录入(同人改名须先人工合并) + 归入需人工 exit 2。"""
        self.list.write_text("UidClash\n", encoding="utf-8")
        rc = xi.main([str(self.list), "--pool", str(self.pool), "--apply"])
        self.assertEqual(rc, 2)
        pool = yaml.safe_load(self.pool.read_text(encoding="utf-8"))
        self.assertEqual(len(pool["accounts"]), 2)          # 未写入
        self.assertTrue(all(a["handle"] != "UidClash" for a in pool["accounts"]))

    def test_all_clean_exit0(self):
        self.list.write_text("@Fresh1\n", encoding="utf-8")
        rc = xi.main([str(self.list), "--pool", str(self.pool), "--apply"])
        self.assertEqual(rc, 0)                             # 无失败 → 0
        pool = yaml.safe_load(self.pool.read_text(encoding="utf-8"))
        self.assertEqual([a["handle"] for a in pool["accounts"]][-1], "Fresh1")

    def test_missing_pool_is_exit3(self):
        rc = xi.main([str(self.list), "--pool", str(self.tmp / "nope.yaml")])
        self.assertEqual(rc, 3)


if __name__ == "__main__":
    unittest.main()
