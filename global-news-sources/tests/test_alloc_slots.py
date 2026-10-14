# /v1/alloc 全量清单档位/窗口辅助单测(2026-10-14 改向: 不做限量分配直回全量)。
# 背景: 档位键小时不补零(推送侧 f"{date}-{hour}"), 外部 bot 曾以补零 "08" 查询
# 被旧实现静默回落到最新档; 本组钉死: 解析容错、窗口=锚点整点、未知显式失败。
import sys
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sources.serve import (_norm_hours, _parse_slot, _slot_window,
                           _latest_anchor, _anchor_dt)

SCH = [8, 11, 17]
D = dt.date(2026, 10, 14)


def test_norm_hours_zero_maps_24_sorted():
    assert _norm_hours([17, 8, 11]) == [8, 11, 17]
    assert _norm_hours([0, 9, 17]) == [9, 17, 24]
    assert _norm_hours([]) == []


def test_parse_slot_padded_and_midnight():
    assert _parse_slot("2026-10-14-8") == (D, 8)
    assert _parse_slot("2026-10-14-08") == (D, 8)      # 补零容错(1014 坑)
    assert _parse_slot(" 2026-10-14-17 ") == (D, 17)
    assert _parse_slot("2026-10-15-0") == (dt.date(2026, 10, 15), 24)  # 午夜归24
    for bad in ("abc", "2026-10-14", "2026-13-01-8", "2026-10-14-8x"):
        try:
            _parse_slot(bad)
            raise AssertionError(f"应拒绝: {bad}")
        except (ValueError, TypeError):
            pass


def test_slot_window_walks_prev_anchor():
    # 8 点档 ← 昨日 17 点(overnight 覆盖)
    s, u = _slot_window(D, 8, SCH)
    assert (s, u) == (dt.datetime(2026, 10, 13, 17), dt.datetime(2026, 10, 14, 8))
    # 11 点档 ← 当日 8 点; 17 点档 ← 当日 11 点
    assert _slot_window(D, 11, SCH) == (dt.datetime(2026, 10, 14, 8),
                                        dt.datetime(2026, 10, 14, 11))
    assert _slot_window(D, 17, SCH) == (dt.datetime(2026, 10, 14, 11),
                                        dt.datetime(2026, 10, 14, 17))
    # 24 点档(若有) ← 当日 17 点, 止于次日零点
    s, u = _slot_window(D, 24, [8, 11, 17, 24])
    assert (s, u) == (dt.datetime(2026, 10, 14, 17), dt.datetime(2026, 10, 15, 0))


def test_latest_anchor():
    assert _latest_anchor(SCH, dt.datetime(2026, 10, 14, 18)) == (D, 17)
    assert _latest_anchor(SCH, dt.datetime(2026, 10, 14, 17)) == (D, 17)   # 含等点
    assert _latest_anchor(SCH, dt.datetime(2026, 10, 14, 16, 59)) == (D, 11)
    assert _latest_anchor(SCH, dt.datetime(2026, 10, 14, 7, 59)) == \
        (dt.date(2026, 10, 13), 17)                                        # 跨日回看
    assert _latest_anchor(SCH, dt.datetime(2026, 10, 14, 9)) == (D, 8)
    assert _latest_anchor([], dt.datetime(2026, 10, 14, 9)) is None


def test_anchor_dt_midnight():
    assert _anchor_dt(D, 24) == dt.datetime(2026, 10, 15, 0)
    assert _anchor_dt(D, 8) == dt.datetime(2026, 10, 14, 8)
