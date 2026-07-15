"""
郑希投研 —— 独立功能 API

封装 services/zhengxi_service：
  GET  /api/zhengxi/available                 数据是否就位
  GET  /api/zhengxi/search                     观点检索（关键词→带出处片段）
  GET  /api/zhengxi/method                      投资方法论（method.md）
  GET  /api/zhengxi/scorecard                   六维评分卡（scorecard.md）
  GET  /api/zhengxi/funds                        郑希精编快照里的基金列表
  POST /api/zhengxi/fund-evidence               准备某基金的证据档案（+cache_key）
  GET  /api/zhengxi/fund-score/stream-report    SSE 流式 AI 六维评分

研究学习辅助，非投资建议、不荐股。
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from services import zhengxi_service as zx

router = APIRouter(prefix="/api/zhengxi", tags=["郑希投研"])

# 证据档案缓存：cache_key -> evidence dict（供 SSE 评分复用）
_evidence_cache: dict[str, dict] = {}


@router.get("/available")
async def available():
    return {"available": zx.available()}


@router.get("/search")
async def search(
    q: str = Query(..., description="关键词，空格分隔多个"),
    any_mode: bool = Query(False, description="True=命中任一关键词；默认要求全部命中"),
    types: str | None = Query(None, description="限定类型，逗号分隔：定期报告,基金经理手记,媒体报道"),
    ctx: int = Query(0, ge=0, le=3, description="命中段落附带前后各 N 段"),
    max_hits: int = Query(20, ge=1, le=60),
):
    """在郑希语料中按关键词检索，返回带出处的原话片段（可溯源）。"""
    if not zx.available():
        raise HTTPException(status_code=503, detail="郑希语料数据未就位")
    keywords = [k for k in q.replace("，", " ").split() if k.strip()]
    if not keywords:
        raise HTTPException(status_code=400, detail="请输入检索关键词")
    type_list = [t.strip() for t in types.split(",")] if types else None
    result = zx.search_corpus(
        keywords, any_mode=any_mode, types=type_list, ctx=ctx, max_hits=max_hits
    )
    return JSONResponse(content=result)


class ChatMessage(BaseModel):
    role: str       # 'user' | 'assistant'
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


@router.post("/chat")
async def chat(req: ChatRequest):
    """对话式郑希导师（SSE 流式）。前端传完整对话历史，后端 RAG 检索语料原话作上下文。"""
    if not zx.available():
        raise HTTPException(status_code=503, detail="郑希语料数据未就位")
    msgs = [{"role": m.role, "content": m.content} for m in req.messages if m.content.strip()]
    if not msgs:
        raise HTTPException(status_code=400, detail="请输入问题")

    async def event_generator():
        import json as _json
        import asyncio
        try:
            # 先组装：识别个股 + 拉数据（阻塞 I/O 放线程池，避免卡事件循环）
            convo, stocks = await asyncio.to_thread(zx.prepare_chat, msgs)
            if stocks:
                yield f"data: {_json.dumps({'_stocks': stocks}, ensure_ascii=False)}\n\n"
            async for chunk in zx.stream_convo(convo):
                yield f"data: {_json.dumps(chunk, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {_json.dumps(f'（出错了：{e}）', ensure_ascii=False)}\n\n"
        yield "data: \"[DONE]\"\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/method")
async def method():
    """郑希投资方法论原文（method.md）。"""
    text = zx.get_method()
    if not text:
        raise HTTPException(status_code=404, detail="未找到 method.md")
    return {"content": text}


@router.get("/scorecard")
async def scorecard():
    """六维风格评分卡原文（scorecard.md）。"""
    text = zx.get_scorecard()
    if not text:
        raise HTTPException(status_code=404, detail="未找到 scorecard.md")
    return {"content": text}


@router.get("/funds")
async def funds():
    """郑希精编快照里的基金（离线可用）。"""
    return {"funds": zx.list_zhengxi_funds()}


class FundEvidenceRequest(BaseModel):
    arg: str   # 基金代码或名称


@router.post("/fund-evidence")
async def fund_evidence(req: FundEvidenceRequest):
    """准备某基金的「郑希框架评分」证据档案（结构化）。
    优先郑希精编快照/本地缓存；缺失时尝试实时抓取（依赖联网）。"""
    arg = (req.arg or "").strip()
    if not arg:
        raise HTTPException(status_code=400, detail="请输入基金代码或名称")

    ev = zx.fund_evidence(arg)
    if ev.get("error"):
        raise HTTPException(status_code=404, detail=ev["error"])

    cache_key = f"zx_{ev.get('code')}"
    _evidence_cache[cache_key] = ev
    return JSONResponse(content={**ev, "cache_key": cache_key})


@router.get("/fund-score/stream-report")
async def fund_score_stream(cache_key: str):
    """SSE 流式输出 AI 六维评分点评。"""
    ev = _evidence_cache.get(cache_key)
    if not ev:
        raise HTTPException(status_code=404, detail=f"证据档案已过期，请重新准备（cache_key={cache_key}）")

    async def event_generator():
        import json as _json
        async for chunk in zx.stream_fund_score(ev):
            yield f"data: {_json.dumps(chunk, ensure_ascii=False)}\n\n"
        yield "data: \"[DONE]\"\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
