"""Streaming API for the movable, page-aware market copilot."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from db import office_db
from services import office_service
from services.copilot_service import (
    build_copilot_context,
    enforce_evidence_boundary,
    get_copilot_role,
    list_copilot_roles,
)


router = APIRouter(prefix="/api/copilot", tags=["copilot"])


class CopilotChatIn(BaseModel):
    message: str
    chat_id: str = ""
    context: dict | None = None
    role: str = "market"


@router.get("/roles")
def roles():
    return {"roles": list_copilot_roles()}


@router.post("/chat/stream")
def chat_stream(body: CopilotChatIn):
    question = body.message.strip()
    if not question:
        raise HTTPException(400, "问题不能为空")
    try:
        role_id, role = get_copilot_role(body.role)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    chat_id = body.chat_id
    history: list[dict] = []
    if chat_id:
        existing = office_db.get_chat(chat_id)
        if not existing:
            raise HTTPException(404, "对话不存在")
        history = [
            {"role": message["role"], "content": message["content"]}
            for message in existing["messages"]
        ]
    else:
        target = ((body.context or {}).get("target") or {}).get("name")
        title_prefix = role["title"]
        title = f"{title_prefix}·{target}：{question[:16]}" if target else f"{title_prefix}：{question[:24]}"
        chat_id = office_db.create_chat("single", ["copilot"], title)

    office_db.add_message(chat_id, "user", question)

    def _stream():
        try:
            context = build_copilot_context(body.context, role_id, question)
            final_response = ""
            final_tools: list[dict] = []
            for event in office_service.chat_with_agent_stream(
                role["agent_id"], question, history, context
            ):
                if event.get("type") == "final":
                    final_response = enforce_evidence_boundary(
                        event.get("response", ""), body.context
                    )
                    final_tools = event.get("tool_calls", [])
                    event = {**event, "response": final_response}
                yield f"data: {json.dumps({**event, 'chat_id': chat_id, 'role': role_id, 'role_title': role['title']}, ensure_ascii=False)}\n\n"

            saved = final_response
            if final_tools:
                saved += "\n\n---\n*调用数据工具：" + "、".join(
                    f"`{item['name']}`" for item in final_tools
                ) + "*"
            office_db.add_message(chat_id, "assistant", saved, agent_id=f"copilot:{role_id}")
            yield 'data: "[DONE]"\n\n'
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")
