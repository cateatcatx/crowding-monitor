import unittest

import pandas as pd

from us_market_calendar import completed_daily_rows, market_context
from relative_strength import build_relative_strength


class USMarketCalendarTests(unittest.TestCase):
    def test_labor_day_and_intraday_are_not_missing_daily_bars(self):
        for now,state in [("2026-09-07T15:00:00Z","holiday"),
                          ("2026-09-08T12:00:00Z","premarket"),
                          ("2026-09-08T15:17:00Z","open")]:
            market=market_context("2026-09-04",now=now)
            self.assertEqual(market["market_state"],state)
            self.assertEqual(market["latest_completed_session"],"2026-09-04")
            self.assertEqual(market["missing_sessions"],0)
            self.assertEqual(market["next_close_beijing"],"2026-09-09 04:00")
        closures={d["date"]:d["reason"] for d in market["calendar"]["closures"]}
        self.assertEqual(closures["2026-09-07"],"Labor Day")

    def test_close_and_publication_grace(self):
        before=market_context("2026-09-04",now="2026-09-08T19:59:59Z")
        just_closed=market_context("2026-09-04",now="2026-09-08T20:01:00Z")
        late=market_context("2026-09-04",now="2026-09-08T20:31:00Z")
        self.assertEqual(before["latest_completed_session"],"2026-09-04")
        self.assertEqual(just_closed["latest_completed_session"],"2026-09-08")
        self.assertTrue(just_closed["publication_pending"])
        self.assertEqual(just_closed["missing_sessions"],0)
        self.assertFalse(late["publication_pending"])
        self.assertEqual(late["missing_sessions"],1)

    def test_early_close_and_dst(self):
        early=market_context("2026-11-25",now="2026-11-27T17:59:00Z")
        self.assertEqual(early["next_close_beijing"],"2026-11-28 02:00")
        for now,expected in [("2026-03-06T16:00:00Z","2026-03-07 05:00"),
                             ("2026-03-09T16:00:00Z","2026-03-10 04:00")]:
            self.assertEqual(market_context("2026-03-05",now=now)["next_close_beijing"],expected)

    def test_missing_trading_day_detected_even_over_weekend(self):
        frame=pd.DataFrame({"date":["2026-09-03"],"soxx":[500.0],"igv":[100.0]})
        result=build_relative_strength(frame,now="2026-09-06T10:00:00Z")
        self.assertTrue(result["stale"])
        self.assertEqual(result["market"]["missing_sessions"],1)

    def test_daily_filter_excludes_holidays_and_unfinished_session(self):
        stamps=[int(pd.Timestamp(d).timestamp()) for d in ["2026-09-04T13:30:00Z", "2026-09-07T13:30:00Z", "2026-09-08T13:30:00Z"]]
        prices=[500,501,502]
        self.assertEqual(completed_daily_rows(stamps,prices,now="2026-09-08T15:00:00Z"),[("2026-09-04",500)])
        self.assertEqual(completed_daily_rows(stamps,prices,now="2026-09-08T20:01:00Z"),[("2026-09-04",500),("2026-09-08",502)])
        early=[int(pd.Timestamp("2026-11-27T14:30:00Z").timestamp())]
        self.assertEqual(completed_daily_rows(early,[503],now="2026-11-27T18:01:00Z"),[("2026-11-27",503)])


if __name__ == "__main__":
    unittest.main()
