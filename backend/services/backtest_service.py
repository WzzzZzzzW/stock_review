"""
规则库 · 真回测服务
─────────────────────────────────────────────────────────────────────────────
口径：每隔 hold_days 个交易日重平衡一次，在当日候选池上重放规则的数值/形态条件，
按 sort_field 排序取 top_k 等权买入，持有 hold_days 个交易日后再平衡。
和基准（上证综指/沪深300/中证500）净值曲线对比。

数据：
- 候选池：
  · 题材规则 (kind=theme) → 题材成分股
  · 数值/形态规则        → 沪深300 成分（首跑较慢，按日缓存）
- 每只候选股：baostock 日K + 衍生（MA5/20/60、量比、振幅）→ data.stock_data.fetch_history_batch
- 基准指数：data.stock_data.fetch_index_history（上证综指等）

性能：
- 首跑 ~60-180s（300 只 × baostock 串行）；按交易日全量缓存，当日再跑/换规则秒级
- 异步执行（后台线程 + 状态轮询），避免阻塞前端
"""
from __future__ import annotations
import threading
import time
import math
from datetime import datetime
import pandas as pd

from db import screen_rule_db as rule_db
from services import screen_service


# ── 任务状态（{rule_id: {...}}）────────────────────────────────────────────────
_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()

BENCHMARKS = {
    "上证综指":  ("sh000001", "上证综指"),
    "沪深300":   ("sh000300", "沪深300"),
    "中证500":   ("sh000905", "中证500"),
}
DEFAULT_BENCHMARK = "上证综指"


# ── 候选池：题材成分 / 沪深300 ─────────────────────────────────────────────────

def _hs300_symbols() -> list[str]:
    """沪深300 成分股（akshare 一次性，按内存缓存，启动一次后稳定）。"""
    cache = getattr(_hs300_symbols, "_cache", None)
    if cache:
        return cache
    syms: list[str] = []
    try:
        import akshare as ak
        df = ak.index_stock_cons_csindex(symbol="000300")
        if df is not None and not df.empty:
            col = next((c for c in ("成分券代码", "代码") if c in df.columns), None)
            if col:
                syms = [str(x).zfill(6) for x in df[col].tolist()]
    except Exception:
        syms = []
    # 兜底（akshare 失败时）：用同花顺/baostock 全市场前 300，至少能跑
    if not syms:
        try:
            from data.stock_data import get_industry_map
            imap = get_industry_map(block=False) or {}
            syms = list(imap.keys())[:300]
        except Exception:
            syms = []
    _hs300_symbols._cache = syms   # type: ignore
    return syms


def _candidate_pool(rule: dict) -> tuple[list[str], str]:
    """根据规则类型选候选池。返回 (symbols, 来源说明)。"""
    if rule.get("kind") == "theme":
        from services.screen_service import theme_symbols
        syms = sorted(theme_symbols(rule.get("theme", "")))
        return syms, f'题材「{rule.get("theme", "")}」成分股'
    return _hs300_symbols(), "沪深300 成分股"


# ── 在某日构造一只股票的 snapshot（mirror screen_service 的 quote dict 字段）──

def _row_to_quote(symbol: str, df: pd.DataFrame, i: int) -> dict | None:
    """把 df 第 i 行转成 screen_service 能评估的 quote dict。"""
    if i < 0 or i >= len(df):
        return None
    row = df.iloc[i]
    close = row.get("close")
    if pd.isna(close):
        return None
    prev = float(row.get("prev_close") or 0)
    high, low = row.get("high"), row.get("low")
    vol_ratio = row.get("vol_ratio")
    return {
        "symbol":       symbol,
        "name":         "",     # ST 判定走 is_st 列，name 留空
        "price":        float(close),
        "change_pct":   float(row.get("pct_change") or 0),
        "turnover":     float(row.get("turn") or 0),
        "volume":       float(row.get("volume") or 0),
        "amount":       float(row.get("amount") or 0),   # screen_service 的 scale=1e8
        "pe":           None if pd.isna(row.get("pe")) else float(row.get("pe")),
        "pb":           None if pd.isna(row.get("pb")) else float(row.get("pb")),
        "high":         None if pd.isna(high) else float(high),
        "low":          None if pd.isna(low)  else float(low),
        "prev_close":   prev if prev else None,
        "market_cap":   None,   # 历史总市值需总股本，本版不评估（条件会被记为不通过）
        "float_cap":    None,
        "volume_ratio": None if pd.isna(vol_ratio) else float(vol_ratio),
        # ST 标记走 baostock isST 列：放进 name 让 _universe_ok 的 "ST" in name 命中
        "_is_st":       bool(row.get("is_st")),
    }


def _eval_patterns_at(df: pd.DataFrame, i: int, active_patterns: list[str]) -> bool:
    """在 df 的第 i 行（结尾）评估形态条件。i 之前必须至少有 60 个交易日的数据。"""
    if not active_patterns:
        return True
    if i < 60:
        return False
    sub = df.iloc[: i + 1].copy()
    if len(sub) < 60:
        return False
    last = sub.iloc[-1]
    close = last["close"]
    ma5, ma20, ma60 = last.get("ma5"), last.get("ma20"), last.get("ma60")
    for k in active_patterns:
        ok = False
        if k == "ma_bullish":
            ok = bool(ma5 and ma20 and ma60 and ma5 > ma20 > ma60 and close > ma5)
        elif k == "above_ma20":
            ok = bool(ma20 and close > ma20)
        elif k == "new_high_60":
            window = sub["close"].iloc[-60:]
            ok = bool(close >= window.max() - 1e-6)
        elif k == "streak_up":
            pct = sub["pct_change"].iloc[-3:].tolist()
            ok = len(pct) == 3 and all((p or 0) > 0 for p in pct)
        elif k == "macd_golden":
            ema12 = sub["close"].ewm(span=12, adjust=False).mean()
            ema26 = sub["close"].ewm(span=26, adjust=False).mean()
            dif   = ema12 - ema26
            dea   = dif.ewm(span=9, adjust=False).mean()
            hist  = (dif - dea) * 2
            if len(hist) >= 2:
                ok = bool(hist.iloc[-1] > 0 and hist.iloc[-2] <= 0)
        elif k == "vol_uptrend":
            vols = sub["volume"].iloc[-5:].tolist()
            from data.stock_data import _is_mild_vol_uptrend
            ok = _is_mild_vol_uptrend(vols, window=5)
        if not ok:
            return False
    return True


# ── 单次重平衡：当日候选→取 top_k ───────────────────────────────────────────────

# 历史日K + 衍生能支持的字段（PE/PB/总市值需要总股本/财务，akshare 日K 不带，回测中跳过）
_HIST_SUPPORTED = {"change_pct", "turnover", "volume", "amount",
                   "amplitude", "price", "volume_ratio"}


def _pick_at_date(date_str: str, frames: dict, rule: dict) -> list[dict]:
    """返回当日入选的股票列表 [{symbol, close, name?}, ...]。"""
    uni = rule.get("universe") or {}
    # 历史不可评估的字段直接跳过（否则全市场都被错误剔除）
    conds = [c for c in (rule.get("conditions") or [])
             if c.get("field") in screen_service.FIELD_MAP
             and c.get("field") in _HIST_SUPPORTED]
    logic = (rule.get("logic") or "AND").upper()
    active_patterns = [k for k in screen_service._PATTERN_KEYS if uni.get(k)]
    sort_field = rule.get("sort_field") or "change_pct"
    sort_dir   = rule.get("sort_dir") or "desc"
    reverse = (str(sort_dir).lower() != "asc")
    top_k = rule.get("_top_k", 10)

    hits: list[dict] = []
    for sym, df in frames.items():
        if df is None or df.empty or "date" not in df.columns:
            continue
        # 找当日在 df 中的位置（≤ date_str 的最近一行）
        try:
            mask = df["date"] <= date_str
            idx_arr = df.index[mask]
            if len(idx_arr) == 0:
                continue
            i = int(idx_arr[-1])
            row_date = df.iloc[i]["date"]
            if row_date != date_str:
                # 当日停牌等 → 跳过
                continue
        except Exception:
            continue

        q = _row_to_quote(sym, df, i)
        if not q:
            continue
        # universe：ST 用 baostock 列覆盖；688/300/8/4/9 用代码前缀
        if uni.get("exclude_st") and q.get("_is_st"):
            continue
        if uni.get("exclude_688") and sym.startswith("688"):
            continue
        if uni.get("exclude_300") and sym.startswith("300"):
            continue
        if uni.get("exclude_bj") and (sym.startswith("8") or sym.startswith("4") or sym.startswith("92")):
            continue

        if conds:
            checks = [screen_service._passes(q, c) for c in conds]
            if not (all(checks) if logic == "AND" else any(checks)):
                continue
        if active_patterns and not _eval_patterns_at(df, i, active_patterns):
            continue

        # 排序键（沿用 screen_service 的取值/缩放）
        meta = screen_service.FIELD_MAP.get(sort_field)
        if meta:
            raw = screen_service._field_value(q, sort_field)
            sort_v = (raw / meta["scale"]) if raw is not None else None
        else:
            sort_v = None
        hits.append({
            "symbol": sym,
            "close":  q["price"],
            "sort_v": sort_v if sort_v is not None else (-math.inf if reverse else math.inf),
        })

    hits.sort(key=lambda x: x["sort_v"], reverse=reverse)
    return hits[: max(1, int(top_k))]


# ── 主入口：跑回测 ─────────────────────────────────────────────────────────────

def _do_backtest(rid: str, window_days: int, hold_days: int, top_k: int, benchmark: str) -> dict:
    rule = rule_db.get_rule(rid)
    if not rule:
        raise RuntimeError(f"规则 {rid} 不存在")
    rule = dict(rule)
    rule["_top_k"] = top_k

    bench_code, bench_label = BENCHMARKS.get(benchmark, BENCHMARKS[DEFAULT_BENCHMARK])

    _update(rid, stage="拉取基准指数", progress=2)
    from data.stock_data import fetch_index_history, fetch_history_batch
    idx_df = fetch_index_history(bench_code, days_back=window_days + 30)
    if idx_df is None or idx_df.empty:
        raise RuntimeError(f"基准 {bench_label} 历史数据拉取失败")
    # 用基准的交易日序列锚定回测时间轴（A股交易日）
    trading_days = list(idx_df["date"].iloc[-(window_days + 1):].astype(str))
    if len(trading_days) < hold_days + 2:
        raise RuntimeError("回测窗口过短")

    _update(rid, stage="确定候选股池", progress=5)
    syms, pool_label = _candidate_pool(rule)
    if not syms:
        raise RuntimeError(f"候选池为空（{pool_label}）")
    pool_size = len(syms)

    _update(rid, stage=f"拉取 {pool_size} 只股票历史日K（akshare 并发，首次约 20s）",
            progress=10, pool_size=pool_size, pool_label=pool_label)
    def _pcb(done: int, total: int):
        # 10% → 65% 区段用于历史拉取进度
        pct = 10 + int(55 * done / max(1, total))
        _update(rid, progress=pct,
                stage=f"拉取历史日K {done}/{total}")
    frames = fetch_history_batch(syms, days_back=window_days + 30, progress_cb=_pcb)

    _update(rid, stage="重放规则、计算每期持仓", progress=70)
    # 标记未参与回测的条件（PE/PB/总市值等历史无法评估的字段）
    raw_conds = rule.get("conditions") or []
    skipped_fields = sorted({
        c.get("field") for c in raw_conds
        if c.get("field") in screen_service.FIELD_MAP
        and c.get("field") not in _HIST_SUPPORTED
    })
    skipped_labels = [screen_service.FIELD_MAP[f]["label"] for f in skipped_fields]
    # 每 hold_days 个交易日重平衡一次
    rebalances: list[dict] = []
    i = 0
    while i + hold_days < len(trading_days):
        d = trading_days[i]
        picks = _pick_at_date(d, frames, rule)
        if picks:
            sell_idx = min(i + hold_days, len(trading_days) - 1)
            sell_date = trading_days[sell_idx]
            # 每只股票期内收益（用其自己在 d / sell_date 的收盘）
            symbol_returns: list[dict] = []
            for p in picks:
                sym = p["symbol"]
                df = frames.get(sym)
                if df is None or df.empty:
                    continue
                try:
                    buy_row = df[df["date"] == d]
                    sell_row = df[df["date"] == sell_date]
                    if buy_row.empty or sell_row.empty:
                        continue
                    bp = float(buy_row.iloc[0]["close"])
                    sp = float(sell_row.iloc[0]["close"])
                    if bp <= 0:
                        continue
                    symbol_returns.append({"symbol": sym, "ret": sp / bp - 1.0})
                except Exception:
                    continue
            if symbol_returns:
                avg = sum(x["ret"] for x in symbol_returns) / len(symbol_returns)
                rebalances.append({
                    "date":  d,
                    "sell":  sell_date,
                    "picks": [x["symbol"] for x in symbol_returns],
                    "ret":   avg,
                    "n":     len(symbol_returns),
                })
        i += hold_days

    _update(rid, stage="构造净值曲线 + 统计", progress=92)
    # 基准限定 trading_days 范围，起点归一化为 1
    win_set = set(trading_days)
    bench_in = idx_df[idx_df["date"].isin(win_set)].copy()
    bench_close = bench_in.set_index("date")["close"].astype(float)
    bench_base = float(bench_close.iloc[0]) if len(bench_close) else 1.0

    # 预建每只股票的 date→close 索引，避免内层 df[df["date"]==d] 慢查询
    price_idx: dict[str, dict] = {}
    for sym in {s for rb in rebalances for s in rb["picks"]}:
        df = frames.get(sym)
        if df is not None and not df.empty:
            price_idx[sym] = dict(zip(df["date"].astype(str), df["close"].astype(float)))
    # 平滑净值：持仓期间逐日按 mean(close[d]/close[buy]) 算实时组合价值；
    # 空仓期净值持平（当日没股票满足规则，真实如此，不是 bug）。
    rb_by_start = {r["date"]: r for r in rebalances}
    nav: list[dict] = []
    strat_nav = 1.0
    in_pos = False
    pos_picks: list[str] = []
    pos_buy_close: dict[str, float] = {}
    pos_start_nav = 1.0
    pos_sell_date: str | None = None
    flat_days = 0   # 统计空仓天数

    for d in trading_days:
        # 段开始：买入开仓
        if d in rb_by_start:
            rb = rb_by_start[d]
            pos_picks = []
            pos_buy_close = {}
            for sym in rb["picks"]:
                bp = price_idx.get(sym, {}).get(d)
                if bp and bp > 0:
                    pos_picks.append(sym)
                    pos_buy_close[sym] = bp
            pos_start_nav = strat_nav
            pos_sell_date = rb["sell"]
            in_pos = bool(pos_picks)

        # 持仓中：当日组合净值 = 起点净值 × 平均(当日close / 买入close)
        if in_pos and pos_picks:
            ratios = []
            for sym in pos_picks:
                cp = price_idx.get(sym, {}).get(d)
                if cp is not None:
                    ratios.append(cp / pos_buy_close[sym])
            if ratios:
                strat_nav = pos_start_nav * (sum(ratios) / len(ratios))
        else:
            flat_days += 1

        # 段结束：平仓
        if in_pos and d == pos_sell_date:
            in_pos = False
            pos_picks = []
            pos_buy_close = {}
            pos_sell_date = None

        bench_v = bench_close.get(d)
        nav.append({
            "date":      d,
            "strategy":  round(strat_nav, 6),
            "benchmark": None if (bench_v is None or pd.isna(bench_v)) else round(float(bench_v) / bench_base, 6),
        })

    # 统计
    total = strat_nav - 1.0
    bench_total = (float(bench_close.iloc[-1]) / bench_base) - 1.0 if len(bench_close) else 0.0
    rets = [r["ret"] for r in rebalances]
    win_rate = round(sum(1 for x in rets if x > 0) / len(rets), 4) if rets else 0.0
    avg_picks = round(sum(r["n"] for r in rebalances) / len(rebalances), 1) if rebalances else 0.0
    # 最大回撤
    peak = 1.0
    max_dd = 0.0
    for n in nav:
        v = n["strategy"]
        if v > peak: peak = v
        dd = (v - peak) / peak
        if dd < max_dd: max_dd = dd
    # Sharpe（按周期，无风险利率忽略）
    if len(rets) >= 2:
        m = sum(rets) / len(rets)
        var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
        sd = math.sqrt(var) if var > 0 else 0.0
        # 年化 ≈ 周期数/年；A股一年约 240 交易日
        ann = (240.0 / hold_days)
        sharpe = round((m / sd) * math.sqrt(ann), 2) if sd > 0 else 0.0
    else:
        sharpe = 0.0

    _update(rid, stage="完成", progress=100)
    return {
        "ok":          True,
        "rule_id":     rid,
        "rule_name":   rule.get("name"),
        "window_days": window_days,
        "hold_days":   hold_days,
        "top_k":       top_k,
        "benchmark":   bench_label,
        "pool_label":  pool_label,
        "pool_size":   pool_size,
        "skipped_conditions": skipped_labels,
        "stats": {
            "total_return_pct":  round(total * 100, 2),
            "bench_return_pct":  round(bench_total * 100, 2),
            "excess_pct":        round((total - bench_total) * 100, 2),
            "max_drawdown_pct":  round(max_dd * 100, 2),
            "win_rate":          win_rate,
            "sharpe":            sharpe,
            "rebalance_count":   len(rebalances),
            "avg_picks":         avg_picks,
            "flat_days":         flat_days,
            "exposure_pct":      round((len(trading_days) - flat_days) / max(1, len(trading_days)) * 100, 1),
        },
        "nav":         nav,
        "rebalances":  rebalances,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ── 任务/状态接口 ──────────────────────────────────────────────────────────────

def _update(rid: str, **patch):
    with _tasks_lock:
        t = _tasks.setdefault(rid, {})
        t.update(patch)


def get_status(rid: str) -> dict:
    with _tasks_lock:
        return dict(_tasks.get(rid, {})) or {"state": "idle"}


def start_backtest(rid: str, window_days: int = 120, hold_days: int = 5,
                   top_k: int = 10, benchmark: str = DEFAULT_BENCHMARK) -> dict:
    """启动一次回测（后台线程）。已在跑则直接返回当前状态。"""
    with _tasks_lock:
        cur = _tasks.get(rid)
        if cur and cur.get("state") == "running":
            return {"ok": True, "state": "running", "message": "已在回测中"}
        _tasks[rid] = {
            "state":    "running",
            "started":  time.time(),
            "stage":    "排队",
            "progress": 0,
            "params":   {"window_days": window_days, "hold_days": hold_days,
                         "top_k": top_k, "benchmark": benchmark},
            "result":   None,
            "error":    None,
        }

    def worker():
        t0 = time.time()
        try:
            res = _do_backtest(rid, window_days, hold_days, top_k, benchmark)
            with _tasks_lock:
                _tasks[rid].update(state="done", result=res, finished=time.time(),
                                   elapsed=round(time.time() - t0, 1))
        except Exception as e:
            with _tasks_lock:
                _tasks[rid].update(state="error", error=str(e), finished=time.time(),
                                   elapsed=round(time.time() - t0, 1))

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True, "state": "running", "message": "回测已开始，约 30s ~ 3 分钟（首次较慢，后续命中缓存秒回）"}
