"""chain_guard 单测: 错误分类 / record+聚合 / 429只冷单池 vs 500冷整IP / order_chain预算排序。"""
import json
import time

import pytest

from sources import chain_guard as g


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """每测独立 zen-usage 目录 + 独立 state(防测试间互相污染)。"""
    monkeypatch.setattr(g, "usage_dir", lambda: tmp_path)
    monkeypatch.setattr(g, "_state_path", lambda: tmp_path / "state.json")
    monkeypatch.setattr(g, "_LOCK", __import__("threading").Lock())
    (tmp_path / f"{g._utc_day()}.jsonl").touch()
    return tmp_path


# ---------- classify ----------

def test_classify_ok():
    assert g.classify() == "ok"
    assert g.classify(status=200) == "other"   # 有状态码就按状态码判, 200 也算 other


def test_classify_429():
    assert g.classify(status=429) == "429_free"
    assert g.classify(body='{"error":"429 too many"}') == "429_free"


def test_classify_500_and_timeout():
    assert g.classify(status=500) == "500_upstream"
    assert g.classify(body="upstream_http_500") == "500_upstream"
    assert g.classify(body="UnknownError: boom") == "500_upstream"

    class FakeTimeout(Exception):
        pass

    FakeTimeout.__name__ = "ReadTimeoutError"
    assert g.classify(exc=FakeTimeout("timed out")) == "timeout"


def test_classify_freetier_keyword_first():
    # FreeTier 关键字优先于状态码
    assert g.classify(status=429, body="FreeTier daily limit") == "ua_freetier"


def test_classify_other():
    assert g.classify(status=403) == "other"


# ---------- 工具函数 ----------

def test_is_bridge_and_node_of():
    assert g.is_bridge("http://127.0.0.1:20133/v1")
    assert g.is_bridge("http://127.0.0.1:20135/v1")
    assert not g.is_bridge("https://api.minimax.chat/v1")
    assert g.node_of("http://127.0.0.1:20133/v1") == "jp"
    assert g.node_of("http://127.0.0.1:20134/v1") == "hk"
    assert g.node_of("http://127.0.0.1:20135/v1") == "hk2"
    assert g.node_of("https://api.minimax.chat/v1") == "minimax"
    assert g.node_of("https://example.com/v1") == "direct"


def test_model_prefix():
    assert g.model_prefix("oc/big-pickle") == "bi"
    assert g.model_prefix("oc/mimo-v2.5-free") == "mi"
    assert g.model_prefix("MiniMax-Text-01") == "mi"
    assert g.model_prefix("") == "??"


# ---------- record + state ----------

def test_record_writes_jsonl_and_state(_isolate):
    g.record(logger="bridge", node="hk", model="oc/big-pickle", ok=True,
             latency_ms=120, egress_ip="1.2.3.4",
             tokens={"prompt": 100, "completion": 50, "total": 150, "cache_read": 30})
    day = g._utc_day()
    lines = [json.loads(x) for x in
             (_isolate / f"{day}.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1
    r = lines[0]
    assert r["node"] == "hk" and r["ok"] and r["prefix"] == "bi"
    assert r["pool_key"] == f"{day}|1.2.3.4|bi"
    assert r["prompt"] == 100 and r["cache_read"] == 30
    st = json.loads((_isolate / "state.json").read_text(encoding="utf-8"))
    nd = st["nodes"][f"hk|{day}"]
    assert nd["n"] == 1 and nd["ok"] == 1 and nd["tok"] == 150


def test_record_never_raises(_isolate):
    # 统计永远不许炸翻译: 传垃圾也不抛
    g.record(logger="x", node=None, model=123, ok="yes", tokens="garbage")


def test_429_only_cools_single_pool(_isolate, monkeypatch):
    """429 = 单池(节点|前缀)冷却, 同节点别的模型不受影响。"""
    now = time.time()
    for _ in range(3):
        g.record(logger="caller", node="hk", model="oc/big-pickle", ok=False,
                 ecls="429_free")
    st = json.loads((_isolate / "state.json").read_text(encoding="utf-8"))
    pb = st["pool_break"]
    assert "hk|bi" in pb
    assert "hk|mi" not in pb
    assert "hk" not in st["ip_break"]        # 429 不冷整 IP
    assert pb["hk|bi"]["until"] > now


def test_500_cools_whole_ip(_isolate, monkeypatch):
    """连续 3 次 500/timeout → 整 IP(节点)熔断, 两免费模型一起停。"""
    now = time.time()
    for _ in range(3):
        g.record(logger="bridge", node="jp", model="oc/mimo-v2.5-free", ok=False,
                 ecls="500_upstream")
    st = json.loads((_isolate / "state.json").read_text(encoding="utf-8"))
    assert "jp" in st["ip_break"]
    assert st["ip_break"]["jp"]["until"] > now


def test_failrate_window_trips_ip_break(_isolate, monkeypatch):
    """15min 窗内 failrate≥30% 且≥5 次 → IP 熔断。"""
    monkeypatch.setitem(g.DEFAULTS, "win_min_calls", 5)
    monkeypatch.setitem(g.DEFAULTS, "win_fail_rate", 0.3)
    for i in range(6):
        g.record(logger="caller", node="hk2", model="oc/big-pickle",
                 ok=(i < 3), ecls="other" if i >= 3 else "ok")
    st = json.loads((_isolate / "state.json").read_text(encoding="utf-8"))
    assert "hk2" in st["ip_break"]


# ---------- order_chain ----------

def _m(node_port, model):
    return {"base_url": f"http://127.0.0.1:{node_port}/v1", "model": model,
            "api_key": "k"}


def test_order_chain_disabled_passes_through(monkeypatch):
    monkeypatch.setitem(g.DEFAULTS, "enabled", False)
    chain = [_m(20133, "oc/big-pickle"), {"base_url": "https://api.minimax.chat/v1",
                                          "model": "MiniMax-Text-01"}]
    assert g.order_chain(chain) == chain


def test_order_chain_minimax_always_tail():
    chain = [{"base_url": "https://api.minimax.chat/v1", "model": "MiniMax-Text-01"},
             _m(20134, "oc/big-pickle"), _m(20133, "oc/mimo-v2.5-free")]
    out = g.order_chain(chain)
    assert out[-1]["base_url"] == "https://api.minimax.chat/v1"
    assert {m["base_url"] for m in out} == {m["base_url"] for m in chain}


def test_order_chain_drops_broken_and_soft_cap(_isolate, monkeypatch):
    """熔断节点与超日软顶节点被摘除; 剩余按用量排序(用得少的优先)。"""
    monkeypatch.setitem(g.DEFAULTS, "daily_soft_cap", 3)
    day = g._utc_day()
    # hk2 打满软顶 3 次
    for _ in range(3):
        g.record(logger="caller", node="hk2", model="oc/big-pickle", ok=True)
    # jp 触发 IP 熔断
    for _ in range(3):
        g.record(logger="caller", node="jp", model="oc/big-pickle", ok=False,
                 ecls="500_upstream")
    # hk 只用 1 次
    g.record(logger="caller", node="hk", model="oc/big-pickle", ok=True)
    chain = [_m(20133, "oc/big-pickle"), _m(20134, "oc/big-pickle"),
             _m(20135, "oc/big-pickle"),
             {"base_url": "https://api.minimax.chat/v1", "model": "MiniMax-Text-01"}]
    out = g.order_chain(chain)
    assert [g.node_of(m["base_url"]) for m in out] == ["hk", "minimax"]


def test_order_chain_empty_returns_empty():
    assert g.order_chain([]) == []


# ---------- usage_report ----------

def test_usage_report_aggregates(_isolate):
    g.record(logger="bridge", node="hk", model="oc/big-pickle", ok=True,
             latency_ms=100, tokens={"prompt": 10, "completion": 5, "total": 15})
    g.record(logger="bridge", node="hk", model="oc/big-pickle", ok=False,
             ecls="429_free", latency_ms=200)
    g.record(logger="caller", node="minimax", model="MiniMax-Text-01", ok=True,
             latency_ms=900, tokens={"prompt": 50, "completion": 50, "total": 100})
    rep = g.usage_report(days=1)
    assert "节点×模型" in rep and "节点日请求" in rep and "熔断现状" in rep
    assert "hk" in rep and "big-pickle" in rep and "minimax" in rep
    assert "429_free×1" in rep          # 错误分布
    assert "池熔断" in rep and "hk/bi" in rep   # 429 → 单池冷却


def test_usage_report_pool_break_shown(_isolate):
    g.record(logger="caller", node="hk", model="oc/big-pickle", ok=False,
             ecls="429_free")
    rep = g.usage_report(days=1)
    assert "池熔断" in rep and "hk/bi" in rep
