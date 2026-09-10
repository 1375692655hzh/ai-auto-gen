"""x_reply(蹭蹭流量·评论生成)单测。mock 掉 config.load / gcompose._llm / RSS 快照,
不依赖真实设置与网络。口径: MoA codex+grok+gemini 合成(2026-09-09)。"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "global-news-sources"))
from server import x_reply

ITEM = {"tweet_id": "2097309231082807795", "handle": "semianalysis_",
        "name": "SemiAnalysis", "text": "TPUv7 Ironwood achieves 50% better perf per dollar than Blackwell Ultra. Google open-sourcing Pallas kernels.",
        "text_zh": "谷歌 TPUv7 每美元性能超 Blackwell Ultra 50%, 开源 Pallas 内核。"}


class _IsolatedCache(unittest.TestCase):
    """每个用例独立临时缓存文件, 不碰真实 data/workbench/x_replies.json。"""

    def _rss(self, items=None):
        return {"updated_at": None, "items": items if items is not None else {ITEM["tweet_id"]: ITEM}}

    def setUp(self):
        self._tmp = Path(__file__).resolve().parent / "_x_reply_test_cache.json"
        self._tmp.unlink(missing_ok=True)
        self._patch = patch.object(x_reply, "CACHE_FILE", self._tmp)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.unlink(missing_ok=True)


RENDER = "定位: 金融投资大V · 证伪交易员\n一句话: 先写这判断在什么条件下作废"


class PromptTests(unittest.TestCase):
    def test_prompt_three_styles_and_rules(self):
        system, user, lang = x_reply.build_prompt(ITEM, RENDER)
        for style, _ in x_reply.STYLES:
            self.assertIn(style, system)
        self.assertIn("锚点", system)            # 反模板指纹
        self.assertIn("禁任何链接", system)
        self.assertIn("refuse", system)          # 站队/敏感哨兵
        self.assertIn(ITEM["text"], user)
        self.assertIn("人设", user)
        self.assertIn("证伪交易员", user)
        self.assertEqual(lang, "en")

    def test_lang_detect_zh(self):
        _, _, lang = x_reply.build_prompt({**ITEM, "text": "今天大盘涨得很好, 央行降息了"}, RENDER)
        self.assertEqual(lang, "zh")


class ValidateTests(unittest.TestCase):
    def test_discard_bad_keep_good(self):
        cands, notes = x_reply._validate([
            {"style": "hook", "text": "What is the memory bandwidth per dollar on TorchTPU stacks?"},
            {"style": "insight", "text": ""},
            {"style": "contrarian", "text": "see more at example.com/news"},
            {"style": "hook", "text": "数" * 200},                      # 400 计权 > 280
        ])
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["style"], "hook")
        self.assertLessEqual(cands[0]["weighted_len"], 280)
        self.assertIn("丢弃", notes)

    def test_url_stripped_by_gcompose(self):
        cands, _ = x_reply._validate([
            {"style": "hook", "text": "Solid point https://x.com/a/status/1 here"}])
        self.assertEqual(len(cands), 1)
        self.assertNotIn("http", cands[0]["text"])

    def test_similarity_note(self):
        cands, notes = x_reply._validate([
            {"style": "hook", "text": "The real question is whether Google can keep Pallas kernels updated quarterly for external stacks."},
            {"style": "insight", "text": "The real question is whether supply of HBM4 constrains TPUv7 ramps into 2027."}])
        self.assertIn("雷同", notes)


class CacheKeyTests(unittest.TestCase):
    def test_key_tracks_text_and_model(self):
        t = {"base_url": "http://x", "model": "m1"}
        k1 = x_reply._cache_key(ITEM, t)
        self.assertNotEqual(k1, x_reply._cache_key({**ITEM, "text": "changed"}, t))
        self.assertNotEqual(k1, x_reply._cache_key(ITEM, {**t, "model": "m2"}))
        self.assertEqual(k1, x_reply._cache_key(ITEM, dict(t)))
        k2 = x_reply._cache_key(ITEM, t, "falsify", "render-A")
        self.assertNotEqual(k1, k2)                       # 人设进 key
        self.assertNotEqual(k2, x_reply._cache_key(ITEM, t, "risk_first", "render-A"))
        self.assertNotEqual(k2, x_reply._cache_key(ITEM, t, "falsify", "render-B"))


class RunReplyTests(_IsolatedCache):
    def test_bad_sid_and_no_post(self):
        r, code = x_reply.run_reply("abc")
        self.assertEqual((code, r["error"]), (4, "bad_status_id"))
        with patch.object(x_reply.x_surge, "load_rss", return_value=self._rss({})):
            r, code = x_reply.run_reply(ITEM["tweet_id"])
        self.assertEqual((code, r["error"]), (4, "no_post"))

    def test_no_llm_config(self):
        with patch.object(x_reply.x_surge, "load_rss", return_value=self._rss()), \
             patch.object(x_reply.config, "load", return_value={"compose": {}}):
            r, code = x_reply.run_reply(ITEM["tweet_id"])
        self.assertEqual((code, r["error"]), (4, "no_llm_config"))

    def test_happy_path_and_cache(self):
        payload = {"comments": [
            {"style": "hook", "text": "What does this mean for NVDA inference attach rates in 2027?"},
            {"style": "insight", "text": "Per-dollar wins only matter if Google keeps Pallas updated; externalization risk is the real story."},
            {"style": "contrarian", "text": "Bottom line: benchmark wins fade if supply cannot scale."}]}
        calls = []

        def fake_llm(cfg4, system, user, max_tokens=2000, timeout=120):
            calls.append(1)
            return json.dumps(payload)

        cfg = {"compose": {"base_url": "http://x", "api_key": "k", "model": "m"}}
        with patch.object(x_reply.x_surge, "load_rss", return_value=self._rss()), \
             patch.object(x_reply.config, "load", return_value=cfg), \
             patch.object(x_reply.gcompose, "_llm", fake_llm):
            r1, code1 = x_reply.run_reply(ITEM["tweet_id"])
            r2, code2 = x_reply.run_reply(ITEM["tweet_id"])   # 第二次命中缓存
        self.assertEqual((code1, code2), (0, 0))
        self.assertEqual(len(r1["candidates"]), 3)
        self.assertTrue(all(c["weighted_len"] <= 280 for c in r1["candidates"]))
        self.assertEqual(len(calls), 1)                       # 缓存挡下第二次调用

    def test_refuse_passthrough(self):
        cfg = {"compose": {"base_url": "http://x", "api_key": "k", "model": "m"}}
        with patch.object(x_reply.x_surge, "load_rss", return_value=self._rss()), \
             patch.object(x_reply.config, "load", return_value=cfg), \
             patch.object(x_reply.gcompose, "_llm",
                          lambda *a, **k: json.dumps({"refuse": True, "reason": "政治向站队"})):
            r, code = x_reply.run_reply(ITEM["tweet_id"])
        self.assertEqual(code, 0)
        self.assertTrue(r["refuse"])
        self.assertEqual(r["reason"], "政治向站队")

    def test_all_invalid_is_llm_failed(self):
        cfg = {"compose": {"base_url": "http://x", "api_key": "k", "model": "m"}}
        with patch.object(x_reply.x_surge, "load_rss", return_value=self._rss()), \
             patch.object(x_reply.config, "load", return_value=cfg), \
             patch.object(x_reply.gcompose, "_llm", lambda *a, **k: json.dumps({"comments": []})):
            r, code = x_reply.run_reply(ITEM["tweet_id"])
        self.assertEqual((code, r["error"]), (3, "llm_failed"))


class GuardTests(unittest.TestCase):
    def test_try_begin_semantics(self):
        sid = "1111111111"
        ok, _ = x_reply.try_begin(sid, force=False)
        self.assertTrue(ok)
        ok2, err2 = x_reply.try_begin(sid, force=False)       # 同帖占用
        self.assertFalse(ok2)
        x_reply.finish(sid)
        ok3, _ = x_reply.try_begin(sid, force=True)
        self.assertTrue(ok3)
        ok4, err4 = x_reply.try_begin(sid, force=True)        # force 冷却 30s
        self.assertFalse(ok4)
        self.assertIn("30", err4)
        x_reply.finish(sid)


class PersonaTests(_IsolatedCache):
    """人设(grok v2): 默认等价/变更 cache miss/截断/refuse 兼容。"""

    def test_resolve_defaults_and_custom(self):
        pid, render, note = x_reply.resolve_persona(None, None)   # 无 settings → 默认
        self.assertEqual(pid, "falsify")
        self.assertIn("证伪交易员", render)
        self.assertEqual(note, "")
        pid2, render2, _ = x_reply.resolve_persona("risk_first", "只做美股期权流")
        self.assertEqual(pid2, "risk_first")
        self.assertIn("只做美股期权流", render2)
        self.assertIn("风险官", render2)

    def test_custom_over_200_truncates_with_note(self):
        long_text = "期权流交易员" * 40                      # 280 字
        pid, render, note = x_reply.resolve_persona("falsify", long_text)
        self.assertIn("截断", note)
        self.assertLessEqual(len(render), 240)

    def test_persona_switch_invalidates_cache(self):
        payload = {"comments": [
            {"style": "hook", "text": "这口径下库存周期还成立吗?"},
            {"style": "insight", "text": "若剔除一次性收益, 增速口径其实不可比。"},
            {"style": "contrarian", "text": "Bottom line: 叙事很满, 定价已满。"}]}
        calls = []
        cfg = {"compose": {"base_url": "http://x", "api_key": "k", "model": "m"}}
        with patch.object(x_reply.x_surge, "load_rss", return_value=self._rss()),              patch.object(x_reply.config, "load", return_value=cfg),              patch.object(x_reply.gcompose, "_llm",
                          lambda *a, **k: (calls.append(1), json.dumps(payload))[1]):
            r1, c1 = x_reply.run_reply(ITEM["tweet_id"], persona_id="falsify")
            r2, c2 = x_reply.run_reply(ITEM["tweet_id"], persona_id="falsify")  # 命中
            r3, c3 = x_reply.run_reply(ITEM["tweet_id"], persona_id="risk_first")
        self.assertEqual((c1, c2, c3), (0, 0, 0))
        self.assertEqual(len(calls), 2)          # 换人设 → cache miss 重生成
        self.assertEqual(r3["persona"], "risk_first")
        self.assertEqual(r1["persona"], "falsify")


    def test_user_persona_card_resolution(self):
        card = {"id": "u_opt", "label": "期权流", "one_liner": "只做伽马方向",
                "lens": "伽马挤压", "voice": "", "do": "", "dont": ""}
        cfg = {"compose": {}, "x_reply": {"personas": [card]}}
        with patch.object(x_reply.config, "load", return_value=cfg):
            pid, render, _ = x_reply.resolve_persona("u_opt", None)
        self.assertEqual(pid, "u_opt")
        self.assertIn("期权流", render)
        self.assertIn("伽马挤压", render)
        self.assertIn("不冷嘲作者", render)   # 空字段用默认骨架兜底(voice)

    def test_user_persona_card_sanitize(self):
        c = x_reply.clean_persona_card({"id": "u _bad!id", "label": "标" * 30,
                                        "evil": "x", "one_liner": "a\nb"})
        self.assertEqual(c["id"], "u_badid")
        self.assertLessEqual(len(c["label"]), 12)
        self.assertNotIn("evil", c)
        self.assertNotIn("\n", c["one_liner"])

    def test_unknown_persona_id_falls_back(self):
        cfg = {"compose": {}, "x_reply": {"personas": []}}
        with patch.object(x_reply.config, "load", return_value=cfg):
            pid, render, _ = x_reply.resolve_persona("no_such", None)
        self.assertEqual(pid, "falsify")

    def test_refuse_still_works_with_persona(self):
        cfg = {"compose": {"base_url": "http://x", "api_key": "k", "model": "m"}}
        with patch.object(x_reply.x_surge, "load_rss", return_value=self._rss()),              patch.object(x_reply.config, "load", return_value=cfg),              patch.object(x_reply.gcompose, "_llm",
                          lambda *a, **k: json.dumps({"refuse": True, "reason": "政治向站队"})):
            r, code = x_reply.run_reply(ITEM["tweet_id"], persona_id="odds")
        self.assertEqual(code, 0)
        self.assertTrue(r["refuse"])

    def test_soft_sentinels_note_not_discard(self):
        cands, notes = x_reply._validate([
            {"style": "hook", "text": "关注我拿完整框架, 这口径下库存周期还成立吗?"},
            {"style": "insight", "text": "作为一名宏观交易员, 我认为口径不可比。"},
            {"style": "contrarian", "text": "Bottom line: 叙事很满, 定价已满。"}])
        self.assertEqual(len(cands), 3)          # 软规则不丢弃
        self.assertIn("引流", notes)
        self.assertIn("自我介绍", notes)


if __name__ == "__main__":
    unittest.main()
