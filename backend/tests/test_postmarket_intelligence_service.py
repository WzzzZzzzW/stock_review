import os
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.postmarket_intelligence_service import (  # noqa: E402
    _intraday_path,
    _mainlines,
    _market_metrics,
    _regime,
)


class PostmarketIntelligenceTests(unittest.TestCase):
    def test_weight_supported_broad_decline_is_not_called_repair(self):
        market = {
            "breadth": {"up": 1709, "down": 3415, "up_ratio": 32.9},
            "limit_stats": {
                "zt_count": 51,
                "dt_count": 185,
                "broken_count": 40,
                "broken_ratio": 44.0,
            },
            "indices": [
                {"name": "上证", "pct": 0.85},
                {"name": "深成指", "pct": -0.71},
                {"name": "创业板", "pct": 0.42},
                {"name": "沪深300", "pct": 1.53},
            ],
            "cap_perf": [
                {"tier": "超大盘 >1000亿", "avg_pct": 1.18},
                {"tier": "小盘 <50亿", "avg_pct": -3.46},
            ],
            "amount": {"total_yi": 27019.21},
            "sentiment": {"score": 36},
        }
        metrics = _market_metrics(market)
        verdict = _regime(metrics, {"available": True, "score_delta": -11})

        self.assertEqual(verdict["regime"], "权重护盘下的普跌退潮")
        self.assertEqual(verdict["stance"], "防守")
        self.assertEqual(verdict["position_cap"], 20)
        self.assertNotIn("扩散修复", verdict["summary"])

    @patch("db.market_radar_db.list_snapshots", return_value=[])
    def test_missing_snapshots_are_reported_instead_of_invented(self, _mock_snapshots):
        path, snapshots = _intraday_path("2026-07-20")

        self.assertFalse(path["available"])
        self.assertEqual(path["snapshot_count"], 0)
        self.assertIn("不推断", path["summary"])
        self.assertEqual(snapshots, [])

    def test_risk_state_cannot_be_promoted_to_confirmed_mainline(self):
        first = {
            "captured_at": "2026-07-20T10:00:00",
            "phase": "intraday",
            "sectors": [{
                "name": "测试板块", "score": 82, "pct": 4.0, "breadth": 0.9,
                "net_in": 20, "rank": 1, "leader": "测试龙头",
            }],
        }
        last = {
            "captured_at": "2026-07-20T15:00:00",
            "phase": "postmarket",
            "sectors": [{
                "name": "测试板块", "score": 70, "pct": 1.0, "breadth": 0.7,
                "net_in": 10, "rank": 1, "leader": "测试龙头",
            }],
        }

        row = _mainlines([first, last])[0]

        self.assertEqual(row["state"], "高位分歧")
        self.assertEqual(row["level"], "分歧降级")
        self.assertEqual(row["action"], "退出主计划")


if __name__ == "__main__":
    unittest.main()
