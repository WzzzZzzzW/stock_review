"""Personal market radar: snapshot deltas, sector rotation, events and portfolio impact."""
from __future__ import annotations

import math
import re
import threading
from datetime import date, datetime
from typing import Any

from db import market_radar_db, watchlist_db


_ATTACK_STATES = {"新启动", "加速", "主线扩散", "主线持续", "轮动增强", "超跌修复"}
_RISK_STATES = {"高位分歧", "资金撤退", "弱势退潮", "假突破"}
_news_warming = False


def _f(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return default if math.isnan(number) or math.isinf(number) else number
    except Exception:
        return default


def _money_yi(value: Any) -> float:
    if value in (None, "", "--"):
        return 0.0
    text = str(value).replace(",", "").strip()
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return 0.0
    number = _f(match.group())
    if "万" in text and "亿" not in text:
        return number / 10000
    if "元" in text and "亿" not in text:
        return number / 100000000
    return number


def _breadth(row: dict) -> float:
    up = _f(row.get("up_count"))
    down = _f(row.get("down_count"))
    return up / (up + down) if up + down > 0 else 0.5


def _normalize_sectors(rows: list[dict]) -> list[dict]:
    normalized = []
    for rank, row in enumerate(rows, 1):
        decision = row.get("decision") or {}
        normalized.append({
            "name": str(row.get("name") or ""),
            "pct": round(_f(row.get("pct_num"), _f(str(row.get("pct") or "0").replace("%", ""))), 2),
            "breadth": round(_breadth(row), 4),
            "up_count": int(_f(row.get("up_count"))),
            "down_count": int(_f(row.get("down_count"))),
            "net_in": round(_money_yi(row.get("net_in")), 3),
            "leader": str(row.get("leader") or "--"),
            "score": int(_f(decision.get("score"), 50)),
            "rank": rank,
            "decision": decision,
        })
    return normalized


def classify_sector_state(current: dict, previous: dict | None = None) -> dict:
    """Classify the rotation stage from level plus change, not daily pct alone."""
    previous = previous or {}
    has_previous = bool(previous)
    score = _f(current.get("score"), 50)
    pct = _f(current.get("pct"))
    breadth = _f(current.get("breadth"), 0.5)
    net_in = _f(current.get("net_in"))
    rank = int(_f(current.get("rank"), 99))
    prev_score = _f(previous.get("score"), score)
    prev_pct = _f(previous.get("pct"), pct)
    prev_breadth = _f(previous.get("breadth"), breadth)
    prev_net = _f(previous.get("net_in"), net_in)
    prev_rank = int(_f(previous.get("rank"), rank))

    delta_score = score - prev_score
    delta_pct = pct - prev_pct
    delta_breadth = (breadth - prev_breadth) * 100
    delta_net = net_in - prev_net
    rank_jump = prev_rank - rank
    velocity = delta_score * 0.35 + delta_pct * 8 + delta_breadth * 0.18 + delta_net * 0.45 + rank_jump * 0.8

    if has_previous and prev_score >= 62 and (delta_score <= -8 or delta_breadth <= -15):
        state = "高位分歧" if score >= 50 else "资金撤退"
    elif has_previous and prev_score >= 52 and score < 45:
        state = "资金撤退"
    elif pct > 0.5 and breadth < 0.44:
        state = "假突破"
    elif has_previous and prev_score < 52 and score >= 60 and delta_breadth >= 6:
        state = "新启动"
    elif score >= 70 and breadth >= 0.68 and (not has_previous or velocity >= -1):
        state = "主线扩散" if not has_previous or delta_breadth >= 5 or delta_score >= 4 else "主线持续"
    elif has_previous and score >= 62 and velocity >= 8:
        state = "加速"
    elif has_previous and prev_score < 48 and score >= 52 and delta_score >= 7:
        state = "超跌修复"
    elif score >= 56 and (not has_previous or velocity >= 1):
        state = "轮动增强"
    elif score < 42:
        state = "弱势退潮"
    else:
        state = "中性整理"

    if state in _ATTACK_STATES:
        tone = "attack"
    elif state in _RISK_STATES:
        tone = "risk"
    else:
        tone = "neutral"

    evidence = []
    if has_previous:
        evidence.append(f"评分{delta_score:+.0f}")
        evidence.append(f"广度{delta_breadth:+.0f}个百分点")
        if abs(delta_net) >= 0.05:
            evidence.append(f"净流入变化{delta_net:+.2f}亿")
        if rank_jump:
            evidence.append(f"排名{rank_jump:+d}")
    else:
        evidence.append(f"当前评分{score:.0f}")
        evidence.append(f"上涨广度{breadth * 100:.0f}%")
        evidence.append("等待下一次快照确认变化")

    return {
        **current,
        "state": state,
        "tone": tone,
        "velocity": round(velocity, 1),
        "delta": {
            "score": round(delta_score, 1),
            "pct": round(delta_pct, 2),
            "breadth": round(delta_breadth, 1),
            "net_in": round(delta_net, 2),
            "rank": rank_jump,
        },
        "evidence": " · ".join(evidence),
    }


def _collect_core() -> tuple[dict, list[dict], dict]:
    from api.daily_report import _fetch_indices, _fetch_sectors
    from api.industry import industry_summary
    from services.market_clock import get_market_status
    from services.verdict_service import compute_market_decision

    status = get_market_status()
    indices = _fetch_indices()
    sector_overview = _fetch_sectors()
    decision = compute_market_decision(indices, sector_overview)
    try:
        industries_payload = industry_summary()
        industry_rows = industries_payload.get("industries", [])
        industry_updated = industries_payload.get("updated_at", "")
    except Exception as exc:
        industry_rows = []
        industry_updated = ""
        print(f"[market-radar] 行业数据不可用: {exc}")
    sectors = _normalize_sectors(industry_rows)

    index_pcts = [_f(row.get("pct")) for row in indices]
    avg_index = sum(index_pcts) / len(index_pcts) if index_pcts else 0.0
    dispersion = max(index_pcts) - min(index_pcts) if index_pcts else 0.0
    total_sectors = max(1, len(sectors))
    positive_sectors = sum(1 for row in sectors if row["pct"] > 0)
    market = {
        "indices": indices,
        "decision": decision,
        "avg_index_pct": round(avg_index, 2),
        "index_dispersion": round(dispersion, 2),
        "sector_up_ratio": round(positive_sectors / total_sectors * 100),
        "sector_count": len(sectors),
        "industry_updated_at": industry_updated,
    }
    return market, sectors, status


def capture_market_snapshot(force: bool = False, only_open: bool = False) -> dict:
    if only_open:
        from services.market_clock import get_market_status
        if not get_market_status().get("is_market_open"):
            return market_radar_db.latest_snapshot() or {}
    market, sectors, status = _collect_core()
    interval = 0 if force else 150
    return market_radar_db.save_snapshot(status.get("phase", "unknown"), market, sectors, interval)


def _capture_status(trade_date: str | None = None) -> dict:
    from services.market_clock import get_market_status

    day = trade_date or date.today().isoformat()
    summary = market_radar_db.snapshot_summary(day)
    intraday = summary["intraday"]
    market_status = get_market_status()
    count = intraday["count"]
    if count >= 2:
        state = "ready"
        message = f"已自动记录{count}个盘中快照，可检验市场方向和板块延续。"
    elif day == market_status["today"] and market_status["phase"] == "intraday":
        state = "collecting"
        message = f"正在自动采集，当前已有{count}个盘中快照；每3分钟新增一次。"
    elif summary["total"] > 0:
        first_any = min(
            (item["first_at"] for item in summary["phases"].values() if item["first_at"]),
            default="",
        )
        first_clock = first_any[11:16] if len(first_any) >= 16 else "收盘后"
        state = "missed_session"
        message = f"程序在该交易日从{first_clock}才开始记录，已错过盘中轨迹；收盘数据不能倒推出真实盘中变化。"
    else:
        state = "missing"
        message = "当天没有运行采集服务，历史盘中轨迹无法由收盘数据真实还原。"
    return {
        "enabled": True,
        "interval_seconds": 180,
        "state": state,
        "message": message,
        "snapshot_count": count,
        "first_at": intraday["first_at"],
        "last_at": intraday["last_at"],
        "next_session": "股票分析服务运行时，下个交易日09:30起自动采集，无需打开页面。" if state in {"missed_session", "missing"} else "",
    }


def _rotation_rows(current: list[dict], previous: list[dict]) -> list[dict]:
    previous_map = {row.get("name"): row for row in previous}
    rows = [classify_sector_state(row, previous_map.get(row.get("name"))) for row in current]
    rows.sort(key=lambda row: (row["tone"] == "attack", row["score"], row["velocity"]), reverse=True)
    return rows


def _build_changes(market: dict, previous_market: dict, rotations: list[dict]) -> list[dict]:
    changes: list[dict] = []
    now = datetime.now().isoformat(timespec="seconds")
    current_decision = market.get("decision") or {}
    previous_decision = previous_market.get("decision") or {}
    score_delta = _f(current_decision.get("score")) - _f(previous_decision.get("score"), _f(current_decision.get("score")))
    if previous_market and (current_decision.get("action") != previous_decision.get("action") or abs(score_delta) >= 6):
        changes.append({
            "key": f"market:{previous_decision.get('action')}:{current_decision.get('action')}",
            "occurred_at": now,
            "severity": "critical" if score_delta <= -8 else "important",
            "category": "market",
            "title": f"市场总指令变为{current_decision.get('action', '待确认')}",
            "detail": f"市场评分变化{score_delta:+.0f}，当前仓位上限{current_decision.get('position_cap', '--')}%。",
            "entity": "全市场",
            "magnitude": abs(score_delta) + 20,
        })

    for row in rotations:
        delta = row.get("delta") or {}
        state = row.get("state")
        meaningful = state in _ATTACK_STATES | _RISK_STATES and (
            abs(_f(delta.get("score"))) >= 5
            or abs(_f(delta.get("breadth"))) >= 8
            or abs(_f(delta.get("rank"))) >= 6
            or abs(_f(delta.get("net_in"))) >= 0.8
        )
        if not meaningful:
            continue
        severity = "critical" if state in {"资金撤退", "主线扩散", "新启动"} else "important"
        action = "升级为进攻方向" if state in _ATTACK_STATES else "降级并控制追涨"
        changes.append({
            "key": f"sector:{row['name']}:{state}",
            "occurred_at": now,
            "severity": severity,
            "category": "rotation",
            "title": f"{row['name']}进入{state}",
            "detail": f"{row['evidence']}；结论：{action}。",
            "entity": row["name"],
            "magnitude": abs(_f(row.get("velocity"))) + (15 if severity == "critical" else 8),
        })

    changes.sort(key=lambda item: item.get("magnitude", 0), reverse=True)
    return changes[:8]


_NEWS_SECTOR_HINTS = {
    "芯片": ["半导体", "元件"], "半导体": ["半导体", "元件"], "算力": ["通信设备", "IT服务"],
    "AI": ["软件开发", "通信设备"], "机器人": ["自动化设备", "通用设备"],
    "创新药": ["化学制药", "生物制品"], "医药": ["化学制药", "生物制品", "医疗服务"],
    "光伏": ["光伏设备"], "锂电": ["电池"], "储能": ["电池", "电网设备"],
    "油价": ["石油行业"], "原油": ["石油行业"], "黄金": ["贵金属"], "铜": ["工业金属"],
    "军工": ["航空装备", "航天装备"], "地产": ["房地产开发"], "白酒": ["白酒"],
    "消费": ["食品饮料", "零售"], "证券": ["证券"], "银行": ["银行"],
}

_PERSONAL_SECTOR_HINTS = {
    # Single-user product: keep high-value known mappings exact, then fall back to generic industry matching.
    "北方华创": "半导体",
    "华天科技": "半导体",
    "长电科技": "半导体",
    "恒瑞医药": "化学制药",
    "药明康德": "医疗服务",
    "浪潮信息": "计算机设备",
    "泛微网络": "软件开发",
    "华友钴业": "能源金属",
}

_BROAD_INDUSTRY_HINTS = {
    "软件和信息技术服务": ["软件开发", "IT服务"],
    "计算机、通信和其他电子设备": ["计算机设备", "通信设备", "消费电子", "半导体", "元件", "其他电子"],
    "有色金属冶炼和压延": ["能源金属", "工业金属", "小金属", "贵金属"],
    "专用设备制造": ["专用设备", "半导体", "自动化设备"],
    "电气机械和器材制造": ["电机", "电网设备", "电池", "光伏设备"],
    "医药制造": ["化学制药", "生物制品", "中药"],
}


def _resolve_personal_sector(name: str, broad_industry: str, rotation_map: dict[str, dict]) -> tuple[str, dict]:
    exact_hint = _PERSONAL_SECTOR_HINTS.get(name, "")
    if exact_hint and exact_hint in rotation_map:
        return exact_hint, rotation_map[exact_hint]
    if broad_industry in rotation_map:
        return broad_industry, rotation_map[broad_industry]
    normalized = broad_industry.replace("制造业", "").replace("行业", "").rstrip("业")
    direct = [sector for sector in rotation_map if sector in broad_industry or (normalized and normalized in sector)]
    if direct:
        best = max(direct, key=lambda sector: _f(rotation_map[sector].get("score"), 50))
        return best, rotation_map[best]
    candidates = []
    for keyword, names in _BROAD_INDUSTRY_HINTS.items():
        if keyword in broad_industry:
            candidates.extend(name for name in names if name in rotation_map)
    if candidates:
        best = max(candidates, key=lambda sector: _f(rotation_map[sector].get("score"), 50))
        return best, rotation_map[best]
    return broad_industry, {}


def _affected_sectors(news: dict, available: set[str]) -> list[str]:
    # Prefer explicit headline transmission. Only consult summaries when the headline has no sector clue.
    for key in ("title", "summary", "one_line"):
        text = str(news.get(key) or "")
        found = []
        for keyword, candidates in _NEWS_SECTOR_HINTS.items():
            if keyword.lower() not in text.lower():
                continue
            for candidate in candidates:
                exact = next((name for name in available if candidate in name or name in candidate), "")
                label = exact or candidate
                if label not in found:
                    found.append(label)
        if found:
            return found[:4]
    return []


def _warm_news_cache() -> None:
    global _news_warming
    if _news_warming:
        return
    _news_warming = True
    try:
        from api.news_trending import _get_items
        _get_items("cn", False)
        _get_items("intl", False)
    except Exception as exc:
        print(f"[market-radar] 新闻缓存预热失败: {exc}")
    finally:
        _news_warming = False


def _news_events(sector_names: set[str]) -> list[dict]:
    try:
        from api.news_feed import _cache as global_cache
        from api.news_feed_cn import _cache as cn_cache
        from services.news_ranking_service import compute_trending

        combined = []
        for market, cache in (("cn", cn_cache), ("intl", global_cache)):
            items = cache.get("items") or []
            if items:
                for row in compute_trending(items, market, top_n=4)[:3]:
                    combined.append({
                        **row,
                        "market": market,
                        "affected_sectors": _affected_sectors(row, sector_names),
                    })
        if not combined:
            threading.Thread(target=_warm_news_cache, daemon=True, name="radar-news-warm").start()
        combined.sort(key=lambda row: _f(row.get("hotness")), reverse=True)
        return combined[:6]
    except Exception:
        return []


def _personal_impact(rotations: list[dict]) -> dict:
    rotation_map = {row["name"]: row for row in rotations}
    try:
        from api.portfolio import _load_store
        positions = _load_store().get("positions", [])
    except Exception:
        positions = []
    watches = watchlist_db.list_items()
    symbols = list(dict.fromkeys(
        [str(row.get("symbol") or "").zfill(6) for row in positions]
        + [str(row.get("code") or "").zfill(6) for row in watches]
    ))
    quotes = {}
    industry_map = {}
    try:
        from api.watchlist import _fetch_sina_hq
        from data.stock_data import get_industry_map
        quotes = _fetch_sina_hq(symbols)
        industry_map = get_industry_map(block=False)
    except Exception:
        pass

    def build(items: list[dict], kind: str) -> list[dict]:
        result = []
        for item in items:
            symbol = str(item.get("symbol") or item.get("code") or "").zfill(6)
            quote = quotes.get(symbol) or {}
            name = quote.get("name") or item.get("name") or symbol
            broad_industry = industry_map.get(symbol, "")
            industry, sector = _resolve_personal_sector(name, broad_industry, rotation_map)
            state = sector.get("state") or "待映射"
            tone = sector.get("tone") or "neutral"
            action = "板块拖累" if tone == "risk" else "板块助攻" if tone == "attack" else "板块中性"
            if sector:
                reason = f"{industry}处于{state}，板块评分{sector.get('score', '--')}。"
            elif broad_industry:
                reason = f"{broad_industry}尚未匹配到可验证板块，保持原计划。"
            else:
                reason = "行业映射尚未完成，不用单日涨跌替代板块判断。"
            result.append({
                "symbol": symbol,
                "name": name,
                "kind": kind,
                "pct_change": round(_f(quote.get("pct_change")), 2),
                "industry": industry or "行业待映射",
                "sector_state": state,
                "sector_score": sector.get("score"),
                "tone": tone,
                "action": action,
                "reason": reason,
            })
        result.sort(key=lambda row: (row["tone"] == "risk", row["tone"] == "attack"), reverse=True)
        return result

    position_rows = build(positions, "position")
    watch_rows = build(watches, "watchlist")
    unique = {row["symbol"]: row for row in watch_rows}
    unique.update({row["symbol"]: row for row in position_rows})
    risks = [row for row in unique.values() if row["tone"] == "risk"]
    opportunities = [row for row in unique.values() if row["tone"] == "attack"]
    return {
        "positions": position_rows,
        "watchlist": watch_rows,
        "summary": f"{len(risks)}只受退潮方向影响，{len(opportunities)}只处于增强方向。",
        "risk_count": len(risks),
        "opportunity_count": len(opportunities),
    }


def _capital_map(rotations: list[dict]) -> dict:
    inflow = sorted(rotations, key=lambda row: row.get("net_in", 0), reverse=True)[:10]
    outflow = sorted(rotations, key=lambda row: row.get("net_in", 0))[:10]
    return {
        "inflow": inflow,
        "outflow": outflow,
        "note": "净流入为数据商成交口径推算，必须与上涨广度、成交变化和龙头承接共同使用。",
    }


def get_stock_capital_ranking(limit: int = 10, force: bool = False) -> dict:
    from data.stock_data import get_realtime_stock_fund_flow_rank

    return get_realtime_stock_fund_flow_rank(
        limit=max(1, min(limit, 20)),
        max_age_seconds=0 if force else 60,
    )


def _briefing(market: dict, rotations: list[dict], news: list[dict], personal: dict) -> dict:
    attack = [row for row in rotations if row.get("tone") == "attack"][:4]
    risk = [row for row in rotations if row.get("tone") == "risk"][:4]
    decision = market.get("decision") or {}
    focus = "、".join(row["name"] for row in attack[:3]) or "暂无通过多维验证的主线"
    avoid = "、".join(row["name"] for row in risk[:3]) or "暂无明确退潮方向"
    return {
        "thesis": decision.get("summary") or "市场证据尚未完整，保持低风险预算。",
        "focus": focus,
        "avoid": avoid,
        "personal": personal.get("summary") or "暂无个人标的映射。",
        "overnight": news[:4],
        "auction_checks": [
            {"time": "09:20", "title": "先看方向，不看单股", "detail": f"检查{focus}是否出现同方向高开，孤立高开不升级。"},
            {"time": "09:25", "title": "检查量能和龙头", "detail": "候选板块必须同时出现龙头承接、上涨家数扩散和成交放大。"},
            {"time": "09:27", "title": "做最终裁决", "detail": f"不满足确认条件就取消计划；优先回避{avoid}。"},
        ],
    }


def get_market_radar(phase: str = "intraday", force: bool = False) -> dict:
    market, sectors, status = _collect_core()
    day = date.today().isoformat()
    current_snapshot = market_radar_db.save_snapshot(
        status.get("phase", phase), market, sectors, 0 if force else 150
    )
    previous_snapshot = market_radar_db.comparison_snapshot(day, minutes_ago=5)
    if previous_snapshot and previous_snapshot.get("captured_at") == current_snapshot.get("captured_at"):
        previous_snapshot = None
    if not previous_snapshot and phase == "premarket":
        previous_snapshot = market_radar_db.latest_any_snapshot(before_date=day)

    previous_market = (previous_snapshot or {}).get("market") or {}
    previous_sectors = (previous_snapshot or {}).get("sectors") or []
    rotations = _rotation_rows(sectors, previous_sectors)
    changes = _build_changes(market, previous_market, rotations)
    market_radar_db.save_events(changes, day)
    timeline = market_radar_db.list_events(day, limit=12)
    if not timeline:
        timeline = [{
            "occurred_at": current_snapshot.get("captured_at"),
            "severity": "info",
            "category": "baseline",
            "title": "市场雷达正在建立比较基线",
            "detail": "下一次快照后开始识别板块加速、分歧、撤退和修复。",
            "entity": "全市场",
        }]

    sector_names = {row["name"] for row in rotations}
    news = _news_events(sector_names)
    personal = _personal_impact(rotations)
    attack = [row for row in rotations if row.get("tone") == "attack"][:8]
    risk = [row for row in rotations if row.get("tone") == "risk"][:8]
    neutral = [row for row in rotations if row.get("tone") == "neutral"][:8]

    result = {
        "phase": phase,
        "actual_phase": status.get("phase"),
        "updated_at": datetime.now().strftime("%H:%M:%S"),
        "comparison_at": (previous_snapshot or {}).get("captured_at", ""),
        "market": market,
        "rotation": {"attack": attack, "risk": risk, "neutral": neutral, "all": rotations},
        "capital": _capital_map(rotations),
        "changes": changes,
        "timeline": timeline,
        "news": news,
        "personal": personal,
        "capture_status": _capture_status(day),
        "data_notes": [
            "板块状态基于涨跌动量、上涨广度、净流入、龙头和时间序列变化综合判断。",
            "净流入不是绝对资金事实，只作为多维证据之一。",
        ],
    }
    if phase == "premarket":
        result["briefing"] = _briefing(market, rotations, news, personal)
    return result


def evaluate_radar_day(trade_date: str | None = None) -> dict:
    day = trade_date or date.today().isoformat()
    snapshots = market_radar_db.list_snapshots(day)
    intraday = [row for row in snapshots if row.get("phase") == "intraday"]
    usable = intraday
    if len(usable) < 2:
        capture_status = _capture_status(day)
        return {
            "trade_date": day,
            "ready": False,
            "snapshot_count": len(usable),
            "verdict": capture_status["message"],
            "market": {},
            "sectors": [],
            "capture_status": capture_status,
            "lessons": [capture_status["next_session"] or "至少需要两个不同时点的市场快照，才能检验盘中判断是否延续。"],
        }

    first, last = usable[0], usable[-1]
    first_market = first.get("market") or {}
    last_market = last.get("market") or {}
    first_decision = first_market.get("decision") or {}
    last_decision = last_market.get("decision") or {}
    first_score = _f(first_decision.get("score"), 50)
    last_score = _f(last_decision.get("score"), 50)

    def posture(score: float) -> str:
        if score >= 57:
            return "attack"
        if score < 46:
            return "risk"
        return "neutral"

    market_consistent = posture(first_score) == posture(last_score)
    market_review = {
        "first_action": first_decision.get("action") or "待确认",
        "last_action": last_decision.get("action") or "待确认",
        "first_score": round(first_score),
        "last_score": round(last_score),
        "consistent": market_consistent,
        "summary": (
            f"早段判断与收盘方向一致，市场评分从{first_score:.0f}到{last_score:.0f}。"
            if market_consistent else
            f"早段判断与收盘方向不一致，市场评分从{first_score:.0f}变为{last_score:.0f}，需要检查转折识别速度。"
        ),
    }

    first_rows = sorted(first.get("sectors") or [], key=lambda row: _f(row.get("score")), reverse=True)[:5]
    last_map = {row.get("name"): row for row in last.get("sectors") or []}
    sector_reviews = []
    for row in first_rows:
        final = last_map.get(row.get("name")) or {}
        initial_score = _f(row.get("score"), 50)
        final_score = _f(final.get("score"), 50)
        followed = final_score >= 56 and final_score >= initial_score - 8
        sector_reviews.append({
            "name": row.get("name") or "--",
            "initial_score": round(initial_score),
            "final_score": round(final_score),
            "followed": followed,
            "summary": "主线延续" if followed else "冲高后降级",
        })
    hit_count = sum(1 for row in sector_reviews if row["followed"])
    hit_rate = round(hit_count / len(sector_reviews) * 100) if sector_reviews else 0
    event_count = len(market_radar_db.list_events(day, limit=50))
    lessons = []
    if not market_consistent:
        lessons.append("市场状态发生方向切换，下一交易日提高指数承接和板块广度变化的权重。")
    if hit_rate < 50:
        lessons.append("早段强势板块延续率偏低，说明轮动快，下一交易日压低追高仓位。")
    else:
        lessons.append("强势板块多数延续，说明主线辨识有效，下一交易日优先观察原主线分歧后的承接。")
    if event_count == 0:
        lessons.append("当日未捕捉到显著状态变化，检查是否因快照时段不足。")

    return {
        "trade_date": day,
        "ready": True,
        "snapshot_count": len(usable),
        "first_at": first.get("captured_at"),
        "last_at": last.get("captured_at"),
        "verdict": f"市场方向判断{'有效' if market_consistent else '需要修正'}；前五强板块延续率{hit_rate}%。",
        "market": market_review,
        "sectors": sector_reviews,
        "sector_hit_rate": hit_rate,
        "event_count": event_count,
        "capture_status": _capture_status(day),
        "lessons": lessons,
    }
