"""
行业汇总 + 行业成分股 API
数据源：akshare 同花顺行业 (summary) + THS HTML scraping (constituent stocks)
缓存 5 分钟
"""
import time
import io
import sys
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/industry", tags=["行业"])

_stock_cache: dict = {}   # {industry_name: (ts, data)}
_STOCK_TTL = 60   # 成分股 1分钟缓存

_cache: dict = {"data": [], "ts": 0.0, "updated_at": ""}
_CACHE_TTL = 60   # 行业汇总 1分钟缓存

# 行业名称→代码 映射缓存
_code_cache: dict = {"data": {}, "ts": 0.0}
_CODE_TTL = 3600  # 1小时


def _get_ths_headers() -> dict:
    """生成同花顺请求头（含 JS cookie）"""
    import py_mini_racer
    import os, akshare

    js_path = os.path.join(
        os.path.dirname(akshare.__file__), "data", "ths.js"
    )
    old = sys.stderr
    sys.stderr = io.StringIO()
    try:
        js_code = py_mini_racer.MiniRacer()
        with open(js_path, "r") as f:
            js_code.eval(f.read())
        v_code = js_code.call("v")
    finally:
        sys.stderr = old

    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/89.0.4389.90 Safari/537.36"
        ),
        "Cookie": f"v={v_code}",
    }


def _get_industry_code(industry_name: str) -> str | None:
    """获取行业名称对应的 THS 代码"""
    now = time.time()
    if not _code_cache["data"] or now - _code_cache["ts"] > _CODE_TTL:
        import akshare as ak
        old = sys.stderr
        sys.stderr = io.StringIO()
        try:
            df = ak.stock_board_industry_name_ths()
        finally:
            sys.stderr = old
        _code_cache["data"] = dict(zip(df["name"], df["code"]))
        _code_cache["ts"] = now

    return _code_cache["data"].get(industry_name)


def _fetch_ths_industry_stocks(industry_name: str) -> list:
    """
    通过爬取同花顺行业详情页获取成分股列表。
    URL 模式：http://q.10jqka.com.cn/thshy/detail/code/{code}/field/199112/order/desc/page/{page}/
    """
    import requests
    from bs4 import BeautifulSoup

    code = _get_industry_code(industry_name)
    if not code:
        return []

    headers = _get_ths_headers()
    headers["Referer"] = f"http://q.10jqka.com.cn/thshy/detail/code/{code}/"

    def fetch_page(page: int) -> tuple[list, int]:
        """返回 (rows_data, total_pages)"""
        if page == 1:
            url = f"http://q.10jqka.com.cn/thshy/detail/code/{code}/"
        else:
            url = (
                f"http://q.10jqka.com.cn/thshy/detail/code/{code}/"
                f"field/199112/order/desc/page/{page}/"
            )
        r = requests.get(url, headers=headers, timeout=12)
        if r.status_code != 200:
            return [], 1

        soup = BeautifulSoup(r.content.decode("gbk", errors="replace"), "lxml")

        # 解析总页数
        page_info = soup.find("span", attrs={"class": "page_info"})
        total = 1
        if page_info:
            parts = page_info.text.strip().split("/")
            if len(parts) == 2:
                try:
                    total = int(parts[1])
                except ValueError:
                    pass

        table = soup.find("table", attrs={"class": lambda c: c and "m-table" in c})
        if not table or not table.find("tbody"):
            return [], total

        rows_data = []
        for row in table.find("tbody").find_all("tr"):
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) >= 5:
                rows_data.append(cells)
        return rows_data, total

    all_rows = []
    rows_p1, total_pages = fetch_page(1)
    all_rows.extend(rows_p1)

    for p in range(2, total_pages + 1):
        rows, _ = fetch_page(p)
        all_rows.extend(rows)

    result = []
    for cells in all_rows:
        # cells: 序号, 代码, 名称, 现价, 涨跌幅(%), 涨跌, 涨速(%), 换手(%), 量比, 振幅(%), 成交额, 流通股, 流通市值, 市盈率
        try:
            price = float(cells[3]) if cells[3] not in ("--", "") else 0.0
        except Exception:
            price = 0.0
        try:
            pct = float(cells[4]) if cells[4] not in ("--", "") else 0.0
        except Exception:
            pct = 0.0
        try:
            turnover = cells[7] if len(cells) > 7 else "--"
        except Exception:
            turnover = "--"
        # 流通市值(亿)
        mktcap = 0.0
        if len(cells) > 12:
            raw = cells[12].replace("亿", "").strip()
            try:
                mktcap = float(raw)
            except Exception:
                mktcap = 0.0

        result.append({
            "symbol":   cells[1],
            "name":     cells[2],
            "price":    round(price, 2),
            "pct":      round(pct, 2),
            "mktcap":   round(mktcap, 2),
            "volume":   cells[10] if len(cells) > 10 else "--",   # 成交额
            "turnover": turnover,
        })

    # 按涨跌幅降序（龙头在前）
    result.sort(key=lambda x: x["pct"], reverse=True)
    return result


@router.get("/summary")
def industry_summary():
    """
    返回同花顺90行业今日涨跌幅、上涨家数、领涨股等数据。
    缓存5分钟，避免频繁请求。
    """
    now = time.time()
    if _cache["data"] and now - _cache["ts"] < _CACHE_TTL:
        return {"industries": _cache["data"], "updated_at": _cache.get("updated_at", "")}

    try:
        import akshare as ak
        old = sys.stderr
        sys.stderr = io.StringIO()
        try:
            df = ak.stock_board_industry_summary_ths()
        finally:
            sys.stderr = old

        if df is None or df.empty:
            raise HTTPException(status_code=503, detail="行业数据为空")

        result = []
        for _, row in df.iterrows():
            pct_raw = str(row.get("涨跌幅", "0") or "0").replace('%', '').strip()
            try:
                pct_num = float(pct_raw)
                pct_str = f"{'+' if pct_num > 0 else ''}{pct_num:.2f}%"
            except ValueError:
                pct_num = 0.0
                pct_str = "--"

            result.append({
                "name":       str(row.get("板块", "")),
                "pct":        pct_str,
                "pct_num":    pct_num,
                "up_count":   str(row.get("上涨家数", "--")),
                "down_count": str(row.get("下跌家数", "--")),
                "net_in":     str(row.get("净流入", "--")),
                "leader":     str(row.get("领涨股", "--")),
            })

        # 按涨幅排序
        result.sort(key=lambda x: x["pct_num"], reverse=True)

        from datetime import datetime
        updated_at = datetime.now().strftime("%H:%M:%S")
        _cache["data"] = result
        _cache["ts"] = now
        _cache["updated_at"] = updated_at
        return {"industries": result, "updated_at": updated_at}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"行业数据获取失败: {e}")


@router.get("/stocks/{industry_name}")
def industry_stocks(industry_name: str):
    """
    获取指定行业的成分股列表（带实时行情），按涨跌幅降序排列。
    数据源：同花顺行业详情页（不依赖东方财富）
    缓存 5 分钟。
    """
    now = time.time()
    cached = _stock_cache.get(industry_name)
    if cached:
        ts, data = cached
        if now - ts < _STOCK_TTL:
            return data

    try:
        result = _fetch_ths_industry_stocks(industry_name)
        _stock_cache[industry_name] = (now, result)
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"成分股获取失败: {e}")
