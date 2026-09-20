"""时间语义回归(2026-09-20 裁决): time=发布时间, 被预告的事件/日历日期只进正文。

背景: 工作台图文页数据面里"本周美股财报前瞻"显示未来日期(如 09-25)——
fetch_earnings_week 曾把被预告的财报事件日期当 time 输出, 数据面 time DESC
排序导致未来条目置顶。三层防线各有测试:
1. 源头: 日历/前瞻类 fetcher 的 time 一律 <= 抓取时刻, 事件时刻在正文里;
2. 兜底: store.query 对 published_at_known=0 且 time 在未来的漏网条目沉底;
3. 存量: items.db 修复语句(known=0 且 time>now → time=fetched_at)幂等有效。

裸克隆可跑: pip install pytest requests 后
  python -m pytest global-news-sources/tests/test_time_semantics.py -q
(无网络: 全部 mock, 不实抓; store 走 GNS_DATA_DIR 指向 pytest 临时目录)
"""

import datetime
import importlib
import sys
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))                 # sources 包(store/_norm_time)
sys.path.insert(0, str(_ROOT / "fetchers"))    # basic/extra fetcher 模块

import basic as fb        # noqa: E402
import extra as fe        # noqa: E402
from sources import store  # noqa: E402

_BJ = datetime.timezone(datetime.timedelta(hours=8))


def _bjnow() -> datetime.datetime:
    return datetime.datetime.now(_BJ)


def _fake_json_resp(payload):
    r = mock.Mock()
    r.raise_for_status = lambda: None
    r.json = lambda: payload
    return r


def _assert_not_future(items: list) -> None:
    """fetcher 输出的 time 是发布时间: 不允许出现晚于当前时刻的值。"""
    now = _bjnow().strftime("%Y-%m-%d %H:%M")
    for it in items:
        assert it["time"] <= now, f"time 出现未来值(事件日期混入发布时间?): {it}"


# ── 1. 源头: fetcher 不再把事件/日历日期当 time ─────────────────────────────

def test_earnings_week_time_is_fetch_time(monkeypatch):
    """核心回归: 本周美股财报前瞻(用户截图元凶)。"""
    rows = [{"symbol": "AAPL", "time": "before open", "epsForecast": "1.5"},
            {"symbol": "MSFT", "time": "after close", "epsForecast": ""}]

    def fake_get(url, **kw):
        return _fake_json_resp({"data": {"rows": rows}})

    monkeypatch.setattr(fb.requests, "get", fake_get)
    monkeypatch.setattr(fb.time, "sleep", lambda s: None)   # 跳过 0.5s 节流
    out = fb.fetch_earnings_week(max_days=3)
    assert len(out) == 3
    _assert_not_future(out)
    # 事件日期语义保留在正文("周X美股财报"), 不丢信息
    assert all("美股财报" in it["text"] and it["text"].startswith("周") for it in out)
    # 同一轮抓取的条目 time 一致(同一发布批次), dedup 键基于 text 不受影响
    assert len({it["time"] for it in out}) == 1


def test_nasdaq_earnings_time_is_fetch_time(monkeypatch):
    rows = [{"symbol": "TSLA", "time": "before open", "epsForecast": "0.8"}]
    monkeypatch.setattr(fb.requests, "get",
                        lambda url, **kw: _fake_json_resp({"data": {"rows": rows}}))
    out = fb.fetch_nasdaq_earnings()
    assert out
    _assert_not_future(out)
    assert "今日美股财报" in out[0]["text"]


def test_jin10_calendar_time_is_fetch_time(monkeypatch):
    """今日日历: 原实现 time=今日事件时点(可能晚于当前几小时), 现改抓取时刻。"""
    today = _bjnow().strftime("%Y-%m-%d")
    payload = {"data": [{"date": today, "name": "美国CPI同比", "star": 3,
                         "time": "20:30", "actual": "",
                         "consensus": "3.2", "previous": "3.0"}]}
    monkeypatch.setattr(fb.requests, "get", lambda url, **kw: _fake_json_resp(payload))
    out = fb.fetch_jin10_calendar()
    assert out
    _assert_not_future(out)
    # 事件时点挪进正文前缀, 信息不丢
    assert "[20:30]" in out[0]["text"]


def test_calendar_week_time_is_fetch_time(monkeypatch):
    """见闻一周前瞻: 原实现 time=未来事件时刻(known=1, 比财报前瞻更隐蔽)。"""
    ev_local = datetime.datetime.now() + datetime.timedelta(days=2)
    data = {"data": {"items": [{"public_date": int(ev_local.timestamp()),
                                "importance": 3, "country": "美国",
                                "title": "FOMC利率决议", "forecast": "5.25",
                                "actual": ""}]}}

    def fake_get(url, referer, **kw):
        return _fake_json_resp(data)

    monkeypatch.setattr(fe, "_get", fake_get)
    out = fe.fetch_calendar_week()
    assert out
    _assert_not_future(out)
    # 正文前缀 [YYYY-MM-DD HH:MM] 是被预告的事件时刻, 与 time 解耦
    ev_in_text = datetime.datetime.strptime(out[0]["text"][1:17], "%Y-%m-%d %H:%M")
    assert ev_in_text > datetime.datetime.now()
    assert "FOMC利率决议" in out[0]["text"]


def test_ff_calendar_week_time_is_fetch_time(monkeypatch):
    ev = (_bjnow() + datetime.timedelta(days=3)).replace(microsecond=0)
    data = [{"title": "CPI y/y", "country": "USD", "impact": "High",
             "date": ev.isoformat(), "forecast": "3.1", "previous": "3.0"}]

    def fake_get(url, referer, **kw):
        return _fake_json_resp(data)

    monkeypatch.setattr(fe, "_get", fake_get)
    out = fe.fetch_ff_calendar_week()
    assert out
    _assert_not_future(out)
    assert out[0]["text"].startswith("[")


# ── 2. 兜底: known=0 且 time 在未来的漏网条目排序沉底 ────────────────────────

_META = {"kind": "market", "title": "Nasdaq美股财报日历", "form": "", "channel": "",
         "risk": "", "markets": ["美国"], "lang": "zh"}


def _seed(monkeypatch, tmp_path):
    monkeypatch.setenv("GNS_DATA_DIR", str(tmp_path))
    importlib.reload(store)                    # 确保无连接缓存, db_path 走新目录
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    store.put("t1", _META, [{"time": "2999-01-01", "text": "未来财报预告甲",
                             "source": "Nasdaq"}])           # 纯日期未来值 → known=0
    store.put("t2", _META, [{"time": now, "text": "正常快讯乙",
                             "source": "Nasdaq"}])           # 真实发布时刻 → known=1
    return now


def test_query_sinks_unknown_future_time(monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path)
    items, _ = store.query()
    order = [it["text"] for it in items]
    # 未来+时间不可信的条目不参与 time DESC 抢位, 沉到正常条目之后
    assert order == ["正常快讯乙", "未来财报预告甲"]


def test_norm_time_known_flag_semantics_unchanged():
    """_norm_time 既有语义回归: 其他源依赖 known=0 标注, 不得被本次改动波及。"""
    assert store._norm_time("2026-09-20 09:30", "fb") == ("2026-09-20 09:30", 1)
    assert store._norm_time("2026-09-25", "fb") == ("2026-09-25 00:00", 0)
    assert store._norm_time("09:30", "fb") == (
        f"{datetime.datetime.now().strftime('%Y-%m-%d')} 09:30", 0)
    assert store._norm_time("garbage", "fb") == ("fb", 0)


# ── 3. 存量修复: 与本地/云端部署同一语句, 幂等可重跑 ─────────────────────────

_BACKFILL_SQL = ("UPDATE items SET time = fetched_at "
                 "WHERE published_at_known = 0 AND time > datetime('now','localtime')")


def test_backfill_rewrites_future_unknown_time(monkeypatch, tmp_path):
    now = _seed(monkeypatch, tmp_path)
    conn = store._connect()
    cur = conn.execute(_BACKFILL_SQL)
    conn.commit()
    assert cur.rowcount == 1                   # 只修 known=0 且未来的那条
    # 幂等: 再跑一遍零改动
    cur2 = conn.execute(_BACKFILL_SQL)
    conn.commit()
    conn.close()
    assert cur2.rowcount == 0
    items, _ = store.query()
    fixed = next(it for it in items if it["text"] == "未来财报预告甲")
    assert fixed["time"] <= now                # 不再是未来日期
    assert fixed["time"] == fixed["fetched_at"]  # 与入库时刻对齐
    kept = next(it for it in items if it["text"] == "正常快讯乙")
    assert kept["time"] == now                 # 正常条目不受影响
