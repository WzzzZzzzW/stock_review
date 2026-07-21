"""Deep post-market intelligence built from close, history and intraday paths.

The output deliberately separates facts, inference and action.  It is usable
without an LLM so a model failure never degrades the review into vague prose.
"""
from __future__ import annotations

from datetime import datetime
from statistics import median
from typing import Any


ENGINE_VERSION = "postmarket-intelligence-v3"


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
    cap_total = sum(int(_f(row.get("count"))) for row in cap_perf)
    equal_weight_avg = (
        sum(_f(row.get("avg_pct")) * int(_f(row.get("count"))) for row in cap_perf) / cap_total
        if cap_total else index_avg
    )
    close_positions = []
    for row in indices:
        high, low, price = _f(row.get("high")), _f(row.get("low")), _f(row.get("price"))
        if high > low:
            close_positions.append((price - low) / (high - low) * 100)
    close_position = sum(close_positions) / len(close_positions) if close_positions else 50.0
    amount = round(_f((market.get("amount") or {}).get("total_yi")), 2)
    top_amount = sum(_f(row.get("amount_yi")) for row in (market.get("rankings") or {}).get("amount") or [])
    top_amount_share = top_amount / amount * 100 if amount else 0.0
    up_over5 = int(_f(breadth.get("up_over5")))
    down_over5 = int(_f(breadth.get("down_over5")))
    tail_ratio = up_over5 / max(down_over5, 1)
    return {
        "up": int(up),
        "down": int(down),
        "up_ratio": round(up_ratio, 1),
        "zt": int(_f(limits.get("zt_count"))),
        "dt": int(_f(limits.get("dt_count"))),
        "broken": int(_f(limits.get("broken_count"))),
        "broken_ratio": round(_f(limits.get("broken_ratio")), 1),
        "max_continuity": int(_f(limits.get("max_continuity"))),
        "up_over5": up_over5,
        "down_over5": down_over5,
        "tail_ratio": round(tail_ratio, 2),
        "amount": amount,
        "top_amount_share": round(top_amount_share, 1),
        "sentiment": int(_f((market.get("sentiment") or {}).get("score"))),
        "index_avg": round(index_avg, 2),
        "equal_weight_avg": round(equal_weight_avg, 2),
        "index_equal_gap": round(index_avg - equal_weight_avg, 2),
        "close_position": round(close_position, 1),
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
    fields = (
        "up_ratio", "zt", "dt", "broken_ratio", "amount", "sentiment", "size_gap",
        "equal_weight_avg", "index_equal_gap", "close_position", "tail_ratio",
    )
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
    prior_rows = [row for row in rows if row["date"] < trade_date]

    def _average(field: str, count: int) -> float | None:
        values = [_f(row.get(field)) for row in prior_rows[:count] if _f(row.get(field)) > 0]
        return round(sum(values) / len(values), 2) if values else None

    amount_avg_5 = _average("amount", 5)
    amount_avg_20 = _average("amount", 20)
    return {
        "sample_days": len(sample),
        "window": f"最近{len(sample)}个已保存交易日",
        "percentiles": percentiles,
        "medians": medians,
        "previous_date": previous.get("date") if previous else "",
        "changes_vs_previous": changes,
        "amount_avg_5": amount_avg_5,
        "amount_avg_20": amount_avg_20,
        "amount_ratio_5": round(_f(current.get("amount")) / amount_avg_5, 2) if amount_avg_5 else None,
        "amount_ratio_20": round(_f(current.get("amount")) / amount_avg_20, 2) if amount_avg_20 else None,
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


def _regime(metrics: dict, path: dict, risk_weights: dict | None = None) -> dict:
    risk_weights = risk_weights or {
        "breadth_low": 2.0,
        "loss_pressure": 2.0,
        "broken_high": 1.0,
        "size_divergence": 1.0,
        "index_divergence": 1.0,
        "intraday_weakened": 1.0,
    }
    up_ratio = metrics["up_ratio"]
    zt, dt = metrics["zt"], metrics["dt"]
    broken_ratio = metrics["broken_ratio"]
    size_gap = metrics["size_gap"]
    dispersion = metrics["index_dispersion"]
    risk = 0
    attack = 0
    reasons = []

    if up_ratio < 35:
        risk += _f(risk_weights.get("breadth_low"), 2.0)
        reasons.append(f"上涨占比仅{up_ratio:.1f}%")
    elif up_ratio >= 60:
        attack += 2
        reasons.append(f"上涨占比达到{up_ratio:.1f}%")
    if dt > max(zt * 1.2, 20):
        risk += _f(risk_weights.get("loss_pressure"), 2.0)
        reasons.append(f"跌停{dt}只显著多于涨停{zt}只")
    elif zt > max(dt * 2, 50):
        attack += 2
        reasons.append(f"涨停{zt}只且明显压过跌停")
    if broken_ratio >= 35:
        risk += _f(risk_weights.get("broken_high"), 1.0)
        reasons.append(f"炸板率{broken_ratio:.1f}%")
    elif broken_ratio and broken_ratio <= 22:
        attack += 1
    if size_gap >= 2:
        risk += _f(risk_weights.get("size_divergence"), 1.0)
        reasons.append(f"超大盘领先小盘{size_gap:.2f}个百分点")
    elif size_gap <= -1:
        attack += 1
    if dispersion >= 1.5:
        risk += _f(risk_weights.get("index_divergence"), 1.0)
        reasons.append(f"指数分化{dispersion:.2f}个百分点")
    if path.get("available") and _f(path.get("score_delta")) <= -8:
        risk += _f(risk_weights.get("intraday_weakened"), 1.0)
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


def _core_judgements(
    metrics: dict,
    history: dict,
    path: dict,
    mainlines: list[dict],
    mainline_analysis: dict | None = None,
) -> list[dict]:
    amount_ratio = history.get("amount_ratio_5")
    if amount_ratio:
        volume_change = (_f(amount_ratio) - 1) * 100
        volume_text = (
            f"成交量比近5日平均多{abs(volume_change):.0f}%"
            if volume_change >= 0 else
            f"成交量比近5日平均少{abs(volume_change):.0f}%"
        )
    else:
        volume_text = "近5日成交样本不足"
    price_up = metrics["index_avg"] > 0
    equal_up = metrics["equal_weight_avg"] > 0
    close_strong = metrics["close_position"] >= 70
    index_gap_text = (
        f"指数比个股平均强{abs(metrics['index_equal_gap']):.2f}点"
        if metrics["index_equal_gap"] >= 0 else
        f"个股平均比指数强{abs(metrics['index_equal_gap']):.2f}点"
    )
    size_gap_text = (
        f"大盘股比小盘股强{abs(metrics['size_gap']):.2f}点"
        if metrics["size_gap"] >= 0 else
        f"小盘股比大盘股强{abs(metrics['size_gap']):.2f}点"
    )
    if metrics["close_position"] >= 85:
        close_text = f"指数接近全天最高点收盘（{metrics['close_position']:.0f}%）"
    elif metrics["close_position"] <= 15:
        close_text = f"指数接近全天最低点收盘（{metrics['close_position']:.0f}%）"
    else:
        close_text = f"指数收在全天波动区间的{metrics['close_position']:.0f}%位置"

    if price_up and equal_up and _f(amount_ratio, 1) >= 1.1 and close_strong:
        volume_conclusion = "成交放大、指数上涨，而且接近最高点收盘，说明今天确实有资金进场。"
        volume_action = "可以适当提高主线仓位，但不要追单只高开股。"
        volume_tone = "attack"
    elif price_up and metrics["index_equal_gap"] >= 1.5:
        volume_conclusion = "指数虽然上涨，但钱主要去了大盘权重，多数股票没有同步变好。"
        volume_action = "只留真正有资金承接的核心股，不买跟风股。"
        volume_tone = "risk"
    elif price_up and _f(amount_ratio, 1) < 0.9:
        volume_conclusion = "指数涨了，但成交反而缩小，说明跟进资金还不够。"
        volume_action = "先不加总仓位，等放量上涨后再提高仓位。"
        volume_tone = "neutral"
    elif not price_up and _f(amount_ratio, 1) >= 1.1:
        volume_conclusion = "成交放大但市场下跌，说明卖出资金更主动。"
        volume_action = "降低仓位，不要把成交放大误当成资金进场。"
        volume_tone = "risk"
    else:
        volume_conclusion = "成交量和价格都没有给出明确方向，暂时不用改变仓位。"
        volume_action = "维持当前仓位，等成交、上涨家数和收盘强度一起变好。"
        volume_tone = "neutral"

    volume_logic = (
        f"两市成交{metrics['amount']:.0f}亿，{volume_text}；主要指数平均{_pct(metrics['index_avg'])}，"
        f"全市场个股平均{_pct(metrics['equal_weight_avg'])}，主要指数平均收在全天波动区间的{metrics['close_position']:.0f}%位置。"
        "成交放大、指数和多数股票同步上涨、收盘位置较高，四项同向才算资金真正进场。"
    )

    tail_ratio = metrics["tail_ratio"]
    if metrics["up_ratio"] >= 60 and metrics["equal_weight_avg"] > 0 and metrics["size_gap"] <= 1.5:
        earning_conclusion = "上涨已经扩散到多数股票，赚钱不只靠少数大盘股。"
        earning_action = "可以从主线龙头扩展到同板块前排，但仍不碰后排跟风股。"
        earning_tone = "attack"
    elif metrics["up_ratio"] >= 50 and metrics["equal_weight_avg"] > 0:
        earning_conclusion = "多数股票开始回暖，但机会仍集中在少数风格。"
        earning_action = "可以小仓位参与主线前排，但不要因为局部上涨就全面加仓。"
        earning_tone = "neutral"
    elif metrics["index_avg"] > 0 and (metrics["equal_weight_avg"] <= 0 or metrics["size_gap"] >= 2):
        earning_conclusion = "指数看起来不错，但多数股票更弱，主要靠大盘股撑着。"
        earning_action = "小盘股和跟风股先不做，只看有资金承接的核心股。"
        earning_tone = "risk"
    else:
        earning_conclusion = "多数股票仍然难赚钱，当前不适合扩大参与。"
        earning_action = "先处理弱势票，不再买跟风股。"
        earning_tone = "risk"
    earning_logic = (
        f"上涨股票占比{metrics['up_ratio']:.1f}%，全市场个股平均{_pct(metrics['equal_weight_avg'])}；"
        f"{size_gap_text}，涨超5%的股票是跌超5%的{tail_ratio:.2f}倍。"
        "这些数据用来判断是多数股票都能赚钱，还是只涨指数和少数大盘股。"
    )

    loss_ratio = metrics["dt"] / max(metrics["zt"], 1)
    if metrics["broken_ratio"] <= 20 and loss_ratio <= 0.5 and tail_ratio >= 2:
        short_conclusion = "涨停股大多能封住，极端亏损也少，追强股的风险较低。"
        short_action = "可以做确认主线的龙头和第一次回调，但不要买后排跟风股。"
        short_tone = "attack"
    elif metrics["broken_ratio"] >= 35 or loss_ratio >= 1:
        short_conclusion = "炸板和跌停都多，追强股容易当天吃面或次日被套。"
        short_action = "停止追涨和做弱转强，只考虑低位、有资金承接的股票。"
        short_tone = "risk"
    else:
        short_conclusion = "短线有所回暖，但追高仍然容易分化。"
        short_action = "只做主线最强的前排股，并限制追高仓位。"
        short_tone = "neutral"
    short_logic = (
        f"涨停打开率{metrics['broken_ratio']:.1f}%，每100只涨停约对应{loss_ratio * 100:.0f}只跌停，"
        f"涨超5%的股票是跌超5%的{tail_ratio:.2f}倍，最高连板{metrics['max_continuity']}板。"
        "同时看涨停能否封住、极端亏损是否增多和高位股是否有人接，才能判断追强股的风险。"
    )

    confirmed = [row for row in mainlines if row.get("level") == "确认主线"]
    risk_lines = [row for row in mainlines if row.get("level") == "分歧降级"]
    confirmed_themes = (
        _confirmed_themes(mainline_analysis)
        if mainline_analysis else
        list(dict.fromkeys(_theme_for_sector(str(row.get("name") or "")) for row in confirmed))[:3]
    )
    names = "、".join(confirmed_themes[:4])
    if len(confirmed) >= 2 and path.get("available") and _f(path.get("breadth_delta")) >= 10:
        rotation_conclusion = f"热点从盘中一直增强到收盘，明天优先看{names}能否继续。"
        rotation_action = "明天先看原有热点回调时有没有资金接住，不提前押注新题材。"
        rotation_tone = "attack"
    elif confirmed:
        rotation_conclusion = f"市场有明确热点，但资金仍在快速轮动：{names}。"
        rotation_action = "只看已确认热点的龙头，不因为局部上涨就全面加仓。"
        rotation_tone = "neutral"
    else:
        rotation_conclusion = "今天没有热点同时得到资金、板块多数股票和龙头的确认。"
        rotation_action = "明天没有主攻热点，不从涨幅榜里硬挑股票。"
        rotation_tone = "risk"
    rotation_logic = (
        f"收盘有{len(confirmed)}个强势行业，合并后只有{len(confirmed_themes)}条产业主线进入明日计划；"
        f"{len(risk_lines)}个方向因为资金撤退或高位走弱被剔除。"
        + (
            f"盘中板块上涨占比{path.get('first_sector_breadth')}%→{path.get('last_sector_breadth')}%，"
            f"市场评分{path.get('first_score')}→{path.get('last_score')}。"
            if path.get("available") else "盘中数据不足，暂时无法判断热点是否全天持续。"
        )
        + "只有板块多数股票上涨、资金流入、龙头走强并且盘中持续，才算明天还能跟踪的热点。"
    )

    return [
        {"key": "volume_price", "title": "资金是不是真进场", "conclusion": volume_conclusion, "logic": volume_logic,
         "evidence": [volume_text, index_gap_text, close_text], "action": volume_action, "tone": volume_tone},
        {"key": "earning_effect", "title": "多数股票好不好赚钱", "conclusion": earning_conclusion, "logic": earning_logic,
         "evidence": [f"全市场个股平均{_pct(metrics['equal_weight_avg'])}", size_gap_text, f"大涨股是大跌股的{tail_ratio:.2f}倍"], "action": earning_action, "tone": earning_tone},
        {"key": "short_ecology", "title": "追强股的风险高不高", "conclusion": short_conclusion, "logic": short_logic,
         "evidence": [f"涨停打开率{metrics['broken_ratio']:.1f}%", f"每100只涨停约{loss_ratio * 100:.0f}只跌停", f"最高连板{metrics['max_continuity']}板"], "action": short_action, "tone": short_tone},
        {"key": "rotation", "title": "热点能不能延续", "conclusion": rotation_conclusion, "logic": rotation_logic,
         "evidence": [f"确认{len(confirmed_themes)}条产业主线", f"{len(confirmed)}个行业同向走强", path.get("pattern") or "盘中数据不足"], "action": rotation_action, "tone": rotation_tone},
    ]


def _theme_for_sector(name: str) -> str:
    groups = (
        ("电子产业链", ("半导体", "元件", "其他电子", "电子化学品", "消费电子", "光学光电子", "通信设备")),
        ("新能源产业链", ("电池", "光伏", "风电", "储能", "电网设备", "充电桩")),
        ("贵金属", ("贵金属", "黄金")),
        ("大消费", ("白酒", "食品加工", "旅游", "酒店", "零售", "美容护理")),
        ("医药生物", ("医药", "中药", "化学制药", "医疗服务", "医疗器械")),
        ("周期资源", ("煤炭", "油气", "钢铁", "有色", "化学原料", "化学纤维")),
        ("大金融", ("银行", "证券", "保险", "多元金融")),
    )
    for theme, keywords in groups:
        if any(keyword in name for keyword in keywords):
            return theme
    return name


def _confirmed_themes(mainline_analysis: dict) -> list[str]:
    return [str(row.get("name")) for row in mainline_analysis.get("themes") or [] if row.get("name")]


def _final_conclusion(verdict: dict, core: list[dict], mainline_analysis: dict) -> dict:
    stance = verdict.get("stance") or "等待确认"
    cap = int(_f(verdict.get("position_cap"), 20))
    confirmed = _confirmed_themes(mainline_analysis)
    if stance in {"进攻", "试错"}:
        market_judgement = "可以参与，但只做资金、广度和龙头承接共同确认的主线，不追后排。"
    elif stance in {"防守", "收缩"}:
        market_judgement = "不主动扩大风险，只保留强于市场且有独立承接的核心。"
    else:
        market_judgement = "保持中等以下仓位，等量价、广度和主线持续性同时确认。"
    focus_text = "、".join(str(name) for name in confirmed[:4] if name) or "暂无通过验证的进攻方向"
    return {
        "headline": verdict.get("regime") or "市场状态待确认",
        "stance": stance,
        "market_judgement": market_judgement,
        "money_effect": core[1]["conclusion"],
        "position_plan": f"明日总仓位上限{cap}%，主看{focus_text}。",
    }


def _mainline_analysis(mainlines: list[dict], market: dict) -> dict:
    rows = []
    for row in mainlines:
        level = row.get("level")
        persistence = int(_f(row.get("persistence")))
        if level == "确认主线" and persistence >= 75:
            stage = "强化"
        elif level == "确认主线":
            stage = "确认"
        elif level == "轮动候选":
            stage = "启动观察"
        elif level == "分歧降级":
            stage = "分歧/退潮"
        else:
            stage = "强度不足"
        if level == "确认主线":
            logic = (
                f"{row.get('name')}的强势不是由单只股票拉动：收盘评分{row.get('score')}，"
                f"板块广度{row.get('breadth')}%，盘中前十持续率{persistence}%，"
                f"净流入推算{_f(row.get('net_in')):+.2f}亿，龙头{row.get('leader')}。"
                "价格、资金、内部扩散和龙头承接同向，因此保留主线资格。"
            )
        elif level == "分歧降级":
            logic = (
                f"{row.get('name')}虽然仍有局部强势，但状态已转为{row.get('state')}，"
                f"广度{row.get('breadth')}%、持续率{persistence}%与资金方向不再同步，不能继续当作主线。"
            )
        else:
            logic = (
                f"{row.get('name')}当前评分{row.get('score')}、广度{row.get('breadth')}%、持续率{persistence}%，"
                "尚未同时通过资金、扩散和龙头承接验证，只作为轮动线索。"
            )
        rows.append({
            **row,
            "stage": stage,
            "logic": logic,
            "judgement": row.get("action"),
            "invalidation": (
                "明日若板块广度降到55%以下、龙头失去承接或放量滞涨，直接取消主线资格。"
                if level == "确认主线" else
                "只有广度、资金和龙头承接同时改善，才能升级。"
            ),
        })

    confirmed_rows = [row for row in rows if row.get("level") == "确认主线"]
    theme_map: dict[str, list[dict]] = {}
    for row in confirmed_rows:
        theme_map.setdefault(_theme_for_sector(str(row.get("name") or "")), []).append(row)
    themes = []
    for theme, members in theme_map.items():
        members.sort(key=lambda item: (_f(item.get("score")), _f(item.get("persistence"))), reverse=True)
        themes.append({
            "name": theme,
            "members": [str(item.get("name")) for item in members],
            "leader": members[0].get("leader") or "--",
            "score": round(sum(_f(item.get("score")) for item in members) / len(members)),
            "breadth": round(sum(_f(item.get("breadth")) for item in members) / len(members)),
            "persistence": round(sum(_f(item.get("persistence")) for item in members) / len(members)),
            "net_in": round(sum(_f(item.get("net_in")) for item in members), 2),
        })
    themes.sort(
        key=lambda item: (
            len(item.get("members") or []) > 1,
            _f(item.get("score")),
            _f(item.get("persistence")),
            _f(item.get("net_in")),
        ),
        reverse=True,
    )
    themes = themes[:3]
    selected_themes = {row["name"] for row in themes}
    for row in rows:
        if row.get("level") == "确认主线" and _theme_for_sector(str(row.get("name") or "")) not in selected_themes:
            row["level"] = "轮动候选"
            row["stage"] = "轮动观察"
            row["judgement"] = "不进入明日主计划"
            row["invalidation"] = "只有强度超过当前主攻线，且广度、资金和龙头承接继续改善，才能升级。"
    confirmed = [row["name"] for row in themes]
    weak_market = [row.get("name") for row in (market.get("sectors") or {}).get("top_down") or [] if row.get("name")]
    return {
        "rows": rows,
        "rotation_summary": (
            f"资金和市场广度共同确认的主攻方向是{'、'.join(confirmed[:4]) or '暂无'}；"
            f"价格与内部广度同步走弱的方向是{'、'.join(weak_market[:4]) or '暂无'}。"
            "这里只描述价格、资金和扩散结果，不把新闻标题直接当成上涨原因。"
        ),
        "themes": themes,
    }


def _tomorrow_plan(verdict: dict, metrics: dict, history: dict, mainlines: list[dict], mainline_analysis: dict) -> dict:
    confirmed = _confirmed_themes(mainline_analysis)
    weak = [row["name"] for row in mainlines if row.get("state") in {"资金撤退", "弱势退潮", "假突破"}]
    median_breadth = _f((history.get("medians") or {}).get("up_ratio"), 50)
    cap = int(_f(verdict.get("position_cap"), 20))
    upgrade_cap = min(80, cap + 20)
    focus_text = "、".join(confirmed[:4]) or "没有通过验证的进攻方向"
    return {
        "default_action": verdict["stance"],
        "position_cap": cap,
        "focus": confirmed[:4],
        "avoid": weak[:4],
        "base_case": f"明日默认按{verdict['stance']}模式执行，总仓位不超过{cap}%，主看{focus_text}。",
        "rationale": (
            f"当前市场定性为{verdict.get('regime')}。仓位上限由量价关系、真实赚钱效应、"
            "短线失败代价和主线持续性共同决定，不会因一根指数阳线或单只高开临时改变。"
        ),
        "allowed": f"只允许参与{focus_text}中的龙头分歧承接和前排二次确认。",
        "forbidden": "禁止追孤立高开、后排补涨、板块广度不足以及放量滞涨的股票。",
        "execution": "竞价只看方向，不直接下结论；开盘后等板块广度、龙头承接和成交同时确认再执行。",
        "upgrade_condition": (
            f"只有全市场上涨占比回到{max(55, round(median_breadth))}%以上、跌停/涨停比降至0.5以下、"
            f"炸板率降到25%以下，并且主线广度继续扩散，才将仓位上限提高到{upgrade_cap}%。"
        ),
        "downgrade_condition": (
            "若指数上涨但等权表现转负、成交放大但收盘远离日内高点，或确认主线的广度、资金和龙头承接同时转弱，"
            "仓位直接压回20%，停止新开仓。"
        ),
    }


def build_postmarket_intelligence(trade_date: str, market: dict) -> dict:
    metrics = _market_metrics(market)
    history = _history_context(trade_date, metrics)
    path, snapshots = _intraday_path(trade_date)
    mainlines = _mainlines(snapshots)
    mainline_analysis = _mainline_analysis(mainlines, market)
    try:
        from services.decision_learning_service import get_effective_weights
        risk_weights, learning_version = get_effective_weights()
    except Exception:
        risk_weights, learning_version = None, {"version": "L0", "sample_count": 0}
    verdict = _regime(metrics, path, risk_weights)
    undercurrents = _undercurrents(metrics, history, path, mainlines)
    core_judgements = _core_judgements(metrics, history, path, mainlines, mainline_analysis)
    final_conclusion = _final_conclusion(verdict, core_judgements, mainline_analysis)
    try:
        from services.market_radar_service import evaluate_radar_day
        audit = evaluate_radar_day(trade_date)
    except Exception as exc:
        audit = {"ready": False, "verdict": f"判断审计暂不可用：{exc}"}
    return {
        "generated_at": datetime.now().isoformat(),
        "engine": ENGINE_VERSION,
        "data_scope": "收盘全市场 + 历史日档案 + 盘中市场雷达",
        "learning_basis": {
            "version": learning_version.get("version", "L0"),
            "sample_count": learning_version.get("sample_count", 0),
            "risk_weights": risk_weights or {},
        },
        "metrics": metrics,
        "verdict": verdict,
        "final_conclusion": final_conclusion,
        "core_judgements": core_judgements,
        "historical_context": history,
        "intraday_path": path,
        "undercurrents": undercurrents,
        "mainlines": mainlines,
        "mainline_analysis": mainline_analysis,
        "audit": audit,
        "tomorrow_plan": _tomorrow_plan(verdict, metrics, history, mainlines, mainline_analysis),
        "data_notes": [
            "历史分位仅基于本软件已保存交易日，不代表全市场长期分布。",
            "板块净流入为数据商成交口径推算，只能与广度、价格、龙头和时间序列共同使用。",
            "缺少盘中快照时不补写盘中路径。",
        ],
    }
