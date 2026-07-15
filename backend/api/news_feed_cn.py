"""
中文A股新闻推送 API
GET /api/news-feed-cn  — 财新 + SHMET快讯 + CCTV + 东方财富，带AI初筛
"""
import time
from fastapi import APIRouter

from data.cn_news_fetcher import aggregate_cn_news
from services.news_impact_service import batch_quick_analyze_cn

router = APIRouter(prefix="/api", tags=["news-feed-cn"])

_cache: dict = {"items": [], "ts": 0.0}
CACHE_TTL = 300  # 5 分钟，与底层 fetcher 对齐


@router.get("/news-feed-cn")
def news_feed_cn(refresh: bool = False):
    """
    中文A股新闻推送，每条附带 AI 个股影响初筛。
    ?refresh=true 强制刷新。
    """
    now = time.time()

    if not refresh and now - _cache["ts"] < CACHE_TTL and _cache["items"]:
        return {
            "items": _cache["items"],
            "cached": True,
            "updated_at": int(_cache["ts"]),
        }

    articles = aggregate_cn_news(force_refresh=refresh)

    if not articles:
        return {"items": [], "cached": False, "updated_at": int(now),
                "error": "暂时无法获取中文新闻源"}

    try:
        analyzed = batch_quick_analyze_cn(articles)
    except Exception:
        analyzed = [
            {**a, "relevant": False, "direction": "neutral",
             "stocks": [], "one_line": ""}
            for a in articles
        ]

    _cache["items"] = analyzed
    _cache["ts"] = now

    return {"items": analyzed, "cached": False, "updated_at": int(now)}
