"""Unified trading-day context for phase-aware frontend behavior."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from services.market_clock import get_market_status


router = APIRouter(prefix="/api/trading-day", tags=["交易日工作流"])


@router.get("/status")
def status():
    return JSONResponse(get_market_status())
