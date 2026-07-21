import os
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.postmarket_intelligence_service import (  # noqa: E402
    _core_judgements,
    _intraday_path,
    _mainline_analysis,
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

    def test_market_metrics_capture_volume_price_and_real_stock_experience(self):
        market = {
            "breadth": {"up": 2800, "down": 2200, "up_ratio": 56, "up_over5": 400, "down_over5": 100},
            "limit_stats": {"zt_count": 80, "dt_count": 10, "broken_ratio": 18, "max_continuity": 6},
            "indices": [
                {"pct": 2.0, "price": 109, "high": 110, "low": 100},
                {"pct": 1.0, "price": 205, "high": 210, "low": 190},
            ],
            "cap_perf": [
                {"tier": "超大盘 >1000亿", "count": 100, "avg_pct": 3.0},
                {"tier": "小盘 <50亿", "count": 900, "avg_pct": -0.5},
            ],
            "amount": {"total_yi": 20000},
        }

        metrics = _market_metrics(market)

        self.assertAlmostEqual(metrics["equal_weight_avg"], -0.15)
        self.assertAlmostEqual(metrics["index_equal_gap"], 1.65)
        self.assertEqual(metrics["close_position"], 82.5)
        self.assertEqual(metrics["tail_ratio"], 4.0)

    def test_core_judgements_do_not_reduce_market_to_limit_counts(self):
        metrics = {
            "amount": 20000, "index_avg": 1.5, "equal_weight_avg": -0.2,
            "index_equal_gap": 1.7, "close_position": 75, "up_ratio": 48,
            "size_gap": 2.5, "tail_ratio": 0.8, "dt": 40, "zt": 60,
            "broken_ratio": 38, "max_continuity": 5,
        }
        rows = _core_judgements(
            metrics,
            {"amount_ratio_5": 1.2},
            {"available": False},
            [],
        )

        self.assertEqual([row["key"] for row in rows], [
            "volume_price", "earning_effect", "short_ecology", "rotation",
        ])
        self.assertIn("权重", rows[0]["conclusion"])
        self.assertIn("真实持股体验", rows[1]["conclusion"])
        self.assertIn("失败样本", rows[2]["conclusion"])

    def test_related_industries_are_grouped_into_one_mainline_theme(self):
        rows = [
            {"name": "半导体", "level": "确认主线", "state": "主线扩散", "action": "保留进攻资格", "score": 82,
             "pct": 5, "breadth": 90, "net_in": 40, "leader": "A", "persistence": 90, "evidence": "x"},
            {"name": "元件", "level": "确认主线", "state": "主线扩散", "action": "保留进攻资格", "score": 78,
             "pct": 4, "breadth": 80, "net_in": 20, "leader": "B", "persistence": 80, "evidence": "y"},
        ]

        result = _mainline_analysis(rows, {"sectors": {"top_down": []}})

        self.assertEqual(len(result["themes"]), 1)
        self.assertEqual(result["themes"][0]["name"], "电子产业链")
        self.assertEqual(result["themes"][0]["members"], ["半导体", "元件"])
        self.assertEqual(result["themes"][0]["net_in"], 60.0)


if __name__ == "__main__":
    unittest.main()
