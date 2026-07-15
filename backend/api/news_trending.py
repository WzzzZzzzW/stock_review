"""
新闻热搜榜 API
GET /api/news-trending?market=cn|intl  → 返回聚类后的热搜榜（带 A 股影响力评分）

数据复用：直接借用 news_feed / news_feed_cn 的 AI 初筛缓存，不重新调 AI。
"""
import time
from fastapi import APIRouter, Query

from data.news_fetcher import get_news_feed
from data.cn_news_fetcher import aggregate_cn_news
from services.news_impact_service import batch_quick_analyze, batch_quick_analyze_cn
from services.news_ranking_service import compute_trending
from api.news_feed import _cache as _global_cache, CACHE_TTL as _GLOBAL_TTL
from api.news_feed_cn import _cache as _cn_cache, CACHE_TTL as _CN_TTL


router = APIRouter(prefix="/api", tags=["news-trending"])


def _get_items(market: str, refresh: bool) -> tuple[list[dict], int]:
    """复用现有缓存；若失效则重新拉取 + AI 初筛。返回 (items, updated_at_epoch)。"""
    now = time.time()
    if market == "cn":
        if not refresh and now - _cn_cache["ts"] < _CN_TTL and _cn_cache["items"]:
            return _cn_cache["items"], int(_cn_cache["ts"])
        articles = aggregate_cn_news(force_refresh=refresh)
        if not articles:
            return [], int(now)
        try:
            analyzed = batch_quick_analyze_cn(articles)
        except Exception:
            analyzed = [{**a, "relevant": False, "direction": "neutral", "stocks": [], "one_line": ""} for a in articles]
        _cn_cache["items"] = analyzed
        _cn_cache["ts"] = now
        return analyzed, int(now)
    # 国际
    if not refresh and now - _global_cache["ts"] < _GLOBAL_TTL and _global_cache["items"]:
        return _global_cache["items"], int(_global_cache["ts"])
    articles = get_news_feed(force_refresh=refresh)
    if not articles:
        return [], int(now)
    try:
        analyzed = batch_quick_analyze(articles)
    except Exception:
        analyzed = [{**a, "relevant": False, "direction": "neutral", "stocks": [], "one_line": ""} for a in articles]
    _global_cache["items"] = analyzed
    _global_cache["ts"] = now
    return analyzed, int(now)


@router.get("/news-trending")
def news_trending(
    market:  str  = Query("cn",   pattern="^(cn|intl)$"),
    top:     int  = Query(10,     ge=3, le=30),
    refresh: bool = False,
):
    """
    market=cn   → 国内财经热搜（财联社/财新/东财/CCTV 等聚类后）
    market=intl → 国际财经热搜（Reuters/BBC/Google 主题源聚类后）
    """
    items, ts = _get_items(market, refresh)
    trending  = compute_trending(items, market, top_n=top)
    return {
        "market":     market,
        "items":      trending,
        "raw_count":  len(items),
        "updated_at": ts,
    }
