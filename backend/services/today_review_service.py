"""
今日复盘总览：市场、持仓、自选、行业、国际形势、风险机会、明日关注。

原则：优先复用现有数据源和缓存，生成结果落库，供日历回看。
"""
from __future__ import annotations

import json
import re
import threading
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
    # 不能直接截断 JSON，否则后半段的持仓/自选会消失且整体不再是合法结构。
    # 调用方应先裁剪字段；这里宁可保留完整证据，也不向模型发送残缺对象。
    return text


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
    fund = stock.get("fund_flow") or {}
    if fund.get("available"):
        main_net = _safe_float(fund.get("main_net_yi"))
        main_pct = fund.get("main_net_pct")
        parts.append(
            f"个股主力净额推算 {main_net:+.2f} 亿"
            + (f"、占比 {_safe_float(main_pct):+.2f}%" if main_pct is not None else "")
        )
    else:
        parts.append("个股主力净额暂不可用，不据此推断资金方向")
    sector = stock.get("sector") or {}
    if sector:
        sector_name = stock.get("industry") or sector.get("name") or "所属行业"
        sector_net = sector.get("net_in_yi")
        sector_flow = sector.get("fund_change") or {}
        sector_text = f"{sector_name}涨跌 {_safe_float(sector.get('pct_num')):+.2f}%"
        if sector.get("breadth_pct") is not None:
            sector_text += f"、上涨广度 {_safe_float(sector.get('breadth_pct')):.1f}%"
        if sector_net is not None:
            sector_text += f"、净流入推算 {_safe_float(sector_net):+.2f} 亿"
        if sector_flow.get("net_in_change_yi") is not None:
            sector_text += f"、盘中净流入变化 {_safe_float(sector_flow.get('net_in_change_yi')):+.2f} 亿"
        if sector.get("leader") and sector.get("leader") != "--":
            sector_text += f"、领涨股 {sector.get('leader')}"
        parts.append(sector_text)
    return "；".join(parts) + "。"


def _stock_decision(stock: dict, purpose: str = "watchlist") -> dict:
    from services.verdict_service import compute_quick_decision

    decision = compute_quick_decision(
        stock,
        stock.get("tech") or {},
        stock.get("decision_context") or {},
        purpose=purpose,
    )
    decision["reason"] = decision["summary"]
    return decision


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


def _build_portfolio(trade_date: str, evidence: dict, progress_cb=None) -> dict:
    if progress_cb:
        progress_cb("整理持仓复盘...")
    try:
        from api.portfolio import (
            _build_daily_trade_flows,
            _empty_summary,
            _enrich_position,
            _fetch_quotes,
            _load_store,
        )

        store = _load_store()
        positions = store.get("positions") or []
        if not positions:
            return {"summary": _empty_summary(), "positions": [], "alerts": [], "conclusion": "暂无持仓。"}

        symbols = [p["symbol"] for p in positions]
        quotes = _fetch_quotes(symbols)
        techs = _tech_map(symbols)
        trade_flows = _build_daily_trade_flows(store.get("trades", []), trade_date)
        stock_evidence = evidence.get("by_symbol") or {}
        enriched = []
        alerts = []
        total_cost = total_value = today_pnl = 0.0
        for p in positions:
            ep = _enrich_position(p, quotes.get(p["symbol"], {}), trade_flows.get(p["symbol"]))
            ep["tech"] = techs.get(p["symbol"], {})
            attached = stock_evidence.get(p["symbol"]) or {}
            ep["industry"] = attached.get("industry", "")
            ep["sector"] = attached.get("sector") or {}
            ep["fund_flow"] = attached.get("fund_flow") or {}
            ep["decision_context"] = {
                "sector": ep["industry"],
                "sector_decision": (ep["sector"].get("decision") or {}),
                "main_net_yi": ep["fund_flow"].get("main_net_yi"),
                "main_net_pct": ep["fund_flow"].get("main_net_pct"),
                "stop_loss": p.get("stop_loss"),
                "target_price": p.get("target_price"),
            }
            ep["decision"] = _stock_decision(ep, purpose="position")
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


def _build_watchlist(
    watchlist: list[dict] | None,
    trade_date: str,
    evidence: dict,
    progress_cb=None,
) -> dict:
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
        stock_evidence = evidence.get("by_symbol") or {}
        market_pct = None
        try:
            from api.daily_report import _fetch_indices
            pcts = [x.get("pct") for x in _fetch_indices() if x.get("pct") is not None]
            market_pct = sum(pcts) / len(pcts) if pcts else None
        except Exception:
            pass
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
            attached = stock_evidence.get(it["code"]) or {}
            industry = attached.get("industry", "")
            row["industry"] = industry
            row["sector"] = attached.get("sector") or {}
            row["fund_flow"] = attached.get("fund_flow") or {}
            row["decision_context"] = {
                "market_pct": market_pct,
                "sector": industry,
                "sector_decision": (row["sector"].get("decision") or {}),
                "main_net_yi": row["fund_flow"].get("main_net_yi"),
                "main_net_pct": row["fund_flow"].get("main_net_pct"),
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
            "analysis_points": [
                f"{s.get('name')}：{(s.get('decision') or {}).get('action')}。{(s.get('decision') or {}).get('summary')}"
                for s in decisions[:8]
            ],
            "decisions": decisions,
        }
    except Exception as e:
        return {"summary": {"count": len(items)}, "stocks": items, "conclusion": f"自选复盘暂不可用：{e}", "error": str(e)}


def _build_industry(evidence: dict, progress_cb=None) -> dict:
    if progress_cb:
        progress_cb("整理行业板块复盘...")
    try:
        industries = evidence.get("sectors") or []
        top_up = sorted(industries, key=lambda x: (x.get("decision") or {}).get("score", 50), reverse=True)[:8]
        top_down = sorted(industries, key=lambda x: (x.get("decision") or {}).get("score", 50))[:8]
        hot = [x for x in top_up if (x.get("decision") or {}).get("action") in ("主线候选", "轮动观察")]
        cold = [x for x in top_down if (x.get("decision") or {}).get("action") == "弱势回避"]
        conclusion = "；".join([
            f"多维主线：{'、'.join(x.get('name', '') for x in hot[:3]) or '暂无达标板块'}",
            f"明确回避：{'、'.join(x.get('name', '') for x in cold[:3]) or '暂无'}",
        ])
        return {
            "updated_at": evidence.get("updated_at", ""),
            "fund_basis": evidence.get("basis", ""),
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
        result: dict[str, Any] = {}

        def _work():
            try:
                from api.news_trending import _get_items
                from services.news_ranking_service import compute_trending
                items, ts = _get_items("intl", refresh=False)
                result["items"] = compute_trending(items, "intl", top_n=8)
                result["ts"] = ts
            except Exception as e:
                result["error"] = str(e)

        worker = threading.Thread(target=_work, daemon=True)
        worker.start()
        worker.join(timeout=25)
        if worker.is_alive():
            return {
                "items": [],
                "conclusion": "国际新闻源响应超时，本日档案不采用未验证的国际信号。",
                "error": "国际新闻源超过25秒",
            }
        if result.get("error"):
            raise RuntimeError(result["error"])
        trends = result.get("items") or []
        relevant = [x for x in trends if _safe_float(x.get("impact_score")) > 0]
        conclusion = "国际侧重点：" + ("、".join(x.get("title", "") for x in relevant[:3]) or "暂无显著 A 股映射热点")
        return {
            "updated_at": result.get("ts", ""),
            "items": trends,
            "conclusion": conclusion,
        }
    except Exception as e:
        return {"items": [], "conclusion": f"国际形势复盘暂不可用：{e}", "error": str(e)}


def _build_extra(market: dict, portfolio: dict, watchlist: dict, industry: dict, international: dict) -> dict:
    def refs(rows: list[dict]) -> list[dict]:
        return [
            {"symbol": str(row.get("symbol") or ""), "name": str(row.get("name") or "")}
            for row in rows if row.get("name") or row.get("symbol")
        ]

    personal = (portfolio.get("positions") or []) + (watchlist.get("stocks") or [])

    def sector_refs(sector: dict, fallback_rows: list[dict]) -> list[dict]:
        name = sector.get("name")
        matched = [row for row in personal if row.get("industry") == name]
        leader = str(sector.get("leader") or "")
        if leader and leader != "--" and all(row.get("name") != leader for row in matched):
            matched.append({"symbol": "", "name": leader})
        return refs(matched[:4] or fallback_rows[:3])

    risks = []
    for sector in (industry.get("top_down") or [])[:3]:
        risks.append({
            "title": f"{sector.get('name')}资金与价格承压",
            "industry": sector.get("name", ""),
            "stocks": sector_refs(sector, market.get("laggards") or []),
            "evidence": (
                f"行业涨跌 {_safe_float(sector.get('pct_num')):+.2f}%，"
                f"净流入推算 {_safe_float(sector.get('net_in_yi')):+.2f} 亿，"
                f"上涨广度 {_safe_float(sector.get('breadth_pct')):.1f}%。"
            ),
            "action": "回避弱势行业，相关持仓和自选统一降级。",
        })

    opportunities = []
    for sector in (industry.get("top_up") or [])[:3]:
        opportunities.append({
            "title": f"{sector.get('name')}通过多维主线初筛",
            "industry": sector.get("name", ""),
            "stocks": sector_refs(sector, market.get("leaders") or []),
            "evidence": (
                f"行业涨跌 {_safe_float(sector.get('pct_num')):+.2f}%，"
                f"净流入推算 {_safe_float(sector.get('net_in_yi')):+.2f} 亿，"
                f"上涨广度 {_safe_float(sector.get('breadth_pct')):.1f}%，"
                f"领涨股 {sector.get('leader') or '--'}。"
            ),
            "action": "只跟踪龙头承接和板块扩散，不追后排。",
        })

    tomorrow = []
    for sector in (industry.get("top_up") or [])[:4]:
        tomorrow.append({
            "theme": f"验证{sector.get('name')}是否延续",
            "industry": sector.get("name", ""),
            "stocks": sector_refs(sector, market.get("leaders") or []),
            "evidence": (
                f"收盘净流入推算 {_safe_float(sector.get('net_in_yi')):+.2f} 亿，"
                f"上涨广度 {_safe_float(sector.get('breadth_pct')):.1f}%。"
            ),
            "trigger": "行业继续位于强度前列，资金、广度和龙头承接至少三项同向。",
            "invalidation": "行业净流入转负、广度跌破55%或龙头失去承接，任一发生即取消。",
            "action": "满足触发条件才进入盘中验证，否则放弃。",
        })

    return {
        "risk_opportunity": {
            "risks": risks[:6],
            "opportunities": opportunities[:6],
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


def _intelligence_market_review(intelligence: dict) -> str:
    final = intelligence.get("final_conclusion") or {}
    verdict = intelligence.get("verdict") or {}
    core = intelligence.get("core_judgements") or []
    mainline = intelligence.get("mainline_analysis") or {}
    plan = intelligence.get("tomorrow_plan") or {}
    learning = intelligence.get("learning") or {}
    yesterday_audit = learning.get("latest_audit") or {}

    core_rows = []
    for item in core:
        core_rows.append(
            f"**{item.get('title')}：{item.get('conclusion')}**\n\n"
            f"逻辑：{item.get('logic')}\n\n"
            f"动作：{item.get('action')}"
        )

    line_rows = []
    for row in (mainline.get("rows") or [])[:6]:
        line_rows.append(
            f"- **{row.get('name')}｜{row.get('stage') or row.get('level')}**："
            f"{row.get('logic') or row.get('evidence')} "
            f"结论：{row.get('judgement') or row.get('action')}；"
            f"失效条件：{row.get('invalidation') or '等待次日验证'}"
        )

    if yesterday_audit:
        yesterday_text = (
            f"**昨日判断：{yesterday_audit.get('judgement', '待复核')}。** "
            f"昨天为{yesterday_audit.get('prior_stance')}、仓位上限{yesterday_audit.get('prior_position_cap')}%；"
            f"今天实际为{yesterday_audit.get('actual_regime')}（{yesterday_audit.get('actual_stance')}）。\n\n"
            f"系统处理：{yesterday_audit.get('learning_action')}"
        )
    else:
        yesterday_text = "尚无可对齐的相邻交易日样本。"
    position_plan = final.get("position_plan") or f"总仓位上限{verdict.get('position_cap', 20)}%"

    return "\n".join([
        "### 一、今日最终结论",
        f"**今日定性：{final.get('headline') or verdict.get('regime') or '待确认'}。**",
        f"市场判断：{final.get('market_judgement') or verdict.get('summary') or '等待数据确认'}",
        f"赚钱效应：{final.get('money_effect') or '等待数据确认'}",
        f"明日仓位：{position_plan}",
        "### 二、四个核心判断",
        "\n\n".join(core_rows) or "新版核心判断正在生成。",
        "### 三、主线与轮动",
        mainline.get("rotation_summary") or "没有方向通过资金、广度、龙头和持续性共同验证。",
        "\n".join(line_rows) or "主线为空，不用涨幅榜强行选方向。",
        "### 四、明日唯一执行方案",
        f"**{plan.get('base_case') or '默认防守，总仓位上限20%。'}**",
        f"依据：{plan.get('rationale') or '等待完整证据'}",
        f"允许：{plan.get('allowed') or '只做确认方向'}",
        f"禁止：{plan.get('forbidden') or '不追后排'}",
        f"升级：{plan.get('upgrade_condition') or '暂无'}",
        f"降级：{plan.get('downgrade_condition') or '暂无'}",
        "### 五、昨日判断审计",
        yesterday_text,
    ])




def _fallback_analysis(
    market: dict,
    portfolio: dict,
    watchlist: dict,
    industry: dict,
    international: dict,
    intelligence: dict,
) -> dict:
    ind_up = industry.get("top_up") or []
    ind_down = industry.get("top_down") or []
    intl_items = international.get("items") or []
    p_points = portfolio.get("analysis_points") or []
    p_summary = portfolio.get("summary") or {}
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
        "market_review": _intelligence_market_review(intelligence),
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


def _stock_ai_payload(stock: dict) -> dict:
    """保留模型真正需要的证据，避免完整技术对象挤掉资金和板块上下文。"""
    tech = stock.get("tech") or {}
    return {
        "symbol": stock.get("symbol"),
        "name": stock.get("name"),
        "industry": stock.get("industry"),
        "price": stock.get("current_price", stock.get("price")),
        "pct_change": stock.get("pct_change"),
        "today_pnl": stock.get("today_pnl"),
        "pnl_pct": stock.get("pnl_pct"),
        "turnover": stock.get("turnover"),
        "technical": tech.get("technical") or {},
        "trend": tech.get("trend") or {},
        "today": tech.get("today") or {},
        "fund_flow": stock.get("fund_flow") or {},
        "sector": stock.get("sector") or {},
        "decision": stock.get("decision") or {},
        "logic_evidence": stock.get("logic"),
    }


def _market_stock_ai_payload(stock: dict) -> dict:
    return {
        "symbol": stock.get("symbol") or stock.get("code"),
        "name": stock.get("name"),
        "industry": stock.get("industry"),
        "pct_change": stock.get("pct_change", stock.get("pct")),
        "amount_yi": stock.get("amount_yi"),
        "turnover": stock.get("turnover"),
    }


def _market_ai_payload(market: dict) -> dict:
    limits = market.get("limit_stats") or {}
    rankings = market.get("rankings") or {}
    sectors = market.get("sectors") or {}
    return {
        "summary": market.get("summary"),
        "sentiment": market.get("sentiment"),
        "breadth": market.get("breadth"),
        "indices": market.get("indices"),
        "amount": market.get("amount"),
        "limit_stats": {
            key: limits.get(key) for key in (
                "zt_count", "dt_count", "broken_count", "broken_ratio",
                "max_continuity", "ladder", "zt_by_industry", "dt_stocks",
            )
        },
        "sectors": {
            "top_up": (sectors.get("top_up") or [])[:10],
            "top_down": (sectors.get("top_down") or [])[:10],
        },
        "rankings": {
            key: [_market_stock_ai_payload(row) for row in (rankings.get(key) or [])[:12]]
            for key in ("gainers", "losers", "amount", "turnover")
        },
        "news": [
            {key: row.get(key) for key in ("title", "summary", "source", "published")}
            for row in (market.get("news") or [])[:10]
        ],
    }


def _intelligence_ai_payload(intelligence: dict) -> dict:
    learning = intelligence.get("learning") or {}
    mainline = intelligence.get("mainline_analysis") or {}
    return {
        "verdict": intelligence.get("verdict"),
        "final_conclusion": intelligence.get("final_conclusion"),
        "core_judgements": (intelligence.get("core_judgements") or [])[:4],
        "historical_context": intelligence.get("historical_context"),
        "intraday_path": intelligence.get("intraday_path"),
        "undercurrents": (intelligence.get("undercurrents") or [])[:8],
        "mainline_analysis": {
            "rotation_summary": mainline.get("rotation_summary"),
            "rows": (mainline.get("rows") or [])[:8],
            "themes": (mainline.get("themes") or [])[:6],
        },
        "learning": {
            key: learning.get(key) for key in (
                "state", "label", "valid_outcomes", "minimum_samples",
                "effective_version", "latest_audit", "next_action",
            )
        },
        "tomorrow_plan": intelligence.get("tomorrow_plan"),
        "data_notes": intelligence.get("data_notes"),
    }


def _industry_ai_payload(industry: dict) -> dict:
    keys = (
        "name", "pct", "pct_num", "up_count", "down_count", "breadth_pct",
        "net_in", "net_in_yi", "fund_change", "leader", "decision",
    )
    return {
        "conclusion": industry.get("conclusion"),
        "fund_basis": industry.get("fund_basis"),
        "top_up": [{key: row.get(key) for key in keys} for row in (industry.get("top_up") or [])[:10]],
        "top_down": [{key: row.get(key) for key in keys} for row in (industry.get("top_down") or [])[:10]],
    }


def _contains_all_stocks(text: str, stocks: list[dict]) -> bool:
    return all(
        (str(row.get("name") or "") and str(row.get("name")) in text)
        or (str(row.get("symbol") or "") and str(row.get("symbol")) in text)
        for row in stocks
    )


def _allowed_stock_refs(market: dict, portfolio: dict, watchlist: dict, industry: dict) -> tuple[set[str], set[str]]:
    rows = list(portfolio.get("positions") or []) + list(watchlist.get("stocks") or [])
    rankings = market.get("rankings") or {}
    for key in ("gainers", "losers", "amount", "turnover"):
        rows.extend(rankings.get(key) or [])
    rows.extend((market.get("limit_stats") or {}).get("dt_stocks") or [])
    names = {str(row.get("name")) for row in rows if row.get("name")}
    symbols = {str(row.get("symbol") or row.get("code")) for row in rows if row.get("symbol") or row.get("code")}
    for row in (industry.get("top_up") or []) + (industry.get("top_down") or []):
        if row.get("leader") and row.get("leader") != "--":
            names.add(str(row.get("leader")))
    return symbols, names


def _valid_structured_stock_items(items: list, symbols: set[str], names: set[str]) -> bool:
    for item in items:
        if not isinstance(item, dict):
            return False
        refs = item.get("stocks")
        if not isinstance(refs, list) or not refs:
            return False
        for ref in refs:
            if not isinstance(ref, dict):
                return False
            symbol = str(ref.get("symbol") or "")
            name = str(ref.get("name") or "")
            if symbol not in symbols and name not in names:
                return False
    return True


def _repair_stock_review(client, model: str, label: str, stocks: list[dict]) -> str:
    names = "、".join(str(row.get("name") or row.get("symbol")) for row in stocks)
    prompt = f"""
你是激进但理性的 A 股复盘助手。上一轮「{label}」漏掉了股票，现在必须单独重写。

必须分析且一个都不能少：{names}。
只分析输入名单，禁止加入名单外股票。输出 markdown 正文，不要 JSON。
先给唯一的整体裁决，再逐只股票写一个 `### 股票名（代码）` 小标题。
每只必须交叉使用：自身趋势量价、个股资金、所属行业涨跌与广度、行业资金及盘中变化、相对行业/市场强弱。
若 fund_flow.available=false，明确写“个股资金数据缺失”，禁止伪造流入流出；行业净流入必须标明为数据商推算口径。
每只最后必须给唯一动作：进攻、保留但不追、降级或剔除。不得把正反理由列完后让用户自己选。
最后给明日执行顺序和每只股票的触发/失效条件。不要承诺收益。

数据：
{_compact_json([_stock_ai_payload(row) for row in stocks], 50000)}
"""
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.25,
        max_tokens=7000,
        tools=[],
        thinking={"type": "disabled"},
        timeout=180,
    )
    return (response.choices[0].message.content or "").strip()


def _build_ai_block_analysis(
    market: dict,
    portfolio: dict,
    watchlist: dict,
    industry: dict,
    international: dict,
    intelligence: dict,
    progress_cb=None,
) -> dict:
    if progress_cb:
        progress_cb("AI 综合生成七大复盘模块...")
    fallback = _fallback_analysis(market, portfolio, watchlist, industry, international, intelligence)
    fallback.update(_build_extra(market, portfolio, watchlist, industry, international))
    fallback["source"] = "deterministic"
    fallback["source_label"] = "AI失败后的数据兜底"
    try:
        from services.ai_client import make_client, CHAT_MODEL

        payload = {
            "portfolio": {
                "summary": portfolio.get("summary"),
                "positions": [_stock_ai_payload(row) for row in (portfolio.get("positions") or [])],
                "analysis_points": portfolio.get("analysis_points"),
                "alerts": portfolio.get("alerts"),
            },
            "watchlist": {
                "summary": watchlist.get("summary"),
                "stocks": [_stock_ai_payload(row) for row in (watchlist.get("stocks") or [])],
                "analysis_points": watchlist.get("analysis_points"),
            },
            "industry": _industry_ai_payload(industry),
            "market": _market_ai_payload(market),
            "postmarket_intelligence": _intelligence_ai_payload(intelligence),
            "international": {
                "conclusion": international.get("conclusion"),
                "items": (international.get("items") or [])[:8],
            },
        }
        prompt = f"""
你是一个激进但理性的 A 股交易复盘助手。用户要看的不是数据罗列，而是市场表面之下正在发生的结构变化。

请把全部证据放在同一个推理过程中交叉验证，输出七个模块。必须严格返回 JSON 对象，键名固定：
market_review, portfolio_review, watchlist_review, industry_review, international_review,
risk_opportunity, tomorrow_watch。

前五个值是 markdown 字符串，要求：
- 每个模块 350-850 字，分 3-5 个 `###` 小标题；不要对每只股票机械复用相同句式，要根据各自证据写出不同的核心矛盾。
- 必须分析「涨跌逻辑」「量价逻辑」「结构/主线」「风险」「明日动作」中与该模块相关的内容。
- 持仓和自选必须逐只解释，不要只说总盈亏；每只都要同时使用四类证据：自身趋势量价、个股资金、所属行业资金与广度、相对行业/市场强弱。
- 个股 fund_flow.available=false 时，必须明确写“个股资金数据缺失”，只能使用成交额、换手和量比判断活跃度，禁止伪造净流入方向。
- 个股 fund_flow.available=true 时，资金数据已经可用，即使 source=ths_market_rank 也禁止再写“数据缺失”或“暂不可用”；必须注明是同花顺资金榜口径，并使用 main_net_yi 与 main_net_pct。
- 主力/大单资金是数据商按成交单大小推算的交易口径，不代表真实机构或散户身份。禁止把净流出直接写成“机构出货”，也禁止把净流入直接写成“机构抢筹”。
- sector.net_in_yi 与 fund_change 是数据商推算口径，必须写“推算”或“资金口径显示”，不能写成真实机构买卖事实。
- 所有判断点必须给唯一动作结论，例如「进攻 / 保留但不追 / 降级 / 剔除 / 收紧仓位」。禁止把正反理由都列出来让用户自己选。
- 自选复盘必须先给“自选池裁决”：谁是第一顺位，谁剔除，谁降级；结论必须是动作，不得写成含糊建议。
- 市场复盘要结合情绪温度、涨跌家数、涨停/跌停/炸板、指数、行业主线、个股榜单和新闻。
- market_review 必须以 postmarket_intelligence 为分析骨架，先给唯一的市场状态和仓位上限，再解释指数与广度背离、大小盘裂口、亏钱效应、历史分位、盘中路径和主线生命周期。
- 严格区分事实、推断和动作；不得把推算净流入写成绝对资金事实，不得在缺少盘中快照时编造盘中路径。
- 必须审计早段判断是否被收盘验证，不能只复述收盘涨跌幅。
- 若 postmarket_intelligence.learning.latest_audit 存在，必须解释昨日仓位预算、主线判断和今日实际结果；若仍在 collecting 状态，只能写“积累样本”，禁止声称AI已经完成权重更新。
- 持仓复盘要做账户归因：区分市场Beta、行业暴露、个股相对强弱和交易假设是否失效，给每只持仓唯一动作。
- 行业板块必须逐个结合涨跌、上涨广度、净流入、盘中净流入变化、龙头和涨停分布，判断是启动、扩散、高潮、分歧还是退潮。
- 国际形势要写清楚国际事件映射到 A 股哪些方向，以及哪些方向纳入计划、哪些方向直接排除，不能只贴新闻标题。
- 不要喊单，不要承诺收益；但必须激进且理性，给明确执行动作。

risk_opportunity 必须是对象，结构严格为：
{{"risks":[{{"title":"", "industry":"", "stocks":[{{"symbol":"", "name":""}}], "evidence":"", "action":""}}],
"opportunities":[同样结构]}}。
- 每条风险和机会必须同时给行业与对应股票，股票只能来自输入中的持仓、自选、行业龙头、涨跌停或成交额榜单，禁止编造代码和名称。
- evidence 必须引用资金、广度、量价或龙头承接中的至少两项；action 给唯一动作。

tomorrow_watch 必须是数组，每项结构严格为：
{{"theme":"", "industry":"", "stocks":[{{"symbol":"", "name":""}}], "evidence":"", "trigger":"", "invalidation":"", "action":""}}。
- 每项都必须有行业、具体股票、明日触发条件和失效条件；不能只写“关注某行业”。
- 选出的股票必须有当日证据支撑，并说明是持仓、自选还是市场龙头。

数据：
{_compact_json(payload, 80000)}
"""
        resp = make_client().chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.35,
            max_tokens=9000,
            tools=[],
            thinking={"type": "disabled"},
            timeout=180,
        )
        parsed = _parse_json_obj(resp.choices[0].message.content or "")
        if not parsed:
            fallback["error"] = "AI 未返回可解析的七模块 JSON，已使用数据兜底。"
            return fallback
        merged = dict(fallback)
        validation_notes = []
        repair_requests: list[tuple[str, str, list[dict]]] = []
        for key in (
            "market_review", "portfolio_review", "watchlist_review",
            "industry_review", "international_review",
        ):
            text = parsed.get(key)
            stocks = (
                portfolio.get("positions") or [] if key == "portfolio_review"
                else watchlist.get("stocks") or [] if key == "watchlist_review"
                else []
            )
            covers_stocks = not stocks or (isinstance(text, str) and _contains_all_stocks(text, stocks))
            if isinstance(text, str) and len(text.strip()) >= 260 and covers_stocks:
                merged[key] = text.strip()
            elif stocks and not covers_stocks:
                label = "持仓复盘" if key == "portfolio_review" else "自选复盘"
                repair_requests.append((key, label, stocks))
        for key, label, stocks in repair_requests:
            try:
                if progress_cb:
                    progress_cb(f"AI 补写完整{label}名单...")
                repaired = _repair_stock_review(make_client(), CHAT_MODEL, label, stocks)
                if len(repaired) >= 260 and _contains_all_stocks(repaired, stocks):
                    merged[key] = repaired
                else:
                    validation_notes.append(f"{key} 补写后仍未覆盖完整名单，已使用数据兜底")
            except Exception as repair_exc:
                validation_notes.append(f"{key} 补写失败，已使用数据兜底：{repair_exc}")
        allowed_symbols, allowed_names = _allowed_stock_refs(market, portfolio, watchlist, industry)
        risk_opportunity = parsed.get("risk_opportunity")
        if isinstance(risk_opportunity, dict):
            risks = risk_opportunity.get("risks")
            opportunities = risk_opportunity.get("opportunities")
            if (
                isinstance(risks, list) and isinstance(opportunities, list)
                and _valid_structured_stock_items(risks, allowed_symbols, allowed_names)
                and _valid_structured_stock_items(opportunities, allowed_symbols, allowed_names)
            ):
                merged["risk_opportunity"] = {
                    "risks": risks[:6],
                    "opportunities": opportunities[:6],
                }
            else:
                validation_notes.append("风险与机会含未知股票或缺少股票，已使用数据兜底")
        tomorrow_watch = parsed.get("tomorrow_watch")
        if (
            isinstance(tomorrow_watch, list) and tomorrow_watch
            and _valid_structured_stock_items(tomorrow_watch, allowed_symbols, allowed_names)
        ):
            merged["tomorrow_watch"] = tomorrow_watch[:6]
        elif tomorrow_watch:
            validation_notes.append("明日关注含未知股票或缺少股票，已使用数据兜底")
        merged["source"] = "ai"
        merged["source_label"] = "大模型综合生成 · 数据证据约束"
        if validation_notes:
            merged["validation_notes"] = validation_notes
        return merged
    except Exception as e:
        fallback["error"] = str(e)
        return fallback


def build_today_review(trade_date: str, watchlist: list[dict] | None = None, progress_cb=None) -> dict:
    normalized_watchlist = _normalize_watchlist(watchlist)
    try:
        from api.portfolio import _load_store

        position_rows = _load_store().get("positions") or []
        position_symbols = [
            str(row.get("symbol") or "")
            for row in position_rows
            if row.get("symbol")
        ]
    except Exception:
        position_rows = []
        position_symbols = []
    review_symbols = list(dict.fromkeys(
        position_symbols + [row["code"] for row in normalized_watchlist]
    ))
    if progress_cb:
        progress_cb("提取个股资金与所属行业资金证据...")
    from services.review_evidence_service import build_review_evidence

    stock_names = {
        str(row.get("symbol") or ""): str(row.get("name") or "")
        for row in position_rows if row.get("symbol")
    }
    stock_names.update({row["code"]: str(row.get("name") or "") for row in normalized_watchlist})
    evidence = build_review_evidence(review_symbols, trade_date, stock_names)
    market = _build_market(trade_date, progress_cb)
    portfolio = _build_portfolio(trade_date, evidence, progress_cb)
    watch = _build_watchlist(normalized_watchlist, trade_date, evidence, progress_cb)
    industry = _build_industry(evidence, progress_cb)
    international = _build_international(progress_cb)
    fallback_extra = _build_extra(market, portfolio, watch, industry, international)
    if progress_cb:
        progress_cb("计算历史分位、盘中路径与市场暗流...")
    from services.postmarket_intelligence_service import build_postmarket_intelligence

    intelligence = build_postmarket_intelligence(trade_date, market)
    try:
        from services.decision_learning_service import record_decision_and_learn
        intelligence["learning"] = record_decision_and_learn(trade_date, intelligence)
    except Exception as exc:
        intelligence["learning"] = {
            "state": "error",
            "label": "自动学习暂不可用",
            "valid_outcomes": 0,
            "minimum_samples": 30,
            "next_action": str(exc),
        }
    analysis = _build_ai_block_analysis(
        market, portfolio, watch, industry, international, intelligence, progress_cb
    )
    risk_opportunity = analysis.get("risk_opportunity") or fallback_extra["risk_opportunity"]
    tomorrow_watch = analysis.get("tomorrow_watch") or fallback_extra["tomorrow_watch"]

    return {
        "trade_date": trade_date,
        "generated_at": datetime.now().isoformat(),
        "market": market,
        "portfolio": portfolio,
        "watchlist": watch,
        "industry": industry,
        "international": international,
        "analysis": analysis,
        "intelligence": intelligence,
        "risk_opportunity": risk_opportunity,
        "tomorrow_watch": tomorrow_watch,
        "evidence_basis": evidence.get("basis", ""),
    }
