import unittest

from services.verdict_service import (
    compute_market_decision,
    compute_quick_decision,
    compute_sector_decision,
)


def _tech(ma5=2, ma20=5, ma60=9, vol=1.5, macd="多头", rsi=60):
    return {
        "today": {"open": 10.0, "high": 10.8, "low": 9.9, "close": 10.7},
        "technical": {
            "ma5_pct": ma5,
            "ma20_pct": ma20,
            "ma60_pct": ma60,
            "vol_ratio": vol,
            "macd_status": macd,
            "rsi14": rsi,
            "bb_pct": 0.72,
        },
        "trend": {"streak": 2},
    }


class MultiDimensionVerdictTests(unittest.TestCase):
    def test_same_pct_gets_different_verdict_from_structure(self):
        quote = {"price": 10.7, "pct_change": 2.0, "open": 10, "high": 10.8, "low": 9.9}
        strong = compute_quick_decision(quote, _tech(), {"market_pct": -0.3})
        weak = compute_quick_decision(
            quote,
            _tech(ma5=-3, ma20=-9, ma60=-15, vol=0.55, macd="空头", rsi=38),
            {"market_pct": 2.5},
        )
        self.assertGreater(strong["score"], weak["score"] + 12)
        self.assertNotEqual(strong["action"], weak["action"])

    def test_single_pct_cannot_create_high_confidence_sector_mainline(self):
        result = compute_sector_decision({"pct_num": 6.0})
        self.assertNotEqual(result["action"], "主线候选")
        self.assertLess(result["coverage"], 50)

    def test_sector_breadth_and_capital_confirm_mainline(self):
        result = compute_sector_decision({
            "pct_num": 3.2,
            "up_count": "42",
            "down_count": "5",
            "net_in": "5.8亿",
            "leader": "测试龙头",
        })
        self.assertEqual(result["action"], "主线候选")
        self.assertGreaterEqual(result["coverage"], 90)

    def test_market_uses_intraday_position_and_breadth(self):
        indices = [
            {"pct": 0.5, "price": 105, "high": 106, "low": 100},
            {"pct": 0.3, "price": 204, "high": 205, "low": 198},
        ]
        result = compute_market_decision(indices, {"total": 90, "up_count": 68, "down_count": 22})
        keys = {d["key"] for d in result["dimensions"]}
        self.assertIn("intraday", keys)
        self.assertIn("breadth", keys)
        self.assertGreater(result["score"], 55)


if __name__ == "__main__":
    unittest.main()
