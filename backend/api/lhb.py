"""
龙虎榜 API
数据源：新浪财经龙虎榜（akshare）
缓存 5 分钟
"""
import time
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query
from utils.fallback_log import report_data_fallback

router = APIRouter(prefix="/api/lhb", tags=["龙虎榜"])

# ── 缓存 ──────────────────────────────────────────────────────────────────────
_CACHE_TTL = 300  # 5 分钟
_AMOUNT_UNIT = "亿元"
_SOURCE_NAME = "新浪财经（AkShare）"
_DAILY_SOURCE_NAME = "新浪财经 / 东方财富（AkShare）"

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
        "source": _DAILY_SOURCE_NAME,
        "sort_by": "amount_desc",
        "is_published": False,
        "message": message,
    }


def _clean_text(value) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def _safe_float(value) -> float | None:
    try:
        number = float(value)
        return None if number != number else number
    except (TypeError, ValueError):
        return None


def _reason_kind(reason: str) -> str:
    if "退市" in reason:
        return "delisting"
    if "连续" in reason or "累计" in reason:
        return "cumulative"
    if "换手率" in reason:
        return "turnover"
    if "振幅" in reason:
        return "amplitude"
    if "涨幅" in reason:
        return "daily_up"
    if "跌幅" in reason:
        return "daily_down"
    return "other"


def _fill_missing_reasons(df, em_df):
    """用东方财富同日榜单补齐新浪空缺的上榜原因。"""
    df["reason"] = df["reason"].astype(object)
    candidates_by_symbol: dict[str, list[dict]] = {}
    for _, row in em_df.iterrows():
        symbol = _clean_text(row.get("代码", "")).zfill(6)
        reason = _clean_text(row.get("上榜原因", ""))
        if not symbol or not reason:
            continue
        candidates = candidates_by_symbol.setdefault(symbol, [])
        if any(item["reason"] == reason for item in candidates):
            continue
        candidates.append({
            "reason": reason,
            "kind": _reason_kind(reason),
            "pct": _safe_float(row.get("涨跌幅")),
            "turnover": _safe_float(row.get("换手率")),
        })

    for symbol, group in df.groupby("symbol", sort=False):
        missing_indexes = [idx for idx in group.index if not _clean_text(df.at[idx, "reason"])]
        if not missing_indexes:
            continue

        known_kinds = {
            _reason_kind(_clean_text(df.at[idx, "reason"]))
            for idx in group.index
            if _clean_text(df.at[idx, "reason"])
        }
        available = [
            item.copy()
            for item in candidates_by_symbol.get(str(symbol).zfill(6), [])
            if item["kind"] not in known_kinds
        ]

        unresolved = []
        for idx in missing_indexes:
            value = _safe_float(df.at[idx, "deviation"])
            scored = []
            for pos, item in enumerate(available):
                reference = None
                if item["kind"] == "turnover":
                    reference = item["turnover"]
                elif item["kind"] in {"daily_up", "daily_down"}:
                    reference = item["pct"]
                if value is not None and reference is not None:
                    scored.append((abs(value - reference), pos))

            if scored and min(scored)[0] <= 0.3:
                _, pos = min(scored)
                df.at[idx, "reason"] = available.pop(pos)["reason"]
            else:
                unresolved.append(idx)

        if len(unresolved) == len(available):
            for idx, item in zip(unresolved, available):
                df.at[idx, "reason"] = item["reason"]

    df["reason"] = df["reason"].map(
        lambda value: _clean_text(value) or "上榜原因暂缺"
    )
    return df


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

    if "reason" in df.columns and df["reason"].map(lambda value: not _clean_text(value)).any():
        try:
            em_df = ak.stock_lhb_detail_em(start_date=date_str, end_date=date_str)
            df = _fill_missing_reasons(df, em_df)
        except Exception as error:
            report_data_fallback(
                "eastmoney",
                "fill_lhb_daily_reasons",
                error,
                context={"date": date_str},
            )
            df["reason"] = df["reason"].map(
                lambda value: _clean_text(value) or "上榜原因暂缺"
            )

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
            "reason":    _clean_text(row.get("reason", "")) or "上榜原因暂缺",
        })

    # 当日明细优先展示资金关注度最高的股票；相同成交额保留源数据顺序。
    entries.sort(key=lambda item: item["amount"], reverse=True)

    updated_at = datetime.now().strftime("%H:%M:%S")
    payload = {
        "entries": entries,
        "date": date_str,
        "updated_at": updated_at,
        "amount_unit": _AMOUNT_UNIT,
        "source": _DAILY_SOURCE_NAME,
        "sort_by": "amount_desc",
        "is_published": True,
        "message": "",
    }
    _daily_cache[date_str] = {"payload": payload, "ts": now}
    return payload
