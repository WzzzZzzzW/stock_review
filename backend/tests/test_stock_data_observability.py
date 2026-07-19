import unittest
from unittest.mock import patch

from data import stock_data


class StockDataObservabilityTests(unittest.TestCase):
    def setUp(self):
        stock_data._business_cache.clear()
        stock_data._history_cache.clear()

    @patch("data.stock_data.report_data_fallback")
    @patch("akshare.stock_zyjs_ths", side_effect=RuntimeError("provider offline"))
    def test_main_business_keeps_empty_fallback_and_reports_error(
        self, _provider, report
    ):
        result = stock_data.fetch_main_business("600519")

        self.assertEqual(result, {"business": "", "products": "", "scope": ""})
        report.assert_called_once()
        self.assertEqual(report.call_args.args[:2], ("akshare", "main_business"))
        self.assertEqual(report.call_args.kwargs["context"], {"symbol": "600519"})

    @patch("data.stock_data.report_data_fallback")
    @patch("akshare.stock_board_industry_summary_ths", side_effect=ValueError("bad payload"))
    def test_industry_rank_keeps_dict_contract_and_reports_error(
        self, _provider, report
    ):
        result = stock_data.get_industry_rank("半导体")

        self.assertEqual(result, {})
        report.assert_called_once()
        self.assertEqual(report.call_args.args[:2], ("akshare", "industry_rank"))

    @patch("data.stock_data._baostock_history_batch", return_value={})
    @patch("data.stock_data.report_data_fallback")
    @patch("akshare.stock_zh_a_hist", side_effect=ConnectionError("network down"))
    def test_history_batch_keeps_empty_frame_and_reports_primary_source_error(
        self, _provider, report, _fallback
    ):
        result = stock_data.fetch_history_batch(["600519"], days_back=20)

        self.assertIn("600519", result)
        self.assertTrue(result["600519"].empty)
        report.assert_called_once()
        self.assertEqual(report.call_args.args[:2], ("akshare", "backtest_history"))


if __name__ == "__main__":
    unittest.main()
