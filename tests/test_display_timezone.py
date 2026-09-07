import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from server import assemble_dashboard, beijing_now_text


class DisplayTimezoneTests(unittest.TestCase):
    def test_utc_is_converted_to_beijing(self):
        with patch("server.datetime") as clock:
            clock.now.return_value = datetime(2026, 9, 7, 1, 30, 15, tzinfo=timezone.utc)
            self.assertEqual(beijing_now_text(), "2026-09-07 09:30:15")
            clock.now.assert_called_once_with(timezone.utc)

    def test_conversion_crosses_midnight(self):
        with patch("server.datetime") as clock:
            clock.now.return_value = datetime(2026, 9, 7, 20, 5, 0, tzinfo=timezone.utc)
            self.assertEqual(beijing_now_text(), "2026-09-08 04:05:00")

    def test_dashboard_declares_display_timezone(self):
        with patch("server.beijing_now_text", return_value="2026-09-07 09:30:15"):
            data = assemble_dashboard()
        self.assertEqual(data["generated_at"], "2026-09-07 09:30:15")
        self.assertEqual(data["display_timezone"], "Asia/Shanghai")


if __name__ == "__main__":
    unittest.main()
