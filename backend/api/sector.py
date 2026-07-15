"""
概念板块 API
数据源：新浪财经概念板块
缓存 60 秒
"""
import time
import json
from datetime import datetime
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/sector", tags=["概念板块"])

_cache: dict = {"data": [], "ts": 0.0, "updated_at": ""}
_CACHE_TTL = 60  # 60秒缓存


def _fetch_sina_concepts() -> list:
    """从新浪财经获取概念板块数据"""
    import requests

    url = "http://money.finance.sina.com.cn/q/view/newFLJK.php?param=class"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.90 Safari/537.36",
        "Referer": "http://finance.sina.com.cn/",
    }

    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    text = r.content.decode("gbk", errors="replace")

    # 解析 JS 变量赋值，提取 JSON 对象
    start = text.find("{")
    if start == -1:
        raise ValueError("未找到 JSON 数据")
    json_str = text[start:]
    # 去掉末尾可能的分号
    json_str = json_str.rstrip().rstrip(";")
    data = json.loads(json_str)

    # 字段说明：key,板块名,公司家数,平均价格,涨跌额,涨跌幅(%),总成交量,总成交额,代码,个股-涨跌幅,个股-当前价,个股-涨跌额,股票名称
    # index:  0    1      2       3       4      5         6      7      8    9            10         11        12
    result = []
    for key, val in data.items():
        parts = val.split(",")
        if len(parts) < 13:
            continue
        try:
            pct_num = float(parts[5])
        except (ValueError, IndexError):
            pct_num = 0.0
        try:
            leader_pct = float(parts[9])
        except (ValueError, IndexError):
            leader_pct = 0.0
        try:
            company_count = int(parts[2])
        except (ValueError, IndexError):
            company_count = 0

        pct_str = f"{'+' if pct_num > 0 else ''}{pct_num:.2f}%"

        result.append({
            "name":          parts[1].strip(),
            "code":          parts[8].strip(),
            "pct":           pct_str,
            "pct_num":       pct_num,
            "leader":        parts[12].strip(),
            "leader_pct":    leader_pct,
            "company_count": company_count,
        })

    # 按涨跌幅降序排列
    result.sort(key=lambda x: x["pct_num"], reverse=True)
    return result


@router.get("/concepts")
def sector_concepts():
    """
    返回新浪财经概念板块今日涨跌幅数据。
    缓存 60 秒。
    """
    now = time.time()
    if _cache["data"] and now - _cache["ts"] < _CACHE_TTL:
        return {"concepts": _cache["data"], "updated_at": _cache["updated_at"]}

    try:
        result = _fetch_sina_concepts()
        updated_at = datetime.now().strftime("%H:%M:%S")
        _cache["data"] = result
        _cache["ts"] = now
        _cache["updated_at"] = updated_at
        return {"concepts": result, "updated_at": updated_at}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"概念板块数据获取失败: {e}")
