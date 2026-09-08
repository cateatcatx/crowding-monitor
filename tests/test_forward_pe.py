import base64
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import forward_pe as pe
import server


class ForwardPeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "cache.json"
        self.seed = pe.read_cache(pe.CACHE_FILE)
        # CI may restore a valid cached image with a previous network warning.
        for chart in self.seed["charts"].values():
            chart["error"] = None

    def write_seed(self):
        self.path.write_text(json.dumps(self.seed), encoding="utf-8")

    def test_parser_selects_exact_forward_pe_and_decodes_url(self):
        html = ('<img alt="Figure 1: S&amp;P 500 APPLICATION SOFTWARE: STOCK PRICE INDEX" src="wrong">'
                '<img alt="Figure 10: S&amp;P 500 APPLICATION SOFTWARE: FORWARD P/E*" '
                'src="https://product.datastream.com/chart?a=1&amp;b=2">')
        self.assertEqual(pe.parse_chart_url(html, pe.CHARTS[1]["title"]),
                         "https://product.datastream.com/chart?a=1&b=2")
        with self.assertRaises(ValueError):
            pe.parse_chart_url(html, pe.CHARTS[0]["title"])
        with self.assertRaises(ValueError):
            pe.parse_chart_url(html.replace("product.datastream.com", "example.com"), pe.CHARTS[1]["title"])

    def test_bad_or_missing_cache_does_not_break_dashboard(self):
        for content in [None, "{}", "null", "not json", '{"charts":{"hardware":null}}']:
            if content is not None:
                self.path.write_text(content, encoding="utf-8")
            data = pe.assemble_forward_pe(self.path)
            self.assertFalse(data["available"])
            self.assertEqual(len(data["charts"]), 2)

    def test_html_and_truncated_images_are_rejected(self):
        raw = base64.b64decode(self.seed["charts"]["hardware"]["image_base64"])
        pe.validate_png(raw)
        for invalid in [b"<html>502</html>", raw[:-20]]:
            with self.assertRaises(ValueError):
                pe.validate_png(invalid)

    def test_partial_failure_retains_previous_image_and_recovers(self):
        self.write_seed()
        software = self.seed["charts"]["software"]
        with patch.object(pe, "fetch_chart", side_effect=[RuntimeError("offline"), software]):
            self.assertEqual(len(pe.refresh_cache(self.path, attempts=1)), 1)
        saved = pe.read_cache(self.path)
        old = self.seed["charts"]["hardware"]
        self.assertEqual(saved["charts"]["hardware"]["image_base64"], old["image_base64"])
        self.assertEqual(saved["charts"]["hardware"]["fetched_at"], old["fetched_at"])
        self.assertIn("offline", saved["charts"]["hardware"]["error"])
        self.assertTrue(all(c["available"] for c in pe.assemble_forward_pe(self.path)["charts"]))
        with patch.object(pe, "fetch_chart", side_effect=[old, software]):
            self.assertEqual(pe.refresh_cache(self.path, attempts=1), [])
        self.assertIsNone(pe.read_cache(self.path)["charts"]["hardware"]["error"])

    def test_cache_age_is_not_reported_as_data_date(self):
        self.write_seed()
        latest_fetch = max(datetime.fromisoformat(c["fetched_at"]) for c in self.seed["charts"].values())
        data = pe.assemble_forward_pe(self.path, now=latest_fetch + timedelta(days=5))
        self.assertTrue(all(c["cache_stale"] for c in data["charts"]))
        self.assertTrue(all("asof" not in c for c in data["charts"]))
        response = server.app.test_client().get("/api/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json["forward_pe"]["charts"]), 2)


if __name__ == "__main__":
    unittest.main()
