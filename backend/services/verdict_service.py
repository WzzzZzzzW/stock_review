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


def _f(v, default=None):
    try:
        x = float(v)
        if x != x:  # NaN
            return default
        return x
    except Exception:
        return default


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
