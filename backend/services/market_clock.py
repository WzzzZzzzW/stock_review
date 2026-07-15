"""A-share trading phase clock used by the API, scheduler, and frontend."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _previous_weekday(day: date) -> date:
    current = day - timedelta(days=1)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def _next_weekday(day: date) -> date:
    current = day + timedelta(days=1)
    while current.weekday() >= 5:
        current += timedelta(days=1)
    return current


def get_market_status(now: datetime | None = None) -> dict:
    current = now.astimezone(SHANGHAI) if now else datetime.now(SHANGHAI)
    today = current.date()
    clock = current.time().replace(tzinfo=None)
    weekday = today.weekday()
    trading_day = weekday < 5

    if not trading_day:
        phase = "premarket"
        session = "non_trading"
        label = "休市准备"
    elif clock < time(9, 15):
        phase = "premarket"
        session = "preopen"
        label = "盘前准备"
    elif clock < time(9, 30):
        phase = "premarket"
        session = "auction"
        label = "集合竞价"
    elif clock < time(11, 30):
        phase = "intraday"
        session = "morning"
        label = "上午交易"
    elif clock < time(13, 0):
        phase = "intraday"
        session = "lunch"
        label = "午间休市"
    elif clock < time(15, 0):
        phase = "intraday"
        session = "afternoon"
        label = "下午交易"
    else:
        phase = "postmarket"
        session = "closed"
        label = "盘后复盘"

    can_generate_postmarket = trading_day and clock >= time(15, 10)
    if trading_day and can_generate_postmarket:
        completed_trade_date = today
    else:
        completed_trade_date = _previous_weekday(today)

    if trading_day and clock < time(15, 0):
        plan_for_date = today
    else:
        plan_for_date = _next_weekday(today)

    return {
        "phase": phase,
        "session": session,
        "label": label,
        "is_trading_day": trading_day,
        "is_market_open": session in {"morning", "afternoon"},
        "can_generate_postmarket": can_generate_postmarket,
        "today": today.isoformat(),
        "completed_trade_date": completed_trade_date.isoformat(),
        "plan_for_date": plan_for_date.isoformat(),
        "server_time": current.isoformat(timespec="seconds"),
    }


def can_generate_review(trade_date: str, now: datetime | None = None) -> bool:
    status = get_market_status(now)
    try:
        target = date.fromisoformat(trade_date)
    except ValueError:
        return False
    today = date.fromisoformat(status["today"])
    if target < today:
        return True
    return target == today and bool(status["can_generate_postmarket"])

