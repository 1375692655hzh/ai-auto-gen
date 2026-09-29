"""feishu_alloc 限量分配引擎单测(MoA 定案 MVP 第一步)。
覆盖终审修订: 事件归并跨档登记/L0只留命中数直通/分簇K限量/owner独占/
备选计入K(grok)/opus行数min(18,供给)/确定性禁random/绝不空表/影子不侵入。"""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sources import feishu_alloc as A


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(A, "_state_path", lambda: tmp_path / "feishu-alloc.json")
    return tmp_path


def _mk_item(url, topics, fv=50, tier=None, ev="", tickers=None, author="a", rate=10):
    tier = tier or ("P0" if fv >= 75 else "P1" if fv >= 60 else "P2" if fv >= 40 else "P3")
    return {"url": url, "text": f"t {url}", "topics": set(topics), "fv_s": f"{fv}·{tier}",
            "fv_tier": tier, "event_type": ev, "tickers": json.dumps(tickers or []),
            "author_handle": author, "_rate": rate, "views": 100, "time": "2026-09-25 10:00:00"}


def _acc(name, owner, mix):
    return {"name": name, "owner": owner, "mix": mix}


US = {"美股": 60, "宏观与政策": 20, "AI与科技": 20}
US2 = {"美股": 55, "宏观与政策": 25, "AI与科技": 20}      # 与 US 余弦>0.7 同簇
CRYPTO = {"加密": 70, "宏观与政策": 30}                    # 与 US 余弦<0.7 跨簇


def test_event_merge_by_ticker_and_url_fallback():
    a = _mk_item("u1", ["美股"], ev="earnings", tickers=["NVDA"])
    b = _mk_item("u2", ["美股"], ev="earnings", tickers=["NVDA", "AMD"])
    c = _mk_item("u3", ["美股"], ev="earnings", tickers=["AAPL"])   # 不同主ticker
    d = _mk_item("u4", ["美股"])                                     # 无键退URL
    evs = A.cluster_events([a, b, c, d])
    keys = [e["key"] for e in evs]
    assert "earnings|NVDA" in keys and len(evs) == 3   # a,b 合并; c 独立; d=url键


def _alloc_main(plan, name):
    """分配层主推(限量分配/直通/持续跟进/大事件/加印), 排除兜底行(grok 裁决:
    兜底行=绝不空表的例外, 不登记不占 K, 不计入独占性断言)。"""
    return [m for m in plan["per_account"][name]["main"]
            if "兜底" not in (m.get("note") or "")]


def test_l0_pass_when_hits_le_2_and_cluster_k_when_more():
    e = _mk_item("u1", ["美股"], fv=80, ev="earnings", tickers=["NVDA"])
    accs = [_acc(f"n{i}", f"o{i}", dict(US)) for i in range(6)]
    plan = A.allocate([e], accs, "s1")
    # 6 个同类号命中 > 2 → 竞争层, P0 K = min(5, ceil(0.2*6)) = 2(兜底行不算分配)
    got = [n for n, v in plan["per_account"].items() if _alloc_main(plan, n)]
    assert len(got) == 2
    # 两个号时直通(换新事件隔离——同事件会被跨档登记接续, v2 正确行为)
    e_b = _mk_item("u9", ["美股"], fv=80, ev="earnings", tickers=["AAPL"])
    accs2 = accs[:2]
    plan2 = A.allocate([e_b], accs2, "s2")
    got2 = [n for n, v in plan2["per_account"].items() if _alloc_main(plan2, n)]
    assert len(got2) == 2 and all("直通" in (m.get("note") or "") for n in got2
                                  for m in plan2["per_account"][n]["main"])


def test_cross_slot_k_accumulates_and_continuity():
    """跨档登记(opus): 同事件次日新帖不重分名额, 已收账号优先接续。"""
    e1 = _mk_item("u1", ["美股"], fv=80, ev="earnings", tickers=["NVDA"])
    accs = [_acc(f"n{i}", f"o{i}", dict(US)) for i in range(6)]
    p1 = A.allocate([e1], accs, "2026-09-25-9")
    first = sorted(n for n, v in p1["per_account"].items() if _alloc_main(p1, n))
    assert len(first) == 2                            # K=2 全天名额(兜底行不算)
    # 次档: 同事件新帖(不同URL同键)
    e2 = _mk_item("u1b", ["美股"], fv=80, ev="earnings", tickers=["NVDA"])
    p2 = A.allocate([e2], accs, "2026-09-25-13")
    got2 = set()
    for n, v in p2["per_account"].items():
        for m in _alloc_main(p2, n):
            got2.add(n)
    assert got2 == set(first)                         # 分配层仍只有这 2 个号
    notes = [m["note"] for n in p2["per_account"] for m in _alloc_main(p2, n)]
    assert any("持续跟进" in x for x in notes)


def test_owner_exclusive():
    e = _mk_item("u1", ["美股"], fv=80, ev="earnings", tickers=["NVDA"])
    accs = [_acc("boss1", "老板", dict(US)), _acc("boss2", "老板", dict(US2)),
            _acc("other", "别人", dict(US))]
    plan = A.allocate([e], accs, "s-owner")
    boss_got = [n for n in ("boss1", "boss2")
                if any(m["key"] == "earnings|NVDA" for m in _alloc_main(plan, n))]
    assert len(boss_got) <= 1                         # 同 owner 分配层只进一个号


def test_owner_dedup_same_slot_two_picks():
    """P1-1 回归(v2 贪心去重): 8 号 2 owner, K=ceil(0.2*8)=2 → 两挑必须异 owner。"""
    e = _mk_item("u1", ["美股"], fv=80, ev="earnings", tickers=["NVDA"])
    accs = ([_acc(f"bossA{i}", "老板A", dict(US)) for i in range(4)]
            + [_acc(f"bossB{i}", "老板B", dict(US2)) for i in range(4)])
    plan = A.allocate([e], accs, "s-ownslot")
    picked = [n for n in plan["per_account"]
              if any(m["note"] == "限量分配" for m in _alloc_main(plan, n))]
    assert len(picked) == 2
    owners = {("老板A" if n.startswith("bossA") else "老板B") for n in picked}
    assert len(owners) == 2


def test_bench_counts_into_k():
    """grok 备选+opus 预留: 15 号 K=3 预留1 → 主推2+备选1=3; 跨档 bench 不再增员。"""
    e = _mk_item("u1", ["美股"], fv=80, ev="earnings", tickers=["NVDA"])
    accs = [_acc(f"n{i}", f"o{i}", dict(US)) for i in range(15)]
    p1 = A.allocate([e], accs, "sb-1")
    st = A._load_state()
    layers = list(st["events"]["earnings|NVDA"]["accounts"].values())
    comp = sum(1 for v in layers if v["layer"] == "comp")
    bench = sum(1 for v in layers if v["layer"] == "bench")
    assert comp == 2 and bench == 1                   # K=3: 预留1给备选
    # 次档: bench 不转正, 总接收不超 K=3
    e2 = _mk_item("u1b", ["美股"], fv=80, ev="earnings", tickers=["NVDA"])
    A.allocate([e2], accs, "sb-2")
    st = A._load_state()
    layers = list(st["events"]["earnings|NVDA"]["accounts"].values())
    budget = sum(1 for v in layers if v["layer"] in ("comp", "bench", "tail"))
    assert budget == 3                                # 主推+备选 ≤ K_day 闭合


def test_quota_is_min_of_cap_and_supply():
    """opus 行数: 主推目标 = min(18, 可用事件数); 不足亮 short。"""
    evs = [_mk_item(f"u{i}", ["美股"], fv=50 + i % 10, ev="product",
                    tickers=[f"T{i}"]) for i in range(5)]
    accs = [_acc("n1", "o1", dict(US))]
    plan = A.allocate(evs, accs, "s-q")
    pa = plan["per_account"]["n1"]
    assert pa["quota"] == 5 and len(pa["main"]) == 5 and not pa["short"]


def test_determinism_same_input_same_output():
    evs = [_mk_item(f"u{i}", ["美股"], fv=50 + i, ev="product", tickers=[f"T{i}"])
           for i in range(12)]
    accs = [_acc(f"n{i}", f"o{i}", dict(US) if i % 2 else dict(US2))
            for i in range(8)]
    p1 = A.allocate(evs, accs, "2026-09-25-9")
    p2 = A.allocate(evs, accs, "2026-09-25-9")        # 同 slot 读快照
    assert p2.get("from_snapshot")
    # 不同 slot 重算也必须同结果(同输入同结果)
    A._save_state({"day": time.strftime("%Y-%m-%d")})
    p3 = A.allocate(evs, accs, "2026-09-25-13")
    A._save_state({"day": time.strftime("%Y-%m-%d")})
    p4 = A.allocate(evs, accs, "2026-09-25-13")
    assert json.dumps(p3["per_account"], sort_keys=True) == \
        json.dumps(p4["per_account"], sort_keys=True)


def test_no_random_in_module_source():
    """禁 random() 纪律: 剥掉 docstring 后源码不得出现 random 调用/导入。"""
    import re
    src = re.sub(r'""".*?"""', "", Path(A.__file__).read_text(encoding="utf-8"), flags=re.S)
    src = re.sub(r"#.*", "", src)
    assert "random" not in src


def test_never_empty_when_supply_exists():
    """绝不空表: 有命中素材的号主推必须非空(K 撑不住也有尾部加印/直通兜底)。"""
    evs = [_mk_item(f"u{i}", ["美股"], fv=30 + i, ev="product", tickers=[f"T{i}"])
           for i in range(6)]
    accs = [_acc(f"n{i}", f"o{i}", dict(US)) for i in range(4)]
    plan = A.allocate(evs, accs, "s-fill")
    for n, v in plan["per_account"].items():
        assert v["main"], f"{n} 空表"


def test_big_event_exemption_distinct_items():
    """大事件: 簇内≥3帖+P97 → 全员覆盖但同簇不同帖, 每档≤1。"""
    its = [_mk_item(f"u{i}", ["宏观与政策"], fv=95, ev="macro", tickers=["FED"])
           for i in range(4)]
    accs = [_acc(f"n{i}", f"o{i}", dict(US)) for i in range(4)]
    plan = A.allocate(its, accs, "s-big")
    reps = set()
    for n, v in plan["per_account"].items():
        assert v["main"], n
        reps.add(v["main"][0]["rep_url"])
    assert len(reps) >= 2                             # 不同号拿不同帖


def test_day_rollover_clears_registry():
    e = _mk_item("u1", ["美股"], fv=80, ev="earnings", tickers=["NVDA"])
    accs = [_acc(f"n{i}", f"o{i}", dict(US)) for i in range(6)]
    A.allocate([e], accs, "d1-9")
    st = A._load_state()
    st["day"] = "2000-01-01"
    A._save_state(st)
    e2 = _mk_item("u1b", ["美股"], fv=80, ev="earnings", tickers=["NVDA"])
    p = A.allocate([e2], accs, "d2-9")
    got = sum(1 for n in p["per_account"] if _alloc_main(p, n))
    assert got == 2                                   # 翻篇后名额重置(兜底行不算)


def test_ghost_registry_name_no_crash_and_blocks_owner():
    """P1-3 回归: 注册表残留已删号名不炸(StopIteration 已修), 其存量 owner 仍拦人。"""
    e = _mk_item("u1", ["美股"], fv=80, ev="earnings", tickers=["NVDA"])
    accs = [_acc(f"n{i}", "老板", dict(US)) for i in range(5)]
    # 注入幽灵: 老板名下旧号 ghost 已拿 comp(模拟早上发过、中午删号)
    st = A._load_state()
    st["day"] = time.strftime("%Y-%m-%d")
    st["events"] = {"earnings|NVDA": {"accounts": {
        "ghost": {"layer": "comp", "owner": "老板"}}}}
    A._save_state(st)
    p = A.allocate([e], accs, "s-ghost")              # 不抛即过
    # 老板(owner)已被幽灵占坑 → 当前 5 个同 owner 号全拿不到分配层(只有兜底)
    allocd = [n for n in p["per_account"] if _alloc_main(p, n)]
    assert allocd == []


def test_state_corruption_isolates_and_raises():
    """P2-4 回归: 状态损坏 → .bad 留证 + StateError 显式失败(禁静默当新一天)。"""
    p = A._state_path()
    p.write_text("{corrupted", encoding="utf-8")
    with pytest.raises(A.StateError):
        A.allocate([_mk_item("u1", ["美股"])], [_acc("n1", "o1", dict(US))], "s-bad")
    assert A._state_path().with_suffix(".bad").exists()
