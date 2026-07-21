"""盘后复盘证据包：个股资金、行业资金、广度、龙头与盘中资金变化。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any


def _f(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(str(value).replace(",", "").strip())
        return default if number != number else number
    except Exception:
        return default


def _yi(value: Any) -> float | None:
    number = _f(value)
    return round(number / 100000000, 2) if number is not None else None


def _breadth(row: dict) -> float | None:
    up = _f(row.get("up_count"))
    down = _f(row.get("down_count"))
    if up is None or down is None or up + down <= 0:
        return None
    return round(up / (up + down) * 100, 1)


def _sector_flow_changes(trade_date: str) -> dict[str, dict]:
    try:
        from db.market_radar_db import list_snapshots

        snapshots = [
            row for row in list_snapshots(trade_date)
            if row.get("phase") in {"intraday", "postmarket"} and row.get("sectors")
        ]
        if not snapshots:
            return {}
        first = {str(row.get("name")): row for row in snapshots[0].get("sectors") or []}
        last = {str(row.get("name")): row for row in snapshots[-1].get("sectors") or []}
        result: dict[str, dict] = {}
        for name, latest in last.items():
            current = _f(latest.get("net_in"))
            opening = _f((first.get(name) or {}).get("net_in"))
            result[name] = {
                "first_net_in_yi": opening,
                "last_net_in_yi": current,
                "net_in_change_yi": round(current - opening, 2)
                if current is not None and opening is not None else None,
                "first_at": snapshots[0].get("captured_at", ""),
                "last_at": snapshots[-1].get("captured_at", ""),
                "snapshot_count": len(snapshots),
            }
        return result
    except Exception:
        return {}


def _stock_fund_flows(symbols: list[str], trade_date: str) -> dict[str, dict]:
    from data.stock_data import get_stock_fund_flow_day

    unique = [symbol for symbol in dict.fromkeys(symbols) if symbol]
    if not unique:
        return {}
    result: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=min(6, len(unique))) as pool:
        futures = {pool.submit(get_stock_fund_flow_day, symbol): symbol for symbol in unique}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                raw = future.result() or {}
            except Exception as exc:
                raw = {"error": str(exc)}
            flow_date = str(raw.get("date") or "")[:10]
            if flow_date != trade_date:
                result[symbol] = {
                    "available": False,
                    "date": flow_date,
                    "note": "个股资金日期与复盘日期不一致，未用于判断。",
                }
                continue
            main_net_yi = _yi(raw.get("main_net"))
            result[symbol] = {
                "available": main_net_yi is not None,
                "date": flow_date,
                "main_net_yi": main_net_yi,
                "main_net_pct": _f(raw.get("main_net_pct")),
                "super_net_yi": _yi(raw.get("super_net")),
                "big_net_yi": _yi(raw.get("big_net")),
                "mid_net_yi": _yi(raw.get("mid_net")),
                "small_net_yi": _yi(raw.get("small_net")),
                "source": raw.get("source", ""),
                "basis": "数据商按成交单大小推算，仅作资金方向证据。",
            }
    return result


def build_review_evidence(
    symbols: list[str],
    trade_date: str,
    stock_names: dict[str, str] | None = None,
) -> dict:
    """一次构建复盘所需的共享资金和行业证据，避免持仓/自选重复请求。"""
    try:
        from api.industry import industry_summary
        from data.stock_data import get_industry_map

        industry_by_symbol = get_industry_map(block=True)
        industry_data = industry_summary()
        sectors = industry_data.get("industries") or []
        updated_at = industry_data.get("updated_at", "")
    except Exception:
        industry_by_symbol = {}
        sectors = []
        updated_at = ""

    changes = _sector_flow_changes(trade_date)
    normalized_sectors = []
    sector_by_name: dict[str, dict] = {}
    for row in sectors:
        name = str(row.get("name") or "")
        normalized = {
            **row,
            "breadth_pct": _breadth(row),
            "net_in_yi": _f(row.get("net_in")),
            "fund_change": changes.get(name) or {},
            "fund_basis": "行业净流入为数据商成交口径推算。",
        }
        normalized_sectors.append(normalized)
        sector_by_name[name] = normalized

    fund_by_symbol = _stock_fund_flows(symbols, trade_date)
    by_symbol = {}
    names = stock_names or {}
    for symbol in dict.fromkeys(symbols):
        broad_industry = str(industry_by_symbol.get(symbol) or "")
        try:
            from services.market_radar_service import _resolve_personal_sector

            industry, sector = _resolve_personal_sector(
                names.get(symbol, ""), broad_industry, sector_by_name
            )
        except Exception:
            industry, sector = broad_industry, sector_by_name.get(broad_industry) or {}
        by_symbol[symbol] = {
            "industry": industry,
            "broad_industry": broad_industry,
            "sector": sector,
            "fund_flow": fund_by_symbol.get(symbol) or {
                "available": False,
                "date": "",
                "note": "个股资金数据暂不可用，禁止据此推断流入或流出。",
            },
        }

    return {
        "trade_date": trade_date,
        "updated_at": updated_at,
        "by_symbol": by_symbol,
        "sectors": normalized_sectors,
        "sector_by_name": sector_by_name,
        "basis": "个股与行业净流入均为数据商按成交口径推算，必须与价格、成交、广度和龙头承接共同判断。",
    }
