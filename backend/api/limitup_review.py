"""
涨停板复盘 API
GET  /api/limitup/dates           — 所有有记录的日期列表
GET  /api/limitup/daily           — 最新一天（或指定日期）
POST /api/limitup/generate        — 手动触发生成（或重新生成）
GET  /api/limitup/status          — 查询生成进度
"""
import threading
from datetime import date, datetime
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

from db.limitup_db import init_db, save_daily, get_daily, list_dates, get_latest_date
from data.limitup_fetcher import fetch_zt_pool, fetch_dt_pool, group_by_concept
from services.limitup_service import generate_full_review  # noqa: template-based, no AI

router = APIRouter(prefix="/api/limitup", tags=["涨停复盘"])

# 防止并发重复生成
_generating_lock = threading.Lock()
_generating_status: dict = {"running": False, "started_at": "", "progress": ""}

init_db()


def _do_generate(trade_date: str):
    global _generating_status
    _generating_status = {"running": True, "started_at": datetime.now().isoformat(), "progress": "采集涨停股池..."}
    try:
        date_fmt = trade_date.replace("-", "")  # YYYYMMDD

        # 1. 采集数据
        zt_stocks = fetch_zt_pool(date_fmt)
        dt_stocks = fetch_dt_pool(date_fmt)

        _generating_status["progress"] = f"获取到{len(zt_stocks)}只涨停股，正在分组..."

        # 2. 分组（含概念热度采集，Plan B 无 AI）
        groups = group_by_concept(zt_stocks, date_fmt=date_fmt)

        _generating_status["progress"] = f"分为{len(groups)}个板块，模板生成中..."

        # 3. 模板生成（Plan B：零 AI 调用）
        payload = generate_full_review(
            trade_date=trade_date,
            zt_groups=groups,
            dt_stocks=dt_stocks,
            total_zt=len(zt_stocks),
            total_dt=len(dt_stocks),
        )

        # 4. 永久存储
        save_daily(trade_date, payload)
        _generating_status = {"running": False, "started_at": "", "progress": f"完成！{trade_date} 共{len(zt_stocks)}只涨停"}

    except Exception as e:
        _generating_status = {"running": False, "started_at": "", "progress": f"失败：{e}"}


@router.get("/dates")
def get_dates():
    return JSONResponse({"dates": list_dates()})


@router.get("/daily")
def get_daily_review(date: str | None = None):
    """
    ?date=2026-05-19 获取指定日期，不传则返回最新一天。
    """
    target = date or get_latest_date()
    if not target:
        return JSONResponse({"data": None, "message": "暂无历史数据，请先生成"})
    data = get_daily(target)
    if not data:
        return JSONResponse({"data": None, "message": f"{target} 暂无数据"})
    return JSONResponse({"data": data, "generating_status": _generating_status})


@router.post("/generate")
def trigger_generate(date: str | None = None):
    """
    手动触发生成。date 格式 YYYY-MM-DD，默认今天。
    生成在后台线程运行，立即返回任务状态。
    """
    if _generating_lock.locked():
        return JSONResponse({"ok": False, "message": "正在生成中，请稍候", "status": _generating_status})

    target_date = date or datetime.today().strftime("%Y-%m-%d")

    def run():
        with _generating_lock:
            _do_generate(target_date)

    t = threading.Thread(target=run, daemon=True)
    t.start()

    return JSONResponse({"ok": True, "message": f"已开始生成 {target_date} 涨停复盘", "status": _generating_status})


@router.get("/status")
def get_status():
    return JSONResponse(_generating_status)
