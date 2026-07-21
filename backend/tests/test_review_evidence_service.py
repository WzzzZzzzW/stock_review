import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from data.stock_data import (
    _fund_flow_from_eastmoney_curl,
    _money_text_to_yuan,
    get_stock_fund_flow_rank_today,
)
from services.review_evidence_service import _stock_fund_flows, build_review_evidence
from services.today_review_service import _build_ai_block_analysis


class ReviewEvidenceTests(unittest.TestCase):
    def test_money_text_to_yuan(self):
        self.assertEqual(_money_text_to_yuan("19.33亿"), 1933000000.0)
        self.assertEqual(_money_text_to_yuan("3500万"), 35000000.0)

    @patch("akshare.stock_fund_flow_individual")
    def test_ths_today_rank_is_normalized_and_filtered(self, stock_flow):
        import pandas as pd
        import data.stock_data as stock_data

        stock_data._ths_today_flow_cache = None
        stock_flow.return_value = pd.DataFrame([{
            "股票代码": 600584,
            "股票简称": "长电科技",
            "流入资金": "114.02亿",
            "流出资金": "94.69亿",
            "净额": "19.33亿",
            "成交额": "208.70亿",
        }])

        result = get_stock_fund_flow_rank_today(["600584", "000001"])

        self.assertEqual(set(result), {"600584"})
        self.assertEqual(result["600584"]["main_net"], 1933000000.0)
        self.assertEqual(result["600584"]["main_net_pct"], 9.26)
        self.assertEqual(result["600584"]["source"], "ths_market_rank")

    @patch("data.stock_data.subprocess.run")
    def test_curl_fallback_parses_structured_fund_flow(self, run):
        run.return_value = SimpleNamespace(
            stdout='{"data":{"klines":["2026-07-21,-165296144,224878128,-59581984,-41571712,-123724432,-1.41,1.92,-0.51,-0.35,-1.05"]}}'
        )

        result = _fund_flow_from_eastmoney_curl("002185", "sz")

        self.assertEqual(result["date"], "2026-07-21")
        self.assertEqual(result["main_net"], -165296144.0)
        self.assertEqual(result["main_net_pct"], -1.41)
        self.assertEqual(result["source"], "eastmoney_curl_fallback")

    @patch("data.stock_data.get_stock_fund_flow_day")
    @patch("data.stock_data.get_stock_fund_flow_rank_today", return_value={})
    def test_stock_flow_only_accepts_review_date(self, _rank, flow):
        flow.side_effect = [
            {"date": "2026-07-21", "main_net": 150000000, "main_net_pct": 2.5},
            {"date": "2026-07-18", "main_net": -90000000, "main_net_pct": -1.2},
        ]

        result = _stock_fund_flows(["600001", "600002"], "2026-07-21")

        self.assertTrue(result["600001"]["available"])
        self.assertEqual(result["600001"]["main_net_yi"], 1.5)
        self.assertFalse(result["600002"]["available"])
        self.assertIn("日期与复盘日期不一致", result["600002"]["note"])

    @patch("services.review_evidence_service.datetime.date")
    @patch("data.stock_data.get_stock_fund_flow_day", return_value={})
    @patch("data.stock_data.get_stock_fund_flow_rank_today")
    def test_stock_flow_uses_ths_batch_when_eastmoney_is_empty(
        self, rank, _flow, date
    ):
        date.today.return_value.isoformat.return_value = "2026-07-21"
        rank.return_value = {
            "600584": {
                "date": "2026-07-21",
                "main_net": 1933000000,
                "main_net_pct": 9.26,
                "source": "ths_market_rank",
                "source_note": "同花顺口径。",
            }
        }

        result = _stock_fund_flows(["600584"], "2026-07-21")

        rank.assert_called_once_with(["600584"])
        self.assertTrue(result["600584"]["available"])
        self.assertEqual(result["600584"]["main_net_yi"], 19.33)
        self.assertEqual(result["600584"]["source"], "ths_market_rank")
        self.assertEqual(result["600584"]["basis"], "同花顺口径。")

    @patch("services.review_evidence_service._stock_fund_flows")
    @patch("services.review_evidence_service._sector_flow_changes")
    @patch("data.stock_data.get_industry_map")
    @patch("api.industry.industry_summary")
    def test_shared_evidence_joins_stock_sector_and_capital(
        self, industry_summary, industry_map, flow_changes, stock_flows
    ):
        industry_summary.return_value = {
            "updated_at": "15:00",
            "industries": [{
                "name": "半导体", "pct_num": 4.2, "up_count": "80",
                "down_count": "20", "net_in": "42.88", "leader": "测试龙头",
            }],
        }
        industry_map.return_value = {"600001": "半导体"}
        flow_changes.return_value = {"半导体": {"net_in_change_yi": 8.5}}
        stock_flows.return_value = {"600001": {"available": True, "main_net_yi": 1.2}}

        result = build_review_evidence(["600001"], "2026-07-21")

        stock = result["by_symbol"]["600001"]
        self.assertEqual(stock["industry"], "半导体")
        self.assertEqual(stock["sector"]["breadth_pct"], 80.0)
        self.assertEqual(stock["sector"]["net_in_yi"], 42.88)
        self.assertEqual(stock["sector"]["fund_change"]["net_in_change_yi"], 8.5)
        self.assertEqual(stock["fund_flow"]["main_net_yi"], 1.2)


class TodayReviewAiTests(unittest.TestCase):
    @patch("services.ai_client.make_client")
    def test_ai_seven_blocks_are_kept_instead_of_template_override(self, make_client):
        long_text = "### 结论\n" + "资金、量价、行业广度和龙头承接共同确认。" * 24
        parsed = {
            "market_review": long_text,
            "portfolio_review": "### 甲\n" + "甲的资金、量价和行业证据共同确认。" * 24,
            "watchlist_review": "### AI自选裁决\n乙。" + "模型基于个股和行业资金给出唯一动作。" * 24,
            "industry_review": long_text,
            "international_review": long_text,
            "risk_opportunity": {
                "risks": [{"title": "风险", "industry": "半导体", "stocks": [{"symbol": "600001", "name": "甲"}], "evidence": "资金与广度转弱", "action": "降级"}],
                "opportunities": [{"title": "机会", "industry": "通信", "stocks": [{"symbol": "600002", "name": "乙"}], "evidence": "资金与量价共振", "action": "进攻"}],
            },
            "tomorrow_watch": [{"theme": "验证通信", "industry": "通信", "stocks": [{"symbol": "600002", "name": "乙"}], "evidence": "资金增强", "trigger": "放量承接", "invalidation": "资金转负", "action": "满足才参与"}],
        }
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=__import__("json").dumps(parsed, ensure_ascii=False)))]
        )
        client = MagicMock()
        client.chat.completions.create.return_value = response
        make_client.return_value = client

        result = _build_ai_block_analysis(
            {},
            {"positions": [{"symbol": "600001", "name": "甲"}]},
            {"stocks": [{"symbol": "600002", "name": "乙"}]},
            {"top_up": [], "top_down": []},
            {"items": []}, {},
        )

        self.assertTrue(result["watchlist_review"].startswith("### AI自选裁决"))
        self.assertEqual(result["risk_opportunity"]["risks"][0]["stocks"][0]["name"], "甲")
        self.assertEqual(result["tomorrow_watch"][0]["trigger"], "放量承接")
        self.assertEqual(result["source"], "ai")

    @patch("services.ai_client.make_client")
    def test_missing_watchlist_names_trigger_ai_repair(self, make_client):
        long_text = "### 结论\n" + "资金、量价、行业广度和龙头承接共同确认。" * 24
        parsed = {
            "market_review": long_text,
            "portfolio_review": long_text,
            "watchlist_review": "### 错误名单\n" + "遗漏了真实自选。" * 40,
            "industry_review": long_text,
            "international_review": long_text,
            "risk_opportunity": {"risks": [], "opportunities": []},
            "tomorrow_watch": [],
        }
        first = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=__import__("json").dumps(parsed, ensure_ascii=False)))]
        )
        repair_text = "### 乙（600002）\n" + "乙的个股资金、量价和所属行业资金共同确认，动作是保留但不追。" * 20
        second = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=repair_text))]
        )
        client = MagicMock()
        client.chat.completions.create.side_effect = [first, second]
        make_client.return_value = client

        result = _build_ai_block_analysis(
            {}, {"positions": []}, {"stocks": [{"symbol": "600002", "name": "乙"}]},
            {"top_up": [], "top_down": []}, {"items": []}, {},
        )

        self.assertEqual(result["watchlist_review"], repair_text)
        self.assertEqual(client.chat.completions.create.call_count, 2)
        self.assertFalse(result.get("validation_notes"))


if __name__ == "__main__":
    unittest.main()
