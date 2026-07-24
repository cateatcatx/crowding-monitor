import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd
from fetch_sk_hynix_foreign_flow import (
    latest_reference_date,
    normalize_record,
    parse_int,
    parse_pct,
    validate_freshness,
    validate_market_consistency,
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
        record = normalize_record(
            {
                "bizdate": "20260723",
                "foreignerPureBuyQuant": "+689,098",
                "foreignerHoldRatio": "52.60%",
                "organPureBuyQuant": "-148,151",
                "individualPureBuyQuant": "-528,844",
                "closePrice": "1,947,000",
                "accumulatedTradingVolume": "7,118,367",
            },
            market="ALL",
        )
        self.assertEqual(record["date"], "2026-07-23")
        self.assertEqual(record["ticker"], "000660")
        self.assertEqual(record["market"], "ALL")
        self.assertEqual(record["foreign_net_shares"], 689098)
        self.assertEqual(record["institution_net_shares"], -148151)
        self.assertEqual(record["foreign_holding_ratio_pct"], 52.6)
        self.assertEqual(record["close_krw"], 1947000)
        self.assertIn("marketType=ALL", record["source_url"])

    def test_reference_date_and_freshness_check(self):
        with TemporaryDirectory() as temp_dir:
            price_file = Path(temp_dir) / "SK_HYNIX.csv"
            price_file.write_text(
                "date,close\n2026-07-22,1830000\n2026-07-24,1759000\n",
                encoding="utf-8",
            )
            expected = latest_reference_date(price_file)
            self.assertEqual(expected, date(2026, 7, 24))

        flow = pd.DataFrame({
            "date": ["2026-07-22", "2026-07-23"],
            "market": ["ALL", "ALL"],
        })
        with self.assertRaisesRegex(RuntimeError, "落后于价格交易日"):
            validate_freshness(flow, expected)
        self.assertEqual(
            validate_freshness(flow, date(2026, 7, 23)),
            date(2026, 7, 23),
        )

    def test_market_consistency(self):
        flow = pd.DataFrame({
            "date": ["2026-07-23"] * 3,
            "market": ["ALL", "KRX", "NXT"],
            "foreign_net_shares": [689098, 689697, -599],
        })
        validate_market_consistency(flow)

        broken = flow.copy()
        broken.loc[broken["market"] == "ALL", "foreign_net_shares"] = 689099
        with self.assertRaisesRegex(RuntimeError, "ALL=KRX\\+NXT"):
            validate_market_consistency(broken)

    def test_market_consistency_requires_synchronized_latest_dates(self):
        flow = pd.DataFrame({
            "date": [
                "2026-07-23", "2026-07-22", "2026-07-22", "2026-07-22",
            ],
            "market": ["ALL", "ALL", "KRX", "NXT"],
            "foreign_net_shares": [5, 3, 2, 1],
        })
        with self.assertRaisesRegex(RuntimeError, "最新日期不一致"):
            validate_market_consistency(flow)

    def test_market_consistency_rejects_missing_active_market_day(self):
        flow = pd.DataFrame({
            "date": [
                "2026-07-21", "2026-07-21", "2026-07-21",
                "2026-07-22", "2026-07-22",
                "2026-07-23", "2026-07-23", "2026-07-23",
            ],
            "market": [
                "ALL", "KRX", "NXT",
                "ALL", "KRX",
                "ALL", "KRX", "NXT",
            ],
            "foreign_net_shares": [3, 2, 1, 2, 2, 7, 4, 3],
        })
        with self.assertRaisesRegex(RuntimeError, "缺少 ALL/KRX/NXT"):
            validate_market_consistency(flow)

    def test_market_consistency_checks_pre_nxt_all_equals_krx(self):
        flow = pd.DataFrame({
            "date": [
                "2025-03-21", "2025-03-21",
                "2025-03-24", "2025-03-24", "2025-03-24",
            ],
            "market": ["ALL", "KRX", "ALL", "KRX", "NXT"],
            "foreign_net_shares": [9, 8, 3, 2, 1],
        })
        with self.assertRaisesRegex(RuntimeError, "NXT上线前不满足 ALL=KRX"):
            validate_market_consistency(flow)

    def test_market_consistency_checks_nxt_launch_boundary(self):
        premature = pd.DataFrame({
            "date": [
                "2025-03-21", "2025-03-21", "2025-03-21",
                "2025-03-24", "2025-03-24", "2025-03-24",
            ],
            "market": ["ALL", "KRX", "NXT", "ALL", "KRX", "NXT"],
            "foreign_net_shares": [3, 2, 1, 3, 2, 1],
        })
        with self.assertRaisesRegex(RuntimeError, "前不应存在NXT记录"):
            validate_market_consistency(premature)

        missing_launch_day = pd.DataFrame({
            "date": [
                "2025-03-21", "2025-03-21",
                "2025-03-25", "2025-03-25", "2025-03-25",
            ],
            "market": ["ALL", "KRX", "ALL", "KRX", "NXT"],
            "foreign_net_shares": [2, 2, 3, 2, 1],
        })
        with self.assertRaisesRegex(RuntimeError, "缺少2025-03-24边界记录"):
            validate_market_consistency(missing_launch_day)


class ForeignFlowDashboardTests(unittest.TestCase):
    def test_seed_data_dashboard_summary(self):
        data_path = Path(__file__).resolve().parents[1] / "data" / "SK_HYNIX_FOREIGN_FLOW.csv"
        data = pd.read_csv(data_path, dtype={"ticker": str})
        data["date"] = pd.to_datetime(data["date"])
        self.assertEqual(set(data["market"].unique()), {"ALL", "KRX", "NXT"})
        self.assertFalse(data.duplicated(["date", "market"]).any())
        all_data = data[data["market"] == "ALL"].sort_values("date")
        latest = all_data.iloc[-1]
        latest_date = latest["date"].strftime("%Y-%m-%d")

        summary = assemble_foreign_flow(latest_date)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["ticker"], "000660")
        self.assertEqual(summary["market"], "ALL")
        self.assertEqual(summary["asof"], latest_date)
        self.assertEqual(
            summary["latest_net_shares"], int(latest["foreign_net_shares"])
        )
        self.assertEqual(
            summary["sum_5d_net_shares"],
            int(all_data["foreign_net_shares"].tail(5).sum()),
        )
        self.assertEqual(
            summary["sum_20d_net_shares"],
            int(all_data["foreign_net_shares"].tail(20).sum()),
        )
        self.assertEqual(
            summary["latest_holding_ratio_pct"],
            round(float(latest["foreign_holding_ratio_pct"]), 2),
        )
        self.assertEqual(
            len(summary["series"]["dates"]),
            min(90, len(all_data)),
        )
        self.assertEqual(len(summary["recent"]), min(10, len(all_data)))
        self.assertTrue(summary["latest_component_ok"])
        self.assertEqual(
            summary["venues"]["ALL"]["latest_net_shares"],
            summary["venues"]["KRX"]["latest_net_shares"]
            + summary["venues"]["NXT"]["latest_net_shares"],
        )
        for row in summary["recent"]:
            self.assertEqual(
                row["total_net_shares"],
                row["krx_net_shares"] + row["nxt_net_shares"],
            )
        self.assertFalse(summary["stale"])

    def test_stale_compares_with_stock_trading_date(self):
        summary = assemble_foreign_flow("2099-01-01")
        self.assertTrue(summary["stale"])

    def test_dashboard_does_not_sum_misaligned_market_windows(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "flow.csv"
            rows = []
            for day in range(1, 6):
                flow_date = f"2026-07-{day:02d}"
                rows.append({
                    "date": flow_date,
                    "ticker": "000660",
                    "market": "ALL",
                    "foreign_net_shares": 10,
                    "foreign_holding_ratio_pct": 52.6,
                })
                if day != 2:
                    rows.append({
                        "date": flow_date,
                        "ticker": "000660",
                        "market": "KRX",
                        "foreign_net_shares": 4,
                        "foreign_holding_ratio_pct": 52.6,
                    })
                rows.append({
                    "date": flow_date,
                    "ticker": "000660",
                    "market": "NXT",
                    "foreign_net_shares": 6,
                    "foreign_holding_ratio_pct": 52.6,
                })
            pd.DataFrame(rows).to_csv(path, index=False)

            with patch("server.FOREIGN_FLOW_FILE", str(path)):
                summary = assemble_foreign_flow("2026-07-05")

        self.assertFalse(summary["latest_component_ok"])
        self.assertIsNone(summary["venues"]["KRX"]["sum_5d_net_shares"])
        self.assertEqual(summary["venues"]["NXT"]["sum_5d_net_shares"], 30)
        self.assertEqual(summary["venues"]["ALL"]["sum_5d_net_shares"], 50)


if __name__ == "__main__":
    unittest.main()
