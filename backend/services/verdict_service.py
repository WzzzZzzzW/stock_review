"""
个股复盘「速览/结论」纯算法服务（不依赖 AI，毫秒级返回）

目标：把分散在各卡片里的原始数据，浓缩成一张「一眼看完」的复盘速览：
  · 当前位置（均线/RSI/距区间高低点）
  · 支撑位 / 压力位（基于近端摆动高低 + 均线）
  · 多空要点（综合财务评分 + 技术信号 + 估值 + 相对强弱 + 龙虎榜）
  · 相对大盘强弱（个股 vs 上证综指 归一化曲线 + 超额收益）
  · 一句话多空判断（stance）

所有结论均来自已采集的客观数据，AI 报告在此基础上做深度归因，不再重复堆砌。
"""
from __future__ import annotations

import re
from typing import Any


def _f(v, default=None):
    try:
        x = float(v)
        if x != x:  # NaN
            return default
        return x
    except Exception:
        return default


def _dim(key: str, label: str, score: float, evidence: str, weight: float) -> dict:
    return {
        "key": key,
        "label": label,
        "score": round(max(0, min(100, score))),
        "evidence": evidence,
        "weight": weight,
    }


def _aggregate_dimensions(dimensions: list[dict], total_weight: float) -> tuple[int, int]:
    """按证据覆盖率收缩分数，避免单一涨跌信号制造极端结论。"""
    if not dimensions:
        return 50, 0
    used = sum(d["weight"] for d in dimensions)
    raw = sum(d["score"] * d["weight"] for d in dimensions) / used
    coverage = min(1.0, used / total_weight)
    adjusted = 50 + (raw - 50) * coverage
    return round(max(0, min(100, adjusted))), round(coverage * 100)


def _money_yi(value: Any) -> float | None:
    """把 1.2亿 / 3500万 / 数字等资金字段统一换算为亿元。"""
    if value in (None, "", "--"):
        return None
    text = str(value).replace(",", "").strip()
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    number = _f(match.group(), 0.0)
    if "万" in text and "亿" not in text:
        return number / 10000
    if "元" in text and "亿" not in text:
        return number / 100000000
    return number


def compute_quick_decision(
    quote: dict,
    tech: dict | None = None,
    context: dict | None = None,
    purpose: str = "watchlist",
) -> dict:
    """统一的快速个股裁决：涨跌幅是证据之一，不能单独决定动作。"""
    tech = tech or quote.get("tech") or {}
    context = context or {}
    technical = tech.get("technical") or {}
    trend = tech.get("trend") or {}
    today = tech.get("today") or {}

    price = _f(quote.get("price"), _f(today.get("close"), 0.0)) or 0.0
    pct = _f(quote.get("pct_change"), _f(today.get("pct_change"), 0.0)) or 0.0
    vol_ratio = _f(technical.get("vol_ratio"))
    ma5_gap = _f(technical.get("ma5_pct"))
    ma20_gap = _f(technical.get("ma20_pct"))
    ma60_gap = _f(technical.get("ma60_pct"))
    rsi = _f(technical.get("rsi14"))
    macd = str(technical.get("macd_status") or "")
    streak = int(_f(trend.get("streak"), 0) or 0)
    dimensions: list[dict] = []
    gaps: list[str] = []

    # 1. 趋势：均线层级和位置
    ma_values = [ma5_gap, ma20_gap, ma60_gap]
    known_ma = [x for x in ma_values if x is not None]
    if known_ma:
        above = sum(1 for x in known_ma if x > 0)
        trend_score = 26 + above / len(known_ma) * 48
        if ma5_gap is not None and ma20_gap is not None:
            trend_score += 10 if ma5_gap >= ma20_gap else -8
        evidence = f"站上 {above}/{len(known_ma)} 条关键均线"
        if ma20_gap is not None:
            evidence += f"，距MA20 {ma20_gap:+.1f}%"
        dimensions.append(_dim("trend", "趋势结构", trend_score, evidence, 18))
    else:
        gaps.append("均线趋势")

    # 2. 量价：同样的涨跌，在放量/缩量下含义相反
    if vol_ratio is not None:
        if pct > 0.3 and vol_ratio >= 1.2:
            score, meaning = min(88, 62 + (vol_ratio - 1.2) * 18), "上涨有增量资金确认"
        elif pct < -0.3 and vol_ratio >= 1.2:
            score, meaning = max(12, 38 - (vol_ratio - 1.2) * 16), "放量下跌，抛压真实"
        elif pct > 0.3 and vol_ratio < 0.8:
            score, meaning = 44, "缩量上涨，持续性不足"
        elif pct < -0.3 and vol_ratio < 0.8:
            score, meaning = 55, "缩量回撤，抛压尚未扩散"
        else:
            score, meaning = 50, "量价暂未形成方向共振"
        dimensions.append(_dim("volume_price", "量价关系", score, f"量比 {vol_ratio:.2f}，{meaning}", 16))
    else:
        gaps.append("量比")

    # 3. 动能：MACD + RSI + 连续性
    if macd or rsi is not None or streak:
        momentum = 50
        notes: list[str] = []
        if macd in ("金叉", "多头"):
            momentum += 16
            notes.append(f"MACD{macd}")
        elif macd in ("死叉", "空头"):
            momentum -= 16
            notes.append(f"MACD{macd}")
        if rsi is not None:
            notes.append(f"RSI {rsi:.0f}")
            if rsi >= 78:
                momentum -= 14
            elif 52 <= rsi <= 68:
                momentum += 8
            elif rsi <= 28:
                momentum -= 4  # 超卖不是买入理由，仍需趋势确认
        if streak >= 5:
            momentum -= 8
            notes.append(f"连涨{streak}日，拥挤")
        elif streak <= -4:
            momentum -= 10
            notes.append(f"连跌{abs(streak)}日")
        dimensions.append(_dim("momentum", "动能质量", momentum, "，".join(notes), 13))
    else:
        gaps.append("动能指标")

    # 4. 日内结构：开盘、最高、最低和当前位置
    open_p = _f(quote.get("open"), _f(today.get("open")))
    high = _f(quote.get("high"), _f(today.get("high")))
    low = _f(quote.get("low"), _f(today.get("low")))
    prev_close = _f(quote.get("prev_close"))
    if price and high and low and high > low:
        close_pos = (price - low) / (high - low)
        intraday = 25 + close_pos * 50
        notes = [f"位于日内区间 {close_pos * 100:.0f}% 位置"]
        if open_p:
            if price > open_p and pct < 0:
                intraday += 10
                notes.append("低开后修复")
            elif price < open_p and pct > 0:
                intraday -= 12
                notes.append("冲高回落至开盘价下")
        if open_p and prev_close:
            gap = (open_p / prev_close - 1) * 100
            if abs(gap) >= 2:
                notes.append(f"开盘缺口 {gap:+.1f}%")
        dimensions.append(_dim("intraday", "日内承接", intraday, "，".join(notes), 11))
    else:
        gaps.append("日内高低开")

    # 5. 相对市场强弱
    market_pct = _f(context.get("market_pct"))
    if market_pct is not None:
        excess = pct - market_pct
        relative_score = 50 + max(-30, min(30, excess * 8))
        dimensions.append(_dim("relative", "相对强弱", relative_score, f"相对市场超额 {excess:+.2f}%", 10))
    else:
        gaps.append("市场基准")

    # 6. 板块共振
    sector_decision = context.get("sector_decision") or {}
    sector_score = _f(sector_decision.get("score"))
    if sector_score is not None:
        dimensions.append(_dim(
            "sector", "板块共振", sector_score,
            f"{context.get('sector') or '所属板块'}：{sector_decision.get('action') or '中性'}，{sector_decision.get('summary') or '无补充证据'}",
            10,
        ))
    else:
        gaps.append("板块共振")

    # 7. 事件催化
    strength = str(context.get("catalyst_strength") or "")
    catalyst = str(context.get("catalyst") or "")
    if strength or catalyst:
        cat_score = {"强": 82, "中": 64, "弱": 46}.get(strength, 55)
        dimensions.append(_dim("catalyst", "事件催化", cat_score, catalyst or f"催化强度：{strength}", 9))
    else:
        gaps.append("事件催化")

    # 8. 可验证资金
    lhb = _f(context.get("lhb_amt"))
    north = _f(context.get("north_signal"))
    if lhb is not None or north is not None:
        capital = 50
        notes = []
        if lhb is not None:
            capital += max(-22, min(22, lhb * 5))
            notes.append(f"龙虎榜净额 {lhb:+.2f}亿")
        if north is not None:
            capital += max(-12, min(12, north * 12))
            notes.append(f"外资信号 {north:+.2f}")
        dimensions.append(_dim("capital", "资金验证", capital, "，".join(notes), 7))
    else:
        gaps.append("资金流")

    # 9. 交易风险：过热、乖离和下行结构都扣分
    if ma20_gap is not None or rsi is not None or technical.get("bb_pct") is not None:
        risk = 70
        notes = []
        if ma20_gap is not None:
            if ma20_gap >= 15:
                risk -= 28
                notes.append(f"距MA20 {ma20_gap:+.1f}%，追高风险高")
            elif ma20_gap <= -8:
                risk -= 24
                notes.append(f"低于MA20 {abs(ma20_gap):.1f}%，趋势破坏")
            else:
                notes.append(f"MA20乖离 {ma20_gap:+.1f}%")
        if rsi is not None and rsi >= 78:
            risk -= 18
            notes.append("RSI过热")
        bb_pct = _f(technical.get("bb_pct"))
        if bb_pct is not None and bb_pct >= 1:
            risk -= 10
            notes.append("突破布林上轨，波动扩张")
        dimensions.append(_dim("risk", "风险收益", risk, "，".join(notes) or "风险处于常态", 6))
    else:
        gaps.append("风险指标")

    score, coverage = _aggregate_dimensions(dimensions, 100)
    confidence = "高" if coverage >= 72 else "中" if coverage >= 48 else "低"
    positives = sorted((d for d in dimensions if d["score"] >= 58), key=lambda d: d["score"], reverse=True)
    negatives = sorted((d for d in dimensions if d["score"] <= 42), key=lambda d: d["score"])

    hard_stop = _f(context.get("stop_loss"))
    target = _f(context.get("target_price"))
    hard_action = None
    if purpose == "position" and price and hard_stop and price <= hard_stop:
        hard_action = "立即减仓"
    elif purpose == "position" and price and target and price >= target:
        hard_action = "兑现利润"

    if purpose == "position":
        action = hard_action or ("持有并允许回踩加仓" if score >= 72 else "继续持有" if score >= 58 else "收紧仓位" if score >= 45 else "减仓")
    elif purpose in ("candidate", "recommend"):
        action = "计划进攻" if score >= 70 and coverage >= 48 else "等待触发" if score >= 52 else "放弃"
    else:
        action = "重点进攻" if score >= 72 and coverage >= 55 else "保留但不追" if score >= 62 else "保留" if score >= 52 else "降级" if score >= 43 else "剔除"

    best = positives[0]["evidence"] if positives else "尚无足够强证据"
    worst = negatives[0]["evidence"] if negatives else "未发现决定性破坏"
    summary = f"{best}；{worst}。"
    if score >= 62:
        trigger = "回踩关键均线不破且量能不低于近20日均量时执行；放量跌破MA20则取消。"
    elif score >= 48:
        trigger = "只有放量站回MA20、相对板块转强后才升级，不满足就不交易。"
    else:
        trigger = "当前不入场；必须先收复MA20并出现量价共振，才重新进入候选。"

    return {
        "score": score,
        "action": action,
        "rank": 100 - score,
        "summary": summary,
        "trigger": trigger,
        "confidence": confidence,
        "coverage": coverage,
        "dimensions_used": len(dimensions),
        "dimensions": dimensions,
        "evidence": {
            "positive": [d["evidence"] for d in positives[:3]],
            "negative": [d["evidence"] for d in negatives[:3]],
        },
        "data_gaps": gaps,
    }


def compute_sector_decision(row: dict) -> dict:
    """板块裁决：涨幅、广度、资金和龙头共同决定是否可称为主线。"""
    dimensions: list[dict] = []
    pct = _f(row.get("pct_num"), _f(row.get("pct")))
    if pct is not None:
        dimensions.append(_dim("momentum", "板块动量", 50 + max(-38, min(38, pct * 10)), f"板块涨跌 {pct:+.2f}%", 25))
    up = _f(row.get("up_count"))
    down = _f(row.get("down_count"))
    if up is not None and down is not None and up + down > 0:
        ratio = up / (up + down)
        dimensions.append(_dim("breadth", "上涨广度", 15 + ratio * 70, f"上涨 {int(up)} / 下跌 {int(down)}，扩散率 {ratio * 100:.0f}%", 35))
    net = _money_yi(row.get("net_in"))
    if net is not None:
        dimensions.append(_dim("capital", "资金净流", 50 + max(-35, min(35, net * 7)), f"板块净流入 {net:+.2f}亿", 25))
    leader = str(row.get("leader") or "").strip()
    if leader and leader != "--":
        dimensions.append(_dim("leadership", "龙头辨识", 64, f"领涨股 {leader}，存在带队标的", 15))

    score, coverage = _aggregate_dimensions(dimensions, 100)
    if score >= 68 and coverage >= 60:
        action = "主线候选"
    elif score >= 56:
        action = "轮动观察"
    elif score >= 45:
        action = "中性降级"
    else:
        action = "弱势回避"
    best = max(dimensions, key=lambda d: d["score"], default=None)
    worst = min(dimensions, key=lambda d: d["score"], default=None)
    if coverage < 60:
        summary = "涨跌表现可见，但广度或资金证据不足，不能认定为主线。"
    elif worst and worst["score"] <= 40:
        summary = f"{best['evidence']}，但{worst['evidence']}，板块一致性不足。"
    else:
        summary = f"{best['evidence']}，多维证据方向一致。" if best else "暂无有效证据。"
    return {
        "score": score,
        "action": action,
        "summary": summary,
        "coverage": coverage,
        "confidence": "高" if coverage >= 75 else "中" if coverage >= 50 else "低",
        "dimensions": dimensions,
    }


def compute_market_decision(indices: list[dict], sectors: dict | None = None) -> dict:
    """市场仓位裁决：指数方向、内部一致性、日内承接和板块广度共同投票。"""
    sectors = sectors or {}
    dimensions: list[dict] = []
    valid = [i for i in indices if _f(i.get("pct")) is not None]
    if valid:
        pcts = [_f(i.get("pct"), 0.0) for i in valid]
        avg = sum(pcts) / len(pcts)
        dimensions.append(_dim("index", "指数方向", 50 + max(-35, min(35, avg * 13)), f"核心指数平均 {avg:+.2f}%", 30))
        dispersion = max(pcts) - min(pcts)
        dimensions.append(_dim(
            "consistency", "指数一致性", max(20, 80 - dispersion * 27),
            f"指数{'相对同向' if dispersion <= 0.8 else '分化明显'}，差值 {dispersion:.2f}个百分点", 18,
        ))
        positions = []
        for item in valid:
            high, low, price = _f(item.get("high")), _f(item.get("low")), _f(item.get("price"))
            if high is not None and low is not None and price is not None and high > low:
                positions.append((price - low) / (high - low))
        if positions:
            pos = sum(positions) / len(positions)
            dimensions.append(_dim("intraday", "日内承接", 20 + pos * 65, f"指数平均收于日内区间 {pos * 100:.0f}% 位置", 22))

    up = _f(sectors.get("up_count"))
    down = _f(sectors.get("down_count"))
    total = _f(sectors.get("total"))
    if up is not None and (total or (up + (down or 0))):
        denominator = total or up + (down or 0)
        ratio = up / denominator if denominator else 0.5
        dimensions.append(_dim("breadth", "板块广度", 15 + ratio * 70, f"上涨板块占比 {ratio * 100:.0f}%", 30))

    score, coverage = _aggregate_dimensions(dimensions, 100)
    if score >= 68:
        posture, cap = "主动进攻", 80
    elif score >= 57:
        posture, cap = "选择性进攻", 60
    elif score >= 46:
        posture, cap = "防守等待", 40
    else:
        posture, cap = "主动收缩", 20
    positives = [d["evidence"] for d in dimensions if d["score"] >= 58]
    negatives = [d["evidence"] for d in dimensions if d["score"] <= 42]
    return {
        "score": score,
        "action": posture,
        "position_cap": cap,
        "coverage": coverage,
        "summary": f"{posture}，总仓位上限 {cap}%。" + (f" 核心依据：{positives[0]}。" if positives else " 暂无足够进攻证据。"),
        "evidence": {"positive": positives[:3], "negative": negatives[:3]},
        "dimensions": dimensions,
    }


# ─────────────────────────────────────────────────────────────────────
# 相对大盘强弱
# ─────────────────────────────────────────────────────────────────────

def compute_relative(ohlcv: list[dict], index_series: list[dict],
                     index_name: str = "上证综指") -> dict:
    """
    个股 vs 大盘相对强弱。
    ohlcv:        [{date, close, ...}]  个股区间日K
    index_series: [{date, close}]       指数同区间日K（已按区间裁剪）
    返回归一化到 100 的双线序列 + 区间收益 + 超额收益。
    """
    if not ohlcv or not index_series:
        return {}

    idx_map = {str(r.get("date"))[:10]: _f(r.get("close")) for r in index_series}
    pts = []
    base_stock = _f(ohlcv[0].get("close"))
    # 用「与个股区间起点最接近的指数收盘」作为指数基准
    base_index = None
    for bar in ohlcv:
        d = str(bar.get("date"))[:10]
        ic = idx_map.get(d)
        if ic is None:
            continue
        if base_index is None:
            base_index = ic
            base_stock = _f(bar.get("close")) or base_stock
        sc = _f(bar.get("close"))
        if sc is None or base_stock in (None, 0) or base_index in (None, 0):
            continue
        pts.append({
            "date": d,
            "stock": round(sc / base_stock * 100, 2),
            "index": round(ic / base_index * 100, 2),
        })

    if len(pts) < 2:
        return {}

    stock_ret = round(pts[-1]["stock"] - 100, 2)
    index_ret = round(pts[-1]["index"] - 100, 2)
    excess = round(stock_ret - index_ret, 2)
    return {
        "index_name": index_name,
        "stock_ret": stock_ret,
        "index_ret": index_ret,
        "excess": excess,
        "outperform": excess > 0,
        "series": pts,
    }


# ─────────────────────────────────────────────────────────────────────
# 支撑 / 压力位
# ─────────────────────────────────────────────────────────────────────

def _swing_levels(ohlcv: list[dict], close: float):
    """基于近 60 根 K 的摆动高低点 + 均线，给出最近的支撑/压力。"""
    window = ohlcv[-60:] if len(ohlcv) > 60 else ohlcv
    highs = [_f(b.get("high")) for b in window if _f(b.get("high")) is not None]
    lows  = [_f(b.get("low"))  for b in window if _f(b.get("low"))  is not None]

    # 摆动高/低：局部极值（前后各 2 根）
    swing_hi, swing_lo = [], []
    hs = [_f(b.get("high")) for b in window]
    ls = [_f(b.get("low"))  for b in window]
    for i in range(2, len(window) - 2):
        h = hs[i]
        l = ls[i]
        if h is not None and h == max(x for x in hs[i-2:i+3] if x is not None):
            swing_hi.append(h)
        if l is not None and l == min(x for x in ls[i-2:i+3] if x is not None):
            swing_lo.append(l)

    last = ohlcv[-1]
    ma20 = _f(last.get("ma20"))
    ma60 = _f(last.get("ma60"))

    # 压力：高于现价的最近摆动高 / 区间高
    above = [x for x in swing_hi if x > close * 1.005]
    resistance = min(above) if above else (max(highs) if highs else close)
    # 支撑：低于现价的最近摆动低 + 均线（取最近的那个）
    below = [x for x in swing_lo if x < close * 0.995]
    for ma in (ma20, ma60):
        if ma is not None and ma < close * 0.995:
            below.append(ma)
    support = max(below) if below else (min(lows) if lows else close)

    return round(support, 2), round(resistance, 2)


# ─────────────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────────────

def compute_verdict(stock_data: dict, financial_score: dict,
                    relative: dict | None = None,
                    valuation: dict | None = None) -> dict:
    """
    生成复盘速览。纯算法、毫秒级。
    """
    price   = stock_data.get("price", {})
    summary = price.get("summary", {})
    ohlcv   = price.get("ohlcv", [])
    lhb     = stock_data.get("lhb", [])

    if not ohlcv:
        return {}

    last = ohlcv[-1]
    close = _f(last.get("close")) or _f(summary.get("end_price"))
    if close is None:
        return {}

    ma5  = _f(last.get("ma5"))
    ma20 = _f(last.get("ma20"))
    ma60 = _f(last.get("ma60"))
    rsi  = _f(summary.get("latest_rsi"))
    macd = _f(summary.get("latest_macd"))
    macd_s = _f(summary.get("latest_macd_s"))
    total_return = _f(summary.get("total_return"), 0)
    max_price = _f(summary.get("max_price"))
    min_price = _f(summary.get("min_price"))

    grade = financial_score.get("grade", "C")
    bull_points: list[str] = []
    bear_points: list[str] = []
    tags: list[str] = []

    # ── 趋势判定（均线多空排列）────────────────────────────
    if ma5 and ma20 and ma60:
        if ma5 > ma20 > ma60:
            trend = "上行"
            tags.append("均线多头排列")
            bull_points.append("均线多头排列（MA5>MA20>MA60），趋势向上")
        elif ma5 < ma20 < ma60:
            trend = "下行"
            tags.append("均线空头排列")
            bear_points.append("均线空头排列（MA5<MA20<MA60），趋势向下")
        else:
            trend = "震荡"
            tags.append("均线缠绕震荡")
    else:
        trend = "震荡"

    # ── 价格 vs 均线 ────────────────────────────────────────
    vs_ma = []
    if ma20:
        if close >= ma20:
            vs_ma.append("站上MA20")
        else:
            vs_ma.append("跌破MA20")
            bear_points.append(f"收盘价跌破 MA20（{ma20:.2f}），短期走弱")
    if ma60:
        if close >= ma60:
            vs_ma.append("站上MA60")
            if trend != "下行":
                bull_points.append(f"站稳 MA60（{ma60:.2f}）上方，中期结构健康")
        else:
            vs_ma.append("跌破MA60")
            bear_points.append(f"位于 MA60（{ma60:.2f}）下方，中期偏弱")

    # ── RSI 区间 ────────────────────────────────────────────
    if rsi is not None:
        if rsi >= 75:
            rsi_zone = "超买"
            tags.append("RSI超买")
            bear_points.append(f"RSI={rsi:.0f} 进入超买区，警惕短线回调")
        elif rsi <= 28:
            rsi_zone = "超卖"
            tags.append("RSI超卖")
            bull_points.append(f"RSI={rsi:.0f} 处超卖区，存在技术反弹诉求")
        else:
            rsi_zone = "中性"
    else:
        rsi_zone = "--"

    # ── MACD ────────────────────────────────────────────────
    if macd is not None and macd_s is not None:
        if macd > macd_s:
            tags.append("MACD金叉")
            if trend != "下行":
                bull_points.append("MACD 位于信号线上方（多头动能）")
        else:
            tags.append("MACD死叉")
            bear_points.append("MACD 位于信号线下方（空头动能）")

    # ── 距区间高低点 ────────────────────────────────────────
    from_high_pct = round((close / max_price - 1) * 100, 1) if max_price else None
    from_low_pct  = round((close / min_price - 1) * 100, 1) if min_price else None
    if from_high_pct is not None and from_high_pct <= -20:
        bull_points.append(f"较区间高点回落 {abs(from_high_pct):.0f}%，估值/情绪已有释放")
    if from_low_pct is not None and from_low_pct >= 40:
        bear_points.append(f"已较区间低点反弹 {from_low_pct:.0f}%，追高需谨慎")

    # ── 财务评分要点（复用，不重复堆叠太多）────────────────
    for p in (financial_score.get("positives") or [])[:2]:
        bull_points.append(p)
    for fl in (financial_score.get("flags") or [])[:3]:
        bear_points.append(fl)

    # ── 估值分位 ────────────────────────────────────────────
    if valuation:
        pe_pct = valuation.get("pe_pct")
        pb_pct = valuation.get("pb_pct")
        if pe_pct is not None:
            if pe_pct <= 25:
                bull_points.append(f"PE 处近年 {pe_pct:.0f}% 分位，估值偏低")
                tags.append("估值偏低")
            elif pe_pct >= 80:
                bear_points.append(f"PE 处近年 {pe_pct:.0f}% 分位，估值偏贵")
                tags.append("估值偏贵")

    # ── 相对大盘 ────────────────────────────────────────────
    if relative:
        ex = relative.get("excess")
        if ex is not None:
            if ex >= 3:
                bull_points.append(f"区间跑赢{relative.get('index_name','大盘')} {ex:.1f}%，强于市场")
                tags.append("强于大盘")
            elif ex <= -3:
                bear_points.append(f"区间跑输{relative.get('index_name','大盘')} {abs(ex):.1f}%，弱于市场")
                tags.append("弱于大盘")

    # ── 龙虎榜 ──────────────────────────────────────────────
    if lhb:
        net = sum(_f(r.get("net_buy"), 0) or 0 for r in lhb)
        if net > 0:
            bull_points.append(f"区间内 {len(lhb)} 次登榜，游资/机构合计净买入 {net:.2f} 亿")
        elif net < 0:
            bear_points.append(f"区间内 {len(lhb)} 次登榜，大户合计净卖出 {abs(net):.2f} 亿（出货特征）")

    support, resistance = _swing_levels(ohlcv, close)

    # ── 一句话判断（stance）────────────────────────────────
    stance = _make_stance(trend, grade, rsi_zone, total_return, relative, valuation,
                          len(bull_points), len(bear_points))

    # ── 多空力量对比（0-100，>50 偏多）──────────────────────
    nb, nr = len(bull_points), len(bear_points)
    bull_ratio = round(nb / (nb + nr) * 100) if (nb + nr) else 50

    return {
        "stance": stance,
        "grade": grade,
        "score": financial_score.get("score"),
        "trend": trend,
        "tags": tags[:6],
        "bull_ratio": bull_ratio,
        "position": {
            "close": round(close, 2),
            "vs_ma": " · ".join(vs_ma) if vs_ma else "--",
            "rsi": round(rsi, 1) if rsi is not None else None,
            "rsi_zone": rsi_zone,
            "from_high_pct": from_high_pct,
            "from_low_pct": from_low_pct,
        },
        "support": support,
        "resistance": resistance,
        "bull_points": bull_points[:6],
        "bear_points": bear_points[:6],
        "relative": relative or {},
        "valuation": valuation or {},
    }


def _make_stance(trend, grade, rsi_zone, total_return, relative, valuation,
                 n_bull, n_bear) -> str:
    """合成一句话多空判断。"""
    parts = []

    # 趋势
    parts.append({"上行": "短期趋势向上", "下行": "短期趋势向下", "震荡": "短期方向不明"}[trend])

    # 相对强弱
    if relative and relative.get("excess") is not None:
        ex = relative["excess"]
        if ex >= 3:
            parts.append("强于大盘")
        elif ex <= -3:
            parts.append("弱于大盘")

    # 估值
    if valuation and valuation.get("pe_pct") is not None:
        pe_pct = valuation["pe_pct"]
        if pe_pct <= 25:
            parts.append("估值偏低")
        elif pe_pct >= 80:
            parts.append("估值偏贵")

    # 超买超卖
    if rsi_zone == "超买":
        parts.append("注意获利回吐")
    elif rsi_zone == "超卖":
        parts.append("超卖或有反弹")

    # 财务底色
    if grade in ("D", "F"):
        parts.append(f"但财务评级{grade}级，基本面差，仅适合博弈不宜价投")
    elif grade == "A":
        parts.append("基本面扎实")

    return "，".join(parts) + "。"
