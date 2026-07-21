import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services import sell_guidance_service


def _response(content: str, finish_reason: str = "stop"):
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


def _valid_payload(decision: str = "持有") -> str:
    return json.dumps({
        "decision": decision,
        "urgency": 25,
        "summary": "缩量回踩未破位，趋势仍可持有",
        "reduce_pct": 0,
        "sell_price": None,
        "stop_price": 29.5,
        "reasons": ["未跌破关键支撑"],
        "matched_rules": [],
        "advice": "跌破29.5元再离场",
    }, ensure_ascii=False)


class SellGuidanceTests(unittest.TestCase):
    @patch("services.sell_guidance_service.make_client")
    def test_diagnose_disables_thinking_and_implicit_tools(self, make_client_mock):
        create = MagicMock(return_value=_response(_valid_payload()))
        make_client_mock.return_value.chat.completions.create = create

        result = sell_guidance_service.diagnose(
            {"symbol": "600000", "name": "测试股", "buy_price": 30, "current_price": 31},
            {},
            [],
        )

        self.assertEqual(result["decision"], "持有")
        request = create.call_args.kwargs
        self.assertEqual(request["tools"], [])
        self.assertEqual(request["tool_choice"], "none")
        self.assertEqual(request["thinking"], {"type": "disabled"})
        self.assertEqual(request["max_tokens"], sell_guidance_service.SELL_GUIDANCE_MAX_TOKENS)

    @patch("services.sell_guidance_service.make_client")
    def test_diagnose_repairs_invalid_first_response(self, make_client_mock):
        create = MagicMock(side_effect=[
            _response("这不是JSON"),
            _response(_valid_payload("减仓")),
        ])
        make_client_mock.return_value.chat.completions.create = create

        result = sell_guidance_service.diagnose(
            {"symbol": "600000", "name": "测试股", "buy_price": 30, "current_price": 28},
            {},
            [],
        )

        self.assertEqual(result["decision"], "减仓")
        self.assertEqual(create.call_count, 2)
        repair_messages = create.call_args.kwargs["messages"]
        self.assertIn("只修复为完整合法的 JSON", repair_messages[-1]["content"])


if __name__ == "__main__":
    unittest.main()
