"""
新闻推送 API
GET /api/news-feed  — 返回带A股影响初筛的国际新闻列表（30分钟缓存）
"""
import time
from fastapi import APIRouter

from data.news_fetcher import get_news_feed
from services.news_impact_service import batch_quick_analyze

router = APIRouter(prefix="/api", tags=["news-feed"])

# 独立于 RSS 缓存的分析结果缓存
_cache: dict = {"items": [], "ts": 0.0}
CACHE_TTL = 1800  # 30分钟


@router.get("/news-feed")
def news_feed(refresh: bool = False):
    """
    返回国际新闻列表，每条附带 AI 快速影响初筛。
    ?refresh=true 强制刷新。
    """
    now = time.time()

    if not refresh and now - _cache["ts"] < CACHE_TTL and _cache["items"]:
        return {
            "items": _cache["items"],
            "cached": True,
            "updated_at": int(_cache["ts"]),
        }

    # 1. 拉取 RSS
    articles = get_news_feed(force_refresh=refresh)

    if not articles:
        return {"items": [], "cached": False, "updated_at": int(now), "error": "暂时无法获取新闻源"}

    # 2. 批量 AI 分析（一次调用）
    try:
        analyzed = batch_quick_analyze(articles)
    except Exception:
        # 分析失败降级：返回无分析的原始新闻
        analyzed = [
            {**a, "relevant": False, "direction": "neutral", "stocks": [], "one_line": ""}
            for a in articles
        ]

    _cache["items"] = analyzed
    _cache["ts"] = now

    return {"items": analyzed, "cached": False, "updated_at": int(now)}
