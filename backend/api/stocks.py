"""
A股全量股票列表 API
数据源：baostock（Socket 协议，不受代理影响）
缓存 24 小时
"""
import time
import baostock as bs
from fastapi import APIRouter
from data.stock_data import _BS_LOCK

try:
    from pypinyin import lazy_pinyin, Style as PinyinStyle
    _HAS_PYPINYIN = True
except ImportError:
    _HAS_PYPINYIN = False


def _pinyin_initials(name: str) -> str:
    """生成股票名称拼音首字母缩写，如 北方华创 -> bfhc"""
    if not _HAS_PYPINYIN:
        return ''
    try:
        # 过滤掉 *ST 前缀等特殊字符，只取汉字/字母
        clean = ''.join(c for c in name if '一' <= c <= '鿿' or c.isalpha())
        initials = lazy_pinyin(clean, style=PinyinStyle.FIRST_LETTER)
        return ''.join(initials).lower()
    except Exception:
        return ''

router = APIRouter(prefix="/api", tags=["stocks"])

_cache: dict = {"stocks": [], "ts": 0.0}
CACHE_TTL = 86400  # 24 小时


def _market(code: str) -> str:
    """根据代码判断板块"""
    c = code.replace("sh.", "").replace("sz.", "")
    if c.startswith("688") or c.startswith("689"):
        return "科创板"
    if c.startswith("6"):
        return "沪市主板"
    if c.startswith("3"):
        return "创业板"
    if c.startswith("8") or c.startswith("4"):
        return "北交所"
    return "深市主板"


def _load_stocks() -> list[dict]:
    with _BS_LOCK:
        lg = bs.login()
        if lg.error_code != "0":
            return []
        try:
            rs = bs.query_stock_basic(code_name="")
            raw = []
            while rs.next():
                raw.append(rs.get_row_data())
        finally:
            bs.logout()

    stocks = []
    for row in raw:
        code_full, name, ipo_date, out_date, stype, status = row
        # type=1 普通股，status=1 上市中，无退市日期
        if stype == "1" and status == "1" and not out_date:
            symbol = code_full.replace("sh.", "").replace("sz.", "")
            stocks.append({
                "symbol":    symbol,
                "name":      name,
                "market":    _market(code_full),
                "full_code": code_full,
                "pinyin":    _pinyin_initials(name),
            })

    # 按代码排序
    stocks.sort(key=lambda x: x["symbol"])
    return stocks


@router.get("/stocks/list")
def stock_list(force_refresh: bool = False):
    """
    返回全量在市A股列表（约5200只）。
    响应：{stocks: [{symbol, name, market}], total, cached}
    结果缓存 24 小时，传 ?force_refresh=true 强制刷新。
    """
    now = time.time()
    if not force_refresh and now - _cache["ts"] < CACHE_TTL and _cache["stocks"]:
        return {
            "stocks": _cache["stocks"],
            "total":  len(_cache["stocks"]),
            "cached": True,
        }

    stocks = _load_stocks()
    _cache["stocks"] = stocks
    _cache["ts"] = now

    return {
        "stocks": stocks,
        "total":  len(stocks),
        "cached": False,
    }
