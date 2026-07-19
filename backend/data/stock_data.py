"""
股票数据采集层 —— 使用 baostock（Socket 协议，不受 HTTP 代理影响）
单次连接拿取所有维度数据，减少 login/logout 开销

注意：baostock 底层是单例 socket，不支持并发访问。
全局锁 _BS_LOCK 确保同时只有一个协程持有连接。
"""
import baostock as bs
import pandas as pd
import datetime
import threading

from utils.fallback_log import report_data_fallback

# baostock 全局互斥锁（socket 不支持并发）
_BS_LOCK = threading.Lock()

# ── baostock 并发熔断 ────────────────────────────────────────────────────────────
# 历史教训：baostock 单 socket，一旦 socket 卡住（网络抖动/半响应），_BS_LOCK 会被
# 永久持有 → 所有 baostock 调用排队 → uvicorn 线程池打满 → 整个后端"假死"。
# 加固策略：
#  1) 锁 acquire 有超时（默认 60s）—— 拿不到就抛 BaostockBusy，调用方降级
#  2) work_fn 跑在 daemon 线程里 + 总超时（默认 90s）—— 卡住时不阻塞主流程
#  3) 一旦超时，进入冷却期 _BS_COOLDOWN（默认 90s），期间新调用快速失败
#     防止刚刚超时的 socket 还在挣扎、新调用又去抢锁加剧问题
# 所有调用方（fetch_patterns_batch、fetch_quick_batch、_build_industry_map、单股复盘）
# 都已有 try/except 兜底（缓存/空集/部分结果），不会让请求返回 500。

import time as _time
import concurrent.futures as _futures


class BaostockBusy(Exception):
    """长时间拿不到 baostock 锁（前一个调用还在跑）。"""
    pass


class BaostockTimeout(Exception):
    """baostock 调用单次超时，已进入冷却期。"""
    pass


class BaostockCooldown(Exception):
    """处于冷却期，拒绝新调用。"""
    pass


_BS_HEALTH = {"unhealthy_until": 0.0, "last_error": ""}
_BS_LOCK_TIMEOUT = 60   # 拿锁最多等多久（秒）
_BS_COOLDOWN     = 90   # 超时后熔断时长（秒）


def _bs_run(work_fn, *, timeout: float, label: str = "baostock"):
    """
    在受保护的环境下跑一段 baostock 工作。
    - 冷却期内直接抛 BaostockCooldown（不会去抢锁，保护 socket）
    - 拿不到锁 → BaostockBusy
    - 工作线程超过 timeout 不返回 → 标记冷却 + BaostockTimeout
    - work_fn 自身 raise 的异常原样抛出
    """
    now = _time.time()
    if now < _BS_HEALTH["unhealthy_until"]:
        wait_s = int(_BS_HEALTH["unhealthy_until"] - now)
        raise BaostockCooldown(f"{label}: 上次超时，冷却中（{wait_s}s 后再试）")

    if not _BS_LOCK.acquire(timeout=_BS_LOCK_TIMEOUT):
        raise BaostockBusy(f"{label}: 锁被长时间占用，请稍后再试")

    try:
        result_box: list = []
        error_box:  list = []
        done = threading.Event()

        def _runner():
            try:
                result_box.append(work_fn())
            except BaseException as e:
                error_box.append(e)
            finally:
                done.set()

        t = threading.Thread(target=_runner, daemon=True, name=f"bs-{label}")
        t.start()
        if not done.wait(timeout):
            # 进入冷却期；线程在后台继续（daemon，不阻塞进程退出）
            _BS_HEALTH["unhealthy_until"] = _time.time() + _BS_COOLDOWN
            _BS_HEALTH["last_error"] = f"timeout({timeout}s)"
            raise BaostockTimeout(
                f"{label}: 单次调用超过 {timeout}s 未返回，已熔断 {_BS_COOLDOWN}s（保护后端）"
            )
        if error_box:
            raise error_box[0]
        return result_box[0] if result_box else None
    finally:
        _BS_LOCK.release()


def get_baostock_health() -> dict:
    """暴露当前 baostock 健康状态（供 /health 或调试用）。"""
    now = _time.time()
    return {
        "healthy":          now >= _BS_HEALTH["unhealthy_until"],
        "cooldown_left_s":  max(0, int(_BS_HEALTH["unhealthy_until"] - now)),
        "last_error":       _BS_HEALTH["last_error"],
        "lock_timeout_s":   _BS_LOCK_TIMEOUT,
        "cooldown_s":       _BS_COOLDOWN,
    }


# ── 工具 ─────────────────────────────────────────────────────────────

def _bs_symbol(symbol: str) -> str:
    """6位代码 → baostock格式 sh.600519 / sz.000001"""
    if symbol.startswith("6"):
        return f"sh.{symbol}"
    return f"sz.{symbol}"


def _safe_float(val, default=None):
    try:
        v = float(val)
        import math
        return default if (math.isnan(v) or math.isinf(v)) else v
    except (TypeError, ValueError):
        return default


def _pct(val, default=None):
    """baostock百分数字段转为 % 字符串，如 0.1496 → '+14.96%'"""
    f = _safe_float(val)
    if f is None:
        return default
    s = f * 100
    return f"{s:+.2f}%" if s != 0 else "0.00%"


def _yi(val, default="--"):
    """元 → 亿元（保留2位）"""
    f = _safe_float(val)
    if f is None:
        return default
    return f"{f/1e8:.2f}亿"


def _current_quarter() -> tuple[int, int]:
    """返回当前最近已披露季度 (year, quarter)。保守回退一个季度。"""
    today = datetime.date.today()
    y, m = today.year, today.month
    q = (m - 1) // 3 + 1 - 1      # 当前季度 - 1
    if q == 0:
        q, y = 4, y - 1
    return y, q


def _prev_quarter(y, q):
    q -= 1
    if q == 0:
        q, y = 4, y - 1
    return y, q


# ── 技术指标（纯 pandas）─────────────────────────────────────────────

def _calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, float("nan"))
    return (100 - 100 / (1 + rs)).round(2)


def _calc_macd(close: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd     = (ema_fast - ema_slow).round(4)
    sig      = macd.ewm(span=signal, adjust=False).mean().round(4)
    return macd, sig


def _calc_bbands(close: pd.Series, period: int = 20):
    mid   = close.rolling(period).mean()
    sigma = close.rolling(period).std()
    return (mid - 2*sigma).round(2), mid.round(2), (mid + 2*sigma).round(2)


# ── 关键事件识别 ──────────────────────────────────────────────────────

def detect_key_events(ohlcv: list[dict], top_n: int = 8) -> list[dict]:
    """从日K数据识别量价异动关键节点（涨跌幅大且成交量放大）"""
    if len(ohlcv) < 5:
        return []
    df = pd.DataFrame(ohlcv)
    # 兼容 pct_change（统一字段名）和旧版 pctChg
    pct_col = "pct_change" if "pct_change" in df.columns else "pctChg"
    df["pct_change"] = pd.to_numeric(df.get(pct_col, 0), errors="coerce").fillna(0)
    df["volume"] = pd.to_numeric(df.get("volume", 0), errors="coerce").fillna(0)
    df["close"]  = pd.to_numeric(df.get("close",  0), errors="coerce")

    vol_ma20 = df["volume"].rolling(20, min_periods=5).mean()
    df["vol_ratio"] = (df["volume"] / vol_ma20).fillna(1).clip(upper=20)

    # 综合得分：|涨跌幅| × √成交量倍率（平衡两者权重）
    df["score"] = df["pct_change"].abs() * df["vol_ratio"].pow(0.5)

    top = df.nlargest(top_n, "score").sort_values("date")
    events = []
    for _, row in top.iterrows():
        pct = row["pct_change"]
        events.append({
            "date":      str(row["date"])[:10],
            "pct_chg":   round(float(pct), 2),
            "close":     round(float(row["close"]), 2) if pd.notna(row["close"]) else 0,
            "vol_ratio": round(float(row["vol_ratio"]), 1),
            "direction": "大涨" if pct > 3 else "大跌" if pct < -3 else ("上涨" if pct > 0 else "下跌"),
        })
    return events


# ── baostock 数据拉取（内部，需在 login 之后调用）────────────────────

def _fetch_name_and_industry(bs_code: str) -> tuple[str, dict]:
    name = bs_code
    industry = {}

    rs = bs.query_stock_basic(code=bs_code)
    if rs.next():
        row = rs.get_row_data()
        name = row[1] if len(row) > 1 else bs_code

    rs = bs.query_stock_industry(code=bs_code)
    if rs.next():
        row = dict(zip(rs.fields, rs.get_row_data()))
        industry = {
            "name":           row.get("industry", ""),
            "classification": row.get("industryClassification", ""),
        }
    return name, industry


# ── 全市场「代码 → 行业」映射（baostock 一次拉全市场，按日缓存 + 后台预热）────────
# 用途：规则库结果表的「行业」列与详情下拉。证监会行业分类，名称形如「J66货币金融服务」，
# 去掉前缀代码（字母+数字）得到「货币金融服务」。一次调用约 10s，故按天缓存并在启动时预热。
import re as _re

_industry_map_cache: dict = {"date": "", "data": {}, "building": False}


def _clean_industry_name(s: str) -> str:
    """去掉证监会分类的前缀代码：'J66货币金融服务' → '货币金融服务'。"""
    return _re.sub(r"^[A-Z]+\d*", "", (s or "").strip()).strip()


def _build_industry_map() -> dict:
    """一次性拉取全市场行业分类（持锁串行，约 10s）。返回 {6位代码: 行业名}。"""
    def _work() -> dict:
        out: dict[str, str] = {}
        lg = bs.login()
        if lg.error_code != "0":
            return out
        try:
            rs = bs.query_stock_industry()
            if rs.error_code != "0":
                return out
            while rs.next():
                row = dict(zip(rs.fields, rs.get_row_data()))
                code = row.get("code", "") or ""
                sym = code.split(".")[-1] if "." in code else code
                ind = _clean_industry_name(row.get("industry", ""))
                if sym and ind:
                    out[sym] = ind
        finally:
            try: bs.logout()
            except Exception: pass
        return out
    try:
        return _bs_run(_work, timeout=40, label="行业映射")
    except (BaostockBusy, BaostockTimeout, BaostockCooldown) as e:
        print(f"[industry-map] {e}")
        return {}


_name_code_cache: dict = {"date": "", "data": {}, "building": False}


def _build_name_code_map() -> dict:
    """从 baostock 行业列表里取「股票名→6位代码」，约 10s。akshare 不可用时的可靠来源。"""
    def _work() -> dict:
        out: dict[str, str] = {}
        lg = bs.login()
        if lg.error_code != "0":
            return out
        try:
            rs = bs.query_stock_industry()
            if rs.error_code != "0":
                return out
            while rs.next():
                row = dict(zip(rs.fields, rs.get_row_data()))
                code = row.get("code", "") or ""
                sym = code.split(".")[-1] if "." in code else code
                name = (row.get("code_name", "") or "").strip()
                if len(sym) == 6 and sym.isdigit() and name:
                    out[name] = sym
        finally:
            try: bs.logout()
            except Exception: pass
        return out
    try:
        return _bs_run(_work, timeout=40, label="名称映射")
    except (BaostockBusy, BaostockTimeout, BaostockCooldown) as e:
        print(f"[name-map] {e}")
        return {}


def get_name_code_map(block: bool = False) -> dict:
    """返回当日「股票名→6位代码」映射。block=True 同步构建（约 10s）；否则后台构建、先返回现有缓存。"""
    today = datetime.date.today().isoformat()
    c = _name_code_cache
    if c["date"] == today and c["data"]:
        return c["data"]
    if block:
        m = _build_name_code_map()
        if m:
            c["date"], c["data"] = today, m
        return c["data"]
    if not c["building"]:
        c["building"] = True

        def _bg():
            try:
                m = _build_name_code_map()
                if m:
                    _name_code_cache["date"] = today
                    _name_code_cache["data"] = m
            finally:
                _name_code_cache["building"] = False

        threading.Thread(target=_bg, daemon=True).start()
    return c["data"]


def get_industry_map(block: bool = False) -> dict:
    """返回当日「代码→行业」映射。
    block=True：同步构建（启动预热用，可阻塞约 10s）。
    block=False：立即返回当前缓存（可能为空/旧），并在后台异步构建（请求路径用，不阻塞）。
    """
    today = datetime.date.today().isoformat()
    c = _industry_map_cache
    if c["date"] == today and c["data"]:
        return c["data"]
    if block:
        m = _build_industry_map()
        if m:
            c["date"], c["data"] = today, m
        return c["data"]
    # 非阻塞：触发一次后台构建，先返回现有（可能为空或昨日）缓存
    if not c["building"]:
        c["building"] = True

        def _bg():
            try:
                m = _build_industry_map()
                if m:
                    _industry_map_cache["date"] = today
                    _industry_map_cache["data"] = m
            finally:
                _industry_map_cache["building"] = False

        threading.Thread(target=_bg, daemon=True).start()
    return c["data"]


# ── 单股「主营业务」（同花顺主营介绍，akshare，按股缓存）────────────────────────
# 纯 HTTP，约 0.5s/只，无需 baostock 锁；规则库详情下拉懒加载时调用。
_business_cache: dict = {}          # {symbol: {"date": iso, "data": {...}}}


def fetch_main_business(symbol: str) -> dict:
    """返回 {business, products, scope}。失败返回空串字段。按天缓存。"""
    today = datetime.date.today().isoformat()
    hit = _business_cache.get(symbol)
    if hit and hit.get("date") == today:
        return hit["data"]
    data = {"business": "", "products": "", "scope": ""}
    try:
        import akshare as ak
        df = ak.stock_zyjs_ths(symbol=symbol)
        if df is not None and not df.empty:
            row = df.iloc[0]
            data = {
                "business": str(row.get("主营业务", "") or "").strip(),
                "products": str(row.get("产品类型", "") or "").strip(),
                "scope":    str(row.get("经营范围", "") or "").strip(),
            }
    except Exception as exc:
        report_data_fallback(
            "akshare", "main_business", exc, context={"symbol": symbol}
        )
    _business_cache[symbol] = {"date": today, "data": data}
    return data


def _fetch_price(bs_code: str, start: str, end: str) -> dict:
    """拉取日K + 技术指标，返回完整 price dict"""
    start_fmt = f"{start[:4]}-{start[4:6]}-{start[6:]}"
    end_fmt   = f"{end[:4]}-{end[4:6]}-{end[6:]}"

    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,open,high,low,close,volume,pctChg,turn",
        start_date=start_fmt,
        end_date=end_fmt,
        frequency="d",
        adjustflag="2",
    )
    df = pd.DataFrame(rs.data, columns=rs.fields)
    if df.empty:
        return {"error": "未找到行情数据", "ohlcv": [], "summary": {}}

    # baostock 返回 pctChg，统一重命名为前端期望的 pct_change
    if "pctChg" in df.columns:
        df.rename(columns={"pctChg": "pct_change"}, inplace=True)

    for col in ["open", "high", "low", "close", "volume", "pct_change", "turn"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["ma5"]  = df["close"].rolling(5).mean().round(2)
    df["ma20"] = df["close"].rolling(20).mean().round(2)
    df["ma60"] = df["close"].rolling(60).mean().round(2)
    df["rsi14"], (df["macd"], df["macd_signal"]) = _calc_rsi(df["close"]), _calc_macd(df["close"])
    df["bb_lower"], df["bb_mid"], df["bb_upper"] = _calc_bbands(df["close"])

    last = df.iloc[-1]
    price_vs_ma = []
    for ma in ["ma5", "ma20", "ma60"]:
        if pd.notna(last[ma]) and pd.notna(last["close"]):
            diff = (last["close"] - last[ma]) / last[ma] * 100
            price_vs_ma.append(f"{'高于' if diff > 0 else '低于'}{ma.upper()} {abs(diff):.1f}%")

    # 日涨跌幅分布统计
    gain_days = int((df["pct_change"] > 0).sum())
    loss_days = int((df["pct_change"] < 0).sum())
    vol_mean  = float(df["volume"].mean())
    vol_max   = float(df["volume"].max())
    vol_max_date = str(df.loc[df["volume"].idxmax(), "date"])

    summary = {
        "start_price":   round(float(df["close"].iloc[0]),  2),
        "end_price":     round(float(df["close"].iloc[-1]), 2),
        "total_return":  round((df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100, 2),
        "max_price":     round(float(df["high"].max()),  2),
        "min_price":     round(float(df["low"].min()),   2),
        "avg_volume":    int(vol_mean),
        "max_volume":    int(vol_max),
        "max_vol_date":  vol_max_date[:10],
        "gain_days":     gain_days,
        "loss_days":     loss_days,
        "latest_rsi":    _safe_float(last["rsi14"]),
        "latest_macd":   _safe_float(last["macd"]),
        "latest_macd_s": _safe_float(last["macd_signal"]),
        "price_vs_ma":   "，".join(price_vs_ma) if price_vs_ma else "均线数据不足",
        "ma5_last":      _safe_float(last["ma5"]),
        "ma20_last":     _safe_float(last["ma20"]),
        "ma60_last":     _safe_float(last["ma60"]),
    }

    # OHLCV for chart（turn=换手率，供「昨日复盘」单日视图使用；前端图表会忽略多余字段）
    cols_chart = ["date", "open", "high", "low", "close", "volume", "turn", "pct_change", "ma5", "ma20", "ma60"]
    sub = df[[c for c in cols_chart if c in df.columns]].where(pd.notnull(df), None)
    ohlcv = sub.to_dict("records")

    # Key events
    events = detect_key_events(ohlcv)

    return {"ohlcv": ohlcv, "summary": summary, "key_events": events}


def _fetch_quarters(bs_code: str) -> dict:
    """拉取近4~8季度多维财务数据"""
    base_y, base_q = _current_quarter()

    def _query_loop(fn, n_quarters: int) -> list[dict]:
        rows, seen = [], set()
        y, q = base_y, base_q
        for _ in range(n_quarters):
            try:
                rs = fn(code=bs_code, year=y, quarter=q)
                fields = rs.fields
                while rs.next():
                    row = dict(zip(fields, rs.get_row_data()))
                    key = row.get("statDate") or row.get("pubDate", "")
                    if key and key not in seen:
                        seen.add(key)
                        rows.append(row)
            except Exception as exc:
                report_data_fallback(
                    "baostock",
                    "quarter_financials",
                    exc,
                    context={
                        "symbol": bs_code,
                        "year": y,
                        "quarter": q,
                        "query": getattr(fn, "__name__", type(fn).__name__),
                    },
                )
            y, q = _prev_quarter(y, q)
        rows.sort(key=lambda r: r.get("statDate", ""), reverse=True)
        return rows

    profit   = _query_loop(bs.query_profit_data,    8)
    growth   = _query_loop(bs.query_growth_data,    8)
    balance  = _query_loop(bs.query_balance_data,   8)
    cashflow = _query_loop(bs.query_cash_flow_data, 8)

    return {
        "profit":   profit[:8],
        "growth":   growth[:4],
        "balance":  balance[:4],
        "cashflow": cashflow[:4],
    }


# ── 新数据源：龙虎榜 / THS热点题材 / 行业横向 / 资金流向 ─────────────────

def get_lhb(symbol: str, start: str, end: str) -> list[dict]:
    """
    获取个股在复盘区间内的龙虎榜上榜记录（akshare）
    start/end 格式：YYYYMMDD
    """
    try:
        import akshare as ak, io, sys
        # 屏蔽 tqdm 进度条
        old_stderr = sys.stderr
        sys.stderr = io.StringIO()
        try:
            df = ak.stock_lhb_detail_em(start_date=start, end_date=end)
        finally:
            sys.stderr = old_stderr
        if df.empty:
            return []
        sub = df[df["代码"] == symbol]
        if sub.empty:
            return []
        records = []
        for _, row in sub.iterrows():
            net = float(row.get("龙虎榜净买额", 0) or 0)
            records.append({
                "date":        str(row.get("上榜日", ""))[:10],
                "reason":      str(row.get("上榜原因", "")),
                "close":       float(row.get("收盘价", 0) or 0),
                "pct_chg":     float(row.get("涨跌幅", 0) or 0),
                "net_buy":     round(net / 1e8, 2),          # 亿元
                "after_1d":    row.get("上榜后1日", "--"),
                "after_5d":    row.get("上榜后5日", "--"),
            })
        return records
    except Exception as exc:
        report_data_fallback(
            "akshare",
            "lhb_detail",
            exc,
            context={"symbol": symbol, "start": start, "end": end},
        )
        return []


def get_ths_hot_context(key_dates: list[str]) -> dict[str, list[str]]:
    """
    获取关键事件日的同花顺市场热点题材
    key_dates: ['2024-11-11', ...]
    返回: {'2024-11-11': ['AI+机器人', '低空经济', ...], ...}
    """
    import requests as _req
    sess = _req.Session()
    sess.trust_env = False

    result = {}
    for date in key_dates[:6]:  # 最多查6个关键日
        try:
            url = f"http://zx.10jqka.com.cn/event/api/getharden/date/{date}/"
            r = sess.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
            data = r.json().get("data", [])
            if not data:
                continue
            # 提取前20只股票的题材标签，去重并排序
            themes: dict[str, int] = {}
            for item in data[:40]:
                reason = item.get("reason", "")
                for tag in reason.split("+"):
                    tag = tag.strip()
                    if tag:
                        themes[tag] = themes.get(tag, 0) + 1
            # 按出现频次排序，取top10
            top = sorted(themes.items(), key=lambda x: -x[1])[:10]
            result[date] = [t for t, _ in top]
        except Exception as exc:
            report_data_fallback(
                "10jqka", "hot_context", exc, context={"date": date}
            )
            continue
    return result


def get_industry_rank(industry_name: str) -> dict:
    """
    获取该公司所属行业的横向对比数据（同花顺90行业）
    返回行业排名、涨跌幅、净流入等
    """
    try:
        import akshare as ak
        df = ak.stock_board_industry_summary_ths()
        if df.empty:
            return {}
        # 模糊匹配行业（baostock格式如 "C27医药制造业" → 提取关键词匹配THS板块）
        import re
        matched = None
        if industry_name:
            # 去掉开头字母+数字前缀，取核心中文词
            core = re.sub(r'^[A-Za-z]\d+\s*', '', industry_name)
            # 尝试不同长度的关键词（从长到短，取最佳匹配）
            for kw_len in [6, 4, 3, 2]:
                kw = core[:kw_len]
                if len(kw) < 2:
                    continue
                hits = df[df["板块"].str.contains(kw, na=False)]
                if not hits.empty:
                    matched = hits.iloc[0]
                    break

        # 全行业排行
        df["涨跌幅_num"] = df["涨跌幅"].apply(
            lambda x: float(str(x).replace('%','').strip()) if x else 0
        )
        df_sorted = df.sort_values("涨跌幅_num", ascending=False).reset_index(drop=True)
        df_sorted["排名"] = df_sorted.index + 1

        total = len(df_sorted)
        result = {"total_industries": total, "top5": [], "matched": None}

        # top5涨幅行业
        for _, row in df_sorted.head(5).iterrows():
            result["top5"].append({
                "name": row["板块"], "pct": row["涨跌幅"], "leader": row.get("领涨股", "")
            })

        # 匹配到的行业
        if matched is not None:
            rank_row = df_sorted[df_sorted["板块"] == matched["板块"]]
            rank = int(rank_row["排名"].iloc[0]) if not rank_row.empty else -1
            result["matched"] = {
                "name":      matched["板块"],
                "pct":       matched["涨跌幅"],
                "net_in":    matched.get("净流入", "--"),
                "up_count":  matched.get("上涨家数", "--"),
                "down_count":matched.get("下跌家数", "--"),
                "leader":    matched.get("领涨股", ""),
                "rank":      rank,
                "total":     total,
            }
        return result
    except Exception as exc:
        report_data_fallback(
            "akshare", "industry_rank", exc, context={"industry": industry_name}
        )
        return {}


# 全市场资金流向缓存（按period，15分钟有效）
_ff_cache: dict[str, tuple[float, "pd.DataFrame"]] = {}
_FF_TTL = 900  # 15分钟

def get_fund_flow(symbol: str) -> dict:
    """
    获取个股近期资金流向（akshare全市场资金流向，带15分钟内存缓存）
    避免每次请求都拉取全市场数据（104页，约30秒）
    注意：此函数应在独立线程中调用，由调用方控制超时（不在内部使用 signal）。
    """
    import time, io, sys, akshare as ak

    result = {}
    for period in ["即时", "3日", "5日"]:
        try:
            now = time.time()
            # 命中缓存
            if period in _ff_cache:
                ts, df_cached = _ff_cache[period]
                if now - ts < _FF_TTL:
                    df = df_cached
                else:
                    df = None
            else:
                df = None

            # 缓存未命中，重新拉取（屏蔽进度条输出）
            if df is None:
                old_stderr = sys.stderr
                sys.stderr = io.StringIO()
                try:
                    df = ak.stock_fund_flow_individual(symbol=period)
                finally:
                    sys.stderr = old_stderr
                if df is not None and not df.empty:
                    _ff_cache[period] = (now, df)

            if df is None or df.empty:
                continue

            col_code = df.columns[1]
            sub = df[df[col_code] == symbol]
            if sub.empty:
                continue
            row = sub.iloc[0]
            result[period] = {
                "inflow":   str(row.get("流入资金", "--")),
                "outflow":  str(row.get("流出资金", "--")),
                "net":      str(row.get("净额", "--")),
                "turnover": str(row.get("换手率", "--")),
            }
        except Exception as exc:
            report_data_fallback(
                "akshare",
                "fund_flow",
                exc,
                context={"symbol": symbol, "period": period},
            )
            continue
    return result


def get_stock_fund_flow_day(symbol: str) -> dict:
    """
    单只股票最近一个交易日的资金流向（东财个股资金流，单股接口，秒级返回）。
    与 get_fund_flow（全市场104页、>30s）不同，这里只拉这一只，适合「昨日复盘」。
    best-effort：失败/被代理屏蔽 → 返回 {}。
    """
    def _num(v):
        try:
            f = float(str(v).replace(",", "").strip())
            return None if (f != f) else f   # NaN guard
        except Exception:
            return None
    try:
        import akshare as ak, io, sys
        if symbol.startswith("6"):
            market = "sh"
        elif symbol.startswith(("8", "4")):
            market = "bj"
        else:
            market = "sz"
        # 与 get_lhb/get_news 一致：直连东财，best-effort（失败→{}，前端显示"暂无"）。
        # 不动环境代理：用户本机若靠代理上网，擅自清代理反而会弄坏。
        old_stderr = sys.stderr
        sys.stderr = io.StringIO()
        try:
            df = ak.stock_individual_fund_flow(stock=symbol, market=market)
        finally:
            sys.stderr = old_stderr
        if df is None or df.empty:
            return {}
        row = df.iloc[-1]
        return {
            "date":         str(row.get("日期", ""))[:10],
            "main_net":     _num(row.get("主力净流入-净额")),       # 元
            "main_net_pct": _num(row.get("主力净流入-净占比")),     # %
            "super_net":    _num(row.get("超大单净流入-净额")),
            "big_net":      _num(row.get("大单净流入-净额")),
            "mid_net":      _num(row.get("中单净流入-净额")),
            "small_net":    _num(row.get("小单净流入-净额")),
        }
    except Exception as exc:
        report_data_fallback(
            "akshare", "stock_fund_flow_day", exc, context={"symbol": symbol}
        )
        return {}


# ── 新闻 & 公告（akshare，独立于 baostock）────────────────────────────

def get_news(symbol: str, limit: int = 10) -> list[dict]:
    try:
        import akshare as ak
        df = ak.stock_news_em(symbol=symbol)
        if df.empty:
            return []
        records = []
        for _, row in df.head(limit).iterrows():
            records.append({
                "title":  row.get("新闻标题", ""),
                "time":   str(row.get("发布时间", ""))[:16],
                "source": row.get("新闻来源", ""),
            })
        return records
    except Exception as exc:
        report_data_fallback(
            "akshare", "stock_news", exc, context={"symbol": symbol}
        )
        return []


def get_announcements(symbol: str) -> list[dict]:
    try:
        import akshare as ak
        df = ak.stock_notice_report(stock=symbol)
        if df is None or df.empty:
            return []
        records = []
        for _, row in df.head(8).iterrows():
            records.append({
                "title": row.get("标题", ""),
                "date":  str(row.get("公告日期", ""))[:10],
                "type":  row.get("公告类型", ""),
            })
        return records
    except Exception as exc:
        report_data_fallback(
            "akshare", "stock_announcements", exc, context={"symbol": symbol}
        )
        return []


# ── 主入口 ────────────────────────────────────────────────────────────

def collect_all(symbol: str, start: str, end: str) -> dict:
    """聚合所有维度数据（单次 baostock 连接 + 串行辅助数据）

    注意：akshare 内部 py-mini-racer (V8 JS引擎) 不是线程安全的，
    多线程并发调用会导致进程崩溃（FATAL: address_pool_manager），
    因此辅助数据改为串行采集。
    """
    bs_code = _bs_symbol(symbol)

    def _bs_work():
        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"baostock 登录失败: {lg.error_msg}")
        try:
            name, industry = _fetch_name_and_industry(bs_code)
            price          = _fetch_price(bs_code, start, end)
            finance        = _fetch_quarters(bs_code)
            return name, industry, price, finance
        finally:
            try: bs.logout()
            except Exception: pass

    # 单股复盘可能拉 1-2 个月日 K + 几张财务表，正常 5-15s；超时上限 60s 已宽
    name, industry, price, finance = _bs_run(_bs_work, timeout=60, label=f"个股复盘 {symbol}")

    # 提取关键事件日期（用于THS热点查询）
    key_dates = [e["date"] for e in price.get("key_events", [])][:6]

    def _safe(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            report_data_fallback(
                "stock_data",
                getattr(fn, "__name__", type(fn).__name__),
                exc,
                context={"symbol": symbol},
            )
            return None

    # 串行采集辅助数据（避免 py-mini-racer 线程安全问题）
    # fund_flow 已禁用：akshare 全市场资金流向接口耗时 >60s，影响复盘响应速度
    aux = {
        "news":          _safe(get_news, symbol)                        or [],
        "announcements": _safe(get_announcements, symbol)               or [],
        "lhb":           _safe(get_lhb, symbol, start, end)            or [],
        "ths_hot":       _safe(get_ths_hot_context, key_dates)         or {},
        "industry_rank": _safe(get_industry_rank, industry.get("name", "")) or {},
        "fund_flow":     {},   # 暂不采集（akshare 接口响应过慢）
        "valuation":     _safe(fetch_valuation, symbol)               or {},
    }

    # 大盘相对强弱：取上证综指同区间收盘（sina 源，稳定），裁剪到个股区间
    index_series: list[dict] = []
    try:
        ohlcv = price.get("ohlcv", [])
        if ohlcv:
            start_d = str(ohlcv[0].get("date"))[:10]
            idx_df = fetch_index_history("sh000001", days_back=400)
            if idx_df is not None and not idx_df.empty:
                sub = idx_df[idx_df["date"] >= start_d]
                index_series = [
                    {"date": str(r["date"])[:10], "close": float(r["close"])}
                    for _, r in sub.iterrows()
                    if pd.notna(r.get("close"))
                ]
    except Exception as exc:
        report_data_fallback(
            "stock_data", "index_relative_strength", exc, context={"symbol": symbol}
        )
        index_series = []

    return {
        "symbol":         symbol,
        "name":           name,
        "industry":       industry,
        "period":         {"start": start, "end": end},
        "price":          price,
        "finance":        finance,
        "news":           aux["news"],
        "announcements":  aux["announcements"],
        "lhb":            aux["lhb"],
        "ths_hot":        aux["ths_hot"],
        "industry_rank":  aux["industry_rank"],
        "fund_flow":      aux["fund_flow"],
        "valuation":      aux["valuation"],
        "index_series":   index_series,
        "index_name":     "上证综指",
    }


# ── 昨日复盘：单日聚焦「这只票最近一个交易日发生了什么」───────────────────────

def _limit_pct(symbol: str) -> float:
    """该股每日涨跌停幅度（%）。无法识别 ST（5%），按板块给主流值。"""
    if symbol.startswith(("688", "689")):   # 科创板
        return 20.0
    if symbol.startswith("3"):              # 创业板
        return 20.0
    if symbol.startswith(("8", "4")):       # 北交所
        return 30.0
    return 10.0                             # 沪深主板


def collect_yesterday(symbol: str) -> dict:
    """
    单日聚焦复盘：只看最近一个交易日。
    拉 ~45 个自然日的日K（保证有 20 日均量/均线/位置上下文），取最后一根 = 「昨日」，
    再补当日维度：龙虎榜席位 / 同花顺热点题材 / 行业横向 / 单股资金流 / 新闻公告。
    """
    import datetime as _dt
    bs_code = _bs_symbol(symbol)
    today = _dt.date.today()
    start = (today - _dt.timedelta(days=45)).strftime("%Y%m%d")
    end   = today.strftime("%Y%m%d")

    def _bs_work():
        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"baostock 登录失败: {lg.error_msg}")
        try:
            name, industry = _fetch_name_and_industry(bs_code)
            price          = _fetch_price(bs_code, start, end)
            return name, industry, price
        finally:
            try: bs.logout()
            except Exception: pass

    name, industry, price = _bs_run(_bs_work, timeout=40, label=f"昨日复盘 {symbol}")

    ohlcv = price.get("ohlcv", [])
    if not ohlcv:
        return {"symbol": symbol, "name": name, "industry": industry,
                "error": "未找到行情数据", "daily": {}}

    last = ohlcv[-1]
    prev = ohlcv[-2] if len(ohlcv) >= 2 else None
    the_date = str(last.get("date"))[:10]

    def _f(v):
        try:
            x = float(v)
            return None if x != x else x
        except Exception:
            return None

    # 量比（vs 前 20 日均量，不含当日）
    prior = ohlcv[-21:-1] if len(ohlcv) > 1 else []
    vols  = [_f(b.get("volume")) or 0 for b in prior]
    avg_vol   = (sum(vols) / len(vols)) if vols else 0
    cur_vol   = _f(last.get("volume")) or 0
    vol_ratio = (cur_vol / avg_vol) if avg_vol else None

    prev_close = _f(prev.get("close")) if prev else None
    high, low  = _f(last.get("high")), _f(last.get("low"))
    amplitude  = round((high - low) / prev_close * 100, 2) if (prev_close and high is not None and low is not None) else None

    pct   = _f(last.get("pct_change")) or 0.0
    limit = _limit_pct(symbol)
    s     = price.get("summary", {})

    daily = {
        "date":        the_date,
        "open":        _f(last.get("open")),
        "high":        high,
        "low":         low,
        "close":       _f(last.get("close")),
        "prev_close":  prev_close,
        "pct_change":  round(pct, 2),
        "amplitude":   amplitude,
        "volume":      int(cur_vol) if cur_vol else None,
        "avg_vol20":   int(avg_vol) if avg_vol else None,
        "vol_ratio":   round(vol_ratio, 2) if vol_ratio else None,
        "turn":        _f(last.get("turn")),                 # 换手率 %
        "ma5":         s.get("ma5_last"),
        "ma20":        s.get("ma20_last"),
        "ma60":        s.get("ma60_last"),
        "price_vs_ma": s.get("price_vs_ma"),
        "rsi":         s.get("latest_rsi"),
        "is_up_limit": pct >= (limit - 0.6),
        "is_dn_limit": pct <= -(limit - 0.6),
        "limit_pct":   limit,
    }

    the_date_compact = the_date.replace("-", "")

    def _safe(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            report_data_fallback(
                "stock_data",
                getattr(fn, "__name__", type(fn).__name__),
                exc,
                context={"symbol": symbol, "review": "yesterday"},
            )
            return None

    lhb       = _safe(get_lhb, symbol, the_date_compact, the_date_compact) or []
    ths_hot   = _safe(get_ths_hot_context, [the_date]) or {}
    ind_rank  = _safe(get_industry_rank, industry.get("name", "")) or {}
    fund_flow = _safe(get_stock_fund_flow_day, symbol) or {}
    # 新闻/公告只保留当日（best-effort：接口按时间倒序，截当日及最近）
    news_all  = _safe(get_news, symbol) or []
    anns_all  = _safe(get_announcements, symbol) or []
    news_day  = [n for n in news_all if str(n.get("time", "")).startswith(the_date)] or news_all[:5]
    anns_day  = [a for a in anns_all if str(a.get("date", "")).startswith(the_date)] or anns_all[:4]

    return {
        "symbol":        symbol,
        "name":          name,
        "industry":      industry,
        "daily":         daily,
        "lhb":           lhb,
        "ths_hot":       ths_hot,
        "industry_rank": ind_rank,
        "fund_flow":     fund_flow,
        "news":          news_day,
        "announcements": anns_day,
    }


# ── 批量快速今日复盘 ──────────────────────────────────────────────────────

# 盘中按 5 分钟桶刷新，盘后按日期缓存。技术结构不能在开盘后被冻结一整天。
_quick_batch_cache: dict[str, dict] = {}   # cache_key → {symbol: result}


def _calc_streak(pct_series: "pd.Series") -> int:
    """计算连涨/连跌天数（正=连涨，负=连跌），最近一天在末尾"""
    vals = list(pct_series.dropna())
    if not vals:
        return 0
    direction = 1 if vals[-1] > 0 else -1
    count = 0
    for v in reversed(vals):
        if (v > 0 and direction == 1) or (v < 0 and direction == -1):
            count += 1
        else:
            break
    return count * direction


def _quick_review_one(bs_code: str, symbol: str) -> dict:
    """单只股票快速技术复盘（baostock 已登录状态下调用）"""
    import math

    end_date   = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=90)   # 拉90天保证MA60有数
    start_fmt  = start_date.strftime("%Y-%m-%d")
    end_fmt    = end_date.strftime("%Y-%m-%d")

    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,open,high,low,close,volume,pctChg,turn",
        start_date=start_fmt,
        end_date=end_fmt,
        frequency="d",
        adjustflag="2",
    )
    df = pd.DataFrame(rs.data, columns=rs.fields)
    if df.empty or len(df) < 2:
        return {"symbol": symbol, "error": "无数据"}

    for col in ["open", "high", "low", "close", "volume", "pctChg", "turn"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.rename(columns={"pctChg": "pct_change"}, inplace=True)
    df = df.dropna(subset=["close"]).reset_index(drop=True)

    # 均线
    df["ma5"]  = df["close"].rolling(5,  min_periods=1).mean().round(2)
    df["ma20"] = df["close"].rolling(20, min_periods=10).mean().round(2)
    df["ma60"] = df["close"].rolling(60, min_periods=30).mean().round(2)

    # RSI14
    delta = df["close"].diff()
    gain  = delta.clip(lower=0).rolling(14, min_periods=14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14, min_periods=14).mean()
    rs_val = gain / loss.replace(0, float("nan"))
    df["rsi14"] = (100 - 100 / (1 + rs_val)).round(2)

    # MACD (12/26/9)
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    macd_line   = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    df["macd"]        = macd_line.round(4)
    df["macd_signal"] = signal_line.round(4)
    df["macd_hist"]   = (macd_line - signal_line).round(4)

    # 布林带 (20, 2)
    ma20  = df["close"].rolling(20, min_periods=10).mean()
    std20 = df["close"].rolling(20, min_periods=10).std()
    df["bb_upper"] = (ma20 + 2 * std20).round(2)
    df["bb_lower"] = (ma20 - 2 * std20).round(2)

    # 量比（今日成交量 / 近20日均量）
    df["vol_ma20"] = df["volume"].rolling(20, min_periods=5).mean()
    df["vol_ratio"] = (df["volume"] / df["vol_ma20"]).round(2)

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last

    def sf(v):
        try:
            f = float(v)
            return None if (math.isnan(f) or math.isinf(f)) else round(f, 4)
        except Exception:
            return None

    close    = sf(last["close"]) or 0
    ma5_v    = sf(last["ma5"])
    ma20_v   = sf(last["ma20"])
    ma60_v   = sf(last["ma60"])
    bb_upper = sf(last["bb_upper"])
    bb_lower = sf(last["bb_lower"])

    # 布林带位置 0=下轨 1=上轨
    bb_pct = None
    if bb_upper and bb_lower and bb_upper != bb_lower:
        bb_pct = round((close - bb_lower) / (bb_upper - bb_lower), 3)

    # MACD 状态
    macd_hist     = sf(last["macd_hist"]) or 0
    prev_macd_hist = sf(prev["macd_hist"]) or 0
    if macd_hist > 0 and prev_macd_hist <= 0:
        macd_status = "金叉"
    elif macd_hist < 0 and prev_macd_hist >= 0:
        macd_status = "死叉"
    elif macd_hist > 0:
        macd_status = "多头"
    else:
        macd_status = "空头"

    # 连涨/连跌
    streak = _calc_streak(df["pct_change"].tail(20))

    # 信号标签
    pct   = sf(last["pct_change"]) or 0
    vol_r = sf(last["vol_ratio"])  or 1
    tags: list[str] = []
    if pct >= 9.5:   tags.append("🚀 涨停")
    elif pct <= -9.5: tags.append("💀 跌停")
    elif pct >= 5:   tags.append("🔥 大涨")
    elif pct <= -5:  tags.append("⚠️ 大跌")

    if vol_r >= 2:    tags.append("📢 量能爆发")
    elif vol_r >= 1.5: tags.append("📈 放量")
    elif vol_r <= 0.5: tags.append("📉 极度缩量")
    elif vol_r <= 0.7: tags.append("📉 缩量")

    if ma5_v and close > ma5_v * 1.03:   tags.append("⬆️ 强势站MA5上方")
    elif ma5_v and close < ma5_v * 0.97: tags.append("⬇️ 弱势跌破MA5")

    if macd_status in ("金叉", "死叉"):   tags.append(f"⚡ MACD{macd_status}")

    rsi = sf(last["rsi14"])
    if rsi and rsi >= 70:  tags.append("🔴 RSI超买")
    elif rsi and rsi <= 30: tags.append("🟢 RSI超卖")

    if streak >= 5:   tags.append(f"📊 连涨{streak}天")
    elif streak <= -5: tags.append(f"📊 连跌{abs(streak)}天")

    # 今日高低点特征
    high_v = sf(last["high"]) or 0
    low_v  = sf(last["low"])  or 0
    if high_v and ma20_v and high_v > ma20_v * 1.05:
        tags.append("🏔️ 突破MA20")
    if bb_pct is not None:
        if bb_pct >= 0.95:   tags.append("🔺 触碰布林上轨")
        elif bb_pct <= 0.05: tags.append("🔻 触碰布林下轨")

    # 近30/60日创新高/低
    recent30 = df["close"].tail(30)
    if close >= float(recent30.max()):   tags.append("🆕 近30日新高")
    elif close <= float(recent30.min()): tags.append("🆘 近30日新低")

    return {
        "symbol": symbol,
        "today": {
            "date":       str(last["date"])[:10],
            "open":       sf(last["open"]),
            "high":       sf(last["high"]),
            "low":        sf(last["low"]),
            "close":      close,
            "pct_change": pct,
            "volume":     int(last["volume"]) if pd.notna(last["volume"]) else 0,
            "turn":       sf(last["turn"]),
        },
        "technical": {
            "ma5":         ma5_v,
            "ma20":        ma20_v,
            "ma60":        ma60_v,
            "ma5_pct":     round((close - ma5_v) / ma5_v * 100, 2) if ma5_v else None,
            "ma20_pct":    round((close - ma20_v) / ma20_v * 100, 2) if ma20_v else None,
            "ma60_pct":    round((close - ma60_v) / ma60_v * 100, 2) if ma60_v else None,
            "rsi14":       rsi,
            "macd":        sf(last["macd"]),
            "macd_signal": sf(last["macd_signal"]),
            "macd_hist":   sf(last["macd_hist"]),
            "macd_status": macd_status,
            "bb_upper":    bb_upper,
            "bb_lower":    bb_lower,
            "bb_pct":      bb_pct,
            "vol_ratio":   sf(last["vol_ratio"]),
        },
        "trend": {
            "streak":    streak,
            "above_ma5":  bool(ma5_v  and close > ma5_v),
            "above_ma20": bool(ma20_v and close > ma20_v),
            "above_ma60": bool(ma60_v and close > ma60_v),
            "tags":       tags,
        },
    }


def fetch_quick_batch(symbols: list[str]) -> list[dict]:
    """
    批量快速技术复盘。盘中每 5 分钟刷新，收盘后数据固定。
    baostock 单例 socket，加全局锁串行执行。
    """
    now_dt = datetime.datetime.now()
    today_str = now_dt.date().isoformat()
    minute = now_dt.hour * 60 + now_dt.minute
    is_intraday = now_dt.weekday() < 5 and (570 <= minute < 690 or 780 <= minute < 900)
    cache_key = f"{today_str}:{minute // 5}" if is_intraday else today_str
    cached = _quick_batch_cache.get(cache_key, {})
    # 网络抖动产生的“无数据/繁忙”不能缓存一整天；下一次请求必须允许重试。
    missing = [s for s in symbols if s not in cached or cached[s].get("error")]

    if missing:
        def _work():
            bs.login()
            try:
                for sym in missing:
                    bs_code = _bs_symbol(sym)
                    try:
                        result = _quick_review_one(bs_code, sym)
                    except Exception as exc:
                        report_data_fallback(
                            "baostock",
                            "quick_review",
                            exc,
                            context={"symbol": sym},
                        )
                        result = {"symbol": sym, "error": str(exc)}
                    cached[sym] = result
            finally:
                try: bs.logout()
                except Exception: pass
        try:
            # 单只 ~0.3s，120 只批 ~40s；上限 120s 留足余量
            _bs_run(_work, timeout=120, label=f"快速复盘 batch({len(missing)})")
            _quick_batch_cache[cache_key] = cached
            if len(_quick_batch_cache) > 64:
                for old_key in list(_quick_batch_cache)[:-32]:
                    _quick_batch_cache.pop(old_key, None)
        except (BaostockBusy, BaostockTimeout, BaostockCooldown) as e:
            report_data_fallback(
                "baostock",
                "quick_review_batch",
                e,
                context={"symbols": len(missing)},
            )
            # 未完成的留空（每只标 error），命中缓存的仍可返回
            for s in missing:
                cached.setdefault(s, {"symbol": s, "error": str(e)})

    return [cached.get(s, {"symbol": s, "error": "未找到"}) for s in symbols]


# ── 回测：批量历史日 K + 衍生指标 ────────────────────────────────────────────────
# 一次 baostock 会话拉多只股票的近 N 天日K，附带均线/量比/振幅，供 backtest_service 重放规则。
# 按日缓存（{date_str: {symbol: DataFrame}}），多次回测/换规则免重复拉取。
_history_cache: dict[str, dict] = {}

# 指数缓存：基准（上证综指/沪深300/中证500）独立缓存，命中即返回
_index_cache: dict[str, dict] = {}   # {date_str: {bs_code: DataFrame}}

# 计算衍生列：MA5/MA20/MA60、量比、振幅、市值（需总股本时调用方提供）
def _enrich_history(df: "pd.DataFrame") -> "pd.DataFrame":
    if df is None or df.empty:
        return df
    for col in ("open", "high", "low", "close", "volume", "amount", "pct_change", "turn", "pe", "pb"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["ma5"]   = df["close"].rolling(5).mean()
    df["ma20"]  = df["close"].rolling(20).mean()
    df["ma60"]  = df["close"].rolling(60).mean()
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ratio"] = (df["volume"] / df["vol_ma5"]).round(2)
    # 振幅 = (high-low)/preclose*100
    df["prev_close"] = df["close"].shift(1)
    df["amplitude"]  = ((df["high"] - df["low"]) / df["prev_close"] * 100).round(2)
    df["amount_yi"]  = (df["amount"] / 1e8).round(3)
    return df


def _baostock_history_one(bs_code: str, start_fmt: str, end_fmt: str) -> "pd.DataFrame":
    """baostock 单只历史日K（已登录态下调用），字段对齐 fetch_history_batch 的输出。"""
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,open,high,low,close,volume,amount,turn,pctChg,isST",
        start_date=start_fmt, end_date=end_fmt, frequency="d", adjustflag="2",
    )
    df = pd.DataFrame(rs.data, columns=rs.fields)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(columns={"pctChg": "pct_change"})
    df["date"] = df["date"].astype(str)
    for col in ("open", "high", "low", "close", "volume", "amount", "turn", "pct_change"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # baostock isST: "1"=ST
    df["is_st"] = df["isST"].astype(str).str.strip().isin(("1", "1.0")) if "isST" in df.columns else False
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    if df.empty:
        return df
    return _enrich_history(df)


def _baostock_history_batch(symbols: list[str], start_fmt: str, end_fmt: str,
                            progress_cb=None) -> dict:
    """
    东财(akshare)不可达时的兜底：用 baostock 单会话串行拉取候选股历史日K。
    单次登录、循环查询，受 _bs_run 熔断/锁保护；拿到多少返回多少（部分失败不影响整体）。
    """
    fetched: dict[str, "pd.DataFrame"] = {}
    if not symbols:
        return fetched

    def _work():
        lg = bs.login()
        if getattr(lg, "error_code", "0") != "0":
            return fetched
        try:
            for j, sym in enumerate(symbols):
                try:
                    fetched[sym] = _baostock_history_one(_bs_symbol(sym), start_fmt, end_fmt)
                except Exception as exc:
                    report_data_fallback(
                        "baostock",
                        "backtest_history",
                        exc,
                        context={"symbol": sym},
                    )
                    fetched[sym] = pd.DataFrame()
                if progress_cb and ((j + 1) % 10 == 0 or j + 1 == len(symbols)):
                    try: progress_cb(j + 1, len(symbols))
                    except Exception: pass
        finally:
            try: bs.logout()
            except Exception: pass
        return fetched

    timeout = min(600.0, 40.0 + 0.6 * len(symbols))
    try:
        _bs_run(_work, timeout=timeout, label=f"回测历史 baostock({len(symbols)})")
    except (BaostockBusy, BaostockTimeout, BaostockCooldown) as exc:
        report_data_fallback(
            "baostock",
            "backtest_history_batch",
            exc,
            context={"symbols": len(symbols)},
        )
        pass   # 拿到多少算多少，部分数据也能跑回测
    return fetched


def fetch_history_batch(symbols: list[str], days_back: int = 200,
                        progress_cb=None) -> dict:
    """
    返回 {symbol: DataFrame(date,open,high,low,close,volume,amount,pct_change,turn,
                            is_st,ma5,ma20,ma60,vol_ratio,amplitude,amount_yi)}
    - 数据源：akshare 东财日 K（线程池并发 12，比 baostock 单 socket 快 ~10×）
    - 按日缓存：同一天反复回测命中即返回
    - PE/PB 不在历史回测字段里；这两类条件交由 backtest_service 跳过并提示
    - 失败的 symbol 返回空 DataFrame（不影响其他股）
    - progress_cb(done, total) 可选：每完成一只调用一次，供 UI 显示进度
    """
    if not symbols:
        return {}
    import akshare as ak
    from concurrent.futures import ThreadPoolExecutor, as_completed

    today_str = datetime.date.today().isoformat()
    end_date  = datetime.date.today()
    start_buffer = max(60, int(days_back * 1.45) + 60)
    start_d = (end_date - datetime.timedelta(days=start_buffer))
    start_str = start_d.strftime("%Y%m%d")
    end_str   = end_date.strftime("%Y%m%d")

    cached = _history_cache.setdefault(today_str, {})
    missing = [s for s in symbols if s not in cached]
    total = len(missing)
    if not total:
        if progress_cb:
            try: progress_cb(len(symbols), len(symbols))
            except Exception: pass
        return {s: cached.get(s, pd.DataFrame()) for s in symbols}

    def _one(sym: str):
        # 北交所等 akshare 也有，先全部尝试
        try:
            df = ak.stock_zh_a_hist(symbol=sym, period="daily",
                                    start_date=start_str, end_date=end_str,
                                    adjust="qfq")
            if df is None or df.empty:
                return sym, pd.DataFrame()
            df = df.rename(columns={
                "日期":   "date", "开盘":"open", "收盘":"close",
                "最高":   "high", "最低":"low",  "成交量":"volume",
                "成交额": "amount", "振幅":"amplitude_raw",
                "涨跌幅": "pct_change", "换手率":"turn",
            })
            df["date"] = df["date"].astype(str)
            df["is_st"] = False   # akshare 无 ST 列，回测里按代码/名称无法判断 → 默认 False
            df = _enrich_history(df)
            # akshare 已经给了振幅，覆盖 _enrich_history 算的（_enrich 用 prev_close 算更准但偶有 NaN）
            if "amplitude_raw" in df.columns:
                df["amplitude"] = pd.to_numeric(df["amplitude_raw"], errors="coerce")
            return sym, df
        except Exception as exc:
            report_data_fallback(
                "akshare",
                "backtest_history",
                exc,
                context={"symbol": sym},
            )
            return sym, pd.DataFrame()

    done = 0
    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = {ex.submit(_one, s): s for s in missing}
        for fut in as_completed(futures):
            sym, df = fut.result()
            cached[sym] = df
            done += 1
            if progress_cb and (done % 10 == 0 or done == total):
                try: progress_cb(done, total)
                except Exception: pass

    # ── baostock 兜底 ──────────────────────────────────────────────
    # 公司代理屏蔽东财（akshare 主源），导致候选股 K 线全空 → 回测全 0。
    # baostock 走自有协议（用户机器上复盘/持仓功能均依赖它），在东财不可达时
    # 仍能取到日 K。这里把东财取空的 symbol 收集起来，统一用 baostock 单会话补齐。
    empty_syms = [s for s in missing if cached.get(s) is None or cached.get(s).empty]
    if empty_syms:
        try:
            bs_fetched = _baostock_history_batch(
                empty_syms,
                start_d.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d"),
                progress_cb,
            )
            for sym, df in bs_fetched.items():
                if df is not None and not df.empty:
                    cached[sym] = df
        except Exception as exc:
            report_data_fallback(
                "baostock",
                "backtest_history_fallback",
                exc,
                context={"symbols": len(empty_syms)},
            )
            pass  # baostock 也不可用时保持空帧，不影响其他股

    _history_cache[today_str] = cached
    return {s: cached.get(s, pd.DataFrame()) for s in symbols}


def fetch_index_history(ak_code: str, days_back: int = 200) -> "pd.DataFrame":
    """
    指数日K（上证综指 sh000001 / 沪深300 sh000300 / 中证500 sh000905）。
    使用 akshare 一次性拉取并按日缓存。
    """
    today_str = datetime.date.today().isoformat()
    cache = _index_cache.setdefault(today_str, {})
    if ak_code in cache:
        return cache[ak_code]
    try:
        import akshare as ak
        df = ak.stock_zh_index_daily(symbol=ak_code)
        if df is None or df.empty:
            df = pd.DataFrame()
        else:
            df = df.rename(columns={"date": "date"})
            df["date"] = df["date"].astype(str)
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            # 只保留窗口内
            end_d = datetime.date.today()
            start_d = (end_d - datetime.timedelta(days=int(days_back * 1.45) + 30)).isoformat()
            df = df[df["date"] >= start_d].reset_index(drop=True)
            df["pct_change"] = df["close"].pct_change() * 100
    except Exception as exc:
        report_data_fallback(
            "akshare", "index_history", exc, context={"index": ak_code}
        )
        df = pd.DataFrame()
    cache[ak_code] = df
    return df


# ── 估值分位（PE/PB 在近年所处历史分位）──────────────────────────────────────
_valuation_cache: dict[str, dict] = {}   # date_str → {symbol: result}


def fetch_valuation(symbol: str) -> dict:
    """
    个股估值分位（best-effort，数据源不可用时返回 {}）。
    返回 {pe, pe_pct, pb, pb_pct, mv_yi, as_of}：
      pe/pb        当前 PE(TTM)/PB
      pe_pct/pb_pct 当前值在 akshare 返回的历史序列中的百分位（0=最低，100=最高）
    用 akshare ak.stock_value_em（东财，日频历史，可算分位）。
    """
    today_str = datetime.date.today().isoformat()
    cache = _valuation_cache.setdefault(today_str, {})
    if symbol in cache:
        return cache[symbol]

    result: dict = {}
    try:
        import akshare as ak
        df = ak.stock_value_em(symbol=symbol)
        if df is not None and not df.empty:
            cols = list(df.columns)

            def _find(*keys):
                for c in cols:
                    if all(k in c for k in keys):
                        return c
                return None

            pe_col = _find("PE", "TTM") or _find("市盈率", "TTM") or _find("PE")
            pb_col = _find("市净率") or _find("PB")
            mv_col = _find("总市值")
            date_col = _find("数据日期") or _find("日期") or cols[0]

            def _pct_rank(series, val):
                vals = [_safe_float(x) for x in series]
                vals = [v for v in vals if v is not None and v > 0]
                if not vals or val is None or val <= 0:
                    return None
                below = sum(1 for v in vals if v <= val)
                return round(below / len(vals) * 100, 1)

            last = df.iloc[-1]
            pe = _safe_float(last.get(pe_col)) if pe_col else None
            pb = _safe_float(last.get(pb_col)) if pb_col else None
            mv = _safe_float(last.get(mv_col)) if mv_col else None
            result = {
                "pe": round(pe, 2) if pe is not None else None,
                "pb": round(pb, 2) if pb is not None else None,
                "pe_pct": _pct_rank(df[pe_col], pe) if pe_col else None,
                "pb_pct": _pct_rank(df[pb_col], pb) if pb_col else None,
                "mv_yi": round(mv / 1e8, 1) if mv is not None else None,
                "as_of": str(last.get(date_col, ""))[:10],
                "history_n": int(len(df)),
            }
    except Exception as exc:
        report_data_fallback(
            "akshare", "valuation", exc, context={"symbol": symbol}
        )
        result = {}

    cache[symbol] = result
    return result


# ── 多日「形态」检测 ───────────────────────────────────────────────────────────
# 用于选股引擎的「形态」后置过滤：单张全市场快照无法判断多日趋势/均线/量能，
# 故对数值筛选后的小候选集，逐只拉近半年日线做形态判定（按交易日缓存）。
# 一次拉取即计算所有形态，避免每种形态各拉一次。

_pattern_cache: dict[str, dict] = {}   # date_str → {symbol: {pattern_key: bool}}


def _is_mild_vol_uptrend(vols: list[float], window: int = 5) -> bool:
    """
    判断「成交量像台阶一样温和放大、一步步往上爬」。
    vols：日成交量序列，旧→新。取最近 window 日判定。
    规则：① 整体放大（末日明显高于首日）② 后半段均量 > 前半段
         ③ 台阶式（最多允许一次明显回落）④ 温和（无单日暴量/异动）。
    """
    vs = [float(v) for v in vols if v and float(v) > 0]
    if len(vs) < max(4, window - 1):     # 数据不足（次新股等）→ 不判通过
        return False
    vs = vs[-window:]
    n = len(vs)
    # ① 整体放大：最后一天明显高于第一天
    if vs[-1] <= vs[0] * 1.05:
        return False
    # ② 趋势向上：后半段均量 > 前半段均量
    half = max(1, n // 2)
    early = sum(vs[:half]) / half
    late  = sum(vs[n - half:]) / half
    if late <= early * 1.05:
        return False
    # ③ 台阶式：最多允许一次明显回落（单日跌幅 > 5%）
    drops = sum(1 for i in range(1, n) if vs[i] < vs[i - 1] * 0.95)
    if drops > 1:
        return False
    # ④ 温和：无单日暴量（今日 > 昨日 2.2 倍视为放量过猛/异动，非「温和」）
    for i in range(1, n):
        if vs[i] > vs[i - 1] * 2.2:
            return False
    return True


# 所有形态的 key（与 services.screen_service.PATTERNS 对应；缺失数据时全部 False）
PATTERN_KEYS = (
    "vol_uptrend",   # 成交量温和放大（台阶式）
    "ma_bullish",    # 均线多头排列 MA5>MA20>MA60 且收盘站上MA5
    "above_ma20",    # 收盘站上20日线
    "macd_golden",   # MACD 金叉（今日 hist 由负转正）
    "new_high_60",   # 创 60 日新高
    "streak_up",     # 连涨 ≥ 3 天
)


def _compute_patterns(df: pd.DataFrame) -> dict:
    """
    输入 baostock 日线 DataFrame（含 close/volume/pctChg，旧→新），
    一次性计算所有形态，返回 {pattern_key: bool}。数据不足的形态 → False。
    """
    out = {k: False for k in PATTERN_KEYS}
    if df is None or df.empty:
        return out

    close = pd.to_numeric(df.get("close"), errors="coerce")
    vol   = pd.to_numeric(df.get("volume"), errors="coerce")
    pct   = pd.to_numeric(df.get("pctChg"), errors="coerce")
    close = close.dropna().reset_index(drop=True)
    if len(close) < 5:
        return out

    last = float(close.iloc[-1])

    # ① 成交量温和放大
    vols = vol.dropna().tolist()
    out["vol_uptrend"] = _is_mild_vol_uptrend(vols)

    # 均线
    ma5  = close.rolling(5,  min_periods=5).mean()
    ma20 = close.rolling(20, min_periods=20).mean()
    ma60 = close.rolling(60, min_periods=60).mean()
    ma5_v  = float(ma5.iloc[-1])  if not pd.isna(ma5.iloc[-1])  else None
    ma20_v = float(ma20.iloc[-1]) if not pd.isna(ma20.iloc[-1]) else None
    ma60_v = float(ma60.iloc[-1]) if not pd.isna(ma60.iloc[-1]) else None

    # ② 均线多头排列：MA5 > MA20 > MA60 且收盘站上 MA5
    if ma5_v and ma20_v and ma60_v:
        out["ma_bullish"] = (ma5_v > ma20_v > ma60_v) and (last >= ma5_v)

    # ③ 站上 20 日线
    if ma20_v:
        out["above_ma20"] = last >= ma20_v

    # ④ MACD 金叉：今日 hist 由负（或0）转正
    if len(close) >= 35:
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal    = macd_line.ewm(span=9, adjust=False).mean()
        hist = macd_line - signal
        if len(hist) >= 2:
            out["macd_golden"] = bool(hist.iloc[-1] > 0 and hist.iloc[-2] <= 0)

    # ⑤ 创 60 日新高：收盘 ≥ 近 60 日最高收盘
    if len(close) >= 20:
        window = close.iloc[-60:] if len(close) >= 60 else close
        out["new_high_60"] = last >= float(window.max()) - 1e-6

    # ⑥ 连涨 ≥ 3 天（用 pctChg；缺失则用收盘差分）
    pcts = pct.dropna().tolist()
    if len(pcts) >= 3:
        streak = 0
        for p in reversed(pcts):
            if p > 0:
                streak += 1
            else:
                break
        out["streak_up"] = streak >= 3
    elif len(close) >= 4:
        streak = 0
        for i in range(len(close) - 1, 0, -1):
            if close.iloc[i] > close.iloc[i - 1]:
                streak += 1
            else:
                break
        out["streak_up"] = streak >= 3

    return out


def fetch_patterns_batch(symbols: list[str]) -> dict:
    """
    返回 {symbol: {pattern_key: bool}}。
    数据源：baostock 近 ~190 天日线（确保 MA60 有效），前复权 adjustflag="2"，
    按交易日缓存（收盘后固定）。北交所(8/4/9)/数据不足/异常 → 全 False。
    baostock 单例 socket，加全局锁串行执行；一次拉取算齐所有形态。
    """
    if not symbols:
        return {}
    today_str = datetime.date.today().isoformat()
    end_date  = datetime.date.today()
    # 110 自然日 ≈ 73 个交易日，足够算 MA60（60 交易日）与 MACD；窗口越小拉取越快
    start_fmt = (end_date - datetime.timedelta(days=115)).strftime("%Y-%m-%d")
    end_fmt   = end_date.strftime("%Y-%m-%d")
    empty = {k: False for k in PATTERN_KEYS}

    cache   = _pattern_cache.get(today_str, {})
    missing = [s for s in symbols if s not in cache]
    if missing:
        def _work():
            bs.login()
            try:
                for sym in missing:
                    res = dict(empty)
                    # 北交所(8/4/9 开头) baostock 代码映射不可靠 → 跳过
                    if not (sym.startswith("8") or sym.startswith("4") or sym.startswith("9")):
                        try:
                            rs = bs.query_history_k_data_plus(
                                _bs_symbol(sym), "date,close,volume,pctChg",
                                start_date=start_fmt, end_date=end_fmt,
                                frequency="d", adjustflag="2",
                            )
                            df = pd.DataFrame(rs.data, columns=rs.fields)
                            res = _compute_patterns(df)
                        except Exception as exc:
                            report_data_fallback(
                                "baostock",
                                "stock_patterns",
                                exc,
                                context={"symbol": sym},
                            )
                            res = dict(empty)
                    cache[sym] = res
            finally:
                try: bs.logout()
                except Exception: pass
        try:
            # 单只 ~0.7s，120 只上限 ~85s；超时 120s
            _bs_run(_work, timeout=120, label=f"形态判定 batch({len(missing)})")
            _pattern_cache[today_str] = cache
        except (BaostockBusy, BaostockTimeout, BaostockCooldown) as e:
            report_data_fallback(
                "baostock",
                "stock_patterns_batch",
                e,
                context={"symbols": len(missing)},
            )
            # 未跑到的留空（全 False）；调用方有 try/except 兜底
            print(f"[patterns] {e}")
            for s in missing:
                cache.setdefault(s, dict(empty))

    return {s: cache.get(s, dict(empty)) for s in symbols}


def fetch_vol_uptrend_set(symbols: list[str], window: int = 5) -> set[str]:
    """向后兼容：成交量温和放大子集。内部走 fetch_patterns_batch（一次拉取算齐）。"""
    pat = fetch_patterns_batch(symbols)
    return {s for s in symbols if pat.get(s, {}).get("vol_uptrend")}
