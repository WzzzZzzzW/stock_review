import unittest
from unittest.mock import patch

from utils.fallback_log import _reset_fallback_log_state, report_data_fallback


class FallbackLogTests(unittest.TestCase):
    def setUp(self):
        _reset_fallback_log_state()

    @patch("utils.fallback_log._LOGGER.warning")
    @patch("utils.fallback_log.time.monotonic", side_effect=[100.0, 110.0, 170.0])
    def test_duplicate_errors_are_throttled_and_counted(self, _clock, warning):
        error = RuntimeError("provider offline")

        self.assertTrue(report_data_fallback("akshare", "industry_rank", error))
        self.assertFalse(report_data_fallback("akshare", "industry_rank", error))
        self.assertTrue(report_data_fallback("akshare", "industry_rank", error))

        self.assertEqual(warning.call_count, 2)
        self.assertEqual(warning.call_args_list[1].args[5], 1)

    @patch("utils.fallback_log._LOGGER.warning")
    def test_context_is_logged_without_raising(self, warning):
        emitted = report_data_fallback(
            "akshare",
            "stock_news",
            ValueError("bad response"),
            context={"symbol": "600519"},
            throttle_seconds=0,
        )

        self.assertTrue(emitted)
        self.assertIn('"symbol":"600519"', warning.call_args.args[6])


if __name__ == "__main__":
    unittest.main()
