from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from datetime import datetime, timedelta, date
import numpy as np

from data.stock_data import collect_all, fetch_quick_batch, collect_yesterday
from services.review_service import (
    generate_review_report, calc_financial_score, stream_review_report,
    stream_yesterday_report,
)
from services.verdict_service import compute_verdict, compute_relative

# 服务端内存缓存：cache_key -> stock_data
_review_data_cache: dict[str, dict] = {}
# 昨日复盘缓存：cache_key -> yesterday_data
_yesterday_cache: dict[str, dict] = {}


def _to_native(obj):
    """递归将 numpy/nan/inf 转为 JSON 兼容的 Python 原生类型"""
    import math
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_native(i) for i in obj]
    return obj

router = APIRouter(prefix="/api/review", tags=["复盘"])


class ReviewRequest(BaseModel):
    symbol: str
    start: str | None = None   # YYYYMMDD，默认 90 天前
    end: str | None = None     # YYYYMMDD，默认今天


class ReviewResponse(BaseModel):
    symbol: str
    name: str
    industry: dict
    period: dict
    report: str
    price_summary: dict
    ohlcv: list
    key_events: list
    indicators: list
    financial_score: dict   # 纯算法评分，grade/score/flags/positives
    lhb: list               # 龙虎榜上榜记录
    ths_hot: dict           # 关键事件日热点题材
    industry_rank: dict     # 行业横向对比
    fund_flow: dict         # 资金流向


@router.post("", response_model=ReviewResponse)
async def create_review(req: ReviewRequest):
    today = datetime.today()
    end = req.end or today.strftime("%Y%m%d")
    start = req.start or (today - timedelta(days=90)).strftime("%Y%m%d")

    try:
        stock_data = collect_all(req.symbol, start, end)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"数据采集失败：{e}")

    if "error" in stock_data.get("price", {}):
        raise HTTPException(status_code=404, detail=f"未找到股票 {req.symbol}")

    # 存入缓存，供后续 /stream-report 使用
    cache_key = f"{req.symbol}_{start}_{end}"
    _review_data_cache[cache_key] = stock_data

    fs = calc_financial_score(
        finance=stock_data.get("finance", {}),
        price_summary=stock_data["price"].get("summary", {}),
    )

    # 相对大盘强弱 + 复盘速览（纯算法，毫秒级，结论先行）
    relative = compute_relative(
        stock_data["price"].get("ohlcv", []),
        stock_data.get("index_series", []),
        stock_data.get("index_name", "上证综指"),
    )
    verdict = compute_verdict(
        stock_data, fs,
        relative=relative,
        valuation=stock_data.get("valuation", {}),
    )
    # 存入 stock_data，供 SSE 阶段的 prompt 复用（避免重复计算/重复堆砌）
    stock_data["_verdict"] = verdict

    payload = _to_native({
        "symbol":        stock_data["symbol"],
        "name":          stock_data["name"],
        "industry":      stock_data.get("industry", {}),
        "period":        stock_data["period"],
        "report":        "",          # AI 报告通过 /stream-report SSE 流式获取
        "cache_key":     cache_key,   # 前端凭此 key 拉取 SSE 流
        "price_summary": stock_data["price"].get("summary", {}),
        "ohlcv":         stock_data["price"].get("ohlcv", []),
        "key_events":    stock_data["price"].get("key_events", []),
        "indicators":    [],
        "financial_score": fs,
        "verdict":       verdict,
        "valuation":     stock_data.get("valuation", {}),
        "relative":      relative,
        "lhb":           stock_data.get("lhb", []),
        "ths_hot":       stock_data.get("ths_hot", {}),
        "industry_rank": stock_data.get("industry_rank", {}),
        "fund_flow":     stock_data.get("fund_flow", {}),
    })
    return JSONResponse(content=payload)


@router.get("/stream-report")
async def stream_report(cache_key: str):
    """SSE 流式输出 AI 复盘报告"""
    from fastapi.responses import StreamingResponse

    stock_data = _review_data_cache.get(cache_key)
    if not stock_data:
        raise HTTPException(status_code=404, detail=f"缓存已过期，请重新查询（cache_key={cache_key}）")

    async def event_generator():
        import json as _json
        async for chunk in stream_review_report(stock_data):
            # JSON encode 保证换行符不破坏 SSE 帧格式
            yield f"data: {_json.dumps(chunk, ensure_ascii=False)}\n\n"
        yield "data: \"[DONE]\"\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 昨日复盘（单日聚焦）────────────────────────────────────────────────────

class YesterdayRequest(BaseModel):
    symbol: str


@router.post("/yesterday")
async def create_yesterday_review(req: YesterdayRequest):
    """采集「最近一个交易日」的单日聚焦数据（量价/资金/席位/题材/消息），
    即时返回结构化数据 + cache_key，AI 叙述走 /yesterday/stream-report SSE。"""
    try:
        data = collect_yesterday(req.symbol)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"数据采集失败：{e}")

    if data.get("error") or not data.get("daily"):
        raise HTTPException(status_code=404, detail=data.get("error") or f"未找到股票 {req.symbol} 的行情")

    the_date = data["daily"].get("date", "")
    cache_key = f"yd_{req.symbol}_{the_date}"
    _yesterday_cache[cache_key] = data

    payload = _to_native({**data, "cache_key": cache_key})
    return JSONResponse(content=payload)


@router.get("/yesterday/stream-report")
async def stream_yesterday(cache_key: str):
    """SSE 流式输出「昨日复盘」AI 叙述"""
    from fastapi.responses import StreamingResponse

    data = _yesterday_cache.get(cache_key)
    if not data:
        raise HTTPException(status_code=404, detail=f"缓存已过期，请重新查询（cache_key={cache_key}）")

    async def event_generator():
        import json as _json
        async for chunk in stream_yesterday_report(data):
            yield f"data: {_json.dumps(chunk, ensure_ascii=False)}\n\n"
        yield "data: \"[DONE]\"\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{symbol}")
async def get_review_ohlcv(symbol: str, start: str | None = None, end: str | None = None):
    """轻量 GET 接口：仅返回 ohlcv 数据，供前端策略回测使用"""
    today = datetime.today()
    end = end or today.strftime("%Y%m%d")
    start = start or (today - timedelta(days=365)).strftime("%Y%m%d")

    try:
        stock_data = collect_all(symbol, start, end)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"数据采集失败：{e}")

    if "error" in stock_data.get("price", {}):
        raise HTTPException(status_code=404, detail=f"未找到股票 {symbol}")

    ohlcv = _to_native(stock_data["price"].get("ohlcv", []))
    return JSONResponse(content={
        "symbol": stock_data["symbol"],
        "name":   stock_data["name"],
        "ohlcv":  ohlcv,
    })


class QuickBatchRequest(BaseModel):
    symbols: list[str]
    sources: list[dict] = []   # [{symbol, source}] 标注来源：自选/持仓/推荐


@router.post("/quick-batch")
async def quick_batch_review(req: QuickBatchRequest):
    """批量今日复盘：自选/持仓/推荐股票多维技术分析"""
    if not req.symbols:
        return JSONResponse({
            "stocks": [],
            "date": date.today().isoformat(),
            "updated_at": "",
            "is_market_open": False,
        })

    # 1. 技术指标（baostock，带日期缓存）
    tech_results = fetch_quick_batch(req.symbols)
    tech_map = {r["symbol"]: r for r in tech_results}

    # 2. 实时价格（新浪财经）
    from api.watchlist import _fetch_sina_hq
    live_map = _fetch_sina_hq(req.symbols)

    # 3. 来源标注
    source_map = {s["symbol"]: s.get("source", "") for s in req.sources}

    # 4. 判断是否在交易时间
    now = datetime.now()
    weekday = now.weekday()  # 0=Mon, 6=Sun
    hour_min = now.hour * 100 + now.minute
    is_market_open = (
        weekday < 5 and
        (925 <= hour_min <= 1130 or 1300 <= hour_min <= 1500)
    )

    # 5. 合并数据
    merged = []
    for sym in req.symbols:
        tech = tech_map.get(sym, {})
        live = live_map.get(sym, {})

        # 实时价格覆盖技术数据中的当日数据
        today_data = dict(tech.get("today", {}))
        if live and not live.get("not_found"):
            today_data["price"]      = live.get("price", today_data.get("close"))
            today_data["pct_change"] = live.get("pct_change", today_data.get("pct_change"))
            today_data["high"]       = live.get("high", today_data.get("high"))
            today_data["low"]        = live.get("low", today_data.get("low"))
            today_data["volume"]     = live.get("volume", today_data.get("volume"))
            today_data["name"]       = live.get("name", "")
            today_data["amount"]     = live.get("amount", 0)
            today_data["open"]       = live.get("open", today_data.get("open"))
            today_data["prev_close"] = live.get("prev_close", 0)

        merged.append({
            "symbol":    sym,
            "name":      today_data.get("name") or live.get("name", sym),
            "source":    source_map.get(sym, ""),
            "today":     today_data,
            "technical": tech.get("technical", {}),
            "trend":     tech.get("trend", {}),
            "error":     tech.get("error"),
        })

    payload = _to_native({
        "stocks":         merged,
        "date":           date.today().isoformat(),
        "updated_at":     datetime.now().strftime("%H:%M:%S"),
        "is_market_open": is_market_open,
    })
    return JSONResponse(content=payload)


@router.get("/stock-info/{symbol}")
async def get_stock_info(symbol: str):
    """快速查询股票基本信息（不生成报告）"""
    import akshare as ak
    try:
        df = ak.stock_zh_a_spot_em()
        row = df[df["代码"] == symbol]
        if row.empty:
            raise HTTPException(status_code=404, detail="股票代码不存在")
        info = row.iloc[0].to_dict()
        return {
            "symbol": symbol,
            "name": info.get("名称"),
            "price": info.get("最新价"),
            "pct_change": info.get("涨跌幅"),
            "volume": info.get("成交量"),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
