"""
除权除息自动调整 — 检测持仓股票的分红送转事件并调整成本+持股数

调整公式（以 10转N派M元 为例，每股调整）：
  新持股数 = 旧持股数 × (1 + (送股+转增) / 10)
  收到现金 = 旧持股数 × M / 10
  新成本   = (旧持股数 × 旧成本 - 收到现金) / 新持股数
  实际效果：净额不变，单价被"摊薄"

注意：派息（不含送转）只摊薄成本，不改变持股数
"""
from __future__ import annotations
import datetime as _dt


def _to_date(s) -> _dt.date | None:
    """容错把字符串/Timestamp转 date"""
    if s is None:
        return None
    if hasattr(s, "date"):
        try:
            return s.date()
        except Exception:
            pass
    try:
        return _dt.datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def fetch_dividend_events(symbol: str) -> list[dict]:
    """
    获取股票的全部历史分红送转事件（按除权除息日升序）
    返回: [{ex_date(date), gift, transfer, dividend, progress, announce_date}]
      gift=送股(每10股X), transfer=转增(每10股X), dividend=派息(每10股X元)
    """
    try:
        import akshare as ak
        df = ak.stock_history_dividend_detail(symbol=symbol, indicator="分红")
    except Exception:
        return []

    events = []
    for _, row in df.iterrows():
        ex_date = _to_date(row.get("除权除息日"))
        progress = str(row.get("进度", "")).strip()
        if not ex_date or progress != "实施":
            continue
        try:
            gift = float(row.get("送股", 0) or 0)
            transfer = float(row.get("转增", 0) or 0)
            dividend = float(row.get("派息", 0) or 0)
        except Exception:
            continue
        if gift == 0 and transfer == 0 and dividend == 0:
            continue
        events.append({
            "ex_date": ex_date,
            "gift": gift,
            "transfer": transfer,
            "dividend": dividend,
            "announce_date": _to_date(row.get("公告日期")),
            "description": _format_event(gift, transfer, dividend),
        })

    events.sort(key=lambda e: e["ex_date"])
    return events


def _format_event(gift: float, transfer: float, dividend: float) -> str:
    """格式化为人类可读的方案描述"""
    parts = []
    if gift > 0:
        parts.append(f"10送{gift:g}")
    if transfer > 0:
        parts.append(f"10转{transfer:g}")
    if dividend > 0:
        parts.append(f"派{dividend:g}元")
    return "·".join(parts) if parts else "无变化"


def apply_event(position: dict, event: dict) -> dict:
    """
    对单个持仓应用一次除权除息事件，返回调整明细。
    position 会被原地修改（quantity, buy_price 更新）。
    """
    old_qty = float(position.get("quantity", 0))
    old_cost = float(position.get("buy_price", 0))

    gift = event["gift"]            # 送股 (每10股X)
    transfer = event["transfer"]    # 转增 (每10股X)
    dividend = event["dividend"]    # 派息 (每10股X元)

    bonus_ratio = (gift + transfer) / 10.0        # 总送转倍数（如 0.2 表示10送2）
    new_qty = old_qty * (1 + bonus_ratio)
    cash_received = old_qty * dividend / 10.0
    old_total = old_qty * old_cost
    new_cost = (old_total - cash_received) / new_qty if new_qty > 0 else old_cost

    position["quantity"] = round(new_qty, 2)
    position["buy_price"] = round(new_cost, 4)

    return {
        "ex_date": event["ex_date"].isoformat(),
        "description": event["description"],
        "qty_before": old_qty,
        "qty_after": position["quantity"],
        "cost_before": old_cost,
        "cost_after": position["buy_price"],
        "cash_received": round(cash_received, 2),
    }


def pending_events_for_position(position: dict) -> list[dict]:
    """
    返回某持仓还没被应用的除权除息事件。
    判定规则：除权除息日 > 买入日 且 > last_adjusted_date（如有）
    """
    symbol = position.get("symbol", "")
    if not symbol:
        return []

    buy_date = _to_date(position.get("buy_date"))
    if not buy_date:
        return []

    last_adj = _to_date(position.get("last_adjusted_date")) or buy_date

    all_events = fetch_dividend_events(symbol)
    today = _dt.date.today()
    pending = [
        e for e in all_events
        if e["ex_date"] > last_adj and e["ex_date"] <= today
    ]
    return pending


def check_and_apply(positions: list[dict]) -> list[dict]:
    """
    对一组持仓批量检测+应用除权除息调整。
    返回应用的调整明细列表（用于UI展示）。
    positions 会被原地修改。
    """
    adjustments = []
    today_iso = _dt.date.today().isoformat()

    for pos in positions:
        pending = pending_events_for_position(pos)
        if not pending:
            # 无待应用事件，但仍然推进 last_adjusted_date 到今天
            pos["last_adjusted_date"] = today_iso
            continue

        for event in pending:
            detail = apply_event(pos, event)
            detail.update({
                "symbol": pos.get("symbol", ""),
                "name": pos.get("name", ""),
            })
            adjustments.append(detail)

        pos["last_adjusted_date"] = today_iso
        # 在备注里追加调整日志
        log_line = f" | {pending[-1]['ex_date'].isoformat()} 除权除息({pending[-1]['description']}) 已自动调整"
        notes = pos.get("notes", "")
        if log_line.strip() not in notes:
            pos["notes"] = (notes or "") + log_line
        pos["updated_at"] = _dt.datetime.now().isoformat()

    return adjustments
