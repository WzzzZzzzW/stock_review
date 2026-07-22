"""
龙虎榜 API
数据源：新浪财经龙虎榜（akshare）
缓存 5 分钟
"""
import time
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/lhb", tags=["龙虎榜"])

# ── 缓存 ──────────────────────────────────────────────────────────────────────
_CACHE_TTL = 300  # 5 分钟
_AMOUNT_UNIT = "亿元"
_SOURCE_NAME = "新浪财经（AkShare）"

_top_cache: dict[str, dict] = {}   # key = str(days)
_daily_cache: dict[str, dict] = {} # key = date_str


def _latest_published_trading_day() -> str:
    """返回最近可能已经披露龙虎榜的交易日，格式 YYYYMMDD。"""
    d = datetime.now()
    # 龙虎榜是盘后数据。16:00 前默认查看上一交易日，避免把未发布误报为失败。
    if d.weekday() < 5 and d.hour < 16:
        d -= timedelta(days=1)
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d -= timedelta(days=1)
    return d.strftime("%Y%m%d")


def _daily_empty_payload(date_str: str, message: str) -> dict:
    return {
        "entries": [],
        "date": date_str,
        "updated_at": datetime.now().strftime("%H:%M:%S"),
        "amount_unit": _AMOUNT_UNIT,
        "source": _SOURCE_NAME,
        "sort_by": "amount_desc",
        "is_published": False,
        "message": message,
    }


# ── 近N日上榜 ─────────────────────────────────────────────────────────────────
@router.get("/top")
def lhb_top(days: int = Query(default=5, description="统计天数，支持 5/10/30/60")):
    """
    近N日龙虎榜上榜股票统计。
    返回：{ stocks: [...], days: int, updated_at: str }
    """
    key = str(days)
    now = time.time()
    cached = _top_cache.get(key)
    if cached and now - cached["ts"] < _CACHE_TTL:
        return {
            "stocks": cached["data"],
            "days": days,
            "updated_at": cached["updated_at"],
            "amount_unit": _AMOUNT_UNIT,
            "source": _SOURCE_NAME,
        }

    try:
        import akshare as ak
        df = ak.stock_lhb_ggtj_sina(symbol=str(days))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"龙虎榜数据获取失败: {e}")

    # 列名映射
    # 股票代码, 股票名称, 上榜次数, 累积购买额, 累积卖出额, 净额, 买入席位数, 卖出席位数
    col_map = {
        "股票代码": "symbol",
        "股票名称": "name",
        "上榜次数": "count",
        "累积购买额": "buy_amount",
        "累积卖出额": "sell_amount",
        "净额": "net_amount",
        "买入席位数": "buy_seats",
        "卖出席位数": "sell_seats",
    }

    # 兼容列名不完全匹配
    actual_cols = list(df.columns)
    rename = {}
    for orig, mapped in col_map.items():
        for col in actual_cols:
            if orig in col:
                rename[col] = mapped
                break

    df = df.rename(columns=rename)

    stocks = []
    for _, row in df.iterrows():
        try:
            # 新浪原始金额单位为万元；除以 10000 后统一以亿元返回。
            buy_amount  = round(float(row.get("buy_amount", 0)) / 10000, 2)
            sell_amount = round(float(row.get("sell_amount", 0)) / 10000, 2)
            net_amount  = round(float(row.get("net_amount", 0)) / 10000, 2)
        except (TypeError, ValueError):
            buy_amount = sell_amount = net_amount = 0.0

        try:
            count = int(row.get("count", 0))
        except (TypeError, ValueError):
            count = 0

        try:
            buy_seats = int(row.get("buy_seats", 0))
            sell_seats = int(row.get("sell_seats", 0))
        except (TypeError, ValueError):
            buy_seats = sell_seats = 0

        stocks.append({
            "symbol":      str(row.get("symbol", "")),
            "name":        str(row.get("name", "")),
            "count":       count,
            "buy_amount":  buy_amount,
            "sell_amount": sell_amount,
            "net_amount":  net_amount,
            "buy_seats":   buy_seats,
            "sell_seats":  sell_seats,
        })

    updated_at = datetime.now().strftime("%H:%M:%S")
    _top_cache[key] = {"data": stocks, "ts": now, "updated_at": updated_at}
    return {
        "stocks": stocks,
        "days": days,
        "updated_at": updated_at,
        "amount_unit": _AMOUNT_UNIT,
        "source": _SOURCE_NAME,
    }


# ── 当日明细 ──────────────────────────────────────────────────────────────────
@router.get("/daily")
def lhb_daily(date: str = Query(default=None, description="日期，格式 YYYYMMDD，默认最近交易日")):
    """
    指定日期的龙虎榜明细。
    返回：{ entries: [...], date: str, updated_at: str }
    """
    date_str = date if date else _latest_published_trading_day()
    try:
        datetime.strptime(date_str, "%Y%m%d")
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="日期格式必须为 YYYYMMDD")

    now = time.time()
    cached = _daily_cache.get(date_str)
    if cached and now - cached["ts"] < _CACHE_TTL:
        return cached["payload"]

    try:
        import akshare as ak
        df = ak.stock_lhb_detail_daily_sina(date=date_str)
    except KeyError:
        message = (
            "今日龙虎榜尚未发布。龙虎榜是收盘后披露数据，不是盘中实时榜单。"
            if date_str == datetime.now().strftime("%Y%m%d")
            else "数据源未返回该日期的龙虎榜，可能是非交易日或当日无公开交易信息。"
        )
        payload = _daily_empty_payload(date_str, message)
        _daily_cache[date_str] = {"payload": payload, "ts": now}
        return payload
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"龙虎榜日报数据获取失败: {e}")

    if df.empty or not any("股票代码" in str(col) for col in df.columns):
        payload = _daily_empty_payload(
            date_str,
            "数据源未返回该日期的龙虎榜，可能是非交易日或当日无公开交易信息。",
        )
        _daily_cache[date_str] = {"payload": payload, "ts": now}
        return payload

    # 列名映射
    # 序号, 股票代码, 股票名称, 收盘价, 对应值, 成交量, 成交额, 指标
    col_map = {
        "股票代码": "symbol",
        "股票名称": "name",
        "收盘价":   "price",
        "对应值":   "deviation",
        "成交量":   "volume",
        "成交额":   "amount",
        "指标":     "reason",
    }

    actual_cols = list(df.columns)
    rename = {}
    for orig, mapped in col_map.items():
        for col in actual_cols:
            if orig in col:
                rename[col] = mapped
                break

    df = df.rename(columns=rename)

    entries = []
    for _, row in df.iterrows():
        try:
            price = round(float(row.get("price", 0)), 2)
        except (TypeError, ValueError):
            price = 0.0

        try:
            deviation = round(float(row.get("deviation", 0)), 2)
        except (TypeError, ValueError):
            deviation = 0.0

        try:
            volume = int(row.get("volume", 0))
        except (TypeError, ValueError):
            volume = 0

        try:
            # 新浪原始成交额单位为万元；除以 10000 后统一以亿元返回。
            amount = round(float(row.get("amount", 0)) / 10000, 2)
        except (TypeError, ValueError):
            amount = 0.0

        entries.append({
            "symbol":    str(row.get("symbol", "")),
            "name":      str(row.get("name", "")),
            "price":     price,
            "deviation": deviation,
            "volume":    volume,
            "amount":    amount,
            "reason":    str(row.get("reason", "")),
        })

    # 当日明细优先展示资金关注度最高的股票；相同成交额保留源数据顺序。
    entries.sort(key=lambda item: item["amount"], reverse=True)

    updated_at = datetime.now().strftime("%H:%M:%S")
    payload = {
        "entries": entries,
        "date": date_str,
        "updated_at": updated_at,
        "amount_unit": _AMOUNT_UNIT,
        "source": _SOURCE_NAME,
        "sort_by": "amount_desc",
        "is_published": True,
        "message": "",
    }
    _daily_cache[date_str] = {"payload": payload, "ts": now}
    return payload
