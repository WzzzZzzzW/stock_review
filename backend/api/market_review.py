"""
今日市场复盘 API（多维度 · 零 AI）
GET  /api/market-review/dates      — 所有有记录的日期列表
GET  /api/market-review/daily      — 最新一天（或指定日期）
POST /api/market-review/generate   — 手动触发生成（或重新生成）
GET  /api/market-review/status     — 查询生成进度
"""
import threading
from datetime import datetime
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from db.market_review_db import init_db, save_daily, get_daily, list_dates, get_latest_date
from services.market_review_service import build_market_review

router = APIRouter(prefix="/api/market-review", tags=["市场复盘"])

# 防止并发重复生成
_generating_lock = threading.Lock()
_generating_status: dict = {"running": False, "started_at": "", "progress": ""}

init_db()


def _do_generate(trade_date: str):
    global _generating_status
    _generating_status = {"running": True, "started_at": datetime.now().isoformat(), "progress": "启动中..."}
    try:
        def _cb(msg: str):
            _generating_status["progress"] = msg

        payload = build_market_review(trade_date, progress_cb=_cb)
        save_daily(trade_date, payload)

        b = payload.get("breadth", {})
        ls = payload.get("limit_stats", {})
        _generating_status = {
            "running": False, "started_at": "",
            "progress": f"完成！{trade_date} {b.get('up', 0)}涨{b.get('down', 0)}跌，涨停{ls.get('zt_count', 0)}",
        }
    except Exception as e:
        _generating_status = {"running": False, "started_at": "", "progress": f"失败：{e}"}


@router.get("/dates")
def get_dates():
    return JSONResponse({"dates": list_dates()})


@router.get("/daily")
def get_daily_review(date: str | None = None):
    """?date=2026-06-10 获取指定日期，不传则返回最新一天。"""
    target = date or get_latest_date()
    if not target:
        return JSONResponse({"data": None, "message": "暂无历史数据，请先生成"})
    data = get_daily(target)
    if not data:
        return JSONResponse({"data": None, "message": f"{target} 暂无数据"})
    return JSONResponse({"data": data, "generating_status": _generating_status})


@router.post("/generate")
def trigger_generate(date: str | None = None):
    """手动触发生成。date 格式 YYYY-MM-DD，默认今天。后台线程运行，立即返回。"""
    if _generating_lock.locked():
        return JSONResponse({"ok": False, "message": "正在生成中，请稍候", "status": _generating_status})

    target_date = date or datetime.today().strftime("%Y-%m-%d")

    def run():
        with _generating_lock:
            _do_generate(target_date)

    threading.Thread(target=run, daemon=True).start()
    return JSONResponse({"ok": True, "message": f"已开始生成 {target_date} 市场复盘", "status": _generating_status})


@router.get("/status")
def get_status():
    return JSONResponse(_generating_status)
