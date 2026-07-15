"""
A股本土新闻获取层 — 实时财经快讯版
聚焦像 财联社/东方财富 那种实时金融快讯，每条都带完整内容

数据源（已全部验证可用，单次0.4-0.8s）：
  ✅ 财联社电报      (stock_info_global_cls)   — 20条/次，金融快讯，含全文+发布时间
  ✅ 东方财富全球财经 (stock_info_global_em)    — 200条/次，含摘要+链接，量最大
  ✅ 同花顺财经      (stock_info_global_ths)   — 20条/次，含全文+链接
  ✅ 富途快讯        (stock_info_global_futu)  — 50条/次，含全文+链接
  ✅ 新浪全球财经    (stock_info_global_sina)  — 20条/次，纯内容
  ✅ 央视新闻        (news_cctv)               — 政策类
"""
import time
import datetime
import re
import threading

_cache: dict = {"items": [], "ts": 0.0}
CACHE_TTL = 300   # 5分钟，比之前的15分钟更新更快


def _clean(s: str) -> str:
    """清理标题/内容中的多余空白"""
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _strip_title_brackets(content: str, title: str) -> str:
    """如果内容以【标题】开头，去掉这个前缀"""
    if not content:
        return ""
    # 去掉【XXX】前缀
    content = re.sub(r"^\s*【[^】]+】\s*", "", content)
    return content.strip()


def _to_iso(date_val, time_val=None) -> str:
    """统一时间格式为 ISO 字符串"""
    if not date_val:
        return ""
    s = str(date_val).strip()
    if time_val:
        t = str(time_val).strip()
        if t and len(s) <= 10:
            return f"{s} {t}"
    return s


# ── 各数据源 ──────────────────────────────────────────────────────────

def _fetch_cls() -> list[dict]:
    """财联社电报 — 实时金融快讯，最高优先级"""
    try:
        import akshare as ak
        df = ak.stock_info_global_cls()
        items = []
        for _, row in df.iterrows():
            title = _clean(row.get("标题", ""))
            content = _clean(row.get("内容", ""))
            if not title and not content:
                continue
            published = _to_iso(row.get("发布日期", ""), row.get("发布时间", ""))
            items.append({
                "title": title or content[:60],
                "content": _strip_title_brackets(content, title),
                "summary": _strip_title_brackets(content, title)[:300],
                "url": "",
                "published": published,
                "source": "财联社",
                "source_type": "flash",
            })
        return items
    except Exception:
        return []


def _fetch_em() -> list[dict]:
    """东方财富全球财经 — 量最大，含原文链接"""
    try:
        import akshare as ak
        df = ak.stock_info_global_em()
        items = []
        for _, row in df.head(50).iterrows():  # 取前50条最新的
            title = _clean(row.get("标题", ""))
            content = _clean(row.get("摘要", ""))
            if not title:
                continue
            items.append({
                "title": title,
                "content": _strip_title_brackets(content, title),
                "summary": _strip_title_brackets(content, title)[:300],
                "url": _clean(row.get("链接", "")),
                "published": _clean(row.get("发布时间", "")),
                "source": "东方财富",
                "source_type": "news",
            })
        return items
    except Exception:
        return []


def _fetch_ths() -> list[dict]:
    """同花顺财经 — 全文+链接"""
    try:
        import akshare as ak
        df = ak.stock_info_global_ths()
        items = []
        for _, row in df.iterrows():
            title = _clean(row.get("标题", ""))
            content = _clean(row.get("内容", ""))
            if not title and not content:
                continue
            items.append({
                "title": title or content[:60],
                "content": content,
                "summary": content[:300],
                "url": _clean(row.get("链接", "")),
                "published": _clean(row.get("发布时间", "")),
                "source": "同花顺",
                "source_type": "news",
            })
        return items
    except Exception:
        return []


def _fetch_futu() -> list[dict]:
    """富途快讯 — 量大，全文"""
    try:
        import akshare as ak
        df = ak.stock_info_global_futu()
        items = []
        for _, row in df.head(30).iterrows():
            title = _clean(row.get("标题", ""))
            content = _clean(row.get("内容", ""))
            if not title and not content:
                continue
            items.append({
                "title": title or content[:60],
                "content": content,
                "summary": content[:300],
                "url": _clean(row.get("链接", "")),
                "published": _clean(row.get("发布时间", "")),
                "source": "富途",
                "source_type": "news",
            })
        return items
    except Exception:
        return []


def _fetch_sina() -> list[dict]:
    """新浪全球财经 — 纯内容"""
    try:
        import akshare as ak
        df = ak.stock_info_global_sina()
        items = []
        for _, row in df.iterrows():
            content = _clean(row.get("内容", ""))
            if not content:
                continue
            cleaned = _strip_title_brackets(content, "")
            # 从【】里提取标题
            m = re.match(r"^\s*【([^】]+)】", content)
            title = _clean(m.group(1)) if m else cleaned[:60]
            items.append({
                "title": title,
                "content": cleaned,
                "summary": cleaned[:300],
                "url": "",
                "published": _clean(row.get("时间", "")),
                "source": "新浪财经",
                "source_type": "flash",
            })
        return items
    except Exception:
        return []


def _fetch_cctv() -> list[dict]:
    """CCTV — 政策性新闻"""
    try:
        import akshare as ak
        today = datetime.date.today().strftime("%Y%m%d")
        df = ak.news_cctv(date=today)
        items = []
        for _, row in df.head(5).iterrows():
            title = _clean(row.get("title", ""))
            content = _clean(row.get("content", ""))
            if title:
                items.append({
                    "title": title,
                    "content": content,
                    "summary": content[:300],
                    "url": "",
                    "published": today,
                    "source": "央视新闻",
                    "source_type": "policy",
                })
        return items
    except Exception:
        return []


# ── 并发聚合 ─────────────────────────────────────────────────────────────

def _fetch_all_concurrent() -> list[dict]:
    """所有源并发拉取，3秒超时"""
    results: dict[str, list] = {}

    def run(name, fn):
        try:
            results[name] = fn()
        except Exception:
            results[name] = []

    fetchers = [
        ("cls",  _fetch_cls),
        ("em",   _fetch_em),
        ("ths",  _fetch_ths),
        ("futu", _fetch_futu),
        ("sina", _fetch_sina),
        ("cctv", _fetch_cctv),
    ]

    threads = [threading.Thread(target=run, args=(n, f), daemon=True) for n, f in fetchers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=4)

    # 按优先级顺序拼接
    return (
        results.get("cls", []) +
        results.get("em", []) +
        results.get("ths", []) +
        results.get("futu", []) +
        results.get("sina", []) +
        results.get("cctv", [])
    )


def aggregate_cn_news(force_refresh: bool = False) -> list[dict]:
    """
    实时财经快讯聚合，带5分钟缓存。
    返回字段：{title, content, summary, url, published, source, source_type}
    """
    global _cache
    now = time.time()

    if not force_refresh and now - _cache["ts"] < CACHE_TTL and _cache["items"]:
        return _cache["items"]

    all_items = _fetch_all_concurrent()

    # 去重（基于标题前30字）
    seen: set[str] = set()
    deduped: list[dict] = []
    for item in all_items:
        key = re.sub(r"\s+", "", item.get("title", ""))[:30]
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)

    # 按发布时间倒序（最新在前），无时间的排后面
    def _sort_key(x):
        t = x.get("published", "")
        return (t == "", t)  # 有时间的优先，时间倒序
    deduped.sort(key=_sort_key, reverse=True)

    result = deduped[:60]  # 最多返回60条
    _cache = {"items": result, "ts": now}

    return result
