"""内容生成回归测试: 纯函数及 mock 边界, 不访问网络或运行时数据。"""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import gcompose


class TextTests(unittest.TestCase):
    def test_weighted_len(self):
        for text, expected in [("https://example.com/long/path", 23),
                               ("中文", 4), ("😀🚀", 4), ("Abc!", 4),
                               ("A中😀 https://x.co", 29), ("", 0)]:
            with self.subTest(text=text):
                self.assertEqual(gcompose.weighted_len(text), expected)

    def test_strip_urls(self):
        self.assertEqual(gcompose._strip_urls("First https://x.co\n\nhttps://y.co\n\nLast"),
                         "First\n\nLast")

    def test_no_urls_unchanged(self):
        text = "  First  \n\n\nLast\n"
        self.assertEqual(gcompose._strip_urls(text), text)

    def test_strip_opinions(self):
        for marker in ("View:", "My take:", "我认为", "Bottom line:"):
            with self.subTest(marker=marker):
                self.assertEqual(gcompose._strip_opinion_lines("Fact\n\n  " + marker + " bullish\n\nEnd"),
                                 ("Fact\n\nEnd", True))

    def test_opinion_empty_guard(self):
        text = "View: bullish\nMy take: uncertain\n我认为还有风险"
        self.assertEqual(gcompose._strip_opinion_lines(text), (text, False))

    def test_quoted_opinion_unchanged(self):
        text = "机构称政策利好科技、利空能源。"
        self.assertEqual(gcompose._strip_opinion_lines(text), (text, False))

    def test_existing_cashtag(self):
        self.assertEqual(gcompose._ensure_cashtags("$nvda rises", ["NVDA"], 280),
                         ("$nvda rises", ""))

    def test_inline_first_uppercase(self):
        self.assertEqual(gcompose._ensure_cashtags("NVDA rises; NVDA leads", ["NVDA"], 280),
                         ("$NVDA rises; NVDA leads", ""))

    def test_lowercase_appended(self):
        self.assertEqual(gcompose._ensure_cashtags("nvda rises", ["NVDA"], 280),
                         ("nvda rises\n\n$NVDA", ""))

    def test_on_monday(self):
        self.assertEqual(gcompose._ensure_cashtags("On Monday", ["ON"], 280),
                         ("On Monday\n\n$ON", ""))

    def test_numeric_ticker_skipped(self):
        self.assertEqual(gcompose._ensure_cashtags("2330 rises", ["2330.TW"], 280),
                         ("2330 rises", ""))

    def test_cashtag_limit(self):
        for text in ("a" * 279, "NVDA " + "a" * 275):
            with self.subTest(text=text[:5]):
                out, note = gcompose._ensure_cashtags(text, ["NVDA"], 280)
                self.assertEqual(out, text)
                self.assertIn("$NVDA", note)
                self.assertLessEqual(gcompose.weighted_len(out), 280)

    def test_extract_tags(self):
        self.assertEqual(gcompose._extract_tags("#财经 $nvda $230 $NVDA #财经 $AAPL #Macro #macro"),
                         ["#财经", "$NVDA", "$AAPL", "#Macro"])

    def test_em_secid(self):
        for ticker, expected in [("600000.SH", "1.600000"), ("000001.SZ", "0.000001"),
                                 ("700.HK", "116.00700"), ("nvda", "105.NVDA")]:
            with self.subTest(ticker=ticker):
                self.assertEqual(gcompose._em_secid(ticker), expected)

    def test_parse_first_json(self):
        self.assertEqual(gcompose._parse_json('prefix {bad} ```json\n{"text":"brace }", "nested":{"a":1}}\n``` {"second":2}'),
                         {"text": "brace }", "nested": {"a": 1}})
        self.assertIsNone(gcompose._parse_json("not json"))


class TemplateTests(unittest.TestCase):
    def test_templates_complete(self):
        self.assertEqual(len(gcompose.TEMPLATES), 13)   # 12 + thread-post(串推, 批次B)
        self.assertEqual(set(gcompose.TEMPLATES), set(gcompose._TPL_SCAFFOLD))
        for slug in gcompose.TEMPLATES:
            with self.subTest(slug=slug):
                scaffold = gcompose._TPL_SCAFFOLD[slug]
                self.assertEqual(len(scaffold), 3)
                self.assertTrue(all(isinstance(s, str) and s.strip() for s in scaffold))

    def test_zero_opinion_and_legacy(self):
        self.assertEqual(len(gcompose.ZERO_OPINION_TEMPLATES), 5)
        self.assertLess(set(gcompose.ZERO_OPINION_TEMPLATES), set(gcompose.TEMPLATES))
        for slug in gcompose.ZERO_OPINION_TEMPLATES:
            for scaffold in gcompose._TPL_SCAFFOLD[slug][1:]:
                self.assertIn("零观点", scaffold)
        self.assertTrue(set(gcompose._TPL_LEGACY.values()) <= set(gcompose.TEMPLATES))

    def test_prompt_scaffolds(self):
        for slug in ("catalyst-take", "news-flash"):
            for tier, index in (("free", 1), ("paid", 2)):
                with self.subTest(slug=slug, tier=tier):
                    system, user = gcompose._compose_prompt(
                        {"lang": "en", "tier": tier, "template": slug}, [], [], "", {}, [])
                    self.assertEqual(system, gcompose._X_STYLE)
                    self.assertIn(gcompose._TPL_SCAFFOLD[slug][index], user)
                    self.assertNotIn(gcompose._TPL_SCAFFOLD[slug][3-index], user)


class BoundaryTests(unittest.TestCase):
    def test_no_items(self):
        with patch.object(gcompose.config, "load", return_value={"compose": {}}):
            result, code = gcompose.run_compose({"items": []})
        self.assertEqual((code, result["error"]), (4, "no_items"))

    def test_no_llm_config(self):
        with patch.object(gcompose.config, "load", return_value={"compose": {}}):
            result, code = gcompose.run_compose({"items": [{"text": "local test"}]})
        self.assertEqual((code, result["error"]), (4, "no_llm_config"))

    def test_market_order_and_fallback(self):
        for pref, order in [("auto", ["yf", "em"]), ("em_first", ["em", "yf"]),
                            ("yf_only", ["yf"]), ("unknown", ["yf", "em"])]:
            calls = []
            def fail(name):
                def fetch(*args):
                    calls.append(name)
                    return None, name + " failed"
                return fetch
            with self.subTest(pref=pref), patch.object(gcompose, "_fetch_ohlcv_yf", side_effect=fail("yf")), \
                    patch.object(gcompose, "_fetch_ohlcv_em", side_effect=fail("em")):
                self.assertEqual(gcompose._fetch_ohlcv("NVDA", pref=pref),
                                 (None, "; ".join(x + " failed" for x in order), ""))
                self.assertEqual(calls, order)

    def test_market_first_success(self):
        for pref, via in [("auto", "yfinance"), ("em_first", "eastmoney"), ("yf_only", "yfinance")]:
            frame = object()
            with self.subTest(pref=pref), patch.object(gcompose, "_fetch_ohlcv_yf", return_value=(frame, "")) as yf, \
                    patch.object(gcompose, "_fetch_ohlcv_em", return_value=(frame, "")) as em:
                self.assertEqual(gcompose._fetch_ohlcv("NVDA", pref=pref), (frame, "", via))
                self.assertEqual(yf.call_count + em.call_count, 1)


class LlmConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("batch_a_cli", Path(__file__).resolve().parents[2] / "cli.py")
        cls.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.cli)

    def test_cli_results_and_no_secret_output(self):
        for cfg, response, code, error in [({}, None, 4, "no_llm_config"),
                ({"base_url": "https://local.invalid", "api_key": "test-secret", "model": "test-model"}, "pong", 0, ""),
                ({"base_url": "https://local.invalid", "api_key": "test-secret", "model": "test-model"}, None, 3, "llm_connection_failed"),
                ({"base_url": "https://local.invalid", "api_key": "test-secret", "model": "test-model"}, RuntimeError("test-secret"), 3, "llm_connection_failed")]:
            output = io.StringIO()
            with self.subTest(code=code), patch.object(gcompose.config, "load", return_value={"compose": cfg}), \
                    patch.object(gcompose.vstudio, "chat_completions", **(
                        {"side_effect": response} if isinstance(response, Exception) else {"return_value": response})) as chat, \
                    contextlib.redirect_stdout(output):
                self.assertEqual(self.cli.workbench_cmd(SimpleNamespace(sub="test-llm")), code)
            self.assertEqual(json.loads(output.getvalue()),
                             {"ok": code == 0, "model": cfg.get("model", ""), "error": error})
            self.assertNotIn("test-secret", output.getvalue())
            if cfg:
                chat.assert_called_once_with(cfg["base_url"], cfg["api_key"], cfg["model"],
                    [{"role": "user", "content": "ping"}], temperature=0, max_tokens=8, timeout=25)
            else:
                chat.assert_not_called()

    def test_endpoint_subprocess_contract(self):
        from server.app import create_app
        endpoint = next(r.endpoint for r in create_app().routes if r.path == "/wb-api/test-llm")
        import inspect
        self.assertFalse(inspect.iscoroutinefunction(endpoint))
        good = {"ok": True, "model": "test", "error": ""}
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=json.dumps(good))) as run:
            self.assertEqual(endpoint(), good)
        self.assertEqual(run.call_args.args[0][:2], ["py", "-3.11"])
        self.assertEqual(run.call_args.args[0][-2:], ["workbench", "test-llm"])
        self.assertEqual(run.call_args.kwargs["timeout"], 40)
        for side_effect, result, status in [
                (subprocess.TimeoutExpired("test", 40), None, 504),
                (OSError("test"), None, 500),
                (None, SimpleNamespace(returncode=3, stdout="not JSON"), 502),
                (None, SimpleNamespace(returncode=4, stdout=json.dumps({"ok": False, "model": "", "error": "no_llm_config"})), 400)]:
            with self.subTest(status=status), patch("subprocess.run", side_effect=side_effect, return_value=result):
                self.assertEqual(endpoint().status_code, status)


if __name__ == "__main__":
    unittest.main()
