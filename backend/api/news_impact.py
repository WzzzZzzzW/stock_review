"""
国际新闻 → A股影响分析 API
支持：纯文本 / URL 链接
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from data.news_fetcher import fetch_url_text
from services.news_impact_service import analyze_news_impact

router = APIRouter(prefix="/api", tags=["news-impact"])


class NewsImpactRequest(BaseModel):
    news_text: str = ""
    url: str = ""
    news_source: str = ""
    news_date: str = ""


@router.post("/news-impact")
def news_impact(req: NewsImpactRequest):
    text = req.news_text.strip()
    source = req.news_source.strip()

    # 优先使用 URL
    if req.url.strip():
        try:
            text = fetch_url_text(req.url.strip())
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"无法获取链接内容：{e}。请直接粘贴新闻文本。"
            )

    if not text or len(text) < 20:
        raise HTTPException(status_code=422, detail="请提供新闻文本或有效的新闻链接")

    try:
        result = analyze_news_impact(
            news_text=text,
            news_source=source,
            news_date=req.news_date.strip(),
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"AI返回格式异常，请重试：{e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
