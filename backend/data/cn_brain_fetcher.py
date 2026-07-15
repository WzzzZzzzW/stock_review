"""
脑库自动导入 — 中国财经内容聚合层

把"能稳定拿到全文/实质内容"的中国源统一成标准条目，供脑库每日自动提炼。
区别于 cn_news_fetcher（那是给推荐系统用的实时快讯），这里偏"可沉淀成规则"的内容：
  ✅ 财联社 / 东方财富 / 同花顺 / 富途 / 新浪  — 复用 cn_news_fetcher 的全文快讯
  ✅ 央视新闻                                  — 政策类
  ✅ 东方财富研报观点 (stock_research_report_em) — 个股/行业逻辑 + 评级 + 机构

每条统一字段：
  {uid, title, content, source, published, bucket}
  bucket ∈ {"news", "policy", "research"}  —— 决定后续如何分组提炼
  uid    —— 内容指纹（md5），用于跨天去重
"""
import hashlib
import html
import re
import threading
import xml.etree.ElementTree as ET

from data import cn_news_fetcher

# 默认 RSS 源（已实测可拉到真 XML；用户可在前端增删）
DEFAULT_RSS_FEEDS = [
    {"url": "https://36kr.com/feed", "name": "36氪"},
    {"url": "https://36kr.com/feed-newsflash", "name": "36氪快讯"},
    {"url": "https://www.tmtpost.com/feed", "name": "钛媒体"},
]

_RSS_UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
}
_ATOM = "{http://www.w3.org/2005/Atom}"


def _uid(source: str, title: str) -> str:
    key = re.sub(r"\s+", "", f"{source}|{title}")[:80]
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:16]


def _clean(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


# ── 快讯 / 政策（复用 cn_news_fetcher）──────────────────────────────────────────

# cn_news_fetcher 里的 source_type → 我们的 bucket
_NEWS_BUCKET = {
    "flash": "news",
    "news": "news",
    "policy": "policy",
}


def _fetch_news_items() -> list[dict]:
    """复用已验证的 6 源快讯聚合，转成脑库标准条目"""
    items: list[dict] = []
    try:
        raw = cn_news_fetcher.aggregate_cn_news()
    except Exception:
        return items

    for r in raw:
        title = _clean(r.get("title", ""))
        content = _clean(r.get("content", "")) or _clean(r.get("summary", ""))
        if not title and not content:
            continue
        src = _clean(r.get("source", "财经"))
        bucket = _NEWS_BUCKET.get(r.get("source_type", "news"), "news")
        items.append({
            "uid": _uid(src, title or content[:40]),
            "title": title or content[:40],
            "content": content,
            "source": src,
            "published": _clean(r.get("published", "")),
            "bucket": bucket,
        })
    return items


# ── 研报观点（东方财富）─────────────────────────────────────────────────────────

def _fetch_research_items(top_n: int = 60) -> list[dict]:
    """
    东方财富研报中心：标题里通常带一句核心观点，附评级/机构/行业。
    没有全文（全文在 PDF 里），但"报告名称 + 评级 + 机构 + 行业"已经能提炼出个股/行业逻辑。
    """
    items: list[dict] = []
    try:
        import akshare as ak
        df = ak.stock_research_report_em()
    except Exception:
        return items

    if df is None or len(df) == 0:
        return items

    # 按日期倒序，取最新的 top_n 条
    try:
        df = df.sort_values("日期", ascending=False)
    except Exception:
        pass

    for _, row in df.head(top_n).iterrows():
        name = _clean(row.get("股票简称", ""))
        report = _clean(row.get("报告名称", ""))
        org = _clean(row.get("机构", ""))
        rating = _clean(row.get("东财评级", ""))
        industry = _clean(row.get("行业", ""))
        date = _clean(row.get("日期", ""))
        if not name or not report:
            continue
        title = f"{org}：{name}「{report}」"
        content = (
            f"{org}给予{name}（{industry}）评级「{rating or '未评级'}」。"
            f"研报观点：{report}。"
        )
        items.append({
            "uid": _uid("研报", f"{name}{report}"),
            "title": title,
            "content": content,
            "source": f"研报·{org}",
            "published": date,
            "bucket": "research",
        })
    return items


# ── RSS 长文（36氪 / 钛媒体 / 用户自定义）──────────────────────────────────────

def _strip_html(s: str) -> str:
    """去标签 + 反转义 HTML 实体（&nbsp; 等）"""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _parse_rss(content: bytes) -> list[dict]:
    """stdlib 解析 RSS2.0 / Atom，返回 [{title, content, link, published}]"""
    out: list[dict] = []
    try:
        root = ET.fromstring(content)
    except Exception:
        return out

    # RSS 2.0: channel/item
    items = root.findall(".//item")
    if items:
        for it in items:
            def g(tag):
                e = it.find(tag)
                return e.text if e is not None and e.text else ""
            body = (
                g("{http://purl.org/rss/1.0/modules/content/}encoded")
                or g("description")
            )
            out.append({
                "title": _strip_html(g("title")),
                "content": _strip_html(body),
                "link": g("link").strip(),
                "published": g("pubDate").strip(),
            })
        return out

    # Atom: entry
    for it in root.findall(f".//{_ATOM}entry"):
        def ga(tag):
            e = it.find(f"{_ATOM}{tag}")
            return e.text if e is not None and e.text else ""
        link_el = it.find(f"{_ATOM}link")
        link = link_el.get("href", "") if link_el is not None else ""
        out.append({
            "title": _strip_html(ga("title")),
            "content": _strip_html(ga("content") or ga("summary")),
            "link": link.strip(),
            "published": (ga("published") or ga("updated")).strip(),
        })
    return out


def _fetch_one_rss(feed: dict, results: list, lock: threading.Lock):
    name = feed.get("name") or feed.get("url", "RSS")
    url = feed.get("url", "")
    if not url:
        return
    try:
        import requests
        r = requests.get(url, headers=_RSS_UA, timeout=12)
        if r.status_code != 200:
            return
        entries = _parse_rss(r.content)
    except Exception:
        return
    rows = []
    for e in entries:
        title = e["title"]
        content = e["content"] or title
        if not title:
            continue
        rows.append({
            "uid": _uid(name, title),
            "title": title,
            "content": content,
            "source": name,
            "published": e["published"],
            "bucket": "article",
        })
    with lock:
        results.extend(rows)


def _fetch_rss_items(feeds: list[dict]) -> list[dict]:
    """并发拉取所有 RSS 源（单源失败静默跳过）"""
    if not feeds:
        return []
    results: list[dict] = []
    lock = threading.Lock()
    threads = [
        threading.Thread(target=_fetch_one_rss, args=(f, results, lock), daemon=True)
        for f in feeds
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=14)
    return results


# ── 对外主入口 ─────────────────────────────────────────────────────────────────

def fetch_brain_items(include_research: bool = True,
                      rss_feeds: list[dict] | None = None) -> list[dict]:
    """
    聚合所有中国源的脑库候选条目（已带 uid 去重指纹，未去重）。
    返回 [{uid, title, content, source, published, bucket}]
    rss_feeds: [{url, name}] 列表；None 表示不抓 RSS。
    """
    items = _fetch_news_items()
    if include_research:
        items += _fetch_research_items()
    if rss_feeds:
        items += _fetch_rss_items(rss_feeds)

    # 同一次内部去重（按 uid）
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        u = it["uid"]
        if u in seen:
            continue
        seen.add(u)
        out.append(it)
    return out


# 桶 → 中文标签
BUCKET_LABEL = {
    "news": "财经快讯",
    "policy": "政策要闻",
    "research": "机构研报",
    "article": "深度长文",
}
