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

    @patch("akshare.stock_lhb_detail_daily_sina")
    def test_daily_sorts_entries_by_amount_descending(self, provider):
        provider.return_value = pd.DataFrame([
            {
                "股票代码": "000001",
                "股票名称": "低成交额",
                "收盘价": 10,
                "对应值": 7,
                "成交量": 100,
                "成交额": 10000,
                "指标": "测试",
            },
            {
                "股票代码": "000002",
                "股票名称": "高成交额",
                "收盘价": 20,
                "对应值": 8,
                "成交量": 200,
                "成交额": 50000,
                "指标": "测试",
            },
        ])

        result = lhb.lhb_daily(date="20260721")

        self.assertEqual(result["sort_by"], "amount_desc")
        self.assertEqual(
            [entry["symbol"] for entry in result["entries"]],
            ["000002", "000001"],
        )

    @patch("akshare.stock_lhb_detail_em")
    @patch("akshare.stock_lhb_detail_daily_sina")
    def test_daily_fills_missing_reason_from_eastmoney(self, sina_provider, em_provider):
        sina_provider.return_value = pd.DataFrame([{
            "股票代码": "300604",
            "股票名称": "长川科技",
            "收盘价": 80.5,
            "对应值": 20.0,
            "成交量": 100,
            "成交额": 1204800,
            "指标": float("nan"),
        }])
        em_provider.return_value = pd.DataFrame([{
            "代码": "300604",
            "涨跌幅": 20.0,
            "换手率": 8.47,
            "上榜原因": "日涨幅达到15%的前5只证券",
        }])

        result = lhb.lhb_daily(date="20260721")

        self.assertEqual(
            result["entries"][0]["reason"],
            "日涨幅达到15%的前5只证券",
        )
        self.assertNotIn("nan", result["entries"][0]["reason"].lower())

    @patch("akshare.stock_lhb_detail_em")
    @patch("akshare.stock_lhb_detail_daily_sina")
    def test_daily_matches_multiple_missing_reasons_by_metric(self, sina_provider, em_provider):
        sina_provider.return_value = pd.DataFrame([
            {
                "股票代码": "300534",
                "股票名称": "陇神戎发",
                "收盘价": 13.8,
                "对应值": 39.53,
                "成交量": 100,
                "成交额": 275067,
                "指标": float("nan"),
            },
            {
                "股票代码": "300534",
                "股票名称": "陇神戎发",
                "收盘价": 13.8,
                "对应值": 33.53,
                "成交量": 100,
                "成交额": 150443,
                "指标": float("nan"),
            },
        ])
        em_provider.return_value = pd.DataFrame([
            {
                "代码": "300534",
                "涨跌幅": 14.62,
                "换手率": 39.53,
                "上榜原因": "连续三个交易日内，涨幅偏离值累计达到30%的证券",
            },
            {
                "代码": "300534",
                "涨跌幅": 14.62,
                "换手率": 39.53,
                "上榜原因": "日换手率达到30%的前5只证券",
            },
        ])

        result = lhb.lhb_daily(date="20260721")
        reasons_by_value = {
            entry["deviation"]: entry["reason"] for entry in result["entries"]
        }

        self.assertIn("换手率", reasons_by_value[39.53])
        self.assertIn("连续三个交易日", reasons_by_value[33.53])

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
