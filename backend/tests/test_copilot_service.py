import json
import unittest
from unittest.mock import patch

from services.copilot_service import (
    build_copilot_context,
    enforce_evidence_boundary,
    get_copilot_role,
    list_copilot_roles,
)


class CopilotContextTests(unittest.TestCase):
    @patch("services.copilot_service.market_radar_db.list_snapshots")
    @patch("services.copilot_service.get_market_radar")
    def test_sector_context_contains_server_side_evidence(self, radar_mock, snapshots_mock):
        radar_mock.return_value = {
            "actual_phase": "intraday",
            "updated_at": "10:15:00",
            "market": {"decision": {"action": "主动收缩", "score": 35}},
            "rotation": {"all": [{"name": "半导体", "pct": -5.35, "breadth": 0.11, "net_in": 42.88}]},
            "news": [{"title": "芯片事件", "affected_sectors": ["半导体"]}],
            "personal": {
                "positions": [{"name": "北方华创", "industry": "半导体"}],
                "watchlist": [{"name": "其他股票", "industry": "软件开发"}],
                "summary": "1只相关",
            },
            "data_notes": ["净流入为推算口径"],
        }
        snapshots_mock.return_value = [{
            "captured_at": "2026-07-16T10:10:00",
            "phase": "intraday",
            "sectors": [{"name": "半导体", "pct": -4.8, "breadth": 0.16, "net_in": 35, "score": 45, "rank": 50}],
        }]

        result = build_copilot_context({
            "page": "盘中市场雷达",
            "phase": "intraday",
            "target": {"type": "sector", "name": "半导体"},
        })
        payload = result["extra"].split("\n", 1)[1].split("\n\n## 本轮角色要求", 1)[0]
        data = json.loads(payload)

        self.assertEqual(data["sector"]["net_in"], 42.88)
        self.assertEqual(data["sector_recent_snapshots"][0]["score"], 45)
        self.assertEqual(data["related_news"][0]["title"], "芯片事件")
        self.assertEqual(data["related_positions_and_watchlist"][0]["name"], "北方华创")
        self.assertEqual(len(data["related_positions_and_watchlist"]), 1)

    def test_roles_route_to_existing_office_agents(self):
        roles = {row["id"] for row in list_copilot_roles()}
        self.assertEqual(
            roles,
            {"market", "fundamentals", "news", "technical", "sentiment", "risk", "zhengxi"},
        )
        role_id, role = get_copilot_role("fundamentals")
        self.assertEqual(role_id, "fundamentals")
        self.assertEqual(role["agent_id"], "fundamentals")

    @patch("services.copilot_service._role_guidance", return_value="郑希方法论证据")
    @patch("services.copilot_service.market_radar_db.list_snapshots", return_value=[])
    @patch("services.copilot_service.get_market_radar")
    def test_zhengxi_role_is_embedded_in_verified_context(self, radar_mock, _snapshots, _guidance):
        radar_mock.return_value = {
            "actual_phase": "intraday",
            "updated_at": "10:15:00",
            "market": {},
            "rotation": {"all": []},
            "news": [],
            "personal": {},
        }
        result = build_copilot_context({"page": "盘中"}, "zhengxi", "怎么看半导体")
        self.assertIn('"assistant_role":{"id":"zhengxi","title":"郑希风格"}', result["extra"])
        self.assertIn("郑希方法论证据", result["extra"])

    def test_sector_answer_removes_unsupported_causal_claims(self):
        response = (
            "**结论**：流入没有取得定价权。\n\n"
            "价格下跌5.35%，广度仅11%。\n\n"
            "合理的推断方向是资金集中在少数权重股。\n\n"
            "三个解释（按可能性排序）：\n\n"
            "早盘流入、尾盘砸盘，但无法验证这一点。\n\n"
            "**影响**：当前弱势回避。"
        )
        cleaned = enforce_evidence_boundary(response, {
            "target": {"type": "sector", "name": "半导体"}
        })

        self.assertIn("流入没有取得定价权", cleaned)
        self.assertIn("价格下跌5.35%", cleaned)
        self.assertNotIn("权重股", cleaned)
        self.assertNotIn("尾盘砸盘", cleaned)
        self.assertIn("当前没有板块内各股票的资金贡献", cleaned)


if __name__ == "__main__":
    unittest.main()
