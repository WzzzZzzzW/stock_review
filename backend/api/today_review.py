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
from pydantic import BaseModel

from db.today_review_db import init_db, save_daily, get_daily, list_dates, get_latest_date
from services.today_review_service import build_today_review

router = APIRouter(prefix="/api/today-review", tags=["今日复盘"])


class WatchItem(BaseModel):
    code: str
    name: str | None = ""
    date: str | None = ""


class GenerateReq(BaseModel):
    date: str | None = None
    watchlist: list[WatchItem] = []


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

        payload = build_today_review(trade_date, watchlist=watchlist or [], progress_cb=_cb)
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
    return JSONResponse({"data": data, "generating_status": _status})


@router.post("/generate")
def generate(req: GenerateReq):
    if _lock.locked():
        return JSONResponse({"ok": False, "message": "正在生成中，请稍候", "status": _status})
    target = req.date or datetime.today().strftime("%Y-%m-%d")
    watchlist = [x.model_dump() for x in req.watchlist]
    if not watchlist:
        watchlist = _saved_watchlist_for(target)

    def run():
        with _lock:
            _do_generate(target, watchlist)

    threading.Thread(target=run, daemon=True).start()
    return JSONResponse({"ok": True, "message": f"已开始生成 {target} 今日复盘", "status": _status})


@router.get("/status")
def status():
    return JSONResponse(_status)
