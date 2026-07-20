"""Context builder for the floating, page-aware market copilot."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

from db import market_radar_db
from services.market_radar_service import get_market_radar


COPILOT_ROLES: dict[str, dict] = {
    "market": {
        "title": "综合决策",
        "desc": "多维证据 · 唯一结论",
        "agent_id": "copilot",
        "instruction": "统筹价格、广度、资金、新闻和个人标的，给出唯一结论与验证条件。",
    },
    "fundamentals": {
        "title": "财务基本面",
        "desc": "财报质量 · 估值 · 护城河",
        "agent_id": "fundamentals",
        "instruction": "优先核验财报质量、盈利趋势、估值和行业地位；缺少财务数据时先调用工具，不用当日涨跌代替基本面。",
    },
    "news": {
        "title": "消息面",
        "desc": "政策事件 · 新闻映射 · 预期差",
        "agent_id": "news",
        "instruction": "优先核验新闻时间、来源、影响链和市场是否已定价；把事实、映射和猜测严格分开。",
    },
    "technical": {
        "title": "技术量价",
        "desc": "趋势 · 量价 · 支撑压力",
        "agent_id": "technical",
        "instruction": "优先分析趋势结构、量价配合、关键支撑压力和失效条件；必须给具体可验证信号。",
    },
    "sentiment": {
        "title": "市场情绪",
        "desc": "广度 · 赚钱效应 · 资金偏好",
        "agent_id": "sentiment",
        "instruction": "优先分析上涨广度、涨停生态、情绪温度、资金偏好和拥挤风险，不得把单一净流入当成主力行为事实。",
    },
    "risk": {
        "title": "风险控制",
        "desc": "仓位 · 回撤 · 退出条件",
        "agent_id": "risk",
        "instruction": "优先检查持仓暴露、相关性、最大回撤和退出条件；结论必须落到仓位、减仓或风险触发线。",
    },
    "zhengxi": {
        "title": "郑希风格",
        "desc": "景气成长 · ROE跃迁 · 客观修正",
        "agent_id": "copilot",
        "instruction": "采用郑希公开景气成长方法论的分析风格，但不得声称自己是郑希本人；重点看景气、ROE跃迁、流动性和逻辑是否变化。",
    },
}


def get_copilot_role(role_id: str | None) -> tuple[str, dict]:
    normalized = str(role_id or "market").strip().lower()
    if normalized not in COPILOT_ROLES:
        raise ValueError(f"未知悬浮助手角色: {normalized}")
    return normalized, COPILOT_ROLES[normalized]


def list_copilot_roles() -> list[dict]:
    return [
        {"id": role_id, "title": role["title"], "desc": role["desc"]}
        for role_id, role in COPILOT_ROLES.items()
    ]


def _role_guidance(role_id: str, role: dict, question: str) -> str:
    guidance = (
        f"当前回答角色：{role['title']}。{role['instruction']}"
        "\n用户可以问任何问题。如果问题与当前页面或投资无关，就像普通大模型一样直接回答，"
        "忽略页面上不相关的行情上下文，不强行联系股票，也不为通用问题调用行情工具。"
    )
    if role_id != "zhengxi":
        return guidance
    try:
        from services.zhengxi_service import build_copilot_guidance
        method = build_copilot_guidance(question)
        if method:
            guidance += "\n\n" + method
    except Exception:
        guidance += "\n郑希语料暂不可用，只按已知的景气成长框架分析，不编造原话。"
    return guidance


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


def build_copilot_context(
    page_context: dict | None = None,
    role_id: str = "market",
    question: str = "",
) -> dict:
    """Enrich a lightweight page target with verified server-side market evidence."""
    role_id, role = get_copilot_role(role_id)
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
        "assistant_role": {"id": role_id, "title": role["title"]},
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
        "capture_status": radar.get("capture_status") or {},
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
            "哪个证据拥有更高决策权。但页面上下文只是补充材料；当它与用户的实际问题无关时，"
            "必须忽略它并直接回答问题。\n" + _compact(evidence)
            + "\n\n## 本轮角色要求\n" + _role_guidance(role_id, role, question)
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
