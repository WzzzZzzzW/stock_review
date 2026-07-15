"""
新闻获取层
- fetch_url_text(url): 抓取链接正文
- get_news_feed():     聚合 RSS，带30分钟缓存
"""
import re
import time
import httpx
import xml.etree.ElementTree as ET
from html.parser import HTMLParser


# ── RSS 源 ──────────────────────────────────────────────────────────
RSS_SOURCES = [
    # ── Google News 主题搜索（覆盖宏观传导链）──
    {
        "name": "关税贸易",
        "url": "https://news.google.com/rss/search?q=tariff+trade+war+china+export+import&hl=en&gl=US&ceid=US:en",
    },
    {
        "name": "美联储利率",
        "url": "https://news.google.com/rss/search?q=federal+reserve+interest+rate+inflation&hl=en&gl=US&ceid=US:en",
    },
    {
        "name": "大宗商品",
        "url": "https://news.google.com/rss/search?q=oil+price+commodity+metals+copper+iron+ore&hl=en&gl=US&ceid=US:en",
    },
    {
        "name": "芯片科技",
        "url": "https://news.google.com/rss/search?q=semiconductor+chip+export+ban+AI+technology+restriction&hl=en&gl=US&ceid=US:en",
    },
    # ── 用户特别关注：国外巨头 IPO + Musk 系 ──
    {
        "name": "科技IPO",
        "url": "https://news.google.com/rss/search?q=tech+IPO+2026+stock+market+debut+listing&hl=en&gl=US&ceid=US:en",
    },
    {
        "name": "马斯克",
        "url": "https://news.google.com/rss/search?q=Elon+Musk+xAI+Neuralink+SpaceX+Tesla&hl=en&gl=US&ceid=US:en",
    },
    {
        "name": "英伟达台积电",
        "url": "https://news.google.com/rss/search?q=Nvidia+TSMC+ASML+chip+Taiwan+AI&hl=en&gl=US&ceid=US:en",
    },
    {
        "name": "地缘政治",
        "url": "https://news.google.com/rss/search?q=China+US+geopolitics+tensions+Taiwan+strait&hl=en&gl=US&ceid=US:en",
    },
    {
        "name": "科技巨头",
        "url": "https://news.google.com/rss/search?q=Apple+Microsoft+Amazon+Google+Meta+earnings&hl=en&gl=US&ceid=US:en",
    },
    # ── 编辑筛选源（更高权威度）──
    {
        "name": "Reuters商业",
        "url": "https://feeds.reuters.com/reuters/businessNews",
    },
    {
        "name": "BBC商业",
        "url": "https://feeds.bbci.co.uk/news/business/rss.xml",
    },
    {
        "name": "CNBC市场",
        "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    },
    {
        "name": "CNBC科技",
        "url": "https://www.cnbc.com/id/19854910/device/rss/rss.html",
    },
    {
        "name": "FT商业",
        "url": "https://www.ft.com/rss/home",
    },
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_feed_cache: dict = {"items": [], "ts": 0.0}
CACHE_TTL = 1800  # 30 分钟


# ── HTML 纯文本提取器 ────────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "header", "aside", "noscript", "meta", "link"}

    def __init__(self):
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag.lower() in self.SKIP and self._skip > 0:
            self._skip -= 1

    def handle_data(self, data):
        if self._skip == 0:
            s = data.strip()
            if len(s) > 15:
                self.parts.append(s)

    def result(self) -> str:
        text = "\n".join(self.parts)
        return re.sub(r"\n{3,}", "\n\n", text)


def fetch_url_text(url: str, timeout: int = 12) -> str:
    """
    抓取 URL，提取可读正文（最长5000字）。
    失败时抛出异常，调用方负责处理。
    """
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=_HEADERS) as client:
        resp = client.get(url)
        resp.raise_for_status()

    html = resp.text
    # 去注释、去 <style> 内联
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)

    extractor = _TextExtractor()
    extractor.feed(html)
    text = extractor.result()

    if len(text) < 80:
        raise ValueError("页面正文过短，可能需要登录或内容受保护")

    return text[:5000]


# ── RSS 解析 ─────────────────────────────────────────────────────────

def _parse_rss(xml_text: str, source_name: str) -> list[dict]:
    """解析 RSS 2.0 / Atom，返回标准化文章列表"""
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    ATOM_NS = "http://www.w3.org/2005/Atom"

    # RSS 2.0
    for item in root.findall(".//item"):
        title   = (item.findtext("title") or "").strip()
        url     = (item.findtext("link")  or "").strip()
        summary = re.sub(r"<[^>]+>", "", item.findtext("description") or "")[:300].strip()
        pub     = (item.findtext("pubDate") or "").strip()   # 保留完整日期字符串
        if title:
            items.append({"title": title, "url": url, "summary": summary,
                           "published": pub, "source": source_name})

    # Atom
    if not items:
        for entry in root.findall(f".//{{{ATOM_NS}}}entry") or root.findall(".//entry"):
            def _t(tag):
                return (entry.findtext(f"{{{ATOM_NS}}}{tag}") or entry.findtext(tag) or "").strip()
            title = _t("title")
            url   = ""
            for lnk in (entry.findall(f"{{{ATOM_NS}}}link") or entry.findall("link")):
                if lnk.get("rel", "alternate") in ("alternate", ""):
                    url = lnk.get("href", "")
                    break
            summary = re.sub(r"<[^>]+>", "", _t("summary"))[:300]
            pub     = (_t("updated") or _t("published")).strip()   # 保留完整日期字符串
            if title:
                items.append({"title": title, "url": url, "summary": summary,
                               "published": pub, "source": source_name})

    return items[:8]


def _fetch_one_rss(source: dict) -> list[dict]:
    try:
        with httpx.Client(follow_redirects=True, timeout=8, headers=_HEADERS) as c:
            resp = c.get(source["url"])
            resp.raise_for_status()
        return _parse_rss(resp.text, source["name"])
    except Exception:
        return []


def get_news_feed(force_refresh: bool = False) -> list[dict]:
    """
    返回聚合新闻列表，带30分钟内存缓存。
    [{title, url, summary, published, source}]
    """
    global _feed_cache
    now = time.time()
    if not force_refresh and now - _feed_cache["ts"] < CACHE_TTL and _feed_cache["items"]:
        return _feed_cache["items"]

    all_items: list[dict] = []
    for src in RSS_SOURCES:
        all_items.extend(_fetch_one_rss(src))

    # 去重（标题前30字）
    seen: set[str] = set()
    deduped: list[dict] = []
    for it in all_items:
        key = it["title"][:30].lower()
        if key not in seen and len(it["title"]) > 10:
            seen.add(key)
            deduped.append(it)

    # 限到 60 条：给 trending 评分留足原料，AI 只会对前 N 条打标签
    result = deduped[:60]
    _feed_cache = {"items": result, "ts": now}
    return result
