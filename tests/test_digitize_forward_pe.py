"""Frozen, visually verified source charts test calibration and loss of information."""
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw
import digitize_forward_pe as digitizer
import forward_pe

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 8, tzinfo=timezone.utc)


class DigitizerTests(unittest.TestCase):
    def fixture(self, key):
        return ((FIXTURES / f"{key}-2026-09-04.png").read_bytes(),
                json.loads((FIXTURES / f"{key}-ocr.json").read_text()))

    def test_real_chart_calibration_and_legend_anchor(self):
        for key, latest, expected_resolution in [("hardware",16.7,4.93),("software",23.4,6.72)]:
            content, labels = self.fixture(key)
            data = digitizer.digitize(content, now=NOW, ocr=labels)
            self.assertEqual(data["asof"], "2026-09-04")
            self.assertEqual(data["values"][-1], latest)
            self.assertAlmostEqual(data["days_per_pixel"], expected_resolution, places=2)
            self.assertGreater(data["pixel_samples"], 1600)
            self.assertEqual(len(data["values"]),len(data["dates"]))
            self.assertTrue(all(a < b for a,b in zip(data["dates"],data["dates"][1:])))
            # Days include weekends by design, never advertised as observed daily prices.
            self.assertIn("2026-08-30", data["dates"])
            self.assertEqual(data["method"], "image_digitized_daily_interpolation")

    def test_obscured_curve_is_not_interpolated_across(self):
        content, labels = self.fixture("hardware")
        image = Image.open(BytesIO(content)).convert("RGB")
        ImageDraw.Draw(image).rectangle((1650,215,1665,950),fill="white")
        stream=BytesIO(); image.save(stream,format="PNG")
        data=digitizer.digitize(stream.getvalue(),now=NOW,ocr=labels)
        self.assertGreater(data["values"].count(None),40)
        self.assertEqual(data["values"][-1],16.7)

    def test_missing_or_nonlinear_axes_and_wrong_legend_fail_closed(self):
        content, labels = self.fixture("hardware")
        with self.assertRaises(ValueError):
            digitizer.digitize(content,now=NOW,ocr=[])
        for before, after in [("2004","1999"),("Sep 04 = 16.7","Sep 04 = 60.0"),
                              ("Sep 04 = 16.7","Jan 04 = 16.7")]:
            changed=json.loads(json.dumps(labels))
            for row in changed:
                row[1]=row[1].replace(before,after)
            with self.assertRaises(ValueError):
                digitizer.digitize(content,now=NOW,ocr=changed)

    def test_quality_failure_retains_old_pair_and_retry_can_recover(self):
        content, labels = self.fixture("hardware")
        old=forward_pe.read_cache(forward_pe.CACHE_FILE)["charts"]["hardware"]
        fresh=dict(old, image_base64="changed", error=None)
        with patch.object(forward_pe,"fetch_chart",return_value=fresh), \
             patch.object(forward_pe.base64,"b64decode",return_value=content), \
             patch.object(forward_pe,"digitize",side_effect=ValueError("bad axes")):
            with self.assertRaisesRegex(RuntimeError,"bad axes"):
                forward_pe.prepare_chart(forward_pe.CHARTS[0],old,attempts=1)
        with patch.object(forward_pe,"fetch_chart",side_effect=[RuntimeError("offline"),old]), \
             patch.object(forward_pe.time,"sleep") as sleep:
            result=forward_pe.prepare_chart(forward_pe.CHARTS[0],old,attempts=2)
            self.assertEqual(result["digitized"]["asof"],old["digitized"]["asof"])
            sleep.assert_called_once()

    def test_changed_image_cannot_regress_date_and_preserves_legend_history(self):
        old=forward_pe.read_cache(forward_pe.CACHE_FILE)["charts"]["hardware"]
        fresh=dict(old,image_base64="changed",error=None)
        series=json.loads(json.dumps(old["digitized"]))
        series["asof"]="2000-01-01"
        with patch.object(forward_pe,"fetch_chart",return_value=fresh), \
             patch.object(forward_pe.base64,"b64decode",return_value=b"image"), \
             patch.object(forward_pe,"digitize",return_value=series):
            with self.assertRaisesRegex(RuntimeError,"更旧"):
                forward_pe.prepare_chart(forward_pe.CHARTS[0],old,attempts=1)
        old["digitized"]["observations"].append({"date":"2026-08-20","value":17.2})
        series=json.loads(json.dumps(old["digitized"]))
        series["observations"]=[series["observations"][0]]
        with patch.object(forward_pe,"fetch_chart",return_value=fresh), \
             patch.object(forward_pe.base64,"b64decode",return_value=b"image"), \
             patch.object(forward_pe,"digitize",return_value=series):
            result=forward_pe.prepare_chart(forward_pe.CHARTS[0],old,attempts=1)["digitized"]
            self.assertEqual(result["values"][result["dates"].index("2026-08-20")],17.2)


if __name__ == "__main__":
    unittest.main()
