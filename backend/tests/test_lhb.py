import unittest
from datetime import datetime
from unittest.mock import patch

import pandas as pd
from fastapi import HTTPException

from api import lhb


class LhbApiTests(unittest.TestCase):
    def setUp(self):
        lhb._top_cache.clear()
        lhb._daily_cache.clear()

    @patch("akshare.stock_lhb_ggtj_sina")
    def test_top_converts_provider_wan_to_display_yi(self, provider):
        provider.return_value = pd.DataFrame(
            [{
                "股票代码": "688008",
                "股票名称": "澜起科技",
                "上榜次数": 1,
                "累积购买额": 399476.90,
                "累积卖出额": 267150.70,
                "净额": 132326.20,
                "买入席位数": 5,
                "卖出席位数": 3,
            }]
        )

        result = lhb.lhb_top(days=5)

        self.assertEqual(result["amount_unit"], "亿元")
        self.assertEqual(result["source"], "新浪财经（AkShare）")
        self.assertEqual(result["stocks"][0]["buy_amount"], 39.95)
        self.assertEqual(result["stocks"][0]["sell_amount"], 26.72)
        self.assertEqual(result["stocks"][0]["net_amount"], 13.23)

    @patch("akshare.stock_lhb_detail_daily_sina")
    def test_daily_converts_provider_wan_to_display_yi(self, provider):
        provider.return_value = pd.DataFrame(
            [{
                "股票代码": "002281",
                "股票名称": "光迅科技",
                "收盘价": 88.88,
                "对应值": 16.2,
                "成交量": 123456,
                "成交额": 1342419.6498,
                "指标": "振幅值达15%的证券",
            }]
        )

        result = lhb.lhb_daily(date="20260721")

        self.assertTrue(result["is_published"])
        self.assertEqual(result["amount_unit"], "亿元")
        self.assertEqual(result["entries"][0]["amount"], 134.24)

    @patch("akshare.stock_lhb_detail_daily_sina", side_effect=KeyError("股票代码"))
    def test_daily_no_data_is_not_reported_as_provider_failure(self, _provider):
        result = lhb.lhb_daily(date=datetime.now().strftime("%Y%m%d"))

        self.assertFalse(result["is_published"])
        self.assertEqual(result["entries"], [])
        self.assertIn("尚未发布", result["message"])

    @patch("akshare.stock_lhb_detail_daily_sina", side_effect=ConnectionError("offline"))
    def test_daily_real_provider_failure_stays_visible(self, _provider):
        with self.assertRaises(HTTPException) as raised:
            lhb.lhb_daily(date="20260721")

        self.assertEqual(raised.exception.status_code, 500)
        self.assertIn("offline", raised.exception.detail)


if __name__ == "__main__":
    unittest.main()
