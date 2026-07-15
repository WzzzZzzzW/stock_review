"""
A股实时行情 API
数据源：腾讯财经 qt.gtimg.cn（不受代理拦截）
批量查询：每批 100 只，10 线程并发，~5200 只约 15 秒
缓存 3 分钟
"""
import time
import math
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["market"])

_cache: dict = {"data": [], "ts": 0.0}
CACHE_TTL   = 180   # 3 分钟
BATCH_SIZE  = 100   # 每次请求股票数
MAX_WORKERS = 10    # 并发线程数

TENCENT_BASE = "http://qt.gtimg.cn/q="


# ── 工具 ─────────────────────────────────────────────────────────────
def _safe(val):
    if val is None:
        return None
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _to_tencent(symbol: str) -> str:
    """A股代码 → 腾讯格式（sh/sz/bj 前缀）"""
    if symbol.startswith('6'):
        return f"sh{symbol}"
    if symbol.startswith('8') or symbol.startswith('4'):
        return f"bj{symbol}"
    return f"sz{symbol}"


def _parse_line(line: str) -> dict | None:
    """解析腾讯财经一行报价数据"""
    if '="' not in line:
        return None
    try:
        val = line.split('="', 1)[1].rstrip('";')
        if not val:
            return None
        f = val.split('~')
        if len(f) < 33:
            return None

        def sf(idx):
            try:
                v = f[idx].strip()
                return float(v) if v else None
            except (ValueError, IndexError):
                return None

        symbol = f[2].zfill(6) if len(f) > 2 else None
        if not symbol:
            return None

        # 成交额：字段[37] 单位万元 → 元
        amt_raw = sf(37)
        amount  = amt_raw * 10_000 if amt_raw else None

        # 总市值 / 流通市值：字段[44][45] 单位亿元 → 元
        mc_raw     = sf(44)
        fc_raw     = sf(45)
        market_cap = mc_raw * 1e8 if mc_raw else None
        float_cap  = fc_raw * 1e8 if fc_raw else None

        return {
            "symbol":     symbol,
            "name":       f[1] if len(f) > 1 else "",
            "price":      sf(3),
            "change_pct": sf(32),
            "change_amt": sf(31),
            "volume":     sf(6),       # 手
            "amount":     amount,      # 元
            "high":       sf(33),
            "low":        sf(34),
            "open":       sf(5),
            "prev_close": sf(4),
            "turnover":   sf(38),      # 换手率 %
            "pe":         sf(39),      # 市盈率 TTM
            "pb":         sf(46),      # 市净率
            "market_cap": market_cap,  # 元
            "float_cap":  float_cap,   # 元
            "volume_ratio": sf(49),    # 量比（今日成交 ÷ 过去5日均量，无量纲）
        }
    except Exception:
        return None


def _fetch_batch(tencent_codes: list[str]) -> list[dict]:
    """拉取一批股票行情（绕过代理）"""
    url  = TENCENT_BASE + ",".join(tencent_codes)
    sess = requests.Session()
    sess.trust_env = False           # 绕过系统/环境代理
    resp = sess.get(url, timeout=15)
    resp.encoding = "gbk"

    quotes = []
    for line in resp.text.splitlines():
        line = line.strip()
        if not line:
            continue
        q = _parse_line(line)
        if q and q.get("symbol"):
            quotes.append(q)
    return quotes


_stock_symbols: list[str] = []   # 模块内缓存的股票代码列表


def _ensure_stock_symbols():
    """确保股票代码列表已加载（从 baostock 或内存缓存）"""
    global _stock_symbols
    if _stock_symbols:
        return

    # 先尝试从 stocks 模块的内存缓存中取（同进程内已加载过）
    try:
        from api.stocks import _cache as _sc, _load_stocks as _ls
        if _sc["stocks"]:
            _stock_symbols = [s["symbol"] for s in _sc["stocks"]]
            return
        stocks = _ls()
        if stocks:
            _sc["stocks"] = stocks
            _sc["ts"]     = time.time()
            _stock_symbols = [s["symbol"] for s in stocks]
            return
    except Exception:
        pass

    # 最终回退：直接调 baostock（持锁串行）
    import baostock as bs
    from data.stock_data import _BS_LOCK
    with _BS_LOCK:
        lg = bs.login()
        if lg.error_code != "0":
            return
        try:
            rs  = bs.query_stock_basic(code_name="")
            raw = []
            while rs.next():
                raw.append(rs.get_row_data())
        finally:
            bs.logout()

    syms = []
    for row in raw:
        code_full, name, ipo_date, out_date, stype, status = row
        if stype == "1" and status == "1" and not out_date:
            syms.append(code_full.replace("sh.", "").replace("sz.", ""))
    _stock_symbols = syms


def _load_quotes() -> list[dict]:
    """并发拉取全量A股行情"""
    _ensure_stock_symbols()
    stocks = _stock_symbols

    tencent_codes = [_to_tencent(s) for s in stocks]

    # 切片成批次
    batches = [
        tencent_codes[i: i + BATCH_SIZE]
        for i in range(0, len(tencent_codes), BATCH_SIZE)
    ]

    all_quotes: list[dict] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_fetch_batch, b): b for b in batches}
        for fut in as_completed(futures):
            try:
                all_quotes.extend(fut.result())
            except Exception:
                pass  # 单批次失败不中断整体

    return all_quotes


# ── API ───────────────────────────────────────────────────────────────
@router.get("/market/quotes")
def market_quotes(force_refresh: bool = False):
    """
    返回全量A股实时行情（约 5200 只）。
    数据源：腾讯财经（10 线程并发，首次约 10–20 秒）。
    缓存 3 分钟；传 ?force_refresh=true 强制刷新。
    """
    now = time.time()
    if not force_refresh and now - _cache["ts"] < CACHE_TTL and _cache["data"]:
        return {
            "quotes":    _cache["data"],
            "total":     len(_cache["data"]),
            "cached":    True,
            "cache_age": int(now - _cache["ts"]),
        }

    try:
        quotes = _load_quotes()
        _cache["data"] = quotes
        _cache["ts"]   = now
        return {
            "quotes":    quotes,
            "total":     len(quotes),
            "cached":    False,
            "cache_age": 0,
        }
    except Exception as e:
        if _cache["data"]:
            return {
                "quotes":    _cache["data"],
                "total":     len(_cache["data"]),
                "cached":    True,
                "cache_age": int(now - _cache["ts"]),
                "error":     str(e),
            }
        return {"quotes": [], "total": 0, "cached": False, "error": str(e)}
