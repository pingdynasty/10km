"""tenkm.timefmt: local clock times and short elapsed times for the operator (R10).
Every test fixes the clock and the zone."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: E402,F401  (test config, no caller env: tests/testenv.py)
from tenkm import timefmt  # noqa: E402

CET = timezone(timedelta(hours=1), "CET")
NOW = "2026-11-15T18:47:10Z"  # 19:47 CET


class TestParse(unittest.TestCase):
    def test_iso_utc_git_offset_and_ps_lstart_are_the_same_instant(self):
        utc = timefmt.parse("2026-11-15T18:47:36Z")
        self.assertEqual(timefmt.parse("2026-11-15T19:47:36+01:00"), utc)
        self.assertEqual(timefmt.parse("Sun Nov 15 19:47:36 2026", CET), utc)
        self.assertEqual(timefmt.parse("Sun Nov  5 19:47:36 2026", CET),
                         utc - timedelta(days=10))

    def test_unreadable_times_are_none(self):
        for text in (None, "", "yesterday", 42):
            self.assertIsNone(timefmt.parse(text))
        self.assertEqual(timefmt.clock(None, NOW, CET), "?")
        self.assertEqual(timefmt.ago("bad", NOW, CET), "?")

    def test_process_handle(self):
        handle = "process:20940:Sun Nov 15 19:47:11 2026"
        self.assertEqual(timefmt.short_handle(handle), "pid 20940")
        self.assertEqual(timefmt.handle_start(handle, CET),
                         datetime(2026, 11, 15, 18, 47, 11, tzinfo=timezone.utc))
        self.assertEqual(timefmt.short_handle("other:x"), "other:x")
        self.assertEqual(timefmt.short_handle(None), "no handle")
        self.assertIsNone(timefmt.handle_start("other:x"))


class TestFormat(unittest.TestCase):
    def test_clock_today_other_day_other_year(self):
        self.assertEqual(timefmt.clock("2026-11-15T18:35:00Z", NOW, CET), "19:35")
        self.assertEqual(timefmt.clock("2026-11-14T22:05:00Z", NOW, CET), "Nov 14 23:05")
        self.assertEqual(timefmt.clock("2025-11-14T22:05:00Z", NOW, CET), "Nov 14 2025 23:05")
        # The local date decides: 23:30 UTC on Nov 14 is already Nov 15 in CET.
        self.assertEqual(timefmt.clock("2026-11-14T23:30:00Z", NOW, CET), "00:30")

    def test_stamp_shows_the_zone(self):
        self.assertEqual(timefmt.stamp(NOW, CET), "Nov 15 19:47 CET")

    def test_elapsed(self):
        cases = {0: "0s", 45: "45s", 59: "59s", 60: "1m", 180: "3m", 3599: "59m",
                 3600: "1h0m", 4320: "1h12m", 86400: "1d0h", 187200: "2d4h", -5: "0s"}
        for seconds, text in cases.items():
            self.assertEqual(timefmt.elapsed(seconds), text, seconds)

    def test_ago(self):
        self.assertEqual(timefmt.ago("2026-11-15T17:53:10Z", NOW, CET), "54m ago")
        self.assertEqual(timefmt.ago("2026-11-13T14:47:10Z", NOW, CET), "2d4h ago")
        self.assertEqual(timefmt.since("2026-11-15T18:47:00Z", NOW, CET), "10s")


if __name__ == "__main__":
    unittest.main()
