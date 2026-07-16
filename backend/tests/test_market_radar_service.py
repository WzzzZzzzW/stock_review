import unittest
from unittest.mock import patch

from services.market_radar_service import classify_sector_state, evaluate_radar_day


class MarketRadarStateTests(unittest.TestCase):
    def test_sector_expansion_requires_breadth_and_score(self):
        result = classify_sector_state(
            {"name": "半导体", "score": 74, "pct": 2.1, "breadth": 0.76, "net_in": 5.2, "rank": 2},
            {"name": "半导体", "score": 56, "pct": 0.7, "breadth": 0.51, "net_in": 1.1, "rank": 13},
        )
        self.assertEqual(result["state"], "主线扩散")
        self.assertEqual(result["tone"], "attack")
        self.assertGreater(result["velocity"], 10)

    def test_positive_pct_with_narrow_breadth_is_fake_breakout(self):
        result = classify_sector_state(
            {"name": "测试板块", "score": 54, "pct": 1.4, "breadth": 0.31, "net_in": -0.3, "rank": 24},
            {"name": "测试板块", "score": 52, "pct": 0.5, "breadth": 0.35, "net_in": 0.2, "rank": 22},
        )
        self.assertEqual(result["state"], "假突破")
        self.assertEqual(result["tone"], "risk")

    def test_breadth_collapse_marks_divergence(self):
        result = classify_sector_state(
            {"name": "电池", "score": 53, "pct": 0.2, "breadth": 0.39, "net_in": -1.5, "rank": 27},
            {"name": "电池", "score": 70, "pct": 2.6, "breadth": 0.72, "net_in": 4.1, "rank": 3},
        )
        self.assertIn(result["state"], {"高位分歧", "资金撤退"})
        self.assertEqual(result["tone"], "risk")

    @patch("services.market_radar_service.market_radar_db.list_events", return_value=[])
    @patch("services.market_radar_service.market_radar_db.list_snapshots")
    def test_postmarket_evaluation_checks_direction_and_sector_follow_through(self, snapshots, _events):
        snapshots.return_value = [
            {
                "phase": "intraday", "captured_at": "2026-07-16T09:35:00",
                "market": {"decision": {"action": "选择性进攻", "score": 62}},
                "sectors": [{"name": "半导体", "score": 70}, {"name": "软件开发", "score": 64}],
            },
            {
                "phase": "intraday", "captured_at": "2026-07-16T14:57:00",
                "market": {"decision": {"action": "选择性进攻", "score": 59}},
                "sectors": [{"name": "半导体", "score": 68}, {"name": "软件开发", "score": 48}],
            },
        ]
        result = evaluate_radar_day("2026-07-16")
        self.assertTrue(result["ready"])
        self.assertTrue(result["market"]["consistent"])
        self.assertEqual(result["sector_hit_rate"], 50)

    @patch("services.market_radar_service.market_radar_db.snapshot_summary")
    @patch("services.market_radar_service.market_radar_db.list_snapshots")
    def test_evaluation_explains_when_collector_started_after_close(self, snapshots, summary):
        snapshots.return_value = [
            {
                "phase": "postmarket",
                "captured_at": "2026-07-16T15:22:38",
                "market": {},
                "sectors": [],
            }
        ]
        summary.return_value = {
            "trade_date": "2026-07-16",
            "total": 1,
            "intraday": {"count": 0, "first_at": "", "last_at": ""},
            "phases": {
                "postmarket": {"count": 1, "first_at": "2026-07-16T15:22:38", "last_at": "2026-07-16T15:22:38"}
            },
        }
        result = evaluate_radar_day("2026-07-16")
        self.assertFalse(result["ready"])
        self.assertEqual(result["capture_status"]["state"], "missed_session")
        self.assertIn("15:22", result["verdict"])
        self.assertIn("不能倒推出", result["verdict"])


if __name__ == "__main__":
    unittest.main()
