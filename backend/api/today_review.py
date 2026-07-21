"""
今日复盘 API
GET  /api/today-review/dates
GET  /api/today-review/daily?date=YYYY-MM-DD
POST /api/today-review/generate
GET  /api/today-review/status
"""
import threading
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from db import watchlist_db
from db.today_review_db import init_db, save_daily, get_daily, list_dates, get_latest_date
from services.market_clock import can_generate_review, get_market_status
from services.today_review_service import build_today_review
from services.decision_learning_service import bootstrap_historical_learning

router = APIRouter(prefix="/api/today-review", tags=["今日复盘"])


class WatchItem(BaseModel):
    code: str
    name: str | None = ""
    date: str | None = ""


class GenerateReq(BaseModel):
    date: str | None = None
    watchlist: list[WatchItem] = Field(default_factory=list)


init_db()

_lock = threading.Lock()
_status: dict = {"running": False, "started_at": "", "progress": ""}


def _saved_watchlist_for(trade_date: str) -> list[dict]:
    data = get_daily(trade_date) or {}
    stocks = ((data.get("watchlist") or {}).get("stocks")) or []
    out = []
    for s in stocks:
        code = s.get("symbol") or s.get("code")
        if code:
            out.append({"code": str(code), "name": s.get("name") or "", "date": s.get("date") or ""})
    return out


def _do_generate(trade_date: str, watchlist: list[dict] | None = None):
    global _status
    _status = {"running": True, "started_at": datetime.now().isoformat(), "progress": "启动中..."}
    try:
        def _cb(msg: str):
            _status["progress"] = msg

        active_watchlist = watchlist if watchlist is not None else watchlist_db.list_items()
        payload = build_today_review(trade_date, watchlist=active_watchlist, progress_cb=_cb)
        save_daily(trade_date, payload)
        _status = {
            "running": False,
            "started_at": "",
            "progress": f"完成！{trade_date} 今日复盘已保存",
        }
    except Exception as e:
        _status = {"running": False, "started_at": "", "progress": f"失败：{e}"}


@router.get("/dates")
def dates():
    return JSONResponse({"dates": list_dates()})


@router.get("/daily")
def daily(date: str | None = None):
    target = date or get_latest_date()
    if not target:
        return JSONResponse({"data": None, "message": "暂无今日复盘，请先生成"})
    data = get_daily(target)
    if not data:
        return JSONResponse({"data": None, "message": f"{target} 暂无今日复盘"})
    intelligence = data.get("intelligence")
    if isinstance(intelligence, dict):
        intelligence["learning"] = bootstrap_historical_learning()
    return JSONResponse({"data": data, "generating_status": _status})


@router.post("/generate")
def generate(req: GenerateReq):
    if _lock.locked():
        return JSONResponse({"ok": False, "message": "正在生成中，请稍候", "status": _status})
    market_status = get_market_status()
    target = req.date or market_status["today"]
    if not can_generate_review(target):
        return JSONResponse({
            "ok": False,
            "message": "盘后复盘仅在交易日15:10后生成；盘中数据不会写入日档案",
            "market_status": market_status,
        }, status_code=409)

    watchlist = [x.model_dump() for x in req.watchlist]
    if watchlist:
        watchlist_db.merge_items(watchlist)
    elif target == market_status["today"]:
        watchlist = watchlist_db.list_items()
    else:
        watchlist = _saved_watchlist_for(target) or watchlist_db.list_items()

    def run():
        with _lock:
            _do_generate(target, watchlist)

    threading.Thread(target=run, daemon=True).start()
    return JSONResponse({"ok": True, "message": f"已开始生成 {target} 今日复盘", "status": _status})


@router.get("/status")
def status():
    return JSONResponse({**_status, "market_status": get_market_status()})
