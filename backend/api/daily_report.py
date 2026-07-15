"""
日度复盘 API
GET /api/daily-report  全市场日度概览（大盘指数 + 板块热力 + 市场情绪）
"""
import math
import time
import requests
from datetime import datetime, date

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/daily-report", tags=["日报"])

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "http://finance.sina.com.cn/",
}

# ── 大盘指数定义 ──────────────────────────────────────────────────────────────
_INDICES = [
    {"id": "sh000001", "key": "sh",    "name": "上证指数"},
    {"id": "sz399001", "key": "sz",    "name": "深证成指"},
    {"id": "sz399006", "key": "cyb",   "name": "创业板指"},
    {"id": "sh000300", "key": "hs300", "name": "沪深300"},
]

# ── 缓存 ──────────────────────────────────────────────────────────────────────
_cache: dict = {"data": None, "ts": 0.0}
_CACHE_TTL = 60   # 1 分钟


def _safe(v, default=0.0) -> float:
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return default


# ── 大盘指数 ──────────────────────────────────────────────────────────────────

def _fetch_indices() -> list[dict]:
    """从新浪财经获取大盘指数行情"""
    ids = ",".join(i["id"] for i in _INDICES)
    url = f"http://hq.sinajs.cn/list={ids}"
    try:
        resp = requests.get(url, timeout=10, headers=_HEADERS)
        resp.encoding = "gbk"
        text = resp.text
    except Exception:
        return []

    result = []
    valid_lines = [
        ln for ln in text.strip().split("\n")
        if '="' in ln and "hq_str_" in ln
    ]

    for idx_def, line in zip(_INDICES, valid_lines):
        data_str = line.split('="')[1].rstrip('";')
        if not data_str:
            result.append({**idx_def, "price": 0, "pct": 0, "change": 0})
            continue
        parts = data_str.split(",")
        if len(parts) < 6:
            continue
        prev  = _safe(parts[2])
        curr  = _safe(parts[3])
        pct   = (curr - prev) / prev * 100 if prev else 0
        result.append({
            "key":        idx_def["key"],
            "name":       idx_def["name"],
            "price":      round(curr, 2),
            "change":     round(curr - prev, 2),
            "pct":        round(pct, 2),
            "open":       round(_safe(parts[1]), 2),
            "prev_close": round(prev, 2),
            "high":       round(_safe(parts[4]), 2),
            "low":        round(_safe(parts[5]), 2),
        })
    return result


# ── 板块热力 ──────────────────────────────────────────────────────────────────

def _fetch_sectors() -> dict:
    """汇总概念板块 + 行业板块，返回涨跌榜"""
    all_sectors: list[dict] = []

    # 1. 概念板块
    try:
        from api.sector import _cache as sec_cache, _fetch_sina_concepts
        if not sec_cache["data"] or time.time() - sec_cache["ts"] > 120:
            sec_cache["data"] = _fetch_sina_concepts()
            sec_cache["ts"]   = time.time()
        for c in sec_cache["data"]:
            all_sectors.append({
                "name":   c["name"],
                "pct":    round(c.get("pct_num", 0), 2),
                "leader": c.get("leader", ""),
                "type":   "概念",
            })
    except Exception:
        pass

    # 2. 行业板块
    try:
        from api.industry import _cache as ind_cache, industry_summary
        if not ind_cache.get("data"):
            industry_summary()
        for ind in ind_cache.get("data", []):
            raw = str(ind.get("pct", "0%")).replace("%", "").replace("+", "").replace("−", "-")
            try:
                pct = float(raw)
            except ValueError:
                pct = 0.0
            all_sectors.append({
                "name":   ind["name"],
                "pct":    round(pct, 2),
                "leader": ind.get("leader", ""),
                "type":   "行业",
            })
    except Exception:
        pass

    if not all_sectors:
        return {"top_up": [], "top_down": [], "total": 0, "up_count": 0, "down_count": 0}

    sorted_s = sorted(all_sectors, key=lambda x: x["pct"], reverse=True)
    up_count   = sum(1 for s in all_sectors if s["pct"] > 0)
    down_count = sum(1 for s in all_sectors if s["pct"] < 0)

    return {
        "top_up":    sorted_s[:8],
        "top_down":  sorted_s[-5:][::-1],
        "total":     len(all_sectors),
        "up_count":  up_count,
        "down_count": down_count,
    }


# ── 市场情绪 ──────────────────────────────────────────────────────────────────

def _market_sentiment(indices: list[dict]) -> dict:
    """根据大盘指数和板块计算市场情绪"""
    if not indices:
        return {"level": "neutral", "label": "观望", "color": "gray"}

    # 用上证 + 创业板均值判断
    pcts = [i["pct"] for i in indices if i.get("pct") is not None]
    avg  = sum(pcts) / len(pcts) if pcts else 0

    if avg >= 2:
        return {"level": "strong_bull", "label": "强势上涨", "color": "red",   "emoji": "🚀"}
    if avg >= 0.5:
        return {"level": "bull",        "label": "温和上涨", "color": "red",   "emoji": "📈"}
    if avg > -0.5:
        return {"level": "neutral",     "label": "震荡整理", "color": "gray",  "emoji": "↔️"}
    if avg > -2:
        return {"level": "bear",        "label": "温和下跌", "color": "green", "emoji": "📉"}
    return     {"level": "strong_bear", "label": "大幅下跌", "color": "green", "emoji": "🔻"}


# ── 主接口 ────────────────────────────────────────────────────────────────────

@router.get("")
async def daily_report():
    """全市场日度复盘：大盘指数 + 板块热力 + 市场情绪"""
    now = time.time()
    if _cache["data"] and now - _cache["ts"] < _CACHE_TTL:
        return JSONResponse(_cache["data"])

    indices   = _fetch_indices()
    sectors   = _fetch_sectors()
    sentiment = _market_sentiment(indices)
    today     = date.today()

    # 判断交易状态
    weekday    = today.weekday()   # 0=Mon, 6=Sun
    now_dt     = datetime.now()
    hour       = now_dt.hour + now_dt.minute / 60
    is_trading = (weekday < 5) and (9.5 <= hour < 11.5 or 13 <= hour < 15)
    is_weekend = weekday >= 5

    payload = {
        "date":       today.isoformat(),
        "weekday":    ["周一","周二","周三","周四","周五","周六","周日"][weekday],
        "updated_at": now_dt.strftime("%H:%M:%S"),
        "is_trading": is_trading,
        "is_weekend": is_weekend,
        "indices":    indices,
        "sectors":    sectors,
        "sentiment":  sentiment,
    }

    _cache["data"] = payload
    _cache["ts"]   = now
    return JSONResponse(payload)
