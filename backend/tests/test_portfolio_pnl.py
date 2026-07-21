import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.portfolio import _build_daily_trade_flows, _calculate_today_pnl  # noqa: E402


class PortfolioPnlTests(unittest.TestCase):
    def test_same_day_position_uses_actual_cost_without_trade_flow(self):
        position = {
            "symbol": "002185",
            "buy_date": "2026-07-21",
            "buy_price": 17.47,
            "quantity": 500,
        }

        pnl, basis = _calculate_today_pnl(
            position,
            current=18.35,
            prev_close=16.85,
            day="2026-07-21",
        )

        self.assertEqual(round(pnl, 2), 440.00)
        self.assertEqual(basis, "same_day_cost")

    def test_existing_position_without_trades_uses_previous_close(self):
        position = {
            "symbol": "603039",
            "buy_date": "2026-07-16",
            "buy_price": 31.895,
            "quantity": 200,
        }

        pnl, basis = _calculate_today_pnl(
            position,
            current=29.50,
            prev_close=28.895,
            day="2026-07-21",
        )

        self.assertEqual(round(pnl, 2), 121.00)
        self.assertEqual(basis, "previous_close")

    def test_synced_buy_flow_separates_pre_buy_price_move(self):
        flows = _build_daily_trade_flows([
            {
                "symbol": "600584",
                "action": "buy",
                "quantity": 100,
                "price": 75.551,
                "trade_date": "2026-07-21",
                "position_synced": True,
            },
            {
                "symbol": "600584",
                "action": "buy",
                "quantity": 10,
                "price": 70,
                "trade_date": "2026-07-21",
                "position_synced": False,
            },
        ], day="2026-07-21")
        position = {
            "symbol": "600584",
            "buy_date": "2026-07-21",
            "buy_price": 75.551,
            "quantity": 100,
        }

        pnl, basis = _calculate_today_pnl(
            position,
            current=84.69,
            prev_close=77.00,
            today_flow=flows["600584"],
            day="2026-07-21",
        )

        self.assertEqual(round(pnl, 2), 913.90)
        self.assertEqual(basis, "trade_flow")

    def test_buy_and_sell_flows_include_opening_position(self):
        position = {
            "symbol": "000001",
            "buy_date": "2026-07-01",
            "buy_price": 8,
            "quantity": 200,
        }
        buy_flow = {
            "buy_quantity": 100,
            "buy_amount": 1200,
            "sell_quantity": 0,
            "sell_amount": 0,
        }
        sell_flow = {
            "buy_quantity": 0,
            "buy_amount": 0,
            "sell_quantity": 100,
            "sell_amount": 1200,
        }

        buy_pnl, _ = _calculate_today_pnl(position, 13, 10, buy_flow, "2026-07-21")
        self.assertEqual(round(buy_pnl, 2), 400.00)

        position["quantity"] = 100
        sell_pnl, _ = _calculate_today_pnl(position, 13, 10, sell_flow, "2026-07-21")
        self.assertEqual(round(sell_pnl, 2), 500.00)


if __name__ == "__main__":
    unittest.main()
