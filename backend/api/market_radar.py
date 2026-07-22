"""Market radar API for pre-market briefing and intraday change detection."""
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from services.market_radar_service import (
    evaluate_radar_day,
    get_market_radar,
    get_stock_capital_ranking,
)


router = APIRouter(prefix="/api/market-radar", tags=["市场雷达"])


@router.get("")
def market_radar(
    phase: str = Query("intraday", pattern="^(premarket|intraday)$"),
    refresh: bool = False,
):
    try:
        return JSONResponse(get_market_radar(phase=phase, force=refresh))
    except Exception as exc:
        return JSONResponse(
            {
                "phase": phase,
                "market": {},
                "rotation": {"attack": [], "risk": [], "neutral": [], "all": []},
                "capital": {"inflow": [], "outflow": [], "note": ""},
                "changes": [],
                "timeline": [],
                "news": [],
                "personal": {"positions": [], "watchlist": [], "summary": ""},
                "error": f"市场雷达暂不可用：{exc}",
            },
            status_code=503,
        )


@router.get("/evaluation")
def radar_evaluation(trade_date: str = ""):
    return JSONResponse(evaluate_radar_day(trade_date or None))


@router.get("/stock-capital")
def stock_capital_ranking(refresh: bool = False):
    try:
        return JSONResponse(get_stock_capital_ranking(limit=10, force=refresh))
    except Exception as exc:
        return JSONResponse(
            {
                "inflow": [],
                "outflow": [],
                "updated_at": "",
                "refresh_seconds": 60,
                "source": "同花顺个股资金榜",
                "note": "实时个股资金榜暂时无法刷新，请稍后重试。",
                "error": f"实时个股资金榜暂不可用：{exc}",
            },
            status_code=503,
        )
