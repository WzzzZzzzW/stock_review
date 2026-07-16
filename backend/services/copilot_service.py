"""Context builder for the floating, page-aware market copilot."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

from db import market_radar_db
from services.market_radar_service import get_market_radar


def _compact(value: Any, max_chars: int = 12000) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
    return text if len(text) <= max_chars else text[:max_chars] + "...[截断]"


def _target_sector(radar: dict, name: str) -> dict:
    rows = ((radar.get("rotation") or {}).get("all") or [])
    return next((row for row in rows if row.get("name") == name), {})


def _sector_history(name: str, limit: int = 8) -> list[dict]:
    if not name:
        return []
    snapshots = market_radar_db.list_snapshots(date.today().isoformat())[-limit:]
    history = []
    for snapshot in snapshots:
        row = next(
            (item for item in snapshot.get("sectors", []) if item.get("name") == name),
            None,
        )
        if row:
            history.append({
                "captured_at": snapshot.get("captured_at"),
                "phase": snapshot.get("phase"),
                "pct": row.get("pct"),
                "breadth": row.get("breadth"),
                "up_count": row.get("up_count"),
                "down_count": row.get("down_count"),
                "net_in": row.get("net_in"),
                "score": row.get("score"),
                "rank": row.get("rank"),
            })
    return history


def build_copilot_context(page_context: dict | None = None) -> dict:
    """Enrich a lightweight page target with verified server-side market evidence."""
    raw = page_context or {}
    requested_phase = str(raw.get("phase") or "intraday")
    phase = requested_phase if requested_phase in {"premarket", "intraday"} else "intraday"
    target = raw.get("target") if isinstance(raw.get("target"), dict) else {}
    target_type = str(target.get("type") or "page")
    target_name = str(target.get("name") or "")
    radar = get_market_radar(phase=phase)

    sector = _target_sector(radar, target_name) if target_type == "sector" else {}
    news = [
        row for row in (radar.get("news") or [])
        if not target_name
        or target_name in (row.get("affected_sectors") or [])
        or target_name in str(row.get("title") or "")
    ][:6]
    personal = radar.get("personal") or {}
    personal_rows = (personal.get("positions") or []) + (personal.get("watchlist") or [])
    related_personal = [
        row for row in personal_rows
        if not target_name
        or row.get("industry") == target_name
        or row.get("name") == target_name
        or row.get("symbol") == target_name
    ]

    evidence = {
        "server_time": datetime.now().isoformat(timespec="seconds"),
        "page": raw.get("page") or "股票分析",
        "requested_phase": requested_phase,
        "actual_phase": radar.get("actual_phase"),
        "radar_updated_at": radar.get("updated_at"),
        "target": {
            "type": target_type,
            "name": target_name,
            "visible_data": target.get("data") or {},
        },
        "market": radar.get("market") or {},
        "sector": sector,
        "sector_recent_snapshots": _sector_history(target_name) if sector else [],
        "related_news": news,
        "related_positions_and_watchlist": related_personal,
        "personal_summary": personal.get("summary"),
        "data_notes": radar.get("data_notes") or [],
        "known_missing_evidence": [
            "没有板块内各股票对净流入的贡献明细，不能判断资金是否集中在少数股票",
            "没有逐笔委托和盘口队列，不能判断托盘、对倒、拆单、诱多或出货",
            "没有板块总成交额和净流入率，不能判断绝对净流入金额相对板块体量是否显著",
        ] if sector else [],
    }
    return {
        "extra": (
            "以下是服务器刚刚核验的页面和市场上下文。回答必须优先使用这些数据，"
            "不得把数据商净流入等推算口径当作绝对事实；若多个维度冲突，必须明确指出"
            "哪个证据拥有更高决策权。\n" + _compact(evidence)
        )
    }


_UNSUPPORTED_SECTOR_CAUSAL_PATTERNS = (
    "资金集中", "集中在", "集中于", "权重股", "托盘", "对倒", "拆单",
    "诱多", "出货", "大单买入", "某只贡献", "一只贡献", "少数股票",
    "少数个股", "合理的推断方向", "可能性极大",
    "按可能性排序", "早盘流入", "尾盘砸盘", "尾盘流出", "无法验证这一点",
)


def enforce_evidence_boundary(response: str, page_context: dict | None = None) -> str:
    """Drop unsupported causal paragraphs when the current context lacks that evidence."""
    target = ((page_context or {}).get("target") or {})
    if target.get("type") != "sector" or not response:
        return response

    blocks = re.split(r"\n{2,}", response)
    kept = [
        block for block in blocks
        if not any(pattern in block for pattern in _UNSUPPORTED_SECTOR_CAUSAL_PATTERNS)
    ]
    cleaned = "\n\n".join(block for block in kept if block.strip()).strip()
    boundary = (
        "**数据边界**：当前没有板块内各股票的资金贡献、板块总成交额和逐笔委托数据，"
        "因此不能判断净流入来自哪些股票，也不能判断具体交易行为。"
    )
    return f"{cleaned}\n\n{boundary}" if cleaned else boundary
