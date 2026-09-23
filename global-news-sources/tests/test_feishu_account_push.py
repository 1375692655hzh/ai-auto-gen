"""账号成分推送回归(2026-09-21/22): 9类投影/作者继承/配额/组卡/节流/
观点优先/浏览增速排序/兜底翻译/私发路由。

裸克隆可跑(离线全 mock, 不实抓不发群):
  python -m pytest global-news-sources/tests/test_feishu_account_push.py -q
"""

import datetime as _dt
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
    at = {"uw": {"美股"}}
    tp = feishu._item_topics("[]", '["美国"]', "uw", at,
                             "BREAKING: Bitcoin rises above $84,000")
    assert tp == {"美股", "加密"}
    tp2 = feishu._item_topics('["宏观与政策>货币政策"]', "[]", "a", {},
                              "ETH ETF inflows surge")
    assert tp2 == {"宏观与政策", "加密"}
    assert feishu._item_topics("[]", "[]", "uw", at, "NVDA earnings beat") == {"美股"}


# ── 2. 作者继承: 池 tags 映射 + 投教信号 ────────────────────────────────────
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


def test_split_quota_largest_remainder_direction():
    q = feishu._split_quota({"美股": 50, "AI与科技": 15, "产业链与制造": 15, "宏观与政策": 20}, 10)
    assert q == {"美股": 5, "AI与科技": 2, "产业链与制造": 1, "宏观与政策": 2}
    q2 = feishu._split_quota({"美股": 50, "亚太股市": 10, "AI与科技": 10,
                              "宏观与政策": 10, "投教科普": 10}, 10)
    assert q2["美股"] == 6 and sum(q2.values()) == 10


# ── 4. 选卡: 观点优先/增速降序/条目单次出现/配额 ─────────────────────────────
def _mk(handle, topics, views, url, *, age_h=1.0, role="", itype="", text=None, zh=""):
    t = (_dt.datetime.now() - _dt.timedelta(hours=age_h)).strftime("%Y-%m-%d %H:%M")
    return {"author_handle": handle, "topics": set(topics), "views": views,
            "likes": 0, "text": text or f"post-{handle}-{views}", "text_zh": zh,
            "url": url, "time": t, "author_role": role, "item_type": itype}


def test_pick_orders_and_dedup():
    items = [_mk("a", {"美股"}, 900, "u1"), _mk("b", {"美股"}, 12000, "u2"),
             _mk("c", {"美股", "AI与科技"}, 500, "u3")]
    per = feishu._pick_for_account(items, {"mix": {"美股": 70, "AI与科技": 30}}, 3)
    assert [i["url"] for i in per["美股"]] == ["u2", "u1"]      # 同龄=views序
    assert per["AI与科技"][0]["url"] == "u3"                     # 单次出现


def test_pick_opinion_first_then_rate():
    items = [_mk("kol1", {"美股"}, 500, "u1", role="kol", age_h=1.0),        # 观点 500/时
             _mk("media1", {"美股"}, 50000, "u2", role="media", age_h=1.0),   # 资讯 5万/时
             _mk("kol2", {"美股"}, 800, "u3", role="trader", age_h=2.0),      # 观点 400/时
             _mk("media2", {"美股"}, 3000, "u4", role="data_bot", age_h=3.0)]  # 资讯 1千/时
    per = feishu._pick_for_account(items, {"mix": {"美股": 100}}, 4)
    assert [i["url"] for i in per["美股"]] == ["u1", "u3", "u2", "u4"]
    # 观点层在前(u1>u3), 资讯层在后(u2>u4)——高流量资讯压不过低流量观点


def test_pick_quota_respected():
    items = [_mk(f"h{i}", {"美股"}, 100 - i, f"u{i}") for i in range(8)]
    per = feishu._pick_for_account(items, {"mix": {"美股": 60, "加密": 40}}, 5)
    assert len(per["美股"]) == 3
    assert "加密" not in per


# ── 5. 组卡: @人/成分串/主题序/全文双语/分块 ─────────────────────────────────
def test_compose_push_basic():
    per = {"美股": [_mk("b", {"美股"}, 12000, "u2", zh="比特币突破8.4万"),
                    _mk("a", {"美股"}, 9, "u1")]}
    mix = {"美股": 60, "AI与科技": 40}
    txt = "\n".join(feishu._compose_push(
        {"name": "Owen聊投资", "owner": "Owen"}, per, mix, "09-21 10:00~12:00", 33))
    assert "@Owen 账号「Owen聊投资」" in txt
    assert "美股60% · AI与科技40%" in txt
    assert "▍美股（命中2·取2" in txt and "👁1.2万" in txt
    assert "译: 比特币突破8.4万" in txt and "译: [未译]" in txt
    assert txt.index("u2") < txt.index("u1")


def test_compose_push_full_text_no_truncation():
    long_en = "word " * 400
    per = {"AI与科技": [_mk("x", {"AI与科技"}, 5, "u", text=long_en)]}
    txt = "\n".join(feishu._compose_push(
        {"name": "N", "owner": "O"}, per, {"AI与科技": 100}, "t", 1))
    assert "word word word word" in txt               # 不再截120字


def test_compose_push_real_at_tag():
    per = {"AI与科技": [_mk("x", {"AI与科技"}, 5, "u")]}
    txt = "\n".join(feishu._compose_push(
        {"name": "N", "owner": "张三", "owner_open_id": "ou_abc"}, per, {"AI与科技": 100},
        "t", 1))
    assert '<at user_id="ou_abc"></at>' in txt


def test_compose_push_dm_header():
    per = {"AI与科技": [_mk("x", {"AI与科技"}, 5, "u")]}
    txt = "\n".join(feishu._compose_push(
        {"name": "N", "owner": "张三", "owner_open_id": "ou_abc", "dm": True},
        per, {"AI与科技": 100}, "t", 1))
    assert "<at" not in txt and "张三 你好｜账号「N」" in txt


def test_compose_push_length_guard():
    items = [_mk(f"h{i}", {"美股"}, i, f"u{i}", text="长文内容" * 100) for i in range(60)]
    chunks = feishu._compose_push({"name": "N", "owner": "O"}, {"美股": items},
                                  {"美股": 100}, "t", 200)
    assert len(chunks) > 1                            # 超长自动分块
    assert all(len(c) <= feishu.MAX_TEXT for c in chunks)
    assert "（续）" in chunks[1]


def test_fmt_views():
    assert feishu._fmt_views(12345) == "1.2万"
    assert feishu._fmt_views(10000) == "1万"
    assert feishu._fmt_views(999) == "999"
    assert feishu._fmt_views(None) == ""


# ── 6. 观点信号 / 增速计算 / 兜底翻译 ────────────────────────────────────────
def test_is_opinion_signals():
    assert feishu._is_opinion({"author_role": "kol", "text": "", "item_type": ""})
    assert feishu._is_opinion({"author_role": "", "text": "", "item_type": "分析"})
    assert feishu._is_opinion({"author_role": "media", "item_type": "快讯",
                               "text": "I think this rally is overextended"})
    assert not feishu._is_opinion({"author_role": "media", "item_type": "快讯",
                                   "text": "BREAKING: CPI rises 3%"})


def test_rate_normalizes_by_age():
    now = _dt.datetime.now()
    new = {"views": 1000,
           "time": (now - _dt.timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M")}
    old = {"views": 1000,
           "time": (now - _dt.timedelta(hours=10)).strftime("%Y-%m-%d %H:%M")}
    assert abs(feishu._rate(new, now) - 2000) < 100   # 0.5h±分钟粒度容差
    assert abs(feishu._rate(old, now) - 100) < 5
    assert feishu._rate({"views": None, "time": ""}, now) == 0.0


def test_translate_missing(monkeypatch):
    import requests as _rq

    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": '```json\n["译A", "译B"]\n```'}}]}

    monkeypatch.setattr(_rq, "post", lambda *a, **k: _R())
    conf = {"digest_models": [{"base_url": "http://x/v1", "api_key": "k", "model": "m"}]}
    items = [{"text": "A", "text_zh": ""}, {"text": "B", "text_zh": None}]
    n = feishu._translate_missing(conf, items)
    assert n == 2 and items[0]["text_zh"] == "译A" and items[1]["text_zh"] == "译B"


# ── 6b. doc 模式(飞书电子表格披露, 2026-09-23) ───────────────────────────────
def test_doc_sheet_title_format():
    import datetime as _dt
    t = _dt.datetime(2026, 9, 23, 9, 30)
    assert feishu._doc_sheet_title(t) == "2026-9-23-9:30"        # 用户命名格式


def test_doc_rows_layout():
    its = [_mk("kol", {"美股"}, 12000, "u1", role="kol", zh="译好",
               age_h=2.0), _mk("m", {"美股"}, 6000, "u2", role="media", age_h=2.0)]
    ordered = feishu._doc_order_all(its, {"美股": 100})
    rows = feishu._doc_rows({"name": "Owenwin888", "owner": "黄正汉"},
                            {"美股": 100}, ordered, "09-23 07:30~09:30", 2)
    assert rows[0][0].startswith("账号: Owenwin888") and rows[0][1] == "所属人: 黄正汉"
    assert rows[1] == feishu._DOC_COLS
    assert rows[2][0] == "美股" and rows[2][1] == "观点" and rows[2][3] == 12000
    assert abs(rows[2][4] - 6000) < 100                          # 增速=12000/2h±分钟粒度
    assert rows[2][5].endswith("P0") or "·P" in rows[2][5]      # 金融价值 "xx·Pn"
    assert isinstance(rows[2][6], int) and 0 <= rows[2][6] <= 10   # 人设匹配 0-10
    assert rows[2][7] == "译好" and rows[2][9] == "u1"
    assert rows[3][1] == "资讯"                                    # 观点行在资讯行前


def test_doc_order_all_no_quota():
    items = [_mk(f"h{i}", {"美股"}, 100 - i, f"u{i}") for i in range(20)]
    ordered = feishu._doc_order_all(items, {"美股": 60, "加密": 40})
    assert len(ordered[0][1]) == 20                                # 全量命中, 不限额
    assert ordered[0][0] == "美股"                                 # mix 降序
    assert all(not ordered[1][1] for _ in [0]) or ordered[1][1] == []  # 加密无命中为空


def test_ensure_doc_creates_once(monkeypatch):
    calls = []

    def fake_post(url, payload, token="", timeout=20):
        calls.append(url)
        if "sheets/v3/spreadsheets" in url:
            return {"code": 0, "data": {"spreadsheet": {
                "spreadsheet_token": "stkn", "url": "https://x.feishu.cn/sheets/stkn"}}}
        if "permissions" in url:
            return {"code": 0}
        return {"code": 0}

    monkeypatch.setattr(feishu, "_post", fake_post)
    monkeypatch.setattr(feishu, "_token", lambda c: "tk")
    st = {}
    t1, u1 = feishu._ensure_doc({"app_id": "a"}, {"name": "N"},
                                {"chat_id": "oc_g"}, st)
    assert t1 == "stkn" and "stkn" in u1 and len(calls) == 2       # 建表+群授权
    t2, _ = feishu._ensure_doc({"app_id": "a"}, {"name": "N"}, {"chat_id": "oc_g"}, st)
    assert t2 == "stkn" and len(calls) == 2                        # 二次走缓存零调用


# ── 7. run_account_push 集成(dry-run 全链 mock) ──────────────────────────────
class _FakeConn:
    def execute(self, sql, params):
        class _R:
            def fetchall(inner):
                return [
                    ("src_twitter_a", "2026-09-22 10:00", "NVDA earnings beat", "",
                     "u1", "UW", '["半导体>代工"]', '["美国"]', "快讯", "analyst",
                     '["NVDA"]', "earnings", 2, "机构"),
                    ("src_twitter_b", "2026-09-22 10:30", "BTC breakout", "",
                     "u2", "crypto_kol", '[]', '["全球"]', "快讯", "media",
                     '[]', "", 1, "大V"),
                    ("src_twitter_a", "2026-09-22 11:00", "dup of u1", "",
                     "u1", "UW", '["半导体>代工"]', '["美国"]', "快讯", "analyst",
                     '["NVDA"]', "earnings", 2, "机构"),
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
    monkeypatch.setattr(feishu, "_store",
                        type("S", (), {"_connect": staticmethod(_FakeConn)})())
    monkeypatch.setattr(feishu, "_author_topics",
                        lambda: {"crypto_kol": {"加密"}, "uw": {"美股"}})
    monkeypatch.setattr(feishu, "_enrich_stats",
                        lambda items, max_handles=40: [it.update(views=1000) for it in items])
    monkeypatch.setattr(feishu, "_translate_missing", lambda conf, items, cap=12: 0)
    rep = feishu.run_account_push(dry_run=True)
    assert rep.get("items") == 2 and rep.get("classified") == 2
    assert rep.get("translated") == 0
    card = "\n".join(rep["preview"])
    assert "oc_new" not in card
    # u1 的 L1=半导体→AI与科技(条目投影优先于作者美股继承), 窗口内无美股素材 → 无美股节
    assert "「Owen聊投资」" in card and "▍加密" in card and "▍AI与科技" in card
    assert "▍美股" not in card
    assert "【观点】" in card and "【资讯】" in card     # u1=analyst观点, u2=media资讯


def test_run_account_push_throttle_gate(monkeypatch):
    conf = {"enabled": True, "app_id": "x", "app_secret": "y", "chat_id": "oc",
            "account_push": {"enabled": True, "interval_h": 2,
                             "accounts": [{"name": "N", "owner": "O",
                                           "mix": {"美股": 100}}]}}
    monkeypatch.setattr(feishu, "_conf", lambda: conf)
    monkeypatch.setattr(feishu, "_load_state",
                        lambda name: ({"last_ts": time.time()}
                                      if name == feishu._PUSH_STATE else {}))
    rep = feishu.run_account_push()                     # 刚推过 → 静默
    assert "skipped" in rep and "不足" in rep["skipped"]


# ── 8. send_text 接收路由(群/私发) ───────────────────────────────────────────
def test_send_text_receive_routing(monkeypatch):
    calls = []

    def fake_post(url, payload, token="", timeout=20):
        calls.append((url, payload))
        return {"code": 0}

    monkeypatch.setattr(feishu, "_post", fake_post)
    monkeypatch.setattr(feishu, "_token", lambda c: "tk")
    conf = {"enabled": True, "app_id": "a", "app_secret": "s", "chat_id": "oc_g"}
    assert feishu.send_text(conf, "hi")[0]              # 缺省群发
    assert "receive_id_type=chat_id" in calls[-1][0] and calls[-1][1]["receive_id"] == "oc_g"
    assert feishu.send_text(conf, "hi", {"type": "open_id", "id": "ou_x"})[0]
    assert "receive_id_type=open_id" in calls[-1][0] and calls[-1][1]["receive_id"] == "ou_x"
    monkeypatch.setattr(feishu, "_post",
                        lambda u, p, token="", timeout=20: {"code": 230002, "msg": "not visible"})
    ok, err = feishu.send_text(conf, "hi", {"type": "open_id", "id": "ou_x"})
    assert not ok and "可用范围" in err


def test_fv_and_persona_score():
    import datetime as _dt
    now = _dt.datetime(2026, 9, 23, 15, 0)
    # FV: 官方源宏观事件 + T1词典 → 保底 P0 (硬规则 ev>=24 & src>=15)
    it = {"text_zh": "美联储FOMC决议维持利率不变, 台积电CoWoS产能吃紧", "text": "",
          "tickers": '["NVDA"]', "event_type": "macro", "dup_count": 5,
          "positioning": "官方", "markets": '["美国", "全球"]', "sectors": "[]",
          "time": "2026-09-23 14:00"}
    assert "P0" in feishu._fv_item_score(it, now)
    # FV: 无名低值 → 硬规则封顶 40 (P2 下)
    it2 = {"text_zh": "今天天气不错", "tickers": "[]", "event_type": "",
           "dup_count": 1, "positioning": "", "markets": "[]", "sectors": "[]",
           "time": "2026-09-23 14:00"}
    assert int(feishu._fv_item_score(it2, now).split("·")[0]) <= 40
    mix = {"美股": 60, "AI与科技": 30, "亚太股市": 10}
    assert feishu._persona_score("美股标普500大涨, 英伟达财报超预期", mix) >= 5
    assert feishu._persona_score("日本牙科激光疗法新潮流", mix) == 0
    assert feishu._persona_score("Nasdaq falls as Fed officials speak", mix) >= 4  # 英文小写兜底
