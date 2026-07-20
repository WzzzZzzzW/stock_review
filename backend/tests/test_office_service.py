import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services import office_service


def _response(content: str, finish_reason: str = "stop"):
    message = SimpleNamespace(content=content, tool_calls=None, reasoning_content=None)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


class OfficeServiceAnswerTests(unittest.TestCase):
    @patch("services.office_service.get_tools_for_agent", return_value=[])
    @patch("services.office_service.make_client")
    def test_stream_retries_when_reasoning_uses_all_output_tokens(
        self, make_client_mock, _get_tools_mock
    ):
        create = MagicMock(side_effect=[
            _response("半截回答", "length"),
            _response("明确估值：35元。"),
        ])
        make_client_mock.return_value.chat.completions.create = create

        events = list(office_service.chat_with_agent_stream(
            "copilot", "给我一个数字，你觉得他值多少"
        ))

        self.assertEqual(events[-1]["type"], "final")
        self.assertEqual(events[-1]["response"], "明确估值：35元。")
        retry = create.call_args_list[1].kwargs
        self.assertEqual(retry["tools"], [])
        self.assertEqual(retry["tool_choice"], "none")
        self.assertEqual(retry["thinking"], {"type": "disabled"})
        self.assertEqual(retry["max_tokens"], office_service.FINAL_ANSWER_MAX_TOKENS)

    @patch("services.office_service.get_tools_for_agent", return_value=[])
    @patch("services.office_service.make_client")
    def test_stream_raises_instead_of_returning_empty_final(
        self, make_client_mock, _get_tools_mock
    ):
        create = MagicMock(side_effect=[_response(""), _response("")])
        make_client_mock.return_value.chat.completions.create = create

        with self.assertRaisesRegex(RuntimeError, "仍未输出正文"):
            list(office_service.chat_with_agent_stream("copilot", "你是谁"))


if __name__ == "__main__":
    unittest.main()
