"""Deep post-market intelligence built from close, history and intraday paths.

The output deliberately separates facts, inference and action.  It is usable
without an LLM so a model failure never degrades the review into vague prose.
"""
from __future__ import annotations

from datetime import datetime
from statistics import median
from typing import Any


def _f(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return default if number != number else number
    except (TypeError, ValueError):
        return default


def _pct(value: float) -> str:
    return f"{value:+.2f}%"


def _percentile(value: float, samples: list[float]) -> int | None:
    clean = sorted(x for x in samples if x == x)
    if not clean:
        return None
    below = sum(1 for x in clean if x < value)
    equal = sum(1 for x in clean if x == value)
    return round((below + equal * 0.5) / len(clean) * 100)


def _market_metrics(market: dict) -> dict:
    breadth = market.get("breadth") or {}
    limits = market.get("limit_stats") or {}
    indices = market.get("indices") or []
    cap_perf = market.get("cap_perf") or []
    up = _f(breadth.get("up"))
    down = _f(breadth.get("down"))
    up_ratio = _f(breadth.get("up_ratio"))
    if not up_ratio and up + down:
        up_ratio = up / (up + down) * 100
    index_pcts = [_f(row.get("pct")) for row in indices]
    index_avg = sum(index_pcts) / len(index_pcts) if index_pcts else 0.0
    index_dispersion = max(index_pcts) - min(index_pcts) if index_pcts else 0.0
    cap_map = {str(row.get("tier") or ""): row for row in cap_perf}
    mega = next((row for name, row in cap_map.items() if "超大盘" in name), {})
    small = next((row for name, row in cap_map.items() if "小盘 <" in name), {})
    return {
        "up": int(up),
        "down": int(down),
        "up_ratio": round(up_ratio, 1),
        "zt": int(_f(limits.get("zt_count"))),
        "dt": int(_f(limits.get("dt_count"))),
        "broken": int(_f(limits.get("broken_count"))),
        "broken_ratio": round(_f(limits.get("broken_ratio")), 1),
        "amount": round(_f((market.get("amount") or {}).get("total_yi")), 2),
        "sentiment": int(_f((market.get("sentiment") or {}).get("score"))),
        "index_avg": round(index_avg, 2),
        "index_dispersion": round(index_dispersion, 2),
        "mega_pct": round(_f(mega.get("avg_pct")), 2),
        "small_pct": round(_f(small.get("avg_pct")), 2),
        "size_gap": round(_f(mega.get("avg_pct")) - _f(small.get("avg_pct")), 2),
    }


def _history_context(trade_date: str, current: dict, limit: int = 20) -> dict:
    from db.market_review_db import get_daily, list_dates

    rows = []
    for item in list_dates():
        day = str(item.get("date") or "")
        if not day or day > trade_date:
            continue
        data = get_daily(day)
        if data:
            rows.append({"date": day, **_market_metrics(data)})
        if len(rows) >= limit:
            break

    previous = next((row for row in rows if row["date"] < trade_date), None)
    sample = rows or [{"date": trade_date, **current}]
    fields = ("up_ratio", "zt", "dt", "broken_ratio", "amount", "sentiment", "size_gap")
    percentiles = {
        field: _percentile(_f(current.get(field)), [_f(row.get(field)) for row in sample])
        for field in fields
    }
    medians = {
        field: round(median([_f(row.get(field)) for row in sample]), 2)
        for field in fields
    }
    changes = {}
    if previous:
        for field in fields:
            changes[field] = round(_f(current.get(field)) - _f(previous.get(field)), 2)
    return {
        "sample_days": len(sample),
        "window": f"最近{len(sample)}个已保存交易日",
        "percentiles": percentiles,
        "medians": medians,
        "previous_date": previous.get("date") if previous else "",
        "changes_vs_previous": changes,
    }


def _intraday_path(trade_date: str) -> tuple[dict, list[dict]]:
    from db.market_radar_db import list_snapshots

    snapshots = list_snapshots(trade_date)
    usable = [row for row in snapshots if row.get("phase") in {"intraday", "postmarket"}]
    if len(usable) < 2:
        return ({
            "available": False,
            "snapshot_count": len(usable),
            "summary": "盘中快照不足，不推断日内资金路径。",
            "first_at": usable[0].get("captured_at", "") if usable else "",
            "last_at": usable[-1].get("captured_at", "") if usable else "",
        }, usable)

    first, last = usable[0], usable[-1]
    first_market = first.get("market") or {}
    last_market = last.get("market") or {}
    first_score = _f((first_market.get("decision") or {}).get("score"), 50)
    last_score = _f((last_market.get("decision") or {}).get("score"), 50)
    first_breadth = _f(first_market.get("sector_up_ratio"))
    last_breadth = _f(last_market.get("sector_up_ratio"))
    score_delta = last_score - first_score
    breadth_delta = last_breadth - first_breadth
    if score_delta <= -8 or breadth_delta <= -20:
        pattern = "盘中转弱"
        summary = "早段承接没有维持到收盘，资金由试探进攻转向收缩。"
    elif score_delta >= 8 or breadth_delta >= 20:
        pattern = "盘中增强"
        summary = "市场状态随交易推进改善，收盘确认强于早段。"
    else:
        pattern = "日内延续"
        summary = "早段定性基本延续到收盘，没有出现足以改写策略的转折。"
    return ({
        "available": True,
        "snapshot_count": len(usable),
        "first_at": first.get("captured_at", ""),
        "last_at": last.get("captured_at", ""),
        "first_score": round(first_score),
        "last_score": round(last_score),
        "score_delta": round(score_delta),
        "first_sector_breadth": round(first_breadth),
        "last_sector_breadth": round(last_breadth),
        "breadth_delta": round(breadth_delta),
        "pattern": pattern,
        "summary": summary,
    }, usable)


def _mainlines(snapshots: list[dict]) -> list[dict]:
    from services.market_radar_service import classify_sector_state

    if not snapshots:
        return []
    first_rows = snapshots[0].get("sectors") or []
    last_rows = snapshots[-1].get("sectors") or []
    first_map = {row.get("name"): row for row in first_rows}
    top_presence: dict[str, int] = {}
    for snap in snapshots:
        for row in sorted(snap.get("sectors") or [], key=lambda x: _f(x.get("score")), reverse=True)[:10]:
            name = str(row.get("name") or "")
            if name:
                top_presence[name] = top_presence.get(name, 0) + 1

    result = []
    total = len(snapshots)
    for row in sorted(last_rows, key=lambda x: _f(x.get("score")), reverse=True)[:10]:
        name = str(row.get("name") or "")
        classified = classify_sector_state(row, first_map.get(name))
        persistence = round(top_presence.get(name, 0) / total * 100) if total else 0
        score = round(_f(row.get("score")))
        breadth = round(_f(row.get("breadth")) * 100)
        net_in = round(_f(row.get("net_in")), 2)
        is_risk_state = classified.get("state") in {"高位分歧", "资金撤退", "弱势退潮", "假突破"}
        if score >= 68 and breadth >= 65 and persistence >= 55 and not is_risk_state:
            level = "确认主线"
            action = "保留进攻资格"
        elif score >= 60 and breadth >= 55 and not is_risk_state:
            level = "轮动候选"
            action = "只等次日承接确认"
        elif is_risk_state:
            level = "分歧降级"
            action = "退出主计划"
        else:
            level = "强度不足"
            action = "不纳入主计划"
        result.append({
            "name": name,
            "state": classified.get("state"),
            "level": level,
            "action": action,
            "score": score,
            "pct": round(_f(row.get("pct")), 2),
            "breadth": breadth,
            "net_in": net_in,
            "leader": row.get("leader") or "--",
            "persistence": persistence,
            "evidence": (
                f"收盘评分{score}，上涨广度{breadth}%，快照前十出现率{persistence}%，"
                f"净流入推算{net_in:+.2f}亿，龙头{row.get('leader') or '--'}。"
            ),
        })
    return result


def _regime(metrics: dict, path: dict) -> dict:
    up_ratio = metrics["up_ratio"]
    zt, dt = metrics["zt"], metrics["dt"]
    broken_ratio = metrics["broken_ratio"]
    size_gap = metrics["size_gap"]
    dispersion = metrics["index_dispersion"]
    risk = 0
    attack = 0
    reasons = []

    if up_ratio < 35:
        risk += 2
        reasons.append(f"上涨占比仅{up_ratio:.1f}%")
    elif up_ratio >= 60:
        attack += 2
        reasons.append(f"上涨占比达到{up_ratio:.1f}%")
    if dt > max(zt * 1.2, 20):
        risk += 2
        reasons.append(f"跌停{dt}只显著多于涨停{zt}只")
    elif zt > max(dt * 2, 50):
        attack += 2
        reasons.append(f"涨停{zt}只且明显压过跌停")
    if broken_ratio >= 35:
        risk += 1
        reasons.append(f"炸板率{broken_ratio:.1f}%")
    elif broken_ratio and broken_ratio <= 22:
        attack += 1
    if size_gap >= 2:
        risk += 1
        reasons.append(f"超大盘领先小盘{size_gap:.2f}个百分点")
    elif size_gap <= -1:
        attack += 1
    if dispersion >= 1.5:
        risk += 1
        reasons.append(f"指数分化{dispersion:.2f}个百分点")
    if path.get("available") and _f(path.get("score_delta")) <= -8:
        risk += 1
        reasons.append("盘中市场评分明显下滑")
    elif path.get("available") and _f(path.get("score_delta")) >= 8:
        attack += 1

    if risk >= 6:
        if size_gap >= 2 and metrics["index_avg"] >= 0:
            name = "权重护盘下的普跌退潮"
        else:
            name = "全面退潮"
        stance, cap = "防守", 20
    elif risk >= 3:
        name, stance, cap = "分化退潮", "收缩", 30
    elif attack >= 5:
        name, stance, cap = "广度扩散进攻", "进攻", 70
    elif attack >= 3:
        name, stance, cap = "结构性进攻", "试错", 50
    else:
        name, stance, cap = "混沌轮动", "等待确认", 40
    confidence = min(95, 58 + len(reasons) * 5 + (8 if path.get("available") else 0))
    return {
        "regime": name,
        "stance": stance,
        "position_cap": cap,
        "confidence": confidence,
        "summary": f"{name}。默认{stance}，次日总仓位上限{cap}%。",
        "evidence": reasons[:6],
    }


def _undercurrents(metrics: dict, history: dict, path: dict, mainlines: list[dict]) -> list[dict]:
    items = []
    sample = history.get("sample_days", 0)
    percentiles = history.get("percentiles") or {}
    changes = history.get("changes_vs_previous") or {}

    if metrics["size_gap"] >= 1.5 and metrics["up_ratio"] < 50:
        items.append({
            "title": "指数红盘掩盖了个股失血",
            "signal": "背离",
            "evidence": f"指数均值{_pct(metrics['index_avg'])}，但上涨占比仅{metrics['up_ratio']:.1f}%；超大盘平均{_pct(metrics['mega_pct'])}，小盘平均{_pct(metrics['small_pct'])}。",
            "inference": "资金在用少数大权重维持指数，真实持股体验弱于指数表面，不能把指数上涨理解为风险偏好修复。",
            "action": "小盘和后排题材退出主计划，只保留有独立承接的核心。",
            "confidence": "高",
        })
    elif metrics["size_gap"] <= -1 and metrics["up_ratio"] >= 55:
        items.append({
            "title": "赚钱效应正在从指数向个股扩散",
            "signal": "扩散",
            "evidence": f"上涨占比{metrics['up_ratio']:.1f}%，小盘领先超大盘{abs(metrics['size_gap']):.2f}个百分点。",
            "inference": "增量风险偏好进入弹性方向，选股机会强于单纯配置指数。",
            "action": "允许在确认主线中做前排试错，后排仍不追。",
            "confidence": "高",
        })

    loss_ratio = metrics["dt"] / max(metrics["zt"], 1)
    items.append({
        "title": "短线资金的真实状态不是看涨停数，而是看失败代价",
        "signal": "退潮" if loss_ratio > 1 or metrics["broken_ratio"] >= 35 else "可控",
        "evidence": f"涨停{metrics['zt']}只、跌停{metrics['dt']}只、炸板率{metrics['broken_ratio']:.1f}%；跌停/涨停比{loss_ratio:.2f}。",
        "inference": (
            "失败样本远多于成功样本，说明接力资金承担的是负期望分布。"
            if loss_ratio > 1 else
            "成功样本仍占优，短线风险尚未失控，但需继续约束追高。"
        ),
        "action": "停止接力和弱转强博弈。" if loss_ratio > 1 else "只做主线前排，不扩散到杂毛。",
        "confidence": "高",
    })

    if sample >= 5:
        items.append({
            "title": "当天不是孤立涨跌，而是历史样本中的异常位置",
            "signal": "历史分位",
            "evidence": (
                f"在最近{sample}个已保存交易日中，上涨广度处于{percentiles.get('up_ratio')}分位，"
                f"跌停数量处于{percentiles.get('dt')}分位，成交额处于{percentiles.get('amount')}分位。"
            ),
            "inference": (
                "成交活跃但广度偏弱，量能没有转化为普遍赚钱效应，筹码交换更像风险释放而非健康增量。"
                if (percentiles.get("amount") or 0) >= 60 and (percentiles.get("up_ratio") or 100) <= 40 else
                "当前强弱已放回自身历史坐标，不再用固定的绝对阈值机械判断。"
            ),
            "action": "高成交不再作为进攻理由，先看次日亏钱效应是否收敛。",
            "confidence": "中高",
        })

    if path.get("available"):
        items.append({
            "title": f"盘中路径确认：{path.get('pattern')}",
            "signal": "路径",
            "evidence": (
                f"{str(path.get('first_at'))[11:16]}至{str(path.get('last_at'))[11:16]}共{path.get('snapshot_count')}个快照，"
                f"市场评分{path.get('first_score')}→{path.get('last_score')}，板块上涨占比{path.get('first_sector_breadth')}%→{path.get('last_sector_breadth')}%。"
            ),
            "inference": path.get("summary"),
            "action": "收盘状态覆盖早盘乐观判断，次日从防守状态重新验证。" if _f(path.get("score_delta")) < 0 else "保留收盘确认方向，次日观察是否继续扩散。",
            "confidence": "高",
        })

    confirmed = [row for row in mainlines if row.get("level") == "确认主线"]
    if confirmed:
        names = "、".join(row["name"] for row in confirmed[:4])
        items.append({
            "title": "局部主线仍在，但不能替代全市场风险判断",
            "signal": "结构",
            "evidence": f"通过收盘评分、广度和盘中持续率共同确认的方向：{names}。",
            "inference": "这些方向是退潮环境中的相对强者，价值在于提供避风方向，而不是证明市场已经全面转强。",
            "action": "只跟踪确认主线龙头，禁止由局部强势外推到全面加仓。",
            "confidence": "中高",
        })

    if changes:
        direction = "改善" if _f(changes.get("up_ratio")) > 0 else "恶化"
        items.append({
            "title": f"相对上一交易日，市场内部结构继续{direction}",
            "signal": "日际变化",
            "evidence": (
                f"上涨广度变化{_f(changes.get('up_ratio')):+.1f}个百分点，涨停变化{_f(changes.get('zt')):+.0f}只，"
                f"跌停变化{_f(changes.get('dt')):+.0f}只，成交额变化{_f(changes.get('amount')):+.0f}亿。"
            ),
            "inference": "连续性比单日结果更重要，结构尚未反转前不因一根指数阳线改变风险预算。",
            "action": "延续当前仓位纪律，直到广度和亏钱效应同时反转。",
            "confidence": "中",
        })
    return items[:6]


def _tomorrow_plan(verdict: dict, metrics: dict, history: dict, mainlines: list[dict]) -> dict:
    confirmed = [row["name"] for row in mainlines if row.get("level") == "确认主线"]
    weak = [row["name"] for row in mainlines if row.get("state") in {"资金撤退", "弱势退潮", "假突破"}]
    median_breadth = _f((history.get("medians") or {}).get("up_ratio"), 50)
    return {
        "default_action": verdict["stance"],
        "position_cap": verdict["position_cap"],
        "focus": confirmed[:4],
        "avoid": weak[:4],
        "base_case": f"开盘按{verdict['stance']}模式执行，不因单只股票高开改变总仓位。",
        "upgrade_condition": (
            f"只有全市场上涨占比回到{max(55, round(median_breadth))}%以上、跌停/涨停比降至0.5以下、"
            "炸板率降到30%以下，并且主线广度继续扩散，才提高一级仓位。"
        ),
        "downgrade_condition": (
            "若上涨占比仍低于30%、跌停继续多于涨停，或确认主线在盘中快照里转为资金撤退，"
            "仓位直接压回20%，停止新开仓。"
        ),
    }


def build_postmarket_intelligence(trade_date: str, market: dict) -> dict:
    metrics = _market_metrics(market)
    history = _history_context(trade_date, metrics)
    path, snapshots = _intraday_path(trade_date)
    mainlines = _mainlines(snapshots)
    verdict = _regime(metrics, path)
    undercurrents = _undercurrents(metrics, history, path, mainlines)
    try:
        from services.market_radar_service import evaluate_radar_day
        audit = evaluate_radar_day(trade_date)
    except Exception as exc:
        audit = {"ready": False, "verdict": f"判断审计暂不可用：{exc}"}
    return {
        "generated_at": datetime.now().isoformat(),
        "engine": "postmarket-intelligence-v1",
        "data_scope": "收盘全市场 + 历史日档案 + 盘中市场雷达",
        "metrics": metrics,
        "verdict": verdict,
        "historical_context": history,
        "intraday_path": path,
        "undercurrents": undercurrents,
        "mainlines": mainlines,
        "audit": audit,
        "tomorrow_plan": _tomorrow_plan(verdict, metrics, history, mainlines),
        "data_notes": [
            "历史分位仅基于本软件已保存交易日，不代表全市场长期分布。",
            "板块净流入为数据商成交口径推算，只能与广度、价格、龙头和时间序列共同使用。",
            "缺少盘中快照时不补写盘中路径。",
        ],
    }
