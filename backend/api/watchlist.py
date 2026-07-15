"""
自选股 & 今日推荐
- GET /api/watchlist/batch?symbols=600519,000858   批量行情（新浪财经）
- GET /api/watchlist/recommend                     今日推荐（5分钟缓存）
"""
import math
import time
import requests
from datetime import datetime, date

import akshare as ak
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from db import watchlist_db

router = APIRouter(prefix="/api/watchlist", tags=["自选"])


class WatchItemIn(BaseModel):
    code: str
    name: str = ""
    date: str = ""


class WatchSyncIn(BaseModel):
    items: list[WatchItemIn] = Field(default_factory=list)

# ── 缓存 ──────────────────────────────────────────────────────────────────────
_hq_cache:  dict = {}   # code → {info, ts}
_rec_cache: dict = {"data": [], "date": "", "ts": 0.0, "at": ""}

_HQ_TTL  = 60
_REC_TTL = 5 * 60

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":    "http://finance.sina.com.cn/",
}


def _safe(v, default=0.0) -> float:
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return default


def _sina_prefix(code: str) -> str:
    """根据股票代码确定新浪市场前缀 sh / sz"""
    c = code.zfill(6)
    if c.startswith(('6', '9', '5')):
        return 'sh'
    return 'sz'


def _fetch_sina_hq(codes: list[str]) -> dict[str, dict]:
    """
    调用新浪财经行情接口，返回 {code: info_dict}
    格式：var hq_str_sh600519="贵州茅台,开盘,昨收,现价,最高,最低,...,成交量,成交额,..."
    """
    if not codes:
        return {}

    ids = [f"{_sina_prefix(c)}{c.zfill(6)}" for c in codes]
    url = f"http://hq.sinajs.cn/list={','.join(ids)}"
    try:
        resp = requests.get(url, timeout=10, headers=_HEADERS)
        resp.encoding = 'gbk'
        text = resp.text
    except Exception:
        return {}

    result: dict[str, dict] = {}
    for line in text.strip().split('\n'):
        if '="' not in line or 'hq_str_' not in line:
            continue
        # 提取代码 & 数据部分
        var_part = line.split('="')[0]              # var hq_str_sh600519
        data_str = line.split('="')[1].rstrip('";') # 数据字段
        # code = 去掉 sh/sz 前缀
        code_raw = var_part.strip().split('_')[-1]  # sh600519 / sz000858
        code = code_raw[2:] if len(code_raw) > 2 else code_raw

        if not data_str:
            result[code] = {"symbol": code, "name": "--", "price": 0,
                            "pct_change": 0, "not_found": True}
            continue

        parts = data_str.split(',')
        if len(parts) < 10:
            continue

        try:
            prev_close = _safe(parts[2])
            current    = _safe(parts[3])
            high       = _safe(parts[4])
            low        = _safe(parts[5])
            volume     = _safe(parts[8])   # 股数（股）
            amount     = _safe(parts[9])   # 成交额（元）
            open_p     = _safe(parts[1])

            # 开盘前 current=0，用昨收价展示，涨跌幅显示 0%
            display_price = current if current > 0 else prev_close
            pct = ((current - prev_close) / prev_close * 100) if (prev_close and current > 0) else 0

            result[code] = {
                "symbol":        code,
                "name":          parts[0].strip() or code,
                "price":         display_price,
                "pct_change":    round(pct, 2),
                "change_amount": round(display_price - prev_close, 2),
                "volume":        volume,
                "amount":        amount,
                "high":          high,
                "low":           low,
                "open":          open_p,
                "prev_close":    prev_close,
                "pre_market":    current == 0,  # 标记是否为盘前状态
            }
        except (ValueError, IndexError):
            continue

    return result


# ── 批量行情 ──────────────────────────────────────────────────────────────────

@router.get("/batch")
def batch_quotes(symbols: str = ""):
    """批量获取实时行情，并附统一多维裁决。"""
    codes = [s.strip() for s in symbols.split(",") if s.strip()]
    if not codes:
        return JSONResponse({"stocks": [], "updated_at": ""})

    now = time.time()
    # 判断哪些需要刷新
    stale = [c for c in codes if c not in _hq_cache or now - _hq_cache[c]["ts"] > _HQ_TTL]
    if stale:
        fresh = _fetch_sina_hq(stale)
        for c, info in fresh.items():
            _hq_cache[c] = {"info": info, "ts": now}

    result = []
    for code in codes:
        if code in _hq_cache:
            result.append(dict(_hq_cache[code]["info"]))
        else:
            result.append({"symbol": code, "name": "--", "price": 0,
                           "pct_change": 0, "not_found": True})

    try:
        from data.stock_data import fetch_quick_batch, get_industry_map
        from services.verdict_service import compute_quick_decision

        tech_map = {
            str(row.get("symbol")): row
            for row in fetch_quick_batch(codes)
            if row.get("symbol")
        }
        industry_map = get_industry_map(block=False)
        market_pct = None
        try:
            from api.daily_report import _fetch_indices
            index_pcts = [i.get("pct") for i in _fetch_indices() if i.get("pct") is not None]
            market_pct = sum(index_pcts) / len(index_pcts) if index_pcts else None
        except Exception:
            pass
        for row in result:
            symbol = row.get("symbol", "")
            tech = tech_map.get(symbol, {})
            row["tech"] = tech
            row["industry"] = industry_map.get(symbol, "")
            row["decision"] = compute_quick_decision(
                row,
                tech,
                {"market_pct": market_pct, "sector": row["industry"]},
                purpose="watchlist",
            )
    except Exception as e:
        for row in result:
            row.setdefault("decision_error", str(e))

    return JSONResponse({
        "stocks":     result,
        "updated_at": datetime.now().strftime("%H:%M:%S"),
    })


# ── 今日推荐辅助函数 ──────────────────────────────────────────────────────────

def _concept_leaders() -> list[dict]:
    """概念板块龙头股（复用 sector.py 缓存）"""
    leaders: list[dict] = []
    try:
        from api.sector import _cache as sec_cache, _fetch_sina_concepts
        if not sec_cache["data"] or time.time() - sec_cache["ts"] > 120:
            sec_cache["data"] = _fetch_sina_concepts()
            sec_cache["ts"]   = time.time()
        for c in sec_cache["data"][:20]:
            leader = c.get("leader", "").strip()
            if not leader:
                continue
            leaders.append({
                "name":       leader,
                "reason_tag": f"🔥 {c['name']}龙头",
                "score":      max(c.get("pct_num", 0), 0),
                "concept":    c["name"],
            })
    except Exception:
        pass
    return leaders


def _lhb_candidates() -> list[dict]:
    """龙虎榜近 5 日净买入（直接用 akshare 新浪接口）"""
    result: list[dict] = []
    try:
        lhb_df = ak.stock_lhb_ggtj_sina(symbol="5")
        if "净额" in lhb_df.columns:
            lhb_df = lhb_df.sort_values("净额", ascending=False)
        for _, r in lhb_df.head(10).iterrows():
            # 列名为"股票代码"/"股票名称"
            sym = str(r.get("股票代码", r.get("代码", ""))).strip().zfill(6)
            if len(sym) != 6 or sym == "000000":
                continue
            net = _safe(r.get("净额"))
            if net <= 0:
                continue
            result.append({
                "symbol":     sym,
                "name":       str(r.get("股票名称", r.get("名称", sym))),
                "reason_tag": "🐉 龙虎榜净买入",
                "score":      net / 1e8,
            })
    except Exception:
        pass
    return result


def _industry_leaders() -> list[dict]:
    """行业板块领涨股（复用 industry.py 缓存，缓存空时主动触发获取）"""
    result: list[dict] = []
    try:
        from api.industry import _cache as ind_cache, industry_summary
        if not ind_cache.get("data"):
            try:
                industry_summary()   # 调用路由函数触发获取并更新缓存
            except Exception:
                pass
        for ind in ind_cache.get("data", [])[:10]:
            leader = str(ind.get("leader", "")).strip()
            if not leader:
                continue
            # pct 是字符串如 "+1.23%"
            pct_str = str(ind.get("pct", "0%")).replace("%","").replace("+","").replace("−","-")
            try:
                pct_num = float(pct_str)
            except ValueError:
                pct_num = 0.0
            result.append({
                "name":       leader,
                "reason_tag": f"📈 {ind['name']}领涨",
                "score":      max(pct_num, 0),
            })
    except Exception:
        pass
    return result


def _name_to_code(names: list[str]) -> dict[str, str]:
    """
    用新浪财经搜索接口把股票名称转为代码
    格式: var suggestvalue="三丰智能,11,300276,sz300276,...;..."
    返回 {name: code}
    """
    mapping: dict[str, str] = {}
    for name in names:
        try:
            url = f"http://suggest3.sinajs.cn/suggest/type=11&key={requests.utils.quote(name)}"
            resp = requests.get(url, timeout=5, headers=_HEADERS)
            resp.encoding = 'gbk'
            text = resp.text
            if '="' not in text:
                continue
            raw = text.split('="')[1].rstrip('";')
            if not raw:
                continue
            for entry in raw.split(';'):
                parts = entry.split(',')
                if len(parts) >= 3 and parts[0].strip() == name:
                    # parts[2] 直接是 6 位股票代码，如 300276
                    code = parts[2].strip()
                    if len(code) == 6 and code.isdigit():
                        mapping[name] = code
                    break
        except Exception:
            continue
    return mapping


def get_recommendations_sync() -> list[dict]:
    """
    同步版今日推荐（供 prediction.py 直接调用）
    逻辑与 daily_recommend 完全一致，可复用缓存
    """
    now   = time.time()
    today = date.today().isoformat()

    if _rec_cache["data"] and _rec_cache["date"] == today and now - _rec_cache["ts"] < _REC_TTL:
        return _rec_cache["data"]

    cand_by_symbol: dict[str, dict] = {}

    for c in _lhb_candidates():
        sym = c["symbol"]
        if sym not in cand_by_symbol:
            cand_by_symbol[sym] = {"symbol": sym, "name": c["name"], "reasons": [], "score": 0.0}
        cand_by_symbol[sym]["reasons"].append(c["reason_tag"])
        cand_by_symbol[sym]["score"] += c["score"]

    con_leaders  = _concept_leaders()
    ind_leaders  = _industry_leaders()
    names_needed = list({c["name"] for c in con_leaders + ind_leaders})
    name_map     = _name_to_code(names_needed) if names_needed else {}

    for c in con_leaders + ind_leaders:
        nm  = c["name"]
        sym = name_map.get(nm, "")
        if not sym:
            continue
        if sym not in cand_by_symbol:
            cand_by_symbol[sym] = {"symbol": sym, "name": nm, "reasons": [], "score": 0.0}
        cand_by_symbol[sym]["reasons"].append(c["reason_tag"])
        cand_by_symbol[sym]["score"] += c.get("score", 0)

    if not cand_by_symbol:
        return []

    hq_map = _fetch_sina_hq(list(cand_by_symbol.keys()))
    symbols = list(cand_by_symbol.keys())
    tech_map: dict[str, dict] = {}
    market_pct = None
    try:
        from data.stock_data import fetch_quick_batch
        tech_map = {
            str(row.get("symbol")): row
            for row in fetch_quick_batch(symbols)
            if row.get("symbol")
        }
        from api.daily_report import _fetch_indices
        pcts = [i.get("pct") for i in _fetch_indices() if i.get("pct") is not None]
        market_pct = sum(pcts) / len(pcts) if pcts else None
    except Exception:
        pass
    result = []
    for sym, info in cand_by_symbol.items():
        hq = hq_map.get(sym)
        if not hq or hq.get("not_found") or hq["price"] <= 0:
            continue
        pct = hq["pct_change"]
        from services.verdict_service import compute_quick_decision
        decision = compute_quick_decision(
            hq,
            tech_map.get(sym) or {},
            {
                "market_pct": market_pct,
                "catalyst_strength": "中" if info["score"] >= 5 else "弱",
                "catalyst": "、".join(dict.fromkeys(info["reasons"])),
            },
            purpose="candidate",
        )
        result.append({
            "symbol":     sym,
            "name":       hq["name"] or info["name"],
            "price":      hq["price"],
            "pct_change": pct,
            "reasons":    list(dict.fromkeys(info["reasons"])),
            "score":      decision["score"],
            "pe":         0,
            "turnover":   0,
            "decision":   decision,
            "tech":       tech_map.get(sym) or {},
        })

    result.sort(key=lambda x: x["score"], reverse=True)
    result = result[:8]

    at = datetime.now().strftime("%H:%M:%S")
    _rec_cache.update({"data": result, "date": today, "ts": now, "at": at})
    return result


@router.get("/recommend")
async def daily_recommend():
    """今日推荐：概念板块龙头 + 龙虎榜净买入 + 行业领涨（每 5 分钟刷新）"""
    today  = date.today().isoformat()
    result = get_recommendations_sync()
    at     = _rec_cache.get("at") or datetime.now().strftime("%H:%M:%S")
    return JSONResponse({"stocks": result, "date": today, "updated_at": at})


@router.get("")
def get_saved_watchlist():
    items = watchlist_db.list_items()
    return JSONResponse({"items": items, "count": len(items)})


@router.post("")
def add_saved_watchlist(item: WatchItemIn):
    try:
        saved = watchlist_db.upsert_item(item.code, item.name, item.date)
    except ValueError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "item": saved})


@router.post("/sync")
def sync_saved_watchlist(body: WatchSyncIn):
    items = watchlist_db.merge_items([item.model_dump() for item in body.items])
    return JSONResponse({"ok": True, "items": items, "count": len(items)})


@router.delete("/{symbol}")
def remove_saved_watchlist(symbol: str):
    removed = watchlist_db.delete_item(symbol)
    return JSONResponse({"ok": True, "removed": removed})
