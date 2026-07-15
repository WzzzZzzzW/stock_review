import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("GLM_API_KEY", "test-glm-key")
os.environ.setdefault("ARK_API_KEY", "test-ark-key")

from config import settings  # noqa: E402
from services.ai_client import (  # noqa: E402
    _ArkStream,
    _build_payload,
    _is_web_search_unavailable,
    _remove_web_search,
    _parse_response,
    ArkAPIError,
)


class _FakeStreamResponse:
    def __init__(self, events):
        self.events = events
        self.closed = False

    def iter_lines(self):
        for event in self.events:
            yield b"data: " + json.dumps(event, ensure_ascii=False).encode("utf-8")
        yield b"data: [DONE]"

    def close(self):
        self.closed = True


class AIClientAdapterTests(unittest.TestCase):
    def test_build_payload_maps_chat_messages_and_function_tools(self):
        payload, timeout = _build_payload("test-model", {
            "messages": [
                {"role": "system", "content": "只给结论"},
                {"role": "user", "content": "查股票"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "snapshot", "arguments": '{"symbol":"002371"}'},
                    }],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "结果"},
            ],
            "tools": [{
                "type": "function",
                "function": {
                    "name": "snapshot",
                    "description": "行情快照",
                    "parameters": {"type": "object", "properties": {}},
                },
            }],
            "max_tokens": 1200,
            "timeout": 90,
        })

        self.assertEqual(timeout, 90)
        self.assertEqual(payload["instructions"], "只给结论")
        self.assertEqual(payload["max_output_tokens"], 1200)
        self.assertFalse(payload["store"])
        self.assertEqual(payload["tools"][0]["name"], "snapshot")
        self.assertEqual(payload["input"][1]["type"], "function_call")
        self.assertEqual(payload["input"][2]["type"], "function_call_output")

    def test_build_payload_adds_web_search_without_local_tools(self):
        with patch.object(settings, "ark_web_search", True):
            payload, _ = _build_payload("test-model", {
                "messages": [{"role": "user", "content": "今天有什么热点新闻"}],
            })

        self.assertEqual(payload["tools"], [{"type": "web_search", "max_keyword": 3}])
        self.assertEqual(payload["tool_choice"], "auto")

    def test_tool_choice_none_is_preserved(self):
        payload, _ = _build_payload("test-model", {
            "messages": [{"role": "user", "content": "不要调用工具"}],
            "tools": [{"type": "web_search", "max_keyword": 3}],
            "tool_choice": "none",
        })

        self.assertEqual(payload["tool_choice"], "none")

    def test_unavailable_web_search_downgrades_without_hallucinating(self):
        error = ArkAPIError(
            "Your account has not activated web search. CC_content_plugin",
            status_code=404,
        )
        self.assertTrue(_is_web_search_unavailable(error))

        payload = _remove_web_search({
            "model": "test-model",
            "input": [{"role": "user", "content": "今天的新闻"}],
            "tools": [{"type": "web_search", "max_keyword": 3}],
            "tool_choice": "auto",
        })
        self.assertNotIn("tools", payload)
        self.assertIn("不得编造实时新闻", payload["instructions"])

    def test_parse_response_preserves_text_reasoning_and_finish_reason(self):
        response = _parse_response({
            "id": "resp_1",
            "model": "test-model",
            "status": "completed",
            "output": [
                {"type": "reasoning", "summary": [{"text": "分析过程"}]},
                {"type": "message", "content": [{"type": "output_text", "text": "最终结论"}]},
            ],
        })

        choice = response.choices[0]
        self.assertEqual(choice.message.content, "最终结论")
        self.assertEqual(choice.message.reasoning_content, "分析过程")
        self.assertEqual(choice.finish_reason, "stop")

    def test_parse_response_maps_function_call(self):
        response = _parse_response({
            "status": "completed",
            "output": [{
                "type": "function_call",
                "call_id": "call_2",
                "name": "snapshot",
                "arguments": '{"symbol":"002371"}',
            }],
        })

        choice = response.choices[0]
        self.assertEqual(choice.finish_reason, "tool_calls")
        self.assertEqual(choice.message.tool_calls[0].id, "call_2")
        self.assertEqual(choice.message.tool_calls[0].function.name, "snapshot")

    def test_parse_response_raises_for_failed_status(self):
        with self.assertRaisesRegex(RuntimeError, "模型内部错误"):
            _parse_response({
                "status": "failed",
                "error": {"message": "模型内部错误"},
            })

    def test_stream_emits_text_and_closes_response(self):
        fake = _FakeStreamResponse([
            {"type": "response.output_text.delta", "delta": "流式"},
            {"type": "response.output_text.delta", "delta": "成功"},
            {"type": "response.completed", "response": {"status": "completed"}},
        ])

        chunks = list(_ArkStream(fake))
        text = "".join(chunk.choices[0].delta.content or "" for chunk in chunks)
        self.assertEqual(text, "流式成功")
        self.assertIsNone(chunks[-1].choices[0].delta.content)
        self.assertTrue(fake.closed)


if __name__ == "__main__":
    unittest.main()
