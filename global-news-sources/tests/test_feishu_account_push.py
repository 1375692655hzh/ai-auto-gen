"""账号成分推送回归(2026-09-21): 9类投影 / 作者继承 / 配额切分 / 选卡组卡 / 节流。

裸克隆可跑(离线全 mock, 不实抓不发群):
  python -m pytest global-news-sources/tests/test_feishu_account_push.py -q
"""

import importlib
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

feishu = importlib.import_module("sources.feishu")


# ── 1. 条目投影: L1 优先 / 加密锁 / 金融按市场 / 作者继承 / 空兜底 ──────────
def test_item_topics_l1_direct():
    tp = feishu._item_topics('["半导体>代工"]', '["全球"]', "someone", {})
    assert tp == {"AI与科技"}


def test_item_topics_crypto_lock_wins():
    tp = feishu._item_topics('["金融与加密>加密资产"]', '["美国"]', "a", {})
    assert tp == {"加密"}


def test_item_topics_fin_non_crypto_by_market():
    assert feishu._item_topics('["金融与加密>券商"]', '["美国"]', "a", {}) == {"美股"}
    assert feishu._item_topics('["金融与加密>银行"]', '["A股"]', "a", {}) == {"A股"}
    assert feishu._item_topics('["金融与加密>银行"]', '["香港"]', "a", {}) == {"亚太股市"}
    # 市场不明确 → 空集(宁漏勿误)
    assert feishu._item_topics('["金融与加密>银行"]', '["全球"]', "a", {}) == set()


def test_item_topics_author_inherit_fallback():
    at = {"kol_ai": {"AI与科技", "美股"}}
    tp = feishu._item_topics("[]", '["美国"]', "Kol_AI", at)      # 大小写归一
    assert tp == {"AI与科技", "美股"}
    assert feishu._item_topics("[]", "[]", "unknown", at) == set()


def test_item_topics_l1_beats_author():
    at = {"macro_kol": {"宏观与政策"}}
    tp = feishu._item_topics('["半导体>存储记忆体"]', "[]", "macro_kol", at)
    assert tp == {"AI与科技"}                                       # 条目投影为准


def test_item_topics_crypto_text_lock_additive():
    # 币帖由纯美股作者发出: 继承美股 + 文本锁附加加密(不替换)
    at = {"uw": {"美股"}}
    tp = feishu._item_topics("[]", '["美国"]', "uw", at,
                             "BREAKING: Bitcoin rises above \$84,000")
    assert tp == {"美股", "加密"}
    # L1 命中时文本锁同样附加
    tp2 = feishu._item_topics('["宏观与政策>货币政策"]', "[]", "a", {},
                              "ETH ETF inflows surge")
    assert tp2 == {"宏观与政策", "加密"}
    # 无命中词不受影响
    assert feishu._item_topics("[]", "[]", "uw", at, "NVDA earnings beat") == {"美股"}


# ── 2. 作者继承: 池 tags 映射 + 投教信号 + 停用排除 ──────────────────────────
def test_author_topics_from_pool(monkeypatch):
    # 桩模拟 _pool_accounts 的产出契约(只含启用账号; enabled 过滤在 _pool_accounts 内)
    monkeypatch.setattr(feishu, "_pool_accounts", lambda: [
        {"handle": "UW", "tags": ["美股"], "enabled": True},
        {"handle": "prof", "tags": ["美股"], "note": "20年股市教授, 每周估值课",
         "positioning": "", "enabled": True},
        {"handle": "tr1", "tags": ["土耳其"], "enabled": True},    # 土标签无映射
    ])
    at = feishu._author_topics()
    assert at["uw"] == {"美股"}
    assert at["prof"] == {"美股", "投教科普"}
    assert at["tr1"] == set()


# ── 3. 配额切分(最大余数法, 每主题≥1) ───────────────────────────────────────
def test_split_quota_owen():
    q = feishu._split_quota({"美股": 60, "AI与科技": 30, "亚太股市": 10}, 10)
    assert sum(q.values()) == 10
    assert q["美股"] == 6 and q["AI与科技"] == 3 and q["亚太股市"] == 1


def test_split_quota_thirds_and_single():
    q = feishu._split_quota({"a": 33, "b": 33, "c": 33}, 10)
    assert sum(q.values()) == 10 and min(q.values()) >= 1
    assert feishu._split_quota({"美股": 100}, 8) == {"美股": 8}
    assert feishu._split_quota({}, 8) == {}


# ── 4. 选卡: 热度降序 / 条目单次出现 / 满额溢出到次优主题 ────────────────────
def _mk(handle, topics, views, url):
    return {"author_handle": handle, "topics": set(topics), "views": views,
            "likes": 0, "text": f"post-{handle}-{views}", "text_zh": "", "url": url}


def test_pick_orders_by_views_and_dedup():
    items = [_mk("a", {"美股"}, 900, "u1"), _mk("b", {"美股"}, 12000, "u2"),
             _mk("c", {"美股", "AI与科技"}, 500, "u3")]
    acc = {"mix": {"美股": 70, "AI与科技": 30}}
    per = feishu._pick_for_account(items, acc, 3)
    assert [i["url"] for i in per["美股"]] == ["u2", "u1"]
    assert per["AI与科技"][0]["url"] == "u3"      # 单次出现: c 只出现在AI(美股满2/2)


def test_pick_quota_respected():
    items = [_mk(f"h{i}", {"美股"}, 100 - i, f"u{i}") for i in range(8)]
    per = feishu._pick_for_account(items, {"mix": {"美股": 60, "加密": 40}}, 5)
    assert len(per["美股"]) == 3                   # 60% of 5
    assert "加密" not in per                       # 无命中素材的主题不出现


# ── 5. 组卡: @人 / 成分串 / 主题序 / 原文截断 / 长度熔断 ──────────────────────
def test_compose_push_basic():
    per = {"美股": [_mk("b", {"美股"}, 12000, "u2"), _mk("a", {"美股"}, 9, "u1")]}
    mix = {"美股": 60, "AI与科技": 40}
    txt = feishu._compose_push(
        {"name": "Owen聊投资", "owner": "Owen"}, per, mix, "09-21 10:00~12:00", 33)
    assert "@Owen 账号「Owen聊投资」" in txt
    assert "美股60% · AI与科技40%" in txt
    assert "▍美股（Top2）" in txt and "👁1.2万" in txt
    assert txt.index("u2") < txt.index("u1")       # 热度降序


def test_compose_push_real_at_tag():
    per = {"AI与科技": [_mk("x", {"AI与科技"}, 5, "u")]}
    txt = feishu._compose_push(
        {"name": "N", "owner": "张三", "owner_open_id": "ou_abc"}, per, {"AI与科技": 100},
        "t", 1)
    assert '<at user_id="ou_abc"></at>' in txt


def test_compose_push_length_guard():
    items = [_mk(f"h{i}", {"美股"}, i, f"u{i}") for i in range(200)]
    txt = feishu._compose_push({"name": "N", "owner": "O"}, {"美股": items},
                               {"美股": 100}, "t", 200)
    assert len(txt) <= feishu.MAX_TEXT


def test_fmt_views():
    assert feishu._fmt_views(12345) == "1.2万"
    assert feishu._fmt_views(10000) == "1万"
    assert feishu._fmt_views(999) == "999"
    assert feishu._fmt_views(None) == ""


# ── 6. run_account_push 集成(dry-run 全链 mock) ──────────────────────────────
class _FakeConn:
    def execute(self, sql, params):
        class _R:
            def fetchall(inner):
                return [
                    ("src_twitter_a", "t1", "NVDA earnings beat", "", "u1", "UW",
                     '["半导体>代工"]', '["美国"]'),
                    ("src_twitter_b", "t2", "BTC breakout", "", "u2", "crypto_kol",
                     '[]', '["全球"]'),
                    ("src_twitter_a", "t3", "dup of u1", "", "u1", "UW",
                     '["半导体>代工"]', '["美国"]'),
                ]
        return _R()

    def close(self):
        pass


def test_run_account_push_dry_run(monkeypatch):
    monkeypatch.setattr(feishu, "_conf", lambda: {
        "enabled": True, "app_id": "x", "app_secret": "y", "chat_id": "oc_old",
        "digest_models": [], "min_items": 2, "watch": {},
        "account_push": {"enabled": True, "interval_h": 2, "window_h": 2,
                         "chat_id": "oc_new", "top_total": 4,
                         "accounts": [{"name": "Owen聊投资", "owner": "Owen",
                                       "mix": {"美股": 60, "加密": 20,
                                               "AI与科技": 20}}]}})
    monkeypatch.setattr(feishu, "_store", type("S", (), {"_connect": staticmethod(_FakeConn)})())
    monkeypatch.setattr(feishu, "_author_topics",
                        lambda: {"crypto_kol": {"加密"}, "uw": {"美股"}})
    monkeypatch.setattr(feishu, "_enrich_stats",
                        lambda items, max_handles=40: [it.update(views=1000) for it in items])
    rep = feishu.run_account_push(dry_run=True)
    assert rep.get("items") == 2 and rep.get("classified") == 2   # u1重复(url同)去重后2条
    assert len(rep["preview"]) == 1
    card = rep["preview"][0]
    assert "oc_new" not in card                                   # 卡片不含chat_id
    # u1 的 L1=半导体→AI与科技(条目投影优先于作者美股继承), 窗口内无美股素材 → 无美股节
    assert "「Owen聊投资」" in card and "▍加密" in card and "▍AI与科技" in card
    assert "▍美股" not in card


def test_run_account_push_throttle_gate(monkeypatch):
    conf = {"enabled": True, "app_id": "x", "app_secret": "y", "chat_id": "oc",
            "account_push": {"enabled": True, "interval_h": 2,
                             "accounts": [{"name": "N", "owner": "O",
                                           "mix": {"美股": 100}}]}}
    monkeypatch.setattr(feishu, "_conf", lambda: conf)
    monkeypatch.setattr(feishu, "_load_state",
                        lambda name: {"last_ts": time.time()} if name == feishu._PUSH_STATE else {})
    rep = feishu.run_account_push()                               # 刚推过 → 静默
    assert "skipped" in rep and "不足" in rep["skipped"]
