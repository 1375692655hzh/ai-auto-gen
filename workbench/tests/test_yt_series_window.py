"""channel_series 图表数据窗口修复的离线测试(2026-09-11 追踪页图表重做配套)。
覆盖: updates 在频道进入追踪(首个订阅快照/added_at 取早)之前的日期置 None(不再画 0);
latest_series 同日多次快照按日折叠取最后值(修 x 轴标签重叠)。"""
import sys
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import yt_track

CID = "UCtest0000000000000000000"


def _day(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


class ChannelSeriesWindowTests(unittest.TestCase):
    def _series(self, videos, row, days=30):
        store = {"videos": videos}
        with patch.object(yt_track, "load_store", lambda: store):
            return yt_track.channel_series(CID, days=days, row=row)

    def _video(self, vid, pub_days_ago, series):
        return {"video_id": vid, "channel_id": CID, "title": "t" + vid,
                "published": time.time() - pub_days_ago * 86400,
                "series": series}

    def test_updates_null_before_evidence(self):
        """频道 3 天前加入: 之前的"每日更新"必须 None(无数据), 之后按发布计数(含 0)。"""
        added = time.time() - 3 * 86400
        row = {"channel_id": CID, "added_at": datetime.fromtimestamp(added).strftime("%Y-%m-%d %H:%M:%S"),
               "subs_series": []}
        vids = {"v1": self._video("v1", 1, [{"ts": int(time.time()), "v": 10}])}
        d = self._series(vids, row)
        upd = {p["date"]: p["v"] for p in d["updates"]}
        ev_day = _day(added)
        self.assertIsNone(upd[_day(time.time() - 10 * 86400)])   # 证据日前 = 无数据
        self.assertIsNone(upd[_day(time.time() - 4 * 86400)])
        self.assertEqual(upd[ev_day] or 0, 0)                    # 证据日当天起有数(可为 0)
        self.assertEqual(upd[_day(time.time() - 86400)], 1)      # 昨天发了 1 条

    def test_evidence_earlier_subs_snapshot(self):
        """订阅快照早于 added_at 时, 证据日取更早者。"""
        snap = time.time() - 20 * 86400
        row = {"channel_id": CID,
               "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "subs_series": [{"ts": int(snap), "v": 5}]}
        d = self._series({}, row)
        upd = {p["date"]: p["v"] for p in d["updates"]}
        self.assertIsNone(upd[_day(time.time() - 25 * 86400)])
        self.assertEqual(upd[_day(snap)] or 0, 0)                # 快照日当天起按 0 计
        # subs 顺延: 快照日前 None, 快照日起为快照值
        subs = {p["date"]: p["v"] for p in d["subs"]}
        self.assertIsNone(subs[_day(time.time() - 25 * 86400)])
        self.assertEqual(subs[_day(snap)], 5)
        self.assertEqual(subs[_day(time.time())], 5)

    def test_latest_collapsed_per_day(self):
        """同日多次快照折叠成 1 点且取最后值; 跨日每天 1 点。"""
        # 锚定"今天/昨天正午"而非 now-86400: 00:00-01:00 之间跑测试时 now-86400-3600
        # 会落到前天, 造出 3 天数据炸断言(0918 午夜 flake 实证)
        today_noon = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0).timestamp()
        yday_noon = today_noon - 86400
        row = {"channel_id": CID, "added_at": "", "subs_series": []}
        vids = {"v1": self._video("v1", 2, [
            {"ts": int(yday_noon) - 3600, "v": 5},
            {"ts": int(yday_noon), "v": 8},           # 同一天, 后值覆盖
            {"ts": int(today_noon) - 600, "v": 20},
            {"ts": int(today_noon), "v": 30},
        ])}
        d = self._series(vids, row)
        ls = d["latest_series"]
        dates = [p["date"] for p in ls]
        self.assertEqual(len(dates), len(set(dates)))            # 无重复日期
        self.assertEqual(len(ls), 2)                             # 两天各 1 点
        self.assertEqual(ls[0]["v"], 8)                          # 首日取最后快照
        self.assertEqual(ls[-1]["v"], 30)
        self.assertEqual(d["latest"]["video_id"], "v1")


class SubsAnchorDeltaTests(unittest.TestCase):
    def test_base_is_prev_day_830(self):
        """订阅差分(8:30 锚点): 基准=昨日8:30最近样本, 昨日后续快照不污染。"""
        BJ = yt_track._BJ

        def ts(d, hm):
            return datetime.strptime(d + " " + hm, "%Y-%m-%d %H:%M").replace(tzinfo=BJ).timestamp()

        ser = [{"ts": ts("2026-09-15", "08:31"), "v": 10},
               {"ts": ts("2026-09-15", "23:00"), "v": 50},
               {"ts": ts("2026-09-16", "12:00"), "v": 60}]
        d, base_ts = yt_track.subs_anchor_delta(ser, ts("2026-09-16", "15:00"))
        self.assertEqual(d, 50)                              # 60 − 昨日8:31的10
        self.assertEqual(datetime.fromtimestamp(base_ts, BJ).strftime("%m-%d %H:%M"),
                         "09-15 08:31")

    def test_empty_series(self):
        self.assertEqual(yt_track.subs_anchor_delta([], time.time()), (None, None))


if __name__ == "__main__":
    unittest.main()
