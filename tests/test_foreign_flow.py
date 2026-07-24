import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
from fetch_sk_hynix_foreign_flow import (
    latest_reference_date,
    normalize_record,
    parse_int,
    parse_pct,
    validate_freshness,
)
from server import assemble_foreign_flow


class ForeignFlowParsingTests(unittest.TestCase):
    def test_parse_signed_integer(self):
        self.assertEqual(parse_int("+689,697"), 689697)
        self.assertEqual(parse_int("-599"), -599)
        self.assertEqual(parse_int("4,119,477"), 4119477)
        self.assertIsNone(parse_int("—"))

    def test_parse_percentage(self):
        self.assertEqual(parse_pct("52.60%"), 52.6)
        self.assertIsNone(parse_pct("-"))

    def test_normalize_record(self):
        record = normalize_record({
            "bizdate": "20260723",
            "foreignerPureBuyQuant": "+689,697",
            "foreignerHoldRatio": "52.60%",
            "organPureBuyQuant": "-148,136",
            "individualPureBuyQuant": "-529,529",
            "closePrice": "1,919,000",
            "accumulatedTradingVolume": "4,119,477",
        })
        self.assertEqual(record["date"], "2026-07-23")
        self.assertEqual(record["ticker"], "000660")
        self.assertEqual(record["market"], "KRX")
        self.assertEqual(record["foreign_net_shares"], 689697)
        self.assertEqual(record["institution_net_shares"], -148136)
        self.assertEqual(record["foreign_holding_ratio_pct"], 52.6)
        self.assertEqual(record["close_krw"], 1919000)

    def test_reference_date_and_freshness_check(self):
        with TemporaryDirectory() as temp_dir:
            price_file = Path(temp_dir) / "SK_HYNIX.csv"
            price_file.write_text(
                "date,close\n2026-07-22,1830000\n2026-07-24,1759000\n",
                encoding="utf-8",
            )
            expected = latest_reference_date(price_file)
            self.assertEqual(expected, date(2026, 7, 24))

        flow = pd.DataFrame({"date": ["2026-07-22", "2026-07-23"]})
        with self.assertRaisesRegex(RuntimeError, "落后于价格交易日"):
            validate_freshness(flow, expected)
        self.assertEqual(
            validate_freshness(flow, date(2026, 7, 23)),
            date(2026, 7, 23),
        )


class ForeignFlowDashboardTests(unittest.TestCase):
    def test_seed_data_dashboard_summary(self):
        data_path = Path(__file__).resolve().parents[1] / "data" / "SK_HYNIX_FOREIGN_FLOW.csv"
        data = pd.read_csv(data_path, dtype={"ticker": str})
        data["date"] = pd.to_datetime(data["date"])
        data = data.sort_values("date")
        latest = data.iloc[-1]
        latest_date = latest["date"].strftime("%Y-%m-%d")

        summary = assemble_foreign_flow(latest_date)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["ticker"], "000660")
        self.assertEqual(summary["asof"], latest_date)
        self.assertEqual(
            summary["latest_net_shares"], int(latest["foreign_net_shares"])
        )
        self.assertEqual(
            summary["sum_5d_net_shares"],
            int(data["foreign_net_shares"].tail(5).sum()),
        )
        self.assertEqual(
            summary["latest_holding_ratio_pct"],
            round(float(latest["foreign_holding_ratio_pct"]), 2),
        )
        self.assertEqual(len(summary["series"]["dates"]), min(90, len(data)))
        self.assertEqual(len(summary["recent"]), min(10, len(data)))
        self.assertFalse(summary["stale"])

    def test_stale_compares_with_stock_trading_date(self):
        summary = assemble_foreign_flow("2099-01-01")
        self.assertTrue(summary["stale"])


if __name__ == "__main__":
    unittest.main()
