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


def test_classify_freetier_keyword():
    # 无状态码时 free-tier 文案归 ua_freetier; 包着 429 的必须归 429(冷却依据)
    assert g.classify(status=429, body="FreeTier daily limit") == "429_free"
    assert g.classify(status=400, body="FreeTier daily limit") == "ua_freetier"


def test_classify_requests_http_error():
    # requests.HTTPError 的状态码挂在 response.status_code 上
    class FakeResp:
        status_code = 429
    class FakeHTTPError(Exception):
        response = FakeResp()
    assert g.classify(exc=FakeHTTPError("boom")) == "429_free"


def test_classify_unreachable_and_429_body_masking():
    # 桥/连接不可达单独归类(算硬失败, 防死桥永排链首)
    class ConnError(Exception):
        pass
    ConnError.__name__ = "ConnectionError"
    assert g.classify(exc=ConnError("refused")) == "unreachable"
    # 500 正文里出现 "429" 字样不能误归配额类(如 retry after 429s)
    assert g.classify(status=502, body="bad gateway, retry after 429s") == "500_upstream"


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


def test_is_bridge_normalizes_localhost(_isolate):
    """urlparse 归一: localhost/::1/尾斜杠/大小写都不能漏判(漏判=双计+池键分裂)。"""
    assert g.is_bridge("http://localhost:20133/v1")
    assert g.is_bridge("http://LOCALHOST:20134/v1/")
    assert g.node_of("http://localhost:20135/v1") == "hk2"
    assert not g.is_bridge("http://127.0.0.1:201333/v1")   # 端口必须精确命中
    assert not g.is_bridge("http://example.com:20133/v1")  # 非本机host不命中


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
    """429 = 单池(节点|前缀)配额槽冷却, 同节点别的模型不受影响。"""
    now = time.time()
    for _ in range(3):
        g.record(logger="caller", node="hk", model="oc/big-pickle", ok=False,
                 ecls="429_free")
    st = json.loads((_isolate / "state.json").read_text(encoding="utf-8"))
    pq = st["pool_quota"]
    assert "hk|bi" in pq
    assert "hk|mi" not in pq
    assert "hk" not in st["ip_break"]        # 429 不冷整 IP
    assert not st.get("pool_health")          # 429 不进健康槽
    assert pq["hk|bi"]["until"] > now


def test_500_single_prefix_only_cools_pool(_isolate):
    """grok#3/astra#6 回归: 单前缀零成功连击只冷池——别的前缀只是这 15 分钟
    没被点到≠死了; 单前缀场景一律不冷整 IP。"""
    for _ in range(3):
        g.record(logger="bridge", node="jp", model="oc/mimo-v2.5-free", ok=False,
                 ecls="500_upstream")
    st = json.loads((_isolate / "state.json").read_text(encoding="utf-8"))
    assert "jp|mi" in st["pool_health"]
    assert "jp" not in st["ip_break"]


def test_500_two_prefixes_zero_ok_trips_ip_break(_isolate):
    """硬失败跨 ≥2 前缀且零成功 → 整 IP(节点)熔断, 两个免费模型一起停。"""
    now = time.time()
    for _ in range(3):
        g.record(logger="bridge", node="jp", model="oc/mimo-v2.5-free", ok=False,
                 ecls="500_upstream")
        g.record(logger="bridge", node="jp", model="oc/big-pickle", ok=False,
                 ecls="500_upstream")
    st = json.loads((_isolate / "state.json").read_text(encoding="utf-8"))
    assert "jp" in st["ip_break"]
    assert st["ip_break"]["jp"]["until"] > now


def test_model_level_500_only_cools_pool(_isolate):
    """09-24 实测回归: mimo 在 hk 连死 3 次但 big-pickle 同节点仍活
    → 只冷 mi 单池, 绝不能 IP 熔断(否则白白扔掉还能用的 bi)。"""
    g.record(logger="caller", node="hk", model="oc/big-pickle", ok=True)
    for _ in range(3):
        g.record(logger="caller", node="hk", model="oc/mimo-v2.5-free", ok=False,
                 ecls="500_upstream")
    st = json.loads((_isolate / "state.json").read_text(encoding="utf-8"))
    assert "hk" not in st["ip_break"]
    assert "hk|mi" in st["pool_health"]


def test_failrate_window_trips_ip_break(_isolate, monkeypatch):
    """窗内 ≥5 次、零成功、硬失败率≥30% 且跨≥2前缀 → IP 熔断(全灭才冷节点)。"""
    monkeypatch.setitem(g.DEFAULTS, "win_min_calls", 5)
    monkeypatch.setitem(g.DEFAULTS, "win_fail_rate", 0.3)
    for i in range(6):
        g.record(logger="caller", node="hk2",
                 model="oc/big-pickle" if i % 2 else "oc/mimo-v2.5-free",
                 ok=False, ecls="500_upstream")
    st = json.loads((_isolate / "state.json").read_text(encoding="utf-8"))
    assert "hk2" in st["ip_break"]


def test_soft_fails_with_successes_no_break(_isolate):
    """有成功前缀时软错误再高也不熔断——降级交给 order_chain 预算排序(failrate 降权)。"""
    for i in range(6):
        g.record(logger="caller", node="hk", model="oc/big-pickle",
                 ok=(i % 2 == 0), ecls="other" if i % 2 else "ok")
    st = json.loads((_isolate / "state.json").read_text(encoding="utf-8"))
    assert "hk" not in st["ip_break"]
    assert not st["pool_quota"] and not st["pool_health"]


# ---------- order_chain ----------

def _m(node_port, model):
    return {"base_url": f"http://127.0.0.1:{node_port}/v1", "model": model,
            "api_key": "k"}


def test_order_chain_disabled_passes_through(monkeypatch):
    monkeypatch.setitem(g.DEFAULTS, "enabled", False)
    chain = [_m(20133, "oc/big-pickle"), {"base_url": "https://api.minimax.chat/v1",
                                          "model": "MiniMax-Text-01"}]
    assert g.order_chain(chain) == chain


def test_order_chain_minimax_always_tail(_isolate):
    chain = [{"base_url": "https://api.minimax.chat/v1", "model": "MiniMax-Text-01"},
             _m(20134, "oc/big-pickle"), _m(20133, "oc/mimo-v2.5-free")]
    g.record(logger="caller", node="hk", model="oc/big-pickle", ok=True)  # 账本非空
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
    assert "配额熔断" in rep and "hk/bi" in rep   # 429 → 配额槽冷到事件日UTC翻篇


def test_usage_report_pool_break_shown(_isolate):
    g.record(logger="caller", node="hk", model="oc/big-pickle", ok=False,
             ecls="429_free")
    rep = g.usage_report(days=1)
    assert "配额熔断" in rep and "hk/bi" in rep


def test_429_cools_to_utc_flip(_isolate):
    """429 冷却到下一个 UTC 翻篇点(不是滑动窗续期), 省每小时空转探测。"""
    now = time.time()
    g.record(logger="caller", node="hk", model="oc/big-pickle", ok=False,
             ecls="429_free")
    st = json.loads((_isolate / "state.json").read_text(encoding="utf-8"))
    info = st["pool_quota"]["hk|bi"]
    assert "翻篇" in info["reason"]
    assert info["until"] > now          # 未来时刻即可(近翻篇点可能 <1h, 不锁死下界)


def test_429_pin_event_day_flip_not_next_day(_isolate, monkeypatch):
    """astra#4=grok#2 回归: 午夜前的 429 在午夜后重算, until 必须钉死
    **事件自己所在日**的翻篇点, 绝不能再续 24h(新的一天白丢)。
    fake clock: 事件 T0=午夜前30s, 重评估 T1=午夜后90s(窗口900s内)。"""
    # _utc_flip_ts 含 +60s 缓冲: 先取"上一个翻篇点"=真实午夜+60
    flip_prev = g._utc_flip_ts(time.time()) - 86400
    t0_ev, t1_re = flip_prev - 90, flip_prev + 30   # 事件在真实午夜前30s, 重评估在其后90s
    clock = {"t": t0_ev}
    monkeypatch.setattr(g.time, "time", lambda: clock["t"])
    g.record(logger="caller", node="hk", model="oc/big-pickle", ok=False,
             ecls="429_free", ts=t0_ev)
    clock["t"] = t1_re
    g.record(logger="caller", node="hk2", model="oc/big-pickle", ok=True, ts=t1_re)
    st = json.loads((_isolate / "state.json").read_text(encoding="utf-8"))
    info = st["pool_quota"]["hk|bi"]
    # 旧bug会续到 _utc_flip_ts(T1)=flip_prev+86400; 正确=钉死 flip_prev(已过期仍留档)
    assert info["until"] <= flip_prev + 1


def test_cross_node_model_death_syncs_all_nodes(_isolate):
    """同前缀在 ≥2 zen 节点各自连击≥2 = 模型级死亡: 全部 zen 节点同步冷该前缀,
    不烧"每个节点各探测 3 次"的冤枉钱, 也不误伤还活着的 bi。"""
    for _ in range(2):
        g.record(logger="caller", node="hk", model="oc/mimo-v2.5-free", ok=False,
                 ecls="500_upstream")
    for _ in range(2):
        g.record(logger="caller", node="hk2", model="oc/mimo-v2.5-free", ok=False,
                 ecls="500_upstream")
    g.record(logger="caller", node="hk", model="oc/big-pickle", ok=True)
    st = json.loads((_isolate / "state.json").read_text(encoding="utf-8"))
    for node in ("jp", "hk", "hk2"):     # 同步冷却, 含尚无人探测的 jp
        assert f"{node}|mi" in st["pool_health"]
    assert "hk" not in st["ip_break"]    # bi 活着, 不误冷节点
    assert "hk2" not in st["ip_break"]


def test_minimax_does_not_cross_contaminate(_isolate):
    """高危回归: MiniMax-M3 剥前缀也是 'mi', 它的失败绝不连坐 zen mi 池。"""
    for _ in range(3):
        g.record(logger="caller", node="minimax", model="MiniMax-M3", ok=False,
                 ecls="timeout")
    for _ in range(2):
        g.record(logger="caller", node="hk", model="oc/mimo-v2.5-free", ok=False,
                 ecls="500_upstream")
    st = json.loads((_isolate / "state.json").read_text(encoding="utf-8"))
    assert "mi" not in st["ip_break"]
    # hk 连击2<3 不冷; 两槽都必须空(更无连坐)
    assert not st["pool_health"] and not st["pool_quota"]


def test_single_1plus1_not_model_dead(_isolate):
    """两节点各 1 次硬失败(可能仅两 IP 同时抖)不够判模型级, 也不冷池(连击<3)。"""
    g.record(logger="caller", node="hk", model="oc/mimo-v2.5-free", ok=False,
             ecls="500_upstream")
    g.record(logger="caller", node="hk2", model="oc/mimo-v2.5-free", ok=False,
             ecls="500_upstream")
    st = json.loads((_isolate / "state.json").read_text(encoding="utf-8"))
    assert not st["pool_quota"] and not st["pool_health"]
    assert not st["ip_break"]


def test_pending_replay_on_lock_miss(_isolate, monkeypatch):
    """抢不到文件锁: 明细进 pending 队列, 下轮抢到锁补聚合, 零丢失。"""
    import contextlib
    seq = [False, True]
    state = {"i": 0}

    @contextlib.contextmanager
    def fake_lock(wait: float = 2.0):
        yield seq[state["i"]] if state["i"] < len(seq) else True
        state["i"] += 1

    monkeypatch.setattr(g, "_state_file_lock", fake_lock)
    g.record(logger="caller", node="hk", model="oc/big-pickle", ok=True)
    st = g._load_state()
    assert not st.get("pools")                    # 首轮被跳过(state.json 可能尚不存在)
    assert (_isolate / "pending.jsonl").exists()  # 进待补队列
    g.record(logger="caller", node="hk", model="oc/big-pickle", ok=True)
    st = g._load_state()
    day = g._utc_day()
    assert st["pools"][f"hk|bi|{day}"]["n"] == 2    # 两条都补上(含pending重放)
    assert not (_isolate / "pending.jsonl").exists()


def test_order_chain_hysteresis(_isolate):
    """可用集合不变时沿用上轮链序: 防"每轮重排→逐节点倾泻到软顶"抖动。"""
    chain = [_m(20134, "oc/big-pickle"), _m(20135, "oc/big-pickle"),
             _m(20133, "oc/big-pickle"),
             {"base_url": "https://api.minimax.chat/v1", "model": "MiniMax-Text-01"}]
    g.record(logger="caller", node="jp", model="oc/big-pickle", ok=True)  # 账本非空
    first = g.order_chain(chain)
    assert [g.node_of(m["base_url"]) for m in first][:3] == ["hk", "hk2", "jp"]
    # hk 用量涨到 3, 若无滞回重排会把 hk 沉到链尾
    for _ in range(2):
        g.record(logger="caller", node="hk", model="oc/big-pickle", ok=True)
    second = g.order_chain(chain)
    assert [g.node_of(m["base_url"]) for m in second][:3] == ["hk", "hk2", "jp"]


def test_order_chain_hysteresis_drops_on_set_change(_isolate):
    """可用集合变了(熔断)必须重排, 滞回不能让死节点赖在链里。"""
    chain = [_m(20134, "oc/big-pickle"), _m(20135, "oc/big-pickle"),
             _m(20133, "oc/big-pickle")]
    g.order_chain(chain)
    for _ in range(3):
        g.record(logger="caller", node="hk2", model="oc/big-pickle", ok=False,
                 ecls="500_upstream")
    out = g.order_chain(chain)
    assert [g.node_of(m["base_url"]) for m in out] == ["hk", "jp"]


def test_order_chain_empty_state_keeps_config_order(_isolate):
    """astra#8 回归: 空账本(读不到可信 state)保配置原序返回, 且绝不写滞回槽——
    否则"全员可用"的空账顺序被钉住, 真熔断来了也不重排。"""
    chain = [_m(20135, "oc/big-pickle"), _m(20133, "oc/big-pickle"),
             _m(20134, "oc/big-pickle")]
    out = g.order_chain(chain)
    assert [g.node_of(m["base_url"]) for m in out] == ["hk2", "jp", "hk"]
    # 空账本路径根本不写 state.json; 即便有文件也不许留滞回槽
    st_path = _isolate / "state.json"
    st = json.loads(st_path.read_text(encoding="utf-8")) if st_path.exists() else {}
    assert not any(k.startswith("chain_order:") for k in st)


# ---------- admit(轮内准入) ----------

def test_admit_blocks_cooled_pool_and_ip(_isolate):
    """astra#1: 429 冷池后 admit 拒同池请求; 健康冷池/软顶到顶同样拒; 别池放行。"""
    base_bi, base_mi = "http://127.0.0.1:20134/v1", "http://127.0.0.1:20134/v1"
    g.record(logger="caller", node="hk", model="oc/big-pickle", ok=False,
             ecls="429_free")
    assert not g.admit(base_bi, "oc/big-pickle")        # 配额槽冷
    assert g.admit(base_mi, "oc/mimo-v2.5-free")        # 同节点别池不受影响
    for _ in range(3):
        g.record(logger="caller", node="hk2", model="oc/mimo-v2.5-free", ok=False,
                 ecls="500_upstream")
    assert not g.admit("http://127.0.0.1:20135/v1", "oc/mimo-v2.5-free")  # 健康槽冷


def test_admit_non_bridge_and_exception_always_true(_isolate, monkeypatch):
    """非 zen( MiniMax 兜底)恒准入; 账本读炸也恒准入——统计永不许卡翻译。"""
    assert g.admit("https://api.minimax.chat/v1", "MiniMax-M3")
    monkeypatch.setattr(g, "_load_state", lambda: (_ for _ in ()).throw(IOError("x")))
    assert g.admit("http://127.0.0.1:20133/v1", "oc/big-pickle")


# ---------- count_n 质量记录(批D) ----------

def test_count_n_false_quality_record(_isolate):
    """badjson 质量记录: 只加 fail 不加 n(与桥的 ok 合成 failrate≈1.0 拉下链首),
    lat/tok 也不动; eid 去重防重放双计。"""
    day = g._utc_day()
    g.record(logger="bridge", node="hk", model="oc/big-pickle", ok=True,
             latency_ms=100, tokens={"prompt": 10, "completion": 5, "total": 15})
    g.record(logger="caller", node="hk", model="oc/big-pickle", ok=False,
             ecls="badjson", count_n=False)
    st = json.loads((_isolate / "state.json").read_text(encoding="utf-8"))
    pd = st["pools"][f"hk|bi|{day}"]
    assert pd["n"] == 1 and pd["fail"] == 1 and pd["ok"] == 1
    nd = st["nodes"][f"hk|{day}"]
    assert nd["n"] == 1                      # 节点总量也不被质量记录放大
