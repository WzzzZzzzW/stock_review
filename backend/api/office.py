"""
AI办公室 API
"""
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services import office_service
from db import office_db

router = APIRouter(prefix="/api/office", tags=["office"])


# ── Models ────────────────────────────────────────────────────────────────────

class ChatIn(BaseModel):
    agent_id: str
    message: str
    chat_id: str = ""           # 不传则新建
    context: dict | None = None


class ConferenceIn(BaseModel):
    question: str
    agent_ids: list[str]
    chat_id: str = ""
    context: dict | None = None
    include_synthesis: bool = True


# ── Agents ────────────────────────────────────────────────────────────────────

@router.get("/agents")
def list_agents():
    """所有 agent 的列表（不含 system prompt）"""
    return {
        "agents": [
            {
                "id": aid,
                "title": a["title"],
                "icon": a["icon"],
                "desc": a["desc"],
                "color": a["color"],
            }
            for aid, a in office_service.AGENTS.items()
        ]
    }


# ── 聊天历史 ──────────────────────────────────────────────────────────────────

@router.get("/chats")
def list_chats():
    return {"chats": office_db.list_chats()}


@router.get("/chats/{chat_id}")
def get_chat(chat_id: str):
    chat = office_db.get_chat(chat_id)
    if not chat:
        raise HTTPException(404, "聊天不存在")
    return chat


@router.delete("/chats/{chat_id}")
def delete_chat(chat_id: str):
    office_db.delete_chat(chat_id)
    return {"ok": True}


# ── 单聊 ──────────────────────────────────────────────────────────────────────

@router.post("/chat")
def chat(body: ChatIn):
    """与单个 agent 对话（非流式，等完整响应）"""
    if body.agent_id not in office_service.AGENTS:
        raise HTTPException(400, "未知 agent")

    # 1. 获取/创建聊天
    chat_id = body.chat_id
    if not chat_id:
        title = body.message[:30]
        chat_id = office_db.create_chat("single", [body.agent_id], title)
        history = []
    else:
        existing = office_db.get_chat(chat_id)
        if not existing:
            raise HTTPException(404, "聊天不存在")
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in existing["messages"]
        ]

    # 2. 保存用户消息
    office_db.add_message(chat_id, "user", body.message)

    # 3. 调用 agent
    try:
        result = office_service.chat_with_agent(
            body.agent_id, body.message, history, body.context
        )
    except Exception as e:
        raise HTTPException(500, f"AI调用失败: {e}")

    response = result["response"]
    tool_calls = result.get("tool_calls", [])

    # 4. 保存回复（把 tool 调用日志拼进 content 末尾）
    saved_content = response
    if tool_calls:
        tool_summary = "\n\n---\n*🔧 调用了工具: " + ", ".join(f"`{t['name']}`" for t in tool_calls) + "*"
        saved_content = response + tool_summary
    office_db.add_message(chat_id, "assistant", saved_content, agent_id=body.agent_id)

    return {
        "chat_id": chat_id,
        "agent_id": body.agent_id,
        "response": response,
        "tool_calls": tool_calls,
    }


# ── 单聊（流式，带进度）───────────────────────────────────────────────────────

@router.post("/chat/stream")
def chat_stream(body: ChatIn):
    """
    与单个 agent 对话——流式版。
    SSE 事件：tool_start / thinking / final / error，让前端实时显示"正在查龙虎榜…"等进度，
    避免单聊要等模型多轮工具调用（约30-60秒）时页面看起来像卡死。
    """
    if body.agent_id not in office_service.AGENTS:
        raise HTTPException(400, "未知 agent")

    chat_id = body.chat_id
    if not chat_id:
        title = body.message[:30]
        chat_id = office_db.create_chat("single", [body.agent_id], title)
        history: list[dict] = []
    else:
        existing = office_db.get_chat(chat_id)
        if not existing:
            raise HTTPException(404, "聊天不存在")
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in existing["messages"]
        ]

    office_db.add_message(chat_id, "user", body.message)

    def _stream():
        try:
            final_response = ""
            final_tools: list[dict] = []
            for ev in office_service.chat_with_agent_stream(
                body.agent_id, body.message, history, body.context
            ):
                if ev.get("type") == "final":
                    final_response = ev.get("response", "")
                    final_tools = ev.get("tool_calls", [])
                yield f"data: {json.dumps({**ev, 'chat_id': chat_id}, ensure_ascii=False)}\n\n"

            # 落库（与非流式 /chat 一致：把工具调用日志拼到末尾）
            saved_content = final_response
            if final_tools:
                saved_content += "\n\n---\n*🔧 调用了工具: " + ", ".join(
                    f"`{t['name']}`" for t in final_tools
                ) + "*"
            office_db.add_message(chat_id, "assistant", saved_content, agent_id=body.agent_id)

            yield 'data: "[DONE]"\n\n'
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


# ── 开会 ──────────────────────────────────────────────────────────────────────

@router.post("/conference")
def conference(body: ConferenceIn):
    """召开多 agent 会议，流式返回每个 agent 的发言"""
    valid_ids = [a for a in body.agent_ids if a in office_service.AGENTS]
    if not valid_ids:
        raise HTTPException(400, "至少选一个 agent")

    # 创建/复用聊天 & 加载历史
    chat_id = body.chat_id
    history: list[dict] = []
    if not chat_id:
        title = body.question[:30]
        agent_set = valid_ids if "trader" in valid_ids or not body.include_synthesis else valid_ids + ["trader"]
        chat_id = office_db.create_chat("conference", agent_set, title)
    else:
        existing = office_db.get_chat(chat_id)
        if existing:
            history = [
                {"role": m["role"], "content": m["content"], "agent_id": m.get("agent_id", "")}
                for m in existing["messages"]
            ]

    office_db.add_message(chat_id, "user", body.question)

    def _stream():
        try:
            for chunk in office_service.hold_conference(
                body.question, valid_ids, body.context, body.include_synthesis,
                history=history,
            ):
                # 把工具调用日志拼到 content 末尾
                saved_content = chunk["content"]
                tool_calls = chunk.get("tool_calls", [])
                if tool_calls:
                    saved_content += "\n\n---\n*🔧 调用了工具: " + ", ".join(
                        f"`{t['name']}`" for t in tool_calls
                    ) + "*"
                office_db.add_message(
                    chat_id, "assistant", saved_content,
                    agent_id=chunk["agent_id"], is_synthesis=chunk.get("is_synthesis", False),
                )
                # SSE 推送
                yield f"data: {json.dumps({**chunk, 'chat_id': chat_id}, ensure_ascii=False)}\n\n"
            yield 'data: "[DONE]"\n\n'
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


# ── 辅助：从其他模块拉上下文 ──────────────────────────────────────────────────

@router.get("/context/{stock_symbol}")
def get_stock_context(stock_symbol: str):
    """
    给定股票代码，组装一个上下文字符串（持仓+脑库相关规则）
    供前端在 chat/conference 调用时一起传入
    """
    import json as _json
    from pathlib import Path

    ctx: dict = {"stock": stock_symbol}

    # 持仓
    portfolio_path = Path(__file__).parent.parent / "data" / "portfolio.json"
    if portfolio_path.exists():
        try:
            data = _json.loads(portfolio_path.read_text(encoding="utf-8"))
            for p in data.get("positions", []):
                if p.get("symbol") == stock_symbol:
                    ctx["positions"] = (
                        f"{p.get('name')}({p['symbol']}): "
                        f"持仓{p.get('quantity')}股, 成本¥{p.get('buy_price')}, "
                        f"买入日{p.get('buy_date')}"
                    )
                    break
        except Exception:
            pass

    # 脑库匹配规则
    try:
        from db import brain_db
        from services import brain_service
        rules = brain_db.list_rules()
        if rules:
            matched = brain_service.match_rules(rules, f"股票{stock_symbol}")
            if matched:
                ctx["brain_rules"] = "\n".join(
                    f"- {r.get('rule', '')}（置信度 {r.get('confidence', 0):.0%}）"
                    for r in matched[:5]
                )
    except Exception:
        pass

    return ctx
