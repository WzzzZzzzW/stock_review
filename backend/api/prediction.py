"""
盘前预测 & 复盘对比 & 持续学习
─────────────────────────────────────────────────────────────────────────────
GET  /api/prediction/latest       取最新预测（不存在则生成）
POST /api/prediction/generate     强制重新生成今日预测
POST /api/prediction/record       记录今日实际并计算与预测的差异
GET  /api/prediction/compare      取最近一次预测 vs 实际对比
GET  /api/prediction/history      历史准确率曲线（最近 30 日）
─────────────────────────────────────────────────────────────────────────────
存储：backend/data/predictions.json
学习：每次 record 后更新各因子权重，影响下一次预测的置信度
"""
import json
import math
import time
import requests
from datetime import datetime, date, timedelta
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/prediction", tags=["预测"])

# ── 存储路径 ──────────────────────────────────────────────────────────────────
_STORE_PATH = Path(__file__).parent.parent / "data" / "predictions.json"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "http://finance.sina.com.cn/",
}

# ── 分离的市场/个股因子权重（持续学习后会更新） ──────────────────────────────
_DEFAULT_MARKET_WEIGHTS = {
    "market_breadth":  0.18,   # 全市场涨跌比
    "index_momentum":  0.15,   # 大盘指数动量
    "sector_momentum": 0.10,   # 热门板块趋势
    "north_flow":      0.22,   # 北向资金净流入
    "global_markets":  0.25,   # 隔夜外盘
    "limit_ratio":     0.10,   # 涨停/跌停家数比
}

_DEFAULT_STOCK_WEIGHTS = {
    "price_momentum": 0.15,   # 个股近期动量
    "ma_signal":      0.22,   # 均线多空排列
    "rsi_signal":     0.12,   # RSI超买超卖
    "bb_signal":      0.08,   # 布林带位置
    "beta_signal":    0.08,   # Beta放大效应
    "lhb_signal":     0.10,   # 龙虎榜信号
    "sector_rec":     0.08,   # 板块推荐逻辑
    "market_regime":  0.12,   # 整体市场方向因子
    "news_signal":    0.05,   # 重大公告信号
}


# ── 持久化辅助 ────────────────────────────────────────────────────────────────

def _load_store() -> dict:
    default = {
        "predictions": {},
        "actuals":     {},
        "accuracy":    [],
        "weights": {
            "market": _DEFAULT_MARKET_WEIGHTS.copy(),
            "stock":  _DEFAULT_STOCK_WEIGHTS.copy(),
        },
    }
    if _STORE_PATH.exists():
        try:
            store = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
            # ── 迁移旧版扁平 weights 到新版嵌套结构 ──────────────────────────
            w = store.get("weights", {})
            if "market" not in w or "stock" not in w:
                store["weights"] = {
                    "market": _DEFAULT_MARKET_WEIGHTS.copy(),
                    "stock":  _DEFAULT_STOCK_WEIGHTS.copy(),
                }
            return store
        except Exception:
            pass
    return default


def _save_store(store: dict):
    _STORE_PATH.write_text(
        json.dumps(store, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def _safe(v, default=0.0) -> float:
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return default


# ── 数据采集 ──────────────────────────────────────────────────────────────────

def _fetch_market_breadth() -> dict:
    """从新浪市场中心获取全市场涨跌家数、涨跌停数"""
    url = (
        "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "Market_Center.getHQNodeDataSimple?num=5000&page=1&sort=changepercent"
        "&asc=0&node=hs_a&symbol=&_s_r_a=page"
    )
    try:
        resp = requests.get(url, timeout=15, headers=_HEADERS)
        data = json.loads(resp.text)
        up_count  = sum(1 for s in data if _safe(s.get("changepercent", 0)) > 0)
        dn_count  = sum(1 for s in data if _safe(s.get("changepercent", 0)) < 0)
        total     = len(data)
        limit_up  = sum(1 for s in data if _safe(s.get("changepercent", 0)) >= 9.9)
        limit_dn  = sum(1 for s in data if _safe(s.get("changepercent", 0)) <= -9.9)
        breadth   = (up_count / total) if total else 0.5
        return {
            "up_count": up_count, "dn_count": dn_count,
            "total": total, "limit_up": limit_up, "limit_dn": limit_dn,
            "breadth": round(breadth, 4),
        }
    except Exception:
        return {"up_count": 0, "dn_count": 0, "total": 0,
                "limit_up": 0, "limit_dn": 0, "breadth": 0.5}


def _fetch_indices_pct() -> dict:
    """获取大盘指数涨跌幅"""
    ids = "sh000001,sz399001,sz399006,sh000300"
    url = f"http://hq.sinajs.cn/list={ids}"
    try:
        resp = requests.get(url, timeout=10, headers=_HEADERS)
        resp.encoding = "gbk"
        result = {}
        keys = ["sh", "sz", "cyb", "hs300"]
        lines = [l for l in resp.text.strip().split("\n") if '="' in l and "hq_str_" in l]
        for key, line in zip(keys, lines):
            data_str = line.split('="')[1].rstrip('";')
            parts    = data_str.split(",")
            if len(parts) < 4:
                result[key] = 0.0
                continue
            prev = _safe(parts[2])
            curr = _safe(parts[3])
            result[key] = round((curr - prev) / prev * 100 if prev else 0, 2)
        return result
    except Exception:
        return {"sh": 0.0, "sz": 0.0, "cyb": 0.0, "hs300": 0.0}


def _fetch_stock_quotes(symbols: list[str]) -> dict[str, dict]:
    """批量获取个股行情"""
    if not symbols:
        return {}
    from api.watchlist import _fetch_sina_hq
    return _fetch_sina_hq(symbols)


def _fetch_top_sectors() -> list[float]:
    """取前 10 热门板块平均涨幅"""
    try:
        from api.sector import _cache as sec_cache, _fetch_sina_concepts
        if not sec_cache["data"] or time.time() - sec_cache["ts"] > 120:
            sec_cache["data"] = _fetch_sina_concepts()
            sec_cache["ts"]   = time.time()
        top10 = [c.get("pct_num", 0) for c in sec_cache["data"][:10]]
        return top10
    except Exception:
        return []


def _fetch_lhb_symbols() -> set[str]:
    """近 5 日龙虎榜净买入股票代码"""
    try:
        import akshare as ak
        df = ak.stock_lhb_ggtj_sina(symbol="5")
        syms = set()
        if "净额" in df.columns:
            df = df[df["净额"] > 0]
        for _, r in df.iterrows():
            sym = str(r.get("股票代码", r.get("代码", ""))).strip().zfill(6)
            if len(sym) == 6 and sym != "000000":
                syms.add(sym)
        return syms
    except Exception:
        return set()


def _fetch_global_markets() -> dict:
    """
    获取隔夜外盘行情：S&P500, NASDAQ, 道指, 恒生, 日经
    从新浪 hq API 解析，格式：name,current,?,change_amount,change_pct,open,prev_close,date,time
    """
    ids = "gb_$spx,gb_$compq,gb_$indu,gb_hkhi,gb_n225"
    url = f"http://hq.sinajs.cn/list={ids}"
    result = {
        "sp500": 0.0, "nasdaq": 0.0, "dow": 0.0,
        "hsi": 0.0, "n225": 0.0, "us_avg": 0.0, "signal": 0.0,
    }
    try:
        resp = requests.get(url, timeout=10, headers=_HEADERS)
        resp.encoding = "gbk"
        lines = [l for l in resp.text.strip().split("\n") if '="' in l]
        keys_map = ["sp500", "nasdaq", "dow", "hsi", "n225"]
        for key, line in zip(keys_map, lines):
            data_str = line.split('="')[1].rstrip('";')
            parts = data_str.split(",")
            if len(parts) >= 5:
                pct_str = parts[4].replace("%", "").strip()
                result[key] = _safe(pct_str)
        us_avg = (result["sp500"] + result["nasdaq"]) / 2.0
        result["us_avg"] = round(us_avg, 4)
        # ±3% 映射到 ±1.0
        result["signal"] = round(max(-1.0, min(1.0, us_avg / 3.0)), 4)
    except Exception:
        pass
    return result


def _fetch_north_flow() -> dict:
    """
    北向资金净流入（沪股通+深股通合计），单位：亿元
    尝试 akshare，失败则返回 0
    """
    result = {"net_flow": 0.0, "signal": 0.0, "trend": "数据不可用"}
    try:
        import akshare as ak
        # 沪股通
        df_sh = ak.stock_em_hsgt_north_net_flow_in_em(symbol="沪股通")
        # 深股通
        df_sz = ak.stock_em_hsgt_north_net_flow_in_em(symbol="深股通")

        def _get_today_flow(df) -> float:
            if df is None or df.empty:
                return 0.0
            # 取最新一行，找到净流入列
            row = df.iloc[-1]
            for col in df.columns:
                if "净" in str(col) or "flow" in str(col).lower() or "净流入" in str(col):
                    return _safe(row[col]) / 1e8  # 转亿元（通常单位是元）
            # 若找不到对应列名，取第二列
            if len(df.columns) > 1:
                val = _safe(row.iloc[1])
                # 如果值很大，视为元单位转换
                return val / 1e8 if abs(val) > 1e6 else val
            return 0.0

        sh_flow = _get_today_flow(df_sh)
        sz_flow = _get_today_flow(df_sz)
        net = round(sh_flow + sz_flow, 2)
        result["net_flow"] = net

        if net > 50:
            sig, trend = 1.0, "外资大举买入A股，强力看多信号"
        elif net > 20:
            sig, trend = 0.6, "北向资金净流入，外资积极布局"
        elif net > 0:
            sig, trend = 0.2, "北向小幅净流入，外资温和做多"
        elif net > -20:
            sig, trend = -0.3, "北向小幅净流出，外资谨慎观望"
        else:
            sig, trend = -0.8, "北向资金大幅净流出，外资撤离A股"

        result["signal"] = sig
        result["trend"] = trend
    except Exception:
        pass
    return result


def _fetch_technical_batch(symbols: list[str]) -> dict[str, dict]:
    """
    开一个 baostock session，批量获取所有股票的 90 天 OHLCV 数据
    同时获取 sh.000001 用于 Beta 计算
    返回 {symbol: {ma5, ma20, ma60, rsi, bb_upper, bb_mid, bb_lower, close, beta,
                    ma_score, rsi_score, bb_score, beta_score}}
    """
    if not symbols:
        return {}

    try:
        from data.stock_data import _BS_LOCK
        import baostock as bs
        import pandas as pd
        import numpy as np
    except ImportError:
        return {}

    def _bs_code(sym: str) -> str:
        return f"sh.{sym}" if sym.startswith("6") else f"sz.{sym}"

    def _fetch_one(bs_sym: str) -> list[float] | None:
        """返回90天的收盘价列表（最旧→最新）"""
        end_date = date.today().isoformat()
        start_date = (date.today() - timedelta(days=130)).isoformat()
        rs = bs.query_history_k_data_plus(
            bs_sym,
            "date,close,high,low,open,volume",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="3",
        )
        rows = []
        while rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            try:
                rows.append({
                    "close": float(row[1]),
                    "high":  float(row[2]),
                    "low":   float(row[3]),
                })
            except (ValueError, IndexError):
                continue
        return rows if len(rows) >= 20 else None

    def _calc_rsi(closes: list[float], period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        gains, losses = [], []
        for i in range(1, len(closes)):
            d = closes[i] - closes[i - 1]
            gains.append(max(d, 0))
            losses.append(max(-d, 0))
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100 - 100 / (1 + rs), 2)

    def _calc_bb(closes: list[float], period: int = 20, std_mult: float = 2.0):
        if len(closes) < period:
            mid = closes[-1] if closes else 0
            return mid, mid, mid
        window = closes[-period:]
        mid = sum(window) / period
        variance = sum((x - mid) ** 2 for x in window) / period
        std = variance ** 0.5
        return round(mid + std_mult * std, 4), round(mid, 4), round(mid - std_mult * std, 4)

    results: dict[str, dict] = {}

    with _BS_LOCK:
        lg = bs.login()
        if lg.error_code != "0":
            return {}
        try:
            # 获取上证指数数据用于 Beta 计算
            index_rows = _fetch_one("sh.000001")
            index_closes = [r["close"] for r in index_rows] if index_rows else []

            # 计算市场方向（用于 beta_signal）
            idx_recent_pct = 0.0
            if len(index_closes) >= 5:
                idx_recent_pct = (index_closes[-1] - index_closes[-5]) / index_closes[-5] * 100

            for sym in symbols:
                bs_sym = _bs_code(sym)
                rows = _fetch_one(bs_sym)
                if not rows:
                    results[sym] = {}
                    continue

                closes = [r["close"] for r in rows]
                highs  = [r["high"]  for r in rows]
                lows   = [r["low"]   for r in rows]
                close  = closes[-1]

                # MA
                ma5  = sum(closes[-5:])  / 5  if len(closes) >= 5  else close
                ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else close
                ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else close

                # RSI
                rsi = _calc_rsi(closes)

                # Bollinger Bands
                bb_upper, bb_mid, bb_lower = _calc_bb(closes)

                # Beta（vs 上证，20日日收益率回归）
                beta = 1.0
                if len(index_closes) >= 21 and len(closes) >= 21:
                    stock_rets = [(closes[i] - closes[i-1]) / closes[i-1]
                                  for i in range(max(1, len(closes)-20), len(closes))]
                    idx_rets   = [(index_closes[i] - index_closes[i-1]) / index_closes[i-1]
                                  for i in range(max(1, len(index_closes)-20), len(index_closes))]
                    n = min(len(stock_rets), len(idx_rets))
                    if n >= 5:
                        sr = stock_rets[-n:]
                        ir = idx_rets[-n:]
                        mean_s = sum(sr) / n
                        mean_i = sum(ir) / n
                        cov = sum((sr[j] - mean_s) * (ir[j] - mean_i) for j in range(n)) / n
                        var_i = sum((ir[j] - mean_i) ** 2 for j in range(n)) / n
                        beta = round(cov / var_i, 3) if var_i != 0 else 1.0

                # ── 打分 ──────────────────────────────────────────────────────

                # MA signal
                if close > ma5 > ma20 > ma60:
                    ma_score = 1.0
                elif close > ma20 and ma5 > ma20:
                    ma_score = 0.6
                elif close > ma20:
                    ma_score = 0.3
                elif close < ma20 and ma5 < ma20:
                    ma_score = -0.6
                elif close < ma5 < ma20 < ma60:
                    ma_score = -1.0
                else:
                    ma_score = 0.0

                # RSI signal
                if rsi > 80:
                    rsi_score = -0.8
                elif rsi > 70:
                    rsi_score = -0.4
                elif rsi > 50:
                    rsi_score = 0.4
                elif rsi > 40:
                    rsi_score = 0.1
                elif rsi > 30:
                    rsi_score = -0.2
                elif rsi > 20:
                    rsi_score = 0.3
                else:
                    rsi_score = 0.7

                # BB signal
                if close > bb_upper:
                    bb_score = -0.7
                elif close > bb_mid + (bb_upper - bb_mid) * 0.5:
                    bb_score = 0.3
                elif close > bb_mid - (bb_mid - bb_lower) * 0.2:
                    bb_score = 0.0
                elif close > bb_lower:
                    bb_score = -0.3
                else:
                    bb_score = 0.6

                # Beta signal
                market_up = idx_recent_pct > 0
                if beta > 1.0:
                    beta_score = 0.3 if market_up else -0.3
                else:
                    beta_score = 0.0

                results[sym] = {
                    "close":     round(close, 4),
                    "ma5":       round(ma5,  4),
                    "ma20":      round(ma20, 4),
                    "ma60":      round(ma60, 4),
                    "rsi":       rsi,
                    "bb_upper":  bb_upper,
                    "bb_mid":    bb_mid,
                    "bb_lower":  bb_lower,
                    "beta":      beta,
                    "ma_score":  ma_score,
                    "rsi_score": rsi_score,
                    "bb_score":  bb_score,
                    "beta_score": beta_score,
                }
        finally:
            bs.logout()

    return results


def _fetch_news_signal(symbol: str) -> dict:
    """
    检查近3日重大公告（akshare），失败返回 0
    返回 {signal: float, detail: str}
    """
    result = {"signal": 0.0, "detail": ""}
    try:
        import akshare as ak
        df = ak.stock_notice_report_em(symbol=symbol)
        if df is None or df.empty:
            return result
        today = date.today()
        cutoff = today + timedelta(days=3)
        # 找近3日的公告
        for _, row in df.iterrows():
            title = str(row.get("公告标题", row.get("title", ""))).lower()
            date_str = str(row.get("公告日期", row.get("date", "")))
            try:
                ann_date = date.fromisoformat(date_str[:10])
            except Exception:
                continue
            if ann_date < today - timedelta(days=1) or ann_date > cutoff:
                continue
            # 分类
            if any(k in title for k in ["分红", "派息", "股息", "分配"]):
                result["signal"] = 0.3
                result["detail"] = f"分红派息公告({ann_date})"
                break
            elif any(k in title for k in ["业绩预增", "盈利", "净利润增长", "增长"]):
                result["signal"] = 0.5
                result["detail"] = f"业绩向好公告({ann_date})"
                break
            elif any(k in title for k in ["配股", "增发", "定增", "可转债", "募资"]):
                result["signal"] = -0.3
                result["detail"] = f"融资摊薄公告({ann_date})"
                break
    except Exception:
        pass
    return result


# ── 核心：因子打分 v2 ─────────────────────────────────────────────────────────

def _score_market_v2(
    breadth: dict,
    idx_pct: dict,
    sector_pcts: list[float],
    north_flow: dict,
    global_markets: dict,
    weights: dict,
) -> tuple[dict, list[str]]:
    """
    市场整体因子打分 v2：6因子全面评估
    factor_scores ∈ (-1, 1)，正=多头，负=空头
    """
    factors: dict[str, float] = {}
    reasons: list[str] = []

    br  = breadth.get("breadth", 0.5)
    lu  = breadth.get("limit_up", 0)
    ld  = breadth.get("limit_dn", 0)
    up  = breadth.get("up_count", 0)
    dn  = breadth.get("dn_count", 0)
    tot = breadth.get("total", max(1, up + dn))

    # 1. 市场宽度（4x 放大）
    breadth_score = max(-1.0, min(1.0, (br - 0.5) * 4.0))
    factors["market_breadth"] = breadth_score

    if br >= 0.65:
        reasons.append(
            f"市场全面做多：{up}家上涨仅{dn}家下跌，涨停{lu}只——"
            f"多方占绝对优势，明日惯性上行概率高，可积极参与")
    elif br >= 0.55:
        reasons.append(
            f"多方略占优：{up}涨/{dn}跌，涨停{lu}只——"
            f"有赚钱效应但尚未全面爆发，选强势板块龙头>买大盘指数")
    elif br >= 0.46:
        reasons.append(
            f"多空拉锯：{up}涨/{dn}跌，市场无明显方向——"
            f"存量博弈特征明显，操作难度大，控制仓位等待明确信号")
    elif br >= 0.35:
        reasons.append(
            f"空方主导：仅{up}家上涨，{dn}家下跌，跌停{ld}只——"
            f"做多信心不足，明日大概率延续弱势，建议轻仓观望")
    else:
        reasons.append(
            f"市场大幅下跌：{up}涨/{dn}跌（跌停{ld}只），宽度仅{br:.0%}——"
            f"恐慌情绪蔓延，抄底需等企稳信号，不要接下落的刀")

    # 2. 大盘指数动量（±2% → ±1.0）
    sh  = idx_pct.get("sh", 0)
    cyb = idx_pct.get("cyb", 0)
    sz  = idx_pct.get("sz", 0)
    avg_idx = (sh * 0.4 + sz * 0.3 + cyb * 0.3)
    idx_score = max(-1.0, min(1.0, avg_idx / 2.0))
    factors["index_momentum"] = idx_score

    if sh > 1 and cyb > 1:
        reasons.append(
            f"上证{sh:+.2f}% 创业板{cyb:+.2f}%，两市同步上涨——"
            f"趋势延续可能性高，若明日高开则短线可持股")
    elif sh > 0 and cyb > 0:
        reasons.append(
            f"上证{sh:+.2f}% 创业板{cyb:+.2f}%，小幅收涨——"
            f"动能有限，关注明日成交量是否放大以确认方向")
    elif (sh > 0) != (cyb > 0):
        stronger = "创业板" if cyb > sh else "主板"
        reasons.append(
            f"上证{sh:+.2f}% 创业板{cyb:+.2f}%，两市分化——"
            f"{stronger}偏强，结构性行情为主，板块选择比方向判断更重要")
    elif sh > -1:
        reasons.append(
            f"上证{sh:.2f}% 创业板{cyb:.2f}%，小幅回调——"
            f"卖压有限，关注明日开盘承接，若缩量回调则属健康调整")
    else:
        reasons.append(
            f"上证{sh:.2f}% 创业板{cyb:.2f}%，两市明显下跌——"
            f"趋势偏空，反弹视作减仓机会而非买入机会")

    # 3. 热门板块趋势（±3% → ±1.0）
    if sector_pcts:
        avg_sec  = sum(sector_pcts) / len(sector_pcts)
        sec_max  = max(sector_pcts)
        sec_min  = min(sector_pcts)
        sec_score = max(-1.0, min(1.0, avg_sec / 3.0))
        factors["sector_momentum"] = sec_score

        if avg_sec > 2:
            reasons.append(
                f"热门板块平均涨{avg_sec:.1f}%，最强{sec_max:.1f}%——"
                f"题材赚钱效应持续，明日龙头高开高走概率大")
        elif avg_sec > 0.5:
            reasons.append(
                f"热门板块均涨{avg_sec:.1f}%——有轮动机会但不宜追高，关注次强板块补涨")
        elif avg_sec > -0.5:
            reasons.append(
                f"板块涨跌参半（均{avg_sec:+.1f}%，最强{sec_max:.1f}%/最弱{sec_min:.1f}%）——"
                f"个股分化明显，靠板块逻辑驱动，精选龙头")
        else:
            reasons.append(
                f"热门板块均跌{abs(avg_sec):.1f}%，最强{sec_max:.1f}%——"
                f"题材降温，前期涨停板注意获利回吐压力")
    else:
        factors["sector_momentum"] = 0.0

    # 4. 涨停/跌停比（limit_ratio）
    limit_ratio_score = 0.0
    if tot > 0:
        net_limit_pct = (lu - ld) / tot * 100
        limit_ratio_score = max(-1.0, min(1.0, net_limit_pct * 0.5))
    factors["limit_ratio"] = limit_ratio_score

    # 5. 北向资金
    net_flow = north_flow.get("net_flow", 0.0)
    north_sig = north_flow.get("signal", 0.0)
    factors["north_flow"] = north_sig

    direction_cn = "买入" if net_flow >= 0 else "卖出"
    abs_flow = abs(net_flow)
    if north_sig != 0.0 or abs_flow > 0:
        bullish_str = "外资积极布局A股，短期多头信号增强" if net_flow > 0 else "外资撤离A股，需警惕情绪压力"
        reasons.append(
            f"北向资金净{direction_cn}{abs_flow:.1f}亿，{bullish_str}——"
            f"外资是A股重要边际资金，方向有一定参考价值")
    else:
        reasons.append("北向资金数据暂不可用，该因子置零")

    # 6. 外盘（global_markets）
    sp500  = global_markets.get("sp500",  0.0)
    nasdaq = global_markets.get("nasdaq", 0.0)
    dow    = global_markets.get("dow",    0.0)
    hsi    = global_markets.get("hsi",    0.0)
    us_avg = global_markets.get("us_avg", 0.0)
    glob_sig = global_markets.get("signal", 0.0)
    factors["global_markets"] = glob_sig

    if sp500 != 0 or nasdaq != 0:
        bias_str = "强" if us_avg > 0 else "弱"
        impact_str = "利好" if us_avg > 0 else "利空"
        reasons.append(
            f"美股昨夜标普{sp500:+.2f}%纳斯达克{nasdaq:+.2f}%，"
            f"外围偏{bias_str}，A股情绪面受{impact_str}影响——"
            f"外盘走强通常带动A股开盘情绪，但隔夜效应递减，关注量能承接")
    else:
        reasons.append("外盘数据暂不可用，该因子置零")

    return factors, reasons


def _score_stock_v2(
    hq: dict,
    tech: dict,
    idx_pct: dict,
    lhb_syms: set[str],
    market_raw_score: float,
    rec_reasons: list[str] | None,
    weights: dict,
) -> tuple[dict, list[str]]:
    """
    个股因子打分 v2：9因子（价格动量/均线/RSI/布林/Beta/龙虎榜/板块/市场方向/公告）
    """
    factors: dict[str, float] = {}
    reasons: list[str] = []

    pct   = hq.get("pct_change", 0)
    price = hq.get("price", 0)
    name  = hq.get("name", "")
    sym   = hq.get("symbol", "")

    # 1. 价格动量
    if pct >= 9.5:
        mom = 1.0
        reasons.append(
            f"今日涨停（+{pct:.2f}%）——强势信号，明日大概率惯性高开；"
            f"若集合竞价高开3%以上且缩量，可持股；放量低走则出")
    elif pct >= 5:
        mom = min(1.0, pct / 8)
        reasons.append(
            f"今日大涨+{pct:.2f}%——明日大概率继续强势，但已有短线获利盘，"
            f"注意早盘是否出现高开低走，若守住昨日收盘则短线多头")
    elif pct >= 2:
        mom = pct / 6
        reasons.append(
            f"今日上涨+{pct:.2f}%——方向向上，只要大盘不崩，明日大概率惯性偏强")
    elif pct >= 0.3:
        mom = pct / 8
        reasons.append(
            f"今日微涨+{pct:.2f}%——多头有意愿但力度不足，需观察明日是否放量")
    elif pct >= -0.3:
        mom = 0.0
        reasons.append(
            f"今日几乎平盘（{pct:+.2f}%）——多空均衡，短期方向待定，看盘面情绪定")
    elif pct >= -2:
        mom = pct / 6
        reasons.append(
            f"今日小跌{pct:.2f}%——短期偏弱，关注是否有成交量萎缩，"
            f"缩量跌 = 正常调整；放量跌 = 抛压较重，需警惕")
    elif pct >= -5:
        mom = pct / 6
        reasons.append(
            f"今日下跌{pct:.2f}%——空方主导，短线不宜抄底，"
            f"等待明日开盘低开幅度判断恐慌程度，若低开后快速拉升可考虑介入")
    elif pct <= -9.5:
        mom = -1.0
        reasons.append(
            f"今日跌停（{pct:.2f}%）——恐慌抛售，明日大概率继续承压或低开；"
            f"若有重大利好则另当别论，否则坚决回避")
    else:
        mom = max(-1.0, pct / 8)
        reasons.append(
            f"今日大跌{pct:.2f}%——趋势走坏，今日就应离场，"
            f"若未出则明日开盘酌情减仓，不要抱侥幸心理等反弹")

    factors["price_momentum"] = max(-1.0, min(1.0, mom))

    # 2-5. 技术指标（来自 baostock 历史数据）
    if tech:
        ma5      = tech.get("ma5",  price)
        ma20     = tech.get("ma20", price)
        ma60     = tech.get("ma60", price)
        rsi      = tech.get("rsi",  50.0)
        bb_upper = tech.get("bb_upper", price)
        bb_mid   = tech.get("bb_mid",   price)
        bb_lower = tech.get("bb_lower", price)
        beta     = tech.get("beta", 1.0)
        close    = tech.get("close", price)

        factors["ma_signal"]   = tech.get("ma_score",   0.0)
        factors["rsi_signal"]  = tech.get("rsi_score",  0.0)
        factors["bb_signal"]   = tech.get("bb_score",   0.0)
        factors["beta_signal"] = tech.get("beta_score", 0.0)

        # MA 文字描述
        ma_s = tech.get("ma_score", 0.0)
        if ma_s >= 1.0:
            reasons.append(
                f"均线多头排列(MA5={ma5:.2f}>MA20={ma20:.2f}>MA60={ma60:.2f})，"
                f"趋势清晰，顺势持有即可")
        elif ma_s >= 0.6:
            reasons.append(
                f"价格站上MA20({ma20:.2f})且MA5上穿——中期趋势向好，"
                f"回踩MA20附近是加仓机会")
        elif ma_s >= 0.3:
            reasons.append(
                f"价格在MA20({ma20:.2f})上方但均线排列不佳——短期偏多，"
                f"注意是否能维持在MA20之上")
        elif ma_s <= -1.0:
            reasons.append(
                f"均线空头排列(价格{close:.2f}<MA5<MA20<MA60={ma60:.2f})，"
                f"趋势走坏，反弹均是减仓机会，不要抄底")
        elif ma_s <= -0.6:
            reasons.append(
                f"价格跌破MA20({ma20:.2f})，均线开始压制——"
                f"反弹时注意减仓，等待均线重新多头排列再入场")
        else:
            reasons.append(
                f"均线信号中性(MA20={ma20:.2f})——价格在均线附近震荡，"
                f"方向不明，控制仓位")

        # RSI 文字描述
        rsi_s = tech.get("rsi_score", 0.0)
        if rsi_s <= -0.8:
            reasons.append(
                f"RSI={rsi:.0f}，超买区域，短线获利盘压力大，"
                f"注意高位震荡风险，可考虑减仓锁利")
        elif rsi_s <= -0.4:
            reasons.append(
                f"RSI={rsi:.0f}，进入超买预警区，追高需谨慎，"
                f"建议等待回调后再评估")
        elif rsi_s >= 0.7:
            reasons.append(
                f"RSI={rsi:.0f}，极度超卖，技术性反弹概率高，"
                f"但需配合量能确认，不宜重仓")
        elif rsi_s >= 0.3:
            reasons.append(
                f"RSI={rsi:.0f}，超卖企稳，技术性反弹概率提升——"
                f"关注是否有量能配合，可轻仓试探")
        elif rsi_s >= 0.4:
            reasons.append(
                f"RSI={rsi:.0f}，动能健康偏强，趋势延续概率较高")
        else:
            reasons.append(
                f"RSI={rsi:.0f}，处于中性区间，动能无明显偏向")

        # BB 文字描述
        bb_s = tech.get("bb_score", 0.0)
        if bb_s <= -0.7:
            reasons.append(
                f"价格突破布林上轨({bb_upper:.2f})，短期超强势但过热风险高——"
                f"可持有但注意止盈，不宜追高")
        elif bb_s >= 0.6:
            reasons.append(
                f"价格触及布林下轨({bb_lower:.2f})，技术面有支撑——"
                f"关注反弹机会，若配合成交量放大可轻仓介入")
        elif bb_s >= 0.3:
            reasons.append(
                f"价格在布林中轨({bb_mid:.2f})上方，处于相对强势区间")
        elif bb_s <= -0.3:
            reasons.append(
                f"价格在布林中轨({bb_mid:.2f})下方，处于相对弱势区间，谨慎")
        else:
            reasons.append(
                f"价格在布林中轨({bb_mid:.2f})附近震荡，方向待选择")

        # Beta 文字描述
        beta_s = tech.get("beta_score", 0.0)
        market_dir_str = "向上" if market_raw_score > 0 else "向下"
        if abs(beta_s) > 0:
            amp_str = "放大上涨" if beta_s > 0 else "放大下跌"
            reasons.append(
                f"Beta={beta:.2f}（高弹性股），大盘{market_dir_str}时该股弹性大——"
                f"当前市场环境下预计{amp_str}效应显著")
    else:
        # 没有技术数据，使用默认值
        factors["ma_signal"]   = 0.0
        factors["rsi_signal"]  = 0.0
        factors["bb_signal"]   = 0.0
        factors["beta_signal"] = 0.0

    # 6. 龙虎榜信号
    if sym in lhb_syms:
        factors["lhb_signal"] = 0.8
        reasons.append(
            f"近5日上龙虎榜且净买入——游资/机构已进场，筹码向强者集中，"
            f"短线有被继续拉升的预期，但若龙虎榜净卖则性质相反")
    else:
        factors["lhb_signal"] = 0.0

    # 7. 板块推荐逻辑
    if rec_reasons:
        factors["sector_rec"] = 0.5
        tag = rec_reasons[0].replace("🔥 ", "").replace("🐉 ", "").replace("📈 ", "")
        reasons.append(
            f"板块逻辑：{tag}——概念热度维持时个股可能继续被资金关注，"
            f"但要区分是真正受益还是纯粹蹭热度")
    else:
        factors["sector_rec"] = 0.0

    # 8. 市场方向因子（市场原始得分 clamp 到 ±1）
    factors["market_regime"] = max(-1.0, min(1.0, market_raw_score))

    # 9. 公告信号（news_signal）
    news = _fetch_news_signal(sym)
    factors["news_signal"] = news.get("signal", 0.0)
    detail = news.get("detail", "")
    if detail:
        if news["signal"] > 0:
            reasons.append(f"重大利好公告：{detail}——短期股价预期受正面刺激")
        else:
            reasons.append(f"注意公告：{detail}——可能对股价产生短期压力")

    return factors, reasons


def _compute_direction(
    factor_scores: dict[str, float],
    weights: dict[str, float],
) -> tuple[str, float, float]:
    """
    方向/幅度/置信度计算
    阈值从 ±0.15 降到 ±0.04：只有真正中性信号才判震荡
    置信度从 55% 起步：系统有立场，不回避
    """
    raw = sum(factor_scores.get(k, 0) * weights.get(k, 0.2) for k in weights)
    raw = max(-1.0, min(1.0, raw))

    if raw > 0.04:
        direction    = "up"
        pct_estimate = round(0.5 + raw * 4.5, 1)
    elif raw < -0.04:
        direction    = "down"
        pct_estimate = round(0.5 + abs(raw) * 4.5, 1)
    else:
        direction    = "flat"
        pct_estimate = round(abs(raw) * 3, 1)

    confidence = round(min(0.90, 0.55 + abs(raw) * 0.35), 2)
    return direction, pct_estimate, confidence


# ── 生成预测 v2 ───────────────────────────────────────────────────────────────

def _generate_prediction(
    watchlist: list[str],
    store: dict,
) -> dict:
    """生成明日预测并写入 store，返回 prediction dict"""
    weights_store = store.get("weights", {})
    # 兼容旧格式（扁平 dict）和新格式（嵌套 market/stock）
    if "market" in weights_store and "stock" in weights_store:
        market_weights = weights_store["market"]
        stock_weights  = weights_store["stock"]
    else:
        market_weights = _DEFAULT_MARKET_WEIGHTS.copy()
        stock_weights  = _DEFAULT_STOCK_WEIGHTS.copy()

    today     = date.today().isoformat()
    pred_date = _next_trading_day()

    # 采集市场数据（并行逻辑用串行实现，保持简洁）
    breadth       = _fetch_market_breadth()
    idx_pct       = _fetch_indices_pct()
    sector_pcts   = _fetch_top_sectors()
    lhb_syms      = _fetch_lhb_symbols()
    global_mkts   = _fetch_global_markets()
    north_flow    = _fetch_north_flow()

    # 取今日推荐
    rec_symbols: list[str] = []
    rec_map: dict[str, list[str]] = {}
    try:
        from api.watchlist import get_recommendations_sync
        recs = get_recommendations_sync()
        for s in recs:
            sym = s.get("symbol", "")
            if sym:
                rec_symbols.append(sym)
                rec_map[sym] = s.get("reasons", [])
    except Exception:
        pass

    all_symbols = list(set(watchlist + rec_symbols))
    hq_map      = _fetch_stock_quotes(all_symbols)

    # 批量获取技术指标（一次 baostock session）
    tech_map = _fetch_technical_batch(all_symbols)

    # ── 市场整体预测 ──────────────────────────────────────────────────────────
    mkt_factors, mkt_reasons = _score_market_v2(
        breadth, idx_pct, sector_pcts, north_flow, global_mkts, market_weights
    )
    mkt_dir, mkt_pct, mkt_conf = _compute_direction(mkt_factors, market_weights)

    # 计算市场原始得分（用于 market_regime 因子）
    market_raw_score = sum(
        mkt_factors.get(k, 0) * market_weights.get(k, 0.2)
        for k in market_weights
    )
    market_raw_score = max(-1.0, min(1.0, market_raw_score))

    # 历史准确率加权调整置信度
    hist_acc = _calc_recent_accuracy(store)
    mkt_conf = round(mkt_conf * 0.6 + hist_acc * 0.4, 2) if hist_acc > 0 else mkt_conf

    # ── 自选股预测 ────────────────────────────────────────────────────────────
    stock_preds: list[dict] = []
    for sym in watchlist:
        hq = hq_map.get(sym)
        if not hq or hq.get("not_found"):
            continue
        tech = tech_map.get(sym, {})
        s_factors, s_reasons = _score_stock_v2(
            hq, tech, idx_pct, lhb_syms, market_raw_score,
            rec_map.get(sym), stock_weights
        )
        s_dir, s_pct, s_conf = _compute_direction(s_factors, stock_weights)
        stock_preds.append({
            "symbol":       sym,
            "name":         hq.get("name", sym),
            "today_pct":    round(hq.get("pct_change", 0), 2),
            "direction":    s_dir,
            "pct_estimate": s_pct,
            "confidence":   s_conf,
            "reasoning":    s_reasons,
            "factors":      s_factors,
        })

    # ── 推荐股预测 ────────────────────────────────────────────────────────────
    rec_preds: list[dict] = []
    for sym in rec_symbols[:8]:
        hq = hq_map.get(sym)
        if not hq or hq.get("not_found"):
            continue
        tech = tech_map.get(sym, {})
        s_factors, s_reasons = _score_stock_v2(
            hq, tech, idx_pct, lhb_syms, market_raw_score,
            rec_map.get(sym), stock_weights
        )
        s_dir, s_pct, s_conf = _compute_direction(s_factors, stock_weights)
        rec_preds.append({
            "symbol":       sym,
            "name":         hq.get("name", sym),
            "today_pct":    round(hq.get("pct_change", 0), 2),
            "direction":    s_dir,
            "pct_estimate": s_pct,
            "confidence":   s_conf,
            "reasoning":    s_reasons,
            "factors":      s_factors,
            "rec_reasons":  rec_map.get(sym, []),
        })

    prediction = {
        "generated_at":   datetime.now().isoformat(),
        "based_on_date":  today,
        "prediction_for": pred_date,
        "watchlist_used": sorted(watchlist),
        "breadth_snapshot":   breadth,
        "index_snapshot":     idx_pct,
        "global_snapshot":    global_mkts,
        "north_flow_snapshot": north_flow,
        "market": {
            "direction":    mkt_dir,
            "pct_estimate": mkt_pct,
            "confidence":   mkt_conf,
            "reasoning":    mkt_reasons,
            "factors":      mkt_factors,
        },
        "stocks":          stock_preds,
        "recommendations": rec_preds,
        "weights_used": {
            "market": market_weights,
            "stock":  stock_weights,
        },
    }

    store["predictions"][pred_date] = prediction
    _save_store(store)
    return prediction


def _next_trading_day() -> str:
    """下一个交易日（简化：跳过周六日）"""
    d = date.today() + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


# ── 记录实际 & 学习 ───────────────────────────────────────────────────────────

def _record_actuals_and_learn(store: dict) -> dict | None:
    """
    获取今日实际行情，与昨日（或最近一次）预测对比，更新权重
    返回 comparison_dict 或 None
    """
    today = date.today().isoformat()
    pred = store["predictions"].get(today)
    if not pred:
        return None

    if today in store["actuals"]:
        return _build_comparison(pred, store["actuals"][today], store)

    idx_actual = _fetch_indices_pct()
    all_syms   = ([s["symbol"] for s in pred.get("stocks", [])] +
                  [s["symbol"] for s in pred.get("recommendations", [])])
    hq_actual  = _fetch_stock_quotes(all_syms)

    actual = {
        "date":        today,
        "recorded_at": datetime.now().isoformat(),
        "indices":     idx_actual,
        "stocks":      {sym: round(hq.get("pct_change", 0), 2)
                        for sym, hq in hq_actual.items() if not hq.get("not_found")},
    }
    store["actuals"][today] = actual

    cmp = _build_comparison(pred, actual, store)
    _update_weights(store, pred, actual, cmp)
    _save_store(store)
    return cmp


def _build_comparison(pred: dict, actual: dict, store: dict) -> dict:
    """构建 prediction vs actual 对比字典"""
    pred_mkt = pred["market"]
    avg_actual = sum(actual["indices"].values()) / max(1, len(actual["indices"]))
    actual_dir = "up" if avg_actual > 0.2 else "down" if avg_actual < -0.2 else "flat"
    mkt_correct = (pred_mkt["direction"] == actual_dir)

    market_cmp = {
        "predicted_direction": pred_mkt["direction"],
        "predicted_pct":       pred_mkt["pct_estimate"],
        "actual_avg_pct":      round(avg_actual, 2),
        "actual_sh":           actual["indices"].get("sh", 0),
        "actual_cyb":          actual["indices"].get("cyb", 0),
        "direction_correct":   mkt_correct,
        "magnitude_error":     round(abs(pred_mkt["pct_estimate"] - abs(avg_actual)), 2),
    }

    stock_cmps  = []
    correct_cnt = 0
    total_cnt   = 0
    for s in pred.get("stocks", []) + pred.get("recommendations", []):
        sym     = s["symbol"]
        act_pct = actual["stocks"].get(sym)
        if act_pct is None:
            continue
        act_dir = "up" if act_pct > 0.3 else "down" if act_pct < -0.3 else "flat"
        correct = (s["direction"] == act_dir)
        if correct:
            correct_cnt += 1
        total_cnt += 1
        stock_cmps.append({
            "symbol":              sym,
            "name":                s["name"],
            "predicted_direction": s["direction"],
            "predicted_pct":       s["pct_estimate"],
            "actual_pct":          act_pct,
            "correct":             correct,
            "error":               round(abs(s["pct_estimate"] - abs(act_pct)), 2),
        })

    stock_acc = round(correct_cnt / total_cnt, 2) if total_cnt else 0
    history   = _calc_history_summary(store)

    return {
        "prediction_for": pred["prediction_for"],
        "based_on_date":  pred["based_on_date"],
        "generated_at":   pred["generated_at"],
        "market":         market_cmp,
        "stocks":         stock_cmps,
        "accuracy": {
            "market_correct": mkt_correct,
            "stock_accuracy": stock_acc,
            "stock_total":    total_cnt,
        },
        "history": history,
    }


def _update_weights(store: dict, pred: dict, actual: dict, cmp: dict):
    """
    根据本次准确率，用指数平滑更新市场/个股权重
    学习率 α=0.15，准确 → 权重 +，不准 → 权重 -
    分别更新 market 和 stock 权重
    """
    ALPHA = 0.15
    weights_store = store.get("weights", {})

    # 兼容旧格式
    if "market" in weights_store and "stock" in weights_store:
        mkt_weights = weights_store["market"]
        stk_weights = weights_store["stock"]
    else:
        mkt_weights = _DEFAULT_MARKET_WEIGHTS.copy()
        stk_weights = _DEFAULT_STOCK_WEIGHTS.copy()

    # ── 更新市场权重 ──────────────────────────────────────────────────────────
    mkt_correct  = cmp["market"]["direction_correct"]
    mkt_factors  = pred["market"].get("factors", {})
    mkt_reward   = 1.0 if mkt_correct else -1.0
    for factor, score in mkt_factors.items():
        if factor not in mkt_weights:
            continue
        contributed = (score * mkt_reward) > 0
        delta = ALPHA if contributed else -ALPHA * 0.5
        mkt_weights[factor] = round(max(0.05, min(0.60, mkt_weights[factor] + delta)), 4)
    total_mw = sum(mkt_weights.values())
    if total_mw > 0:
        for k in mkt_weights:
            mkt_weights[k] = round(mkt_weights[k] / total_mw, 4)

    # ── 更新个股权重（基于平均个股准确率） ───────────────────────────────────
    stock_acc = cmp["accuracy"]["stock_accuracy"]
    stk_reward = 1.0 if stock_acc >= 0.5 else -1.0
    # 对市场方向相关因子（market_regime）以市场准确率为准
    for factor in list(stk_weights.keys()):
        if factor == "market_regime":
            contributed = mkt_correct
            delta = ALPHA if contributed else -ALPHA * 0.5
        else:
            # 其他股票因子以整体股票准确率为参考
            delta = ALPHA * 0.5 if stk_reward > 0 else -ALPHA * 0.3
        stk_weights[factor] = round(max(0.02, min(0.50, stk_weights[factor] + delta)), 4)
    total_sw = sum(stk_weights.values())
    if total_sw > 0:
        for k in stk_weights:
            stk_weights[k] = round(stk_weights[k] / total_sw, 4)

    store["weights"] = {"market": mkt_weights, "stock": stk_weights}

    # 记录准确率历史
    store["accuracy"].append({
        "date":           actual["date"],
        "market_correct": mkt_correct,
        "stock_accuracy": cmp["accuracy"]["stock_accuracy"],
        "weights": {"market": mkt_weights.copy(), "stock": stk_weights.copy()},
    })
    store["accuracy"] = store["accuracy"][-60:]


def _calc_recent_accuracy(store: dict, n: int = 10) -> float:
    """计算最近 n 次预测的市场方向准确率"""
    history = store.get("accuracy", [])
    recent  = history[-n:] if len(history) >= n else history
    if not recent:
        return 0.0
    correct = sum(1 for r in recent if r.get("market_correct", False))
    return round(correct / len(recent), 2)


def _calc_history_summary(store: dict) -> dict:
    """汇总历史准确率统计"""
    acc = store.get("accuracy", [])
    if not acc:
        return {"total_days": 0, "market_direction_pct": 0, "avg_stock_acc": 0,
                "trend": "暂无数据", "recent": []}
    total    = len(acc)
    mkt_pct  = round(sum(1 for r in acc if r.get("market_correct")) / total * 100, 1)
    stk_avg  = round(sum(r.get("stock_accuracy", 0) for r in acc) / total * 100, 1)
    recent10 = acc[-10:]
    r10_mkt  = round(sum(1 for r in recent10 if r.get("market_correct")) / len(recent10) * 100, 1)
    if total < 3:
        trend = "数据积累中"
    elif r10_mkt > mkt_pct + 5:
        trend = "准确率提升中"
    elif r10_mkt < mkt_pct - 5:
        trend = "准确率下降"
    else:
        trend = "准确率稳定"
    return {
        "total_days":           total,
        "market_direction_pct": mkt_pct,
        "avg_stock_acc":        stk_avg,
        "trend":                trend,
        "recent":               [{"date": r["date"], "market_correct": r["market_correct"],
                                  "stock_accuracy": r.get("stock_accuracy", 0)} for r in acc[-30:]],
    }


# ── API 路由 ──────────────────────────────────────────────────────────────────

@router.get("/latest")
async def get_latest_prediction(watchlist: str = ""):
    """取最新预测；若自选股变化或预测不存在则自动重新生成"""
    store     = _load_store()
    pred_date = _next_trading_day()
    symbols   = sorted([s.strip() for s in watchlist.split(",") if s.strip()])

    pred = store["predictions"].get(pred_date)

    watchlist_changed = (
        pred is None or
        sorted(pred.get("watchlist_used", [])) != symbols
    )
    if watchlist_changed:
        pred = _generate_prediction(symbols, store)

    today = date.today().isoformat()
    comparison = None
    if store["predictions"].get(today) and today not in store["actuals"]:
        comparison = _record_actuals_and_learn(store)
    elif today in store["actuals"] and store["predictions"].get(today):
        comparison = _build_comparison(
            store["predictions"][today],
            store["actuals"][today],
            store,
        )

    weights_store = store.get("weights", {})
    return JSONResponse({
        "prediction": pred,
        "comparison": comparison,
        "history":    _calc_history_summary(store),
        "weights":    weights_store,
    })


@router.post("/generate")
async def generate_prediction(watchlist: str = ""):
    """强制重新生成预测（清除当日旧预测）"""
    store     = _load_store()
    symbols   = sorted([s.strip() for s in watchlist.split(",") if s.strip()])
    pred_date = _next_trading_day()
    store["predictions"].pop(pred_date, None)
    pred = _generate_prediction(symbols, store)
    return JSONResponse({"prediction": pred, "weights": store.get("weights", {})})


@router.post("/record")
async def record_actuals(watchlist: str = ""):
    """收盘后：记录今日实际行情，对比预测，更新权重"""
    store = _load_store()
    cmp   = _record_actuals_and_learn(store)
    if not cmp:
        return JSONResponse({"error": "未找到今日预测，请先生成预测"}, status_code=404)
    return JSONResponse({"comparison": cmp, "weights": store.get("weights", {})})


@router.get("/compare")
async def get_comparison():
    """取最近一次预测 vs 实际对比结果"""
    store = _load_store()
    for d in sorted(store["actuals"].keys(), reverse=True):
        pred = store["predictions"].get(d)
        if pred:
            cmp = _build_comparison(pred, store["actuals"][d], store)
            return JSONResponse(cmp)
    return JSONResponse({"error": "暂无对比数据"}, status_code=404)


@router.get("/history")
async def get_history():
    """历史准确率曲线（最近 30 日）"""
    store = _load_store()
    return JSONResponse({
        "history": _calc_history_summary(store),
        "weights": store.get("weights", {}),
    })
