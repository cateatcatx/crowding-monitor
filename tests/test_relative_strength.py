import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from relative_strength import assemble_relative_strength, build_relative_strength, refresh_cache
from server import app


def sample(count=100):
    return pd.DataFrame({"date": pd.bdate_range("2025-01-01", periods=count),
                         "soxx": 100 + np.arange(count, dtype=float), "igv": 50.0})


class RelativeStrengthTests(unittest.TestCase):
    def test_ratio_returns_and_ma(self):
        frame = sample()
        result = build_relative_strength(frame, now="2025-05-21")
        summary = result["summary"]
        self.assertEqual(summary["ratio"], 3.98)
        self.assertEqual(result["series"]["index"][0], 100)
        self.assertEqual(summary["change_5d_pct"], round((199 / 194 - 1) * 100, 2))
        self.assertEqual(summary["change_20d_pct"], round((199 / 179 - 1) * 100, 2))
        self.assertEqual(summary["change_60d_pct"], round((199 / 139 - 1) * 100, 2))
        self.assertEqual(summary["ma20"], 3.79)
        self.assertTrue(summary["above_ma20"])
        json.dumps(result, allow_nan=False)

    def test_constant_ratio_is_flat_even_when_both_prices_rise(self):
        frame = sample()
        frame["igv"] = frame.soxx / 2
        result = build_relative_strength(frame)
        self.assertEqual(result["summary"]["change_60d_pct"], 0)
        self.assertTrue(all(v == 100 for v in result["series"]["index"]))

    def test_invalid_missing_and_duplicates_do_not_forward_fill(self):
        frame = sample(6)
        frame.loc[1, "soxx"] = 0
        frame.loc[2, "igv"] = np.nan
        frame.loc[3, "soxx"] = np.inf
        frame = pd.concat([frame, frame.iloc[[5]]]).iloc[::-1]
        result = build_relative_strength(frame)
        self.assertEqual(len(result["series"]["dates"]), 3)
        self.assertEqual(result["series"]["dates"], sorted(result["series"]["dates"]))
        self.assertIsNone(result["summary"]["change_5d_pct"])
        self.assertIsNone(result["summary"]["ma20"])
        json.dumps(result, allow_nan=False)

    def test_ma_computed_before_window_and_no_lookahead(self):
        frame = sample(400)
        result = build_relative_strength(frame)
        self.assertIsNotNone(result["series"]["ma60"][0])
        first = pd.Timestamp(result["series"]["dates"][0])
        i = frame.index[frame.date == first][0]
        expected = (frame.soxx.iloc[i-19:i+1] / 50).mean() / (frame.soxx.iloc[i] / 50) * 100
        self.assertAlmostEqual(result["series"]["ma20"][0], expected, places=4)
        frame.loc[len(frame)-1, "soxx"] *= 3
        updated = build_relative_strength(frame)
        self.assertEqual(updated["series"]["ma20"][0], result["series"]["ma20"][0])

    def test_weekend_is_not_stale(self):
        frame = pd.DataFrame({"date": ["2026-09-04"], "soxx": [519.86], "igv": [104.57]})
        self.assertFalse(build_relative_strength(frame, now="2026-09-05")["stale"])
        self.assertTrue(build_relative_strength(frame, now="2026-09-10")["stale"])

    def test_missing_or_malformed_cache_is_nonfatal(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "pair.csv"
            self.assertFalse(assemble_relative_strength(path)["available"])
            path.write_text("wrong,columns\n1,2\n")
            self.assertFalse(assemble_relative_strength(path)["available"])

    def test_failed_leg_keeps_cache_untouched(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "pair.csv"
            sample().to_csv(path, index=False)
            original = path.read_bytes()
            def fetch(symbol):
                if symbol == "IGV":
                    raise RuntimeError("offline")
                return sample().set_index("date").soxx
            with patch("relative_strength.fetch_close", side_effect=fetch):
                with self.assertRaisesRegex(RuntimeError, "offline"):
                    refresh_cache(path)
            self.assertEqual(path.read_bytes(), original)

    def test_refresh_checks_dates_and_does_not_regress_cache(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "pair.csv"
            frame = sample()
            frame.to_csv(path, index=False)
            original = path.read_bytes()
            def mismatch(symbol):
                return frame.set_index("date").soxx.iloc[:(-1 if symbol == "IGV" else None)]
            with patch("relative_strength.fetch_close", side_effect=mismatch):
                with self.assertRaisesRegex(ValueError, "dates differ"):
                    refresh_cache(path)
            with patch("relative_strength.fetch_close", return_value=frame.set_index("date").soxx.iloc[:-1]):
                with self.assertRaisesRegex(ValueError, "older data"):
                    refresh_cache(path)
            self.assertEqual(path.read_bytes(), original)

    def test_refresh_success_and_dashboard_integration(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "pair.csv"
            frame = sample()
            with patch("relative_strength.fetch_close", return_value=frame.set_index("date").soxx):
                refresh_cache(path)
            result = assemble_relative_strength(path)
            self.assertEqual(result["summary"]["ratio"], 1)
        with patch("server.assemble_relative_strength", return_value=result):
            response = app.test_client().get("/api/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["relative_strength"]["summary"]["ratio"], 1)


if __name__ == "__main__":
    unittest.main()
