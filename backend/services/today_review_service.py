"""
今日复盘总览：市场、持仓、自选、行业、国际形势、风险机会、明日关注。

原则：优先复用现有数据源和缓存，生成结果落库，供日历回看。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
        return default if f != f else f
    except Exception:
        return default


def _pct_label(v: float) -> str:
    return f"{v:+.2f}%"


def _compact_json(obj: Any, limit: int = 12000) -> str:
    text = json.dumps(obj, ensure_ascii=False, default=str)
    return text[:limit]


def _md_list(items: list[str]) -> str:
    return "\n".join(f"- {x}" for x in items if x) or "- 暂无明确结论"


def _parse_json_obj(raw: str) -> dict:
    if not raw:
        return {}
    raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return {}
    return {}


def _tech_map(symbols: list[str]) -> dict[str, dict]:
    symbols = [s for s in dict.fromkeys(symbols) if s]
    if not symbols:
        return {}
    try:
        from data.stock_data import fetch_quick_batch
        rows = fetch_quick_batch(symbols[:30])
        return {str(r.get("symbol")): r for r in rows if r.get("symbol")}
    except Exception as e:
        return {s: {"symbol": s, "error": str(e)} for s in symbols}


def _stock_logic(stock: dict) -> str:
    name = stock.get("name") or stock.get("symbol")
    pct = _safe_float(stock.get("pct_change"))
    tech = stock.get("tech") or {}
    today = tech.get("today") or {}
    technical = tech.get("technical") or {}
    trend = tech.get("trend") or {}
    tags = trend.get("tags") or []
    vol = technical.get("vol_ratio")
    ma20 = technical.get("ma20_pct")
    macd = technical.get("macd_status")
    turn = today.get("turn") or stock.get("turnover")

    direction = "上涨" if pct > 0 else "下跌" if pct < 0 else "平盘"
    parts = [f"{name} 今日{direction}{_pct_label(pct)}"]
    if vol is not None:
        if vol >= 1.5:
            parts.append(f"量能放大至 {vol} 倍，说明有新增资金/换手参与")
        elif vol <= 0.7:
            parts.append(f"量能仅 {vol} 倍，属于缩量，直接降低持续性评分")
        else:
            parts.append(f"量能 {vol} 倍，整体接近常态")
    if ma20 is not None:
        parts.append(f"收盘相对20日线 {ma20:+.2f}%")
    if macd:
        parts.append(f"MACD {macd}")
    if turn:
        parts.append(f"换手 {turn}%")
    if tags:
        parts.append("信号：" + "、".join(tags[:4]))
    return "；".join(parts) + "。"


def _stock_decision(stock: dict) -> dict:
    name = stock.get("name") or stock.get("symbol")
    pct = _safe_float(stock.get("pct_change"))
    tech = stock.get("tech") or {}
    technical = tech.get("technical") or {}
    trend = tech.get("trend") or {}
    tags = " ".join(trend.get("tags") or [])
    vol = _safe_float(technical.get("vol_ratio"))
    ma20 = _safe_float(technical.get("ma20_pct"))
    macd = str(technical.get("macd_status") or "")
    hot = ma20 >= 18 or "RSI超买" in tags or "连涨" in tags
    trend_bad = ma20 < -3 or "死叉" in macd or "空头" in macd
    trend_good = ma20 > 0 and ("多头" in macd or "强势" in tags)

    if pct <= -5:
        action = "剔除"
        reason = f"{name}单日下跌{_pct_label(pct)}，触发大阴线裁决，短线先出自选池。"
        rank = 5
    elif pct <= -3 and hot:
        action = "剔除"
        reason = f"{name}高位过热后下跌{_pct_label(pct)}，退潮信号优先于中期趋势，明日主计划剔除。"
        rank = 5
    elif pct >= 4 and trend_good and not hot and vol >= 1.05:
        action = "重点进攻"
        reason = f"{name}涨幅{_pct_label(pct)}，站上20日线{ma20:+.2f}%，MACD偏多且量能不弱，是自选池第一顺位。"
        rank = 0
    elif pct >= 3 and trend_good and hot:
        action = "保留但不追"
        reason = f"{name}走势强，但距20日线{ma20:+.2f}%且有过热信号，保留为一线标的，但不追高买单。"
        rank = 1
    elif pct > 0 and trend_bad:
        action = "剔除"
        reason = f"{name}表面红盘{_pct_label(pct)}，但趋势仍未修复，反弹质量不合格。"
        rank = 3
    elif pct <= 0 and trend_bad:
        action = "剔除"
        reason = f"{name}价格和趋势同时走弱，继续留在自选池只会占用注意力。"
        rank = 4
    elif 0 < vol < 0.85:
        action = "降级"
        reason = f"{name}量比仅{vol:.2f}，资金参与不足，不作为明日主攻标的。"
        rank = 3
    else:
        action = "保留"
        reason = f"{name}结构没有明显破坏，但进攻性不足，只保留为备选。"
        rank = 2
    return {"action": action, "reason": reason, "rank": rank}


def _build_market(trade_date: str, progress_cb=None) -> dict:
    def _p(msg: str):
        if progress_cb:
            progress_cb(msg)

    _p("整理市场复盘...")
    try:
        from db.market_review_db import get_daily as get_market_daily, save_daily as save_market_daily
        from services.market_review_service import build_market_review

        data = get_market_daily(trade_date)
        required = ("distribution", "rankings", "cap_perf", "sectors", "news", "ai_review")
        if not data or any(k not in data or data.get(k) in (None, [], {}, "") for k in required):
            data = build_market_review(trade_date, progress_cb=progress_cb, use_ai=True)
            save_market_daily(trade_date, data)
        return {
            "summary": data.get("summary", ""),
            "sentiment": data.get("sentiment", {}),
            "breadth": data.get("breadth", {}),
            "distribution": data.get("distribution", []),
            "limit_stats": data.get("limit_stats", {}),
            "indices": data.get("indices", []),
            "amount": data.get("amount", {}),
            "rankings": data.get("rankings", {}),
            "cap_perf": data.get("cap_perf", []),
            "sectors": data.get("sectors", {}),
            "news": data.get("news", []),
            "leaders": (data.get("rankings", {}) or {}).get("gainers", [])[:8],
            "laggards": (data.get("rankings", {}) or {}).get("losers", [])[:5],
            "ai_review": data.get("ai_review", ""),
        }
    except Exception as e:
        return {"summary": f"市场复盘暂不可用：{e}", "error": str(e)}


def _build_portfolio(progress_cb=None) -> dict:
    if progress_cb:
        progress_cb("整理持仓复盘...")
    try:
        from api.portfolio import _load_store, _fetch_quotes, _enrich_position, _empty_summary

        positions = (_load_store().get("positions") or [])
        if not positions:
            return {"summary": _empty_summary(), "positions": [], "alerts": [], "conclusion": "暂无持仓。"}

        symbols = [p["symbol"] for p in positions]
        quotes = _fetch_quotes(symbols)
        techs = _tech_map(symbols)
        enriched = []
        alerts = []
        total_cost = total_value = today_pnl = 0.0
        for p in positions:
            ep = _enrich_position(p, quotes.get(p["symbol"], {}))
            ep["tech"] = techs.get(p["symbol"], {})
            ep["logic"] = _stock_logic(ep)
            enriched.append(ep)
            total_cost += ep.get("cost_value", 0)
            total_value += ep.get("current_value", 0)
            today_pnl += ep.get("today_pnl", 0)
            if ep.get("at_stop_loss"):
                alerts.append({"level": "risk", "text": f"{ep.get('name')} 已触及止损价"})
            elif ep.get("near_stop_loss"):
                alerts.append({"level": "warn", "text": f"{ep.get('name')} 接近止损位"})
            elif ep.get("at_target"):
                alerts.append({"level": "good", "text": f"{ep.get('name')} 已到目标价"})

        total_pnl = total_value - total_cost
        summary = {
            "total_cost": round(total_cost, 2),
            "total_value": round(total_value, 2),
            "total_pnl_amount": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl / total_cost * 100 if total_cost > 0 else 0, 2),
            "today_pnl": round(today_pnl, 2),
            "position_count": len(enriched),
        }
        top = sorted(enriched, key=lambda x: x.get("today_pnl", 0), reverse=True)
        conclusion = (
            f"持仓 {len(enriched)} 只，今日盈亏 {today_pnl:+.2f} 元，"
            f"总浮盈亏 {total_pnl:+.2f} 元（{summary['total_pnl_pct']:+.2f}%）。"
        )
        return {
            "summary": summary,
            "positions": enriched,
            "top_winners": top[:3],
            "top_losers": list(reversed(top[-3:])),
            "alerts": alerts,
            "conclusion": conclusion,
            "analysis_points": [
                _stock_logic(s) for s in enriched[:8]
            ],
        }
    except Exception as e:
        return {"summary": {}, "positions": [], "alerts": [], "conclusion": f"持仓复盘暂不可用：{e}", "error": str(e)}


def _normalize_watchlist(watchlist: list[dict] | None) -> list[dict]:
    out = []
    for it in watchlist or []:
        code = str(it.get("code") or it.get("symbol") or "").strip()
        if len(code) == 6 and code.isdigit():
            out.append({"code": code, "name": it.get("name") or "", "date": it.get("date") or ""})
    return out


def _build_watchlist(watchlist: list[dict] | None, progress_cb=None) -> dict:
    if progress_cb:
        progress_cb("整理自选复盘...")
    items = _normalize_watchlist(watchlist)
    if not items:
        return {"summary": {"count": 0}, "stocks": [], "conclusion": "暂无自选股快照。"}
    try:
        from api.watchlist import _fetch_sina_hq
        symbols = [x["code"] for x in items]
        quotes = _fetch_sina_hq(symbols)
        techs = _tech_map(symbols)
        stocks = []
        for it in items:
            q = quotes.get(it["code"], {})
            row = {
                "symbol": it["code"],
                "name": q.get("name") or it.get("name") or it["code"],
                "date": it.get("date", ""),
                "price": q.get("price", 0),
                "pct_change": q.get("pct_change", 0),
                "turnover": q.get("turnover", 0),
                "tech": techs.get(it["code"], {}),
            }
            row["logic"] = _stock_logic(row)
            row["decision"] = _stock_decision(row)
            stocks.append(row)
        up = sum(1 for s in stocks if _safe_float(s.get("pct_change")) > 0)
        down = sum(1 for s in stocks if _safe_float(s.get("pct_change")) < 0)
        avg = round(sum(_safe_float(s.get("pct_change")) for s in stocks) / len(stocks), 2)
        top = sorted(stocks, key=lambda s: _safe_float(s.get("pct_change")), reverse=True)
        decisions = sorted(stocks, key=lambda s: (s.get("decision") or {}).get("rank", 9))
        keep = [s for s in decisions if (s.get("decision") or {}).get("action") in ("重点进攻", "保留但不追", "保留")]
        cut = [s for s in decisions if (s.get("decision") or {}).get("action") in ("剔除", "降级")]
        leader = decisions[0] if decisions else {}
        if leader:
            conclusion = (
                f"自选 {len(stocks)} 只，{up} 涨 {down} 跌，平均涨跌 {_pct_label(avg)}。"
                f"裁决：第一顺位 {leader.get('name')}（{(leader.get('decision') or {}).get('action')}），"
                f"保留 {len(keep)} 只，剔除/降级 {len(cut)} 只。"
            )
        else:
            conclusion = f"自选 {len(stocks)} 只，{up} 涨 {down} 跌，平均涨跌 {_pct_label(avg)}。"
        return {
            "summary": {"count": len(stocks), "up": up, "down": down, "avg_pct": avg},
            "stocks": stocks,
            "top_winners": top[:5],
            "top_losers": list(reversed(top[-5:])),
            "conclusion": conclusion,
            "analysis_points": [_stock_logic(s) for s in top[:8]],
            "decisions": decisions,
        }
    except Exception as e:
        return {"summary": {"count": len(items)}, "stocks": items, "conclusion": f"自选复盘暂不可用：{e}", "error": str(e)}


def _build_industry(progress_cb=None) -> dict:
    if progress_cb:
        progress_cb("整理行业板块复盘...")
    try:
        from api.industry import industry_summary
        data = industry_summary()
        industries = data.get("industries", [])
        top_up = industries[:8]
        top_down = sorted(industries, key=lambda x: _safe_float(x.get("pct_num")))[:8]
        hot = [x for x in top_up if _safe_float(x.get("pct_num")) > 0]
        cold = [x for x in top_down if _safe_float(x.get("pct_num")) < 0]
        conclusion = "；".join([
            f"领涨：{'、'.join(x.get('name', '') for x in hot[:3]) or '暂无'}",
            f"领跌：{'、'.join(x.get('name', '') for x in cold[:3]) or '暂无'}",
        ])
        return {
            "updated_at": data.get("updated_at", ""),
            "top_up": top_up,
            "top_down": top_down,
            "conclusion": conclusion,
        }
    except Exception as e:
        return {"top_up": [], "top_down": [], "conclusion": f"行业板块复盘暂不可用：{e}", "error": str(e)}


def _build_international(progress_cb=None) -> dict:
    if progress_cb:
        progress_cb("整理国际形势复盘...")
    try:
        from api.news_trending import _get_items
        from services.news_ranking_service import compute_trending
        items, ts = _get_items("intl", refresh=False)
        trends = compute_trending(items, "intl", top_n=8)
        relevant = [x for x in trends if _safe_float(x.get("impact_score")) > 0]
        conclusion = "国际侧重点：" + ("、".join(x.get("title", "") for x in relevant[:3]) or "暂无显著 A 股映射热点")
        return {
            "updated_at": ts,
            "items": trends,
            "conclusion": conclusion,
        }
    except Exception as e:
        return {"items": [], "conclusion": f"国际形势复盘暂不可用：{e}", "error": str(e)}


def _build_extra(market: dict, portfolio: dict, watchlist: dict, industry: dict, international: dict) -> dict:
    risks = []
    opportunities = []

    sentiment = market.get("sentiment", {}) or {}
    limit_stats = market.get("limit_stats", {}) or {}
    score = int(sentiment.get("score", 0) or 0)
    if score >= 72:
        risks.append("市场情绪偏热，追高和炸板风险前置收紧。")
    elif score <= 35:
        risks.append("市场情绪偏冷，仓位和试错频率要收紧。")
    if _safe_float(limit_stats.get("broken_ratio")) >= 30:
        risks.append(f"炸板率 {limit_stats.get('broken_ratio')}%，短线接力分歧偏大。")
    for a in (portfolio.get("alerts") or [])[:3]:
        risks.append(a.get("text", ""))

    top_ind = (industry.get("top_up") or [])[:3]
    if top_ind:
        opportunities.append("强势行业：" + "、".join(x.get("name", "") for x in top_ind))
    leaders = (market.get("leaders") or [])[:3]
    if leaders:
        opportunities.append("市场强势股：" + "、".join(x.get("name", "") for x in leaders))
    wtop = (watchlist.get("top_winners") or [])[:3]
    if wtop:
        opportunities.append("自选强势股：" + "、".join(x.get("name", "") for x in wtop))

    tomorrow = []
    if top_ind:
        tomorrow.append("开盘后只做延续性最强的领涨行业；龙头断板或板块掉出涨幅前列，直接放弃追击。")
    if limit_stats.get("max_continuity"):
        tomorrow.append(f"最高 {limit_stats.get('max_continuity')} 连板梯队不晋级就降低短线接力权重，晋级才保留进攻仓位。")
    if international.get("items"):
        tomorrow.append("国际热点只看开盘直接映射的行业；没有高开承接和成交放大，就不纳入交易计划。")

    return {
        "risk_opportunity": {
            "risks": [x for x in risks if x][:6],
            "opportunities": [x for x in opportunities if x][:6],
        },
        "tomorrow_watch": tomorrow[:6],
    }


def _watchlist_review_text(watchlist: dict) -> str:
    decisions = watchlist.get("decisions") or sorted(
        watchlist.get("stocks") or [],
        key=lambda s: (s.get("decision") or _stock_decision(s)).get("rank", 9)
    )
    if not decisions:
        return "\n".join([
            "### 自选池裁决",
            "自选池为空，明日不从自选方向主动开新仓。",
            "### 明日动作",
            "先补齐观察标的，再按量价和主线强度筛选；没有数据的股票不进入主计划。"
        ])
    attack, backup, cut, lines = [], [], [], []
    for s in decisions:
        d = s.get("decision") or _stock_decision(s)
        name = s.get("name") or s.get("symbol")
        action = d.get("action", "保留")
        reason = d.get("reason", "")
        if action in ("重点进攻", "保留但不追"):
            attack.append(name)
        elif action == "保留":
            backup.append(name)
        else:
            cut.append(f"{name}（{action}）")
        lines.append(f"- **{name}：{action}。** {reason}")
    first = decisions[0]
    first_name = first.get("name") or first.get("symbol")
    first_action = (first.get("decision") or _stock_decision(first)).get("action", "保留")
    verdict = (
        f"第一顺位是 {first_name}（{first_action}），明日主计划只围绕 {'、'.join(attack)} 做盘中验证。"
        if attack else
        "自选池没有达到进攻标准的票，明日不从自选里主动开新仓。"
    )
    return "\n".join([
        "### 自选池裁决",
        f"{verdict} 保留备选 {len(backup)} 只，剔除或降级 {len(cut)} 只。",
        "### 逐只动作",
        "\n".join(lines),
        "### 明日执行",
        "主攻名单：" + ("、".join(attack) if attack else "空") + "。",
        "备选名单：" + ("、".join(backup) if backup else "空") + "。",
        "清理名单：" + ("、".join(cut) if cut else "空") + "。"
    ])


def _fallback_analysis(market: dict, portfolio: dict, watchlist: dict, industry: dict, international: dict) -> dict:
    m_sent = market.get("sentiment", {}) or {}
    breadth = market.get("breadth", {}) or {}
    limit_stats = market.get("limit_stats", {}) or {}
    sectors = market.get("sectors", {}) or {}
    indices = market.get("indices") or []
    rankings = market.get("rankings") or {}
    news = market.get("news") or []
    amount = market.get("amount", {}) or {}
    ind_up = industry.get("top_up") or []
    ind_down = industry.get("top_down") or []
    intl_items = international.get("items") or []
    up = _safe_float(breadth.get("up"))
    down = _safe_float(breadth.get("down"))
    up_ratio = up / (up + down) * 100 if (up + down) else 0
    zt = _safe_float(limit_stats.get("zt_count"))
    dt = _safe_float(limit_stats.get("dt_count"))
    broken = _safe_float(limit_stats.get("broken_count"))
    broken_ratio = _safe_float(limit_stats.get("broken_ratio"))
    idx_line = "；".join(
        f"{x.get('name')} {_pct_label(_safe_float(x.get('pct')))}"
        for x in indices[:4]
        if x.get("name")
    )
    up_sectors = "、".join(x.get("name", "") for x in (sectors.get("top_up") or [])[:5]) or "暂无明显领涨"
    down_sectors = "、".join(x.get("name", "") for x in (sectors.get("top_down") or [])[:5]) or "暂无明显领跌"
    gainers = "、".join(x.get("name", "") for x in (rankings.get("gainers") or [])[:5]) or "暂无"
    losers = "、".join(x.get("name", "") for x in (rankings.get("losers") or [])[:5]) or "暂无"
    news_focus = "；".join(x.get("title", "") for x in news[:3] if x.get("title")) or "暂无足够新闻样本"
    p_points = portfolio.get("analysis_points") or []
    w_points = watchlist.get("analysis_points") or []
    p_summary = portfolio.get("summary") or {}
    w_summary = watchlist.get("summary") or {}
    intl_titles = [x.get("title", "") for x in intl_items[:6] if x.get("title")]
    intl_map = []
    for title in intl_titles:
        low = title.lower()
        if any(k in low for k in ["oil", "energy", "iran", "north sea"]):
            intl_map.append("能源/油气链、煤化工和高耗能行业成本端")
        elif any(k in low for k in ["ai", "chip", "semiconductor", "power demand"]):
            intl_map.append("AI算力、半导体、电力设备和数据中心")
        elif any(k in low for k in ["yen", "fed", "dollar", "currency"]):
            intl_map.append("汇率敏感资产、出口链和外资风险偏好")
        elif any(k in low for k in ["renewables", "solar", "wind"]):
            intl_map.append("新能源、电力设备和储能")
        elif any(k in low for k in ["china", "xi"]):
            intl_map.append("政策预期、央国企和大盘风险偏好")
    intl_map_line = "、".join(dict.fromkeys(intl_map)) or "无清晰映射，国际线不纳入主交易计划"
    return {
        "market_review": "\n".join([
            "### 市场定性与赚钱效应",
            f"今天市场情绪为 {m_sent.get('label', '未知')}（{m_sent.get('score', 0)}℃），{m_sent.get('desc', '')}。全市场上涨 {int(up)} 家、下跌 {int(down)} 家，上涨占比约 {up_ratio:.1f}%，说明盘面不是单纯指数行情，而是多数个股参与的扩散型修复。两市成交约 {round(_safe_float(amount.get('total_yi')))} 亿；成交放大叠加炸板偏高时，策略直接从追板切到低吸核心和首分歧承接。",
            "### 涨跌逻辑",
            f"涨停 {int(zt)} 只、跌停 {int(dt)} 只、炸板 {int(broken)} 只，炸板率 {broken_ratio:.1f}%。涨停数量处在活跃区间，短线资金仍在寻找弹性；炸板率偏高时直接降低追板权重。指数表现为：{idx_line or '暂无指数数据'}，把资金优先分配给强于指数的题材和中小盘方向。",
            "### 主线结构",
            f"板块上，领涨方向集中在 {up_sectors}，领跌方向集中在 {down_sectors}。个股强势榜包括 {gainers}，弱势榜包括 {losers}。领涨板块内部有多只涨停且成交额榜同步出现同方向个股时，直接升级为主线；只有少数个股孤立上涨时，定性为情绪套利，不纳入主计划。",
            "### 风险与明日动作",
            f"最高连板 {limit_stats.get('max_continuity', 0)} 板，是短线高度锚点。明天执行三条：涨停数量低于百只就降低接力权重；炸板率不回落就放弃追板；领涨行业掉出涨幅榜和成交榜就切掉对应题材。新闻侧重点：{news_focus}。只做和盘面主线共振的消息，单纯消息刺激一律不追。",
        ]),
        "portfolio_review": "\n".join([
            "### 持仓表现与账户状态",
            f"{portfolio.get('conclusion', '暂无持仓。')} 持仓数量 {p_summary.get('position_count', 0)} 只，今日盈亏 {_safe_float(p_summary.get('today_pnl')):+.2f} 元，总浮盈亏 {_safe_float(p_summary.get('total_pnl_amount')):+.2f} 元。这里不能只看结果，关键是判断盈亏来自趋势延续、情绪波动，还是个股自身量价走弱。",
            "### 逐只涨跌与量价逻辑",
            _md_list(p_points) or "- 暂无持仓明细可分析。",
            "### 操作动作",
            "放量上涨并站稳20日线的持仓保留进攻权重；放量下跌的持仓直接降级，先处理风险。缩量上涨不加仓，缩量下跌不恐慌卖，但跌破关键均线就执行减仓。持仓复盘的核心不是今天赚亏多少钱，而是交易假设是否还成立。",
            "### 明日检查项",
            "明天开盘按板块相对强弱执行：强于板块则保留，弱于板块则降级。盘中量比异常放大且跌破前一日低点，直接减仓。账户浮盈集中在单一持仓时，不再继续加码同一方向。"
        ]),
        "watchlist_review": _watchlist_review_text(watchlist),
        "industry_review": "\n".join([
            "### 行业主线",
            "领涨方向：" + ("、".join(f"{x.get('name', '')}({_pct_label(_safe_float(x.get('pct_num')))})" for x in ind_up[:6]) or "暂无") + "。行业复盘不能只看谁涨得多，还要看领涨行业是否和市场情绪、涨停分布、新闻催化形成共振。涨幅靠前但内部涨停少、龙头不明确的行业降级为轮动，不追涨；有梯队、有龙头、有成交的方向才升级为主线。",
            "### 弱势方向",
            "领跌方向：" + ("、".join(f"{x.get('name', '')}({_pct_label(_safe_float(x.get('pct_num')))})" for x in ind_down[:6]) or "暂无") + "。连续出现在跌幅榜的行业直接回避；前期强势方向单日回调时，只保留龙头承接强、成交不塌的标的，其余全部降级。",
            "### 轮动与持续性",
            "明天只承认继续留在涨幅榜前列、且完成龙头到跟风扩散的行业。只有单一行业强且涨跌家数收窄时，直接降低追高权重；多个相关行业联动走强时，才把它升级为主线。",
            "### 交易映射",
            "行业板块复盘最终落到持仓和自选：持仓属于领涨行业且强于行业就保留，属于领跌行业就降级处理。自选股处在强行业但量能不跟，仍然不进主计划。"
        ]),
        "international_review": "\n".join([
            "### 国际形势",
            f"{international.get('conclusion', '暂无国际热点。')} 国际新闻不能直接等同于 A 股买卖信号，只作为风险偏好、商品价格、汇率和产业链预期的过滤器。今天纳入扫描的海外线索包括：{_md_list(intl_titles[:5])}",
            "### A股映射",
            f"潜在映射方向包括：{intl_map_line}。海外 AI、电力需求、芯片或能源事件升温时，只把算力、电力设备、半导体、油气、化工中开盘承接最强的方向纳入计划；汇率和美联储预期扰动加强时，外资权重、出口链和高估值成长股统一收紧风险权重。",
            "### 风险偏好",
            "国际形势对盘面的影响通常分为两层：第一层是开盘情绪，例如隔夜美股、美元、原油和地缘消息；第二层是产业映射，例如 AI 需求、能源供给、贸易政策是否改变某些行业的盈利预期。只看标题容易误判，必须看 A 股盘中有没有真实成交和涨停反馈。",
            "### 明日动作",
            "海外线索只在 A 股相关行业开盘放量承接时纳入交易计划。相关板块只高开不放量，直接判定为消息兑现；低开后放量翻红并带动持仓/自选同方向走强，才升级为可执行线索。"
        ]),
    }


def _build_ai_block_analysis(market: dict, portfolio: dict, watchlist: dict, industry: dict, international: dict, progress_cb=None) -> dict:
    if progress_cb:
        progress_cb("AI 生成五大复盘分析...")
    fallback = _fallback_analysis(market, portfolio, watchlist, industry, international)
    try:
        from services.ai_client import make_client, CHAT_MODEL

        payload = {
            "market": {
                "summary": market.get("summary"),
                "sentiment": market.get("sentiment"),
                "breadth": market.get("breadth"),
                "limit_stats": market.get("limit_stats"),
                "indices": market.get("indices"),
                "sectors": market.get("sectors"),
                "rankings": market.get("rankings"),
                "news": market.get("news"),
            },
            "portfolio": {
                "summary": portfolio.get("summary"),
                "positions": portfolio.get("positions"),
                "analysis_points": portfolio.get("analysis_points"),
                "alerts": portfolio.get("alerts"),
            },
            "watchlist": {
                "summary": watchlist.get("summary"),
                "stocks": watchlist.get("stocks"),
                "analysis_points": watchlist.get("analysis_points"),
                "decisions": watchlist.get("decisions"),
            },
            "industry": industry,
            "international": international,
        }
        prompt = f"""
你是一个激进但理性的 A 股交易复盘助手。用户要看的不是数据罗列，而是每天可执行的复盘分析。

请基于下面 JSON，分别输出五个模块的 markdown 分析。必须严格返回 JSON 对象，键名固定：
market_review, portfolio_review, watchlist_review, industry_review, international_review。

每个值都是 markdown 字符串，要求：
- 每个模块 350-700 字，分 3-5 个 `###` 小标题。
- 必须分析「涨跌逻辑」「量价逻辑」「结构/主线」「风险」「明日动作」中与该模块相关的内容。
- 持仓和自选必须逐只解释，不要只说总盈亏；要结合 pct_change、vol_ratio、MA5/MA20/MA60、MACD、换手、标签。
- 所有判断点必须给唯一动作结论，例如「进攻 / 保留但不追 / 降级 / 剔除 / 收紧仓位」。禁止把正反理由都列出来让用户自己选。
- 自选复盘必须先给“自选池裁决”：谁是第一顺位，谁剔除，谁降级；结论必须是动作，不得写成含糊建议。
- 市场复盘要结合情绪温度、涨跌家数、涨停/跌停/炸板、指数、行业主线、个股榜单和新闻。
- 行业板块要分析为什么这些行业强/弱、是否轮动、持续性怎么看。
- 国际形势要写清楚国际事件映射到 A 股哪些方向，以及哪些方向纳入计划、哪些方向直接排除，不能只贴新闻标题。
- 不要喊单，不要承诺收益；但必须激进且理性，给明确执行动作。

数据：
{_compact_json(payload, 22000)}
"""
        resp = make_client().chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.35,
            max_tokens=5000,
            timeout=180,
        )
        parsed = _parse_json_obj(resp.choices[0].message.content or "")
        if not parsed:
            return fallback
        merged = dict(fallback)
        for k, v in parsed.items():
            text = str(v)
            if len(text) >= 260:
                merged[k] = text
        merged["watchlist_review"] = _watchlist_review_text(watchlist)
        return merged
    except Exception as e:
        fallback["error"] = str(e)
        return fallback


def build_today_review(trade_date: str, watchlist: list[dict] | None = None, progress_cb=None) -> dict:
    market = _build_market(trade_date, progress_cb)
    portfolio = _build_portfolio(progress_cb)
    watch = _build_watchlist(watchlist, progress_cb)
    industry = _build_industry(progress_cb)
    international = _build_international(progress_cb)
    extra = _build_extra(market, portfolio, watch, industry, international)
    analysis = _build_ai_block_analysis(market, portfolio, watch, industry, international, progress_cb)

    return {
        "trade_date": trade_date,
        "generated_at": datetime.now().isoformat(),
        "market": market,
        "portfolio": portfolio,
        "watchlist": watch,
        "industry": industry,
        "international": international,
        "analysis": analysis,
        **extra,
    }
