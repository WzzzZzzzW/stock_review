"""
统一 AI 客户端工厂。

聊天模型走火山方舟 Responses API，但对业务层继续暴露项目原有的
``client.chat.completions.create(...)`` 外形。这样普通回答、流式输出和
AI 办公室的函数工具调用都能切换供应商，而不需要改动二十多处业务代码。

视觉模型（GLM-4V）仍走独立客户端，不参与聊天模型切换。
"""
from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import requests
from openai import OpenAI

from config import settings


MODEL_CHAIN = [
    "deepseek-v4-flash-260425",
]
CHAT_MODEL = MODEL_CHAIN[0]

VISION_MODEL = "glm-4v-flash"

_STATE_PATH = Path(__file__).parent.parent / "data" / "ai_model_state.json"
_DEFAULT_TIMEOUT = 180
_WEB_SEARCH_TOOL = {"type": "web_search", "max_keyword": 3}
_QUOTA_HINTS = (
    "insufficient", "balance", "arrear", "quota", "exhaust",
    "expired", "limit exceeded", "余额", "额度", "欠费", "已用完",
)

_state_lock = threading.Lock()
_cur = {"idx": None, "date": None}
_web_search_available: bool | None = None


class ArkAPIError(RuntimeError):
    """带 HTTP 状态码的方舟接口错误，供模型链判断是否需要故障转移。"""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _is_quota_error(error: Exception) -> bool:
    if getattr(error, "status_code", None) == 402:
        return True
    message = str(error).lower()
    return any(hint in message for hint in _QUOTA_HINTS)


def _current_start() -> int:
    """读取当天生效的模型下标；跨天从链首重新探测。"""
    today = date.today().isoformat()
    with _state_lock:
        if _cur["idx"] is None or _cur["date"] != today:
            idx = 0
            try:
                state = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
                if state.get("date") == today:
                    idx = int(state.get("idx", 0))
            except Exception:
                pass
            if not 0 <= idx < len(MODEL_CHAIN):
                idx = 0
            _cur["idx"], _cur["date"] = idx, today
        return _cur["idx"]


def _commit(idx: int) -> None:
    today = date.today().isoformat()
    with _state_lock:
        _cur["idx"], _cur["date"] = idx, today
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(
            json.dumps(
                {"idx": idx, "date": today, "model": MODEL_CHAIN[idx]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass


def current_model() -> str:
    return MODEL_CHAIN[_current_start()]


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(part for part in parts if part)
    return str(content)


def _chat_messages_to_responses(messages: list[dict]) -> tuple[str, list[dict]]:
    """把 Chat Completions 消息转换成 Responses API 的 input items。"""
    instructions: list[str] = []
    items: list[dict] = []

    for message in messages:
        role = message.get("role", "user")
        content = _content_text(message.get("content"))

        if role in {"system", "developer"}:
            if content:
                instructions.append(content)
            continue

        if role == "tool":
            items.append({
                "type": "function_call_output",
                "call_id": message.get("tool_call_id", ""),
                "output": content,
            })
            continue

        if role == "assistant" and message.get("tool_calls"):
            if content:
                items.append({"role": "assistant", "content": content})
            for tool_call in message["tool_calls"]:
                function = tool_call.get("function", {})
                items.append({
                    "type": "function_call",
                    "call_id": tool_call.get("id", ""),
                    "name": function.get("name", ""),
                    "arguments": function.get("arguments", "{}"),
                })
            continue

        normalized_role = "assistant" if role == "assistant" else "user"
        items.append({"role": normalized_role, "content": content})

    return "\n\n".join(instructions), items


def _responses_tools(tools: list[dict]) -> list[dict]:
    converted: list[dict] = []
    for tool in tools:
        if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
            function = tool["function"]
            item = {
                "type": "function",
                "name": function.get("name", ""),
                "description": function.get("description", ""),
                "parameters": function.get("parameters", {"type": "object", "properties": {}}),
            }
            if "strict" in function:
                item["strict"] = function["strict"]
            converted.append(item)
        else:
            converted.append(dict(tool))
    return converted


def _responses_tool_choice(tool_choice: Any) -> Any:
    if not isinstance(tool_choice, dict):
        return tool_choice
    if tool_choice.get("type") == "function" and isinstance(tool_choice.get("function"), dict):
        return {"type": "function", "name": tool_choice["function"].get("name", "")}
    return tool_choice


def _build_payload(model: str, kwargs: dict) -> tuple[dict, float | tuple[float, float]]:
    options = dict(kwargs)
    messages = options.pop("messages", [])
    instructions, input_items = _chat_messages_to_responses(messages)
    timeout = options.pop("timeout", _DEFAULT_TIMEOUT)

    payload: dict[str, Any] = {
        "model": model,
        "stream": bool(options.pop("stream", False)),
        "input": input_items,
        "store": False,
    }
    if instructions:
        payload["instructions"] = instructions

    max_tokens = options.pop("max_tokens", None)
    if max_tokens is not None:
        payload["max_output_tokens"] = max_tokens
    if "temperature" in options:
        payload["temperature"] = options.pop("temperature")
    if "top_p" in options:
        payload["top_p"] = options.pop("top_p")

    tools = _responses_tools(options.pop("tools", []) or [])
    if not tools and settings.ark_web_search and _web_search_available is not False:
        tools = [dict(_WEB_SEARCH_TOOL)]
    if tools:
        payload["tools"] = tools
        tool_choice = options.pop("tool_choice", "auto")
        payload["tool_choice"] = _responses_tool_choice(tool_choice)
    else:
        options.pop("tool_choice", None)

    # 保留少量 Responses API 原生可选项，避免未来调用者再次改适配层。
    for key in ("metadata", "service_tier", "reasoning"):
        if key in options:
            payload[key] = options.pop(key)

    return payload, timeout


def _raise_for_ark_error(response: requests.Response) -> None:
    if response.status_code < 400:
        return
    try:
        body = response.json()
        error = body.get("error") or body
        message = error.get("message") if isinstance(error, dict) else str(error)
    except Exception:
        message = response.text[:1000]
    raise ArkAPIError(
        f"火山方舟请求失败 ({response.status_code}): {message or '未知错误'}",
        status_code=response.status_code,
    )


def _is_web_search_unavailable(error: Exception) -> bool:
    message = str(error).lower()
    return (
        getattr(error, "status_code", None) == 404
        and ("web search" in message or "content_plugin" in message)
    )


def _remove_web_search(payload: dict) -> dict:
    downgraded = dict(payload)
    remaining_tools = [
        tool for tool in downgraded.get("tools", [])
        if tool.get("type") != "web_search"
    ]
    if remaining_tools:
        downgraded["tools"] = remaining_tools
        downgraded["tool_choice"] = "auto"
    else:
        downgraded.pop("tools", None)
        downgraded.pop("tool_choice", None)

    notice = (
        "当前方舟账户未开通网页搜索。不得编造实时新闻、实时行情或最新事件；"
        "若输入中没有可靠的当日数据，必须明确说明无法联网核实。"
    )
    existing = downgraded.get("instructions", "")
    downgraded["instructions"] = f"{existing}\n\n{notice}".strip()
    return downgraded


def _post(payload: dict, timeout: float | tuple[float, float]) -> requests.Response:
    if not settings.ark_api_key:
        raise ArkAPIError("未配置 ARK_API_KEY")
    response = requests.post(
        settings.ark_responses_url,
        headers={
            "Authorization": f"Bearer {settings.ark_api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
        stream=bool(payload.get("stream")),
    )
    _raise_for_ark_error(response)
    return response


def _tool_call(item: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=item.get("call_id") or item.get("id", ""),
        type="function",
        function=SimpleNamespace(
            name=item.get("name", ""),
            arguments=item.get("arguments", "{}"),
        ),
    )


def _parse_response(body: dict) -> SimpleNamespace:
    if body.get("status") == "failed":
        error = body.get("error") or {}
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise ArkAPIError(f"火山方舟响应失败: {message or '未知错误'}")

    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls: list[SimpleNamespace] = []

    for item in body.get("output", []):
        item_type = item.get("type")
        if item_type == "message":
            for part in item.get("content", []):
                if part.get("type") == "output_text" and part.get("text"):
                    text_parts.append(part["text"])
        elif item_type == "reasoning":
            for part in item.get("summary", []):
                if part.get("text"):
                    reasoning_parts.append(part["text"])
        elif item_type == "function_call":
            tool_calls.append(_tool_call(item))

    incomplete_reason = (body.get("incomplete_details") or {}).get("reason")
    if tool_calls:
        finish_reason = "tool_calls"
    elif body.get("status") == "incomplete" and incomplete_reason == "length":
        finish_reason = "length"
    else:
        finish_reason = "stop"

    message = SimpleNamespace(
        role="assistant",
        content="".join(text_parts),
        reasoning_content="\n".join(reasoning_parts) or None,
        tool_calls=tool_calls or None,
    )
    choice = SimpleNamespace(index=0, message=message, finish_reason=finish_reason)
    return SimpleNamespace(
        id=body.get("id", ""),
        model=body.get("model", CHAT_MODEL),
        choices=[choice],
        usage=body.get("usage"),
    )


def _stream_chunk(content: str | None = None, finish_reason: str | None = None) -> SimpleNamespace:
    delta = SimpleNamespace(content=content, reasoning_content=None)
    choice = SimpleNamespace(index=0, delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], model=CHAT_MODEL)


class _ArkStream(Iterator[SimpleNamespace]):
    def __init__(self, response: requests.Response):
        self._response = response
        self._iterator = self._events()

    def __iter__(self) -> "_ArkStream":
        return self

    def __next__(self) -> SimpleNamespace:
        return next(self._iterator)

    def _events(self) -> Iterator[SimpleNamespace]:
        finish_reason = "stop"
        try:
            for raw_line in self._response.iter_lines():
                if not raw_line.startswith(b"data: "):
                    continue
                raw_data = raw_line[6:]
                if raw_data.strip() == b"[DONE]":
                    break
                try:
                    event = json.loads(raw_data.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue

                event_type = event.get("type")
                if event_type == "response.output_text.delta":
                    yield _stream_chunk(content=event.get("delta", ""))
                elif event_type == "response.incomplete":
                    reason = (event.get("response", {}).get("incomplete_details") or {}).get("reason")
                    finish_reason = "length" if reason == "length" else "stop"
                elif event_type in {"response.failed", "error"}:
                    error = event.get("response", {}).get("error") or event.get("error") or event
                    message = error.get("message") if isinstance(error, dict) else str(error)
                    raise ArkAPIError(f"火山方舟流式响应失败: {message}")
            yield _stream_chunk(finish_reason=finish_reason)
        finally:
            self._response.close()


def _ark_create(model: str, **kwargs):
    global _web_search_available
    payload, timeout = _build_payload(model, kwargs)
    try:
        response = _post(payload, timeout)
    except ArkAPIError as error:
        if not _is_web_search_unavailable(error):
            raise
        _web_search_available = False
        response = _post(_remove_web_search(payload), timeout)
    if payload["stream"]:
        return _ArkStream(response)
    try:
        return _parse_response(response.json())
    finally:
        response.close()


class _Completions:
    def create(self, **kwargs):
        kwargs.pop("model", None)
        start = _current_start()
        last_error: Exception | None = None
        for idx in range(start, len(MODEL_CHAIN)):
            try:
                response = _ark_create(MODEL_CHAIN[idx], **kwargs)
                if idx != start:
                    _commit(idx)
                return response
            except Exception as error:  # noqa: BLE001
                if _is_quota_error(error):
                    last_error = error
                    continue
                raise
        raise last_error or RuntimeError("所有方舟聊天模型额度均不可用，请检查账户余额")


class _Chat:
    def __init__(self):
        self.completions = _Completions()


class FailoverClient:
    def __init__(self):
        self.chat = _Chat()


def make_client() -> FailoverClient:
    return FailoverClient()


def web_search_status() -> str:
    if not settings.ark_web_search:
        return "disabled"
    if _web_search_available is False:
        return "unavailable_fallback"
    return "enabled_unverified"


def make_vision_client() -> OpenAI:
    """智谱视觉模型客户端（图片转文本），不参与聊天模型切换。"""
    return OpenAI(
        api_key=settings.glm_api_key,
        base_url="https://open.bigmodel.cn/api/paas/v4/",
    )
