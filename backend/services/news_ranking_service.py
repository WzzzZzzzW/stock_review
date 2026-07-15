"""
新闻热搜榜服务 —— 给 news_feed / news_feed_cn 的条目算「A 股影响力热度」+ 跨源聚类
─────────────────────────────────────────────────────────────────────────────
核心组件：
- 跨源聚类：标题/摘要分词后做 Jaccard 相似度，同一事件多家媒体合并为一个 cluster
- 来源权重：财新/路透/Bloomberg/CCTV 这类权威源加分，自媒体降权
- 新鲜度：6 小时半衰期指数衰减
- 关键词加成：IPO、Fed、加息、关税、芯片、油价 … 这些有强传导链的事件加分
- 综合热度：source × freshness × cluster_boost × keyword_boost × direction_boost

为什么纯算法不调 AI 聚类：1) 免 token 成本 2) 不增加延迟 3) Jaccard 在标题级别足够准
"""
from __future__ import annotations
import math
import re
import time
from datetime import datetime, timezone

# ── 来源权重 ──────────────────────────────────────────────────────────────────
# 权威媒体加分；自媒体/Google News 这类聚合源略低
_SOURCE_WEIGHT = {
    # 国内权威
    "财新":           1.20,
    "央视新闻":       1.15,
    "CCTV":           1.15,
    "财联社":         1.10,
    "东方财富":       1.00,
    "同花顺":         1.00,
    "新浪财经":       0.95,
    "富途":           0.95,
    "SHMET快讯":      0.90,
    # 国际权威
    "Reuters":        1.20,
    "Reuters商业":    1.20,
    "Bloomberg":      1.20,
    "Financial Times": 1.20,
    "FT商业":         1.20,
    "BBC商业":        1.10,
    "BBC":            1.10,
    "WSJ":            1.15,
    "CNBC市场":       1.10,
    "CNBC科技":       1.10,
    "CNBC":           1.10,
    # 主题聚合（Google News）—— 略低，因为是搜索结果而非编辑筛选
    "Google财经":     0.85,
    "关税贸易":       0.90,
    "美联储利率":     0.90,
    "大宗商品":       0.90,
    "芯片科技":       0.90,
    "科技IPO":        0.95,  # 用户特别关注
    "马斯克":         0.95,  # 用户特别关注
    "英伟达台积电":   0.95,
    "地缘政治":       0.90,
    "科技巨头":       0.90,
}
_DEFAULT_SOURCE_WEIGHT = 0.85


def _source_weight(source: str) -> float:
    if not source:
        return _DEFAULT_SOURCE_WEIGHT
    # 前缀匹配（"Reuters商业" 也命中 "Reuters"）
    for k, w in _SOURCE_WEIGHT.items():
        if source.startswith(k):
            return w
    return _DEFAULT_SOURCE_WEIGHT


# ── 关键词加成（按市场区分）──────────────────────────────────────────────────
# 命中越多越热；权重表示该关键词的"A 股传导含金量"
_KEYWORDS_CN = {
    # 政策/监管
    "央行": 1.0, "证监会": 1.0, "银保监会": 0.8, "财政部": 0.9, "国务院": 0.8,
    "降息": 1.2, "降准": 1.2, "加息": 1.2, "MLF": 0.9, "LPR": 1.0,
    "政策": 0.5, "新政": 0.7, "印花税": 1.0,
    # 产业链
    "新能源": 0.9, "光伏": 0.9, "锂电": 0.9, "储能": 0.8,
    "半导体": 1.0, "芯片": 1.0, "AI": 1.0, "大模型": 1.0,
    "军工": 0.7, "医药": 0.6, "创新药": 0.9,
    "白酒": 0.6, "消费": 0.5,
    # 事件
    "IPO": 0.9, "上市": 0.5, "重组": 0.8, "并购": 0.8,
    "涨停": 0.7, "跌停": 0.7, "停牌": 0.7,
    "龙头": 0.6, "业绩": 0.5, "财报": 0.6,
}
_KEYWORDS_INTL = {
    # 货币/利率（强 A 股传导）
    "Fed": 1.5, "Federal Reserve": 1.5, "interest rate": 1.2, "rate cut": 1.4,
    "rate hike": 1.4, "inflation": 1.0, "CPI": 1.0, "PCE": 0.9, "FOMC": 1.3,
    # 贸易/关税
    "tariff": 1.5, "trade war": 1.4, "export ban": 1.3, "sanction": 1.2,
    "chip export": 1.4, "semiconductor": 1.2,
    # 大宗/汇率
    "oil": 1.0, "crude": 1.0, "copper": 0.9, "iron ore": 0.9,
    "yuan": 1.1, "RMB": 1.1, "dollar": 0.8,
    # 科技巨头/IPO（用户特别提及）
    "IPO":      1.6, "listing":   0.9, "market debut": 1.2,
    "Musk":     1.5, "xAI":       1.5, "Neuralink": 1.3, "SpaceX": 1.0,
    "OpenAI":   1.2, "Anthropic": 1.0,
    "Nvidia":   1.3, "TSMC":      1.3, "ASML":      1.2,
    "Apple":    0.9, "Tesla":     1.0, "Microsoft": 0.8, "Google": 0.7, "Meta": 0.7,
    # 地缘
    "Taiwan":   1.2, "Taiwan strait": 1.3,
    "China":    0.8, "Russia": 0.7,
}


def _keyword_boost(text: str, market: str) -> float:
    """返回 0..3 的加成值。命中多个关键词时按 log 收益递减。"""
    kw_table = _KEYWORDS_CN if market == "cn" else _KEYWORDS_INTL
    low = text or ""
    if market != "cn":
        low = low.lower()
    score = 0.0
    for kw, w in kw_table.items():
        check = kw if market == "cn" else kw.lower()
        if check in low:
            score += w
    if score <= 0:
        return 0.0
    # log 收益递减：3 个强关键词得 ~2.0，1 个 ~1.0
    return min(3.0, math.log1p(score))


# ── 新鲜度（半衰期 6 小时）────────────────────────────────────────────────────

def _freshness(published: str | None, half_life_h: float = 6.0) -> float:
    """0..1。无时间戳默认 0.5（中位）。"""
    if not published:
        return 0.5
    try:
        # 支持 ISO 8601 / RFC 822 / 简单日期
        s = published.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            # RFC 822（RSS 常见）
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(published)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
        if age_h < 0:
            return 1.0
        return float(math.exp(-math.log(2) * age_h / half_life_h))
    except Exception:
        return 0.5


# ── 标题分词 + 聚类 ──────────────────────────────────────────────────────────
# CN：jieba 可用则 jieba；否则用 2-gram 兜底（无依赖）
# EN：lowercase + 去停用词 + 词干（简单复数去除）

_STOPWORDS_CN = {
    "的", "了", "和", "是", "在", "对", "与", "及", "或", "为", "有", "等",
    "今日", "今天", "昨日", "昨天", "本周", "本月", "近日",
    "据", "称", "表示", "宣布", "消息", "报道", "公告", "突发",
}
_STOPWORDS_EN = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "by",
    "is", "are", "was", "were", "be", "as", "at", "with", "from", "that",
    "this", "it", "its", "but", "not", "has", "have", "had", "will",
    "says", "said", "amid", "after", "before", "over", "into",
}


def _tokenize_cn(text: str) -> set[str]:
    text = re.sub(r"[　\s·・,，.。!！?？\(\)（）\[\]【】「」《》\"'：:;；\-—_/+]", " ", text)
    try:
        import jieba   # type: ignore
        toks = [t.strip() for t in jieba.cut(text) if t.strip()]
    except Exception:
        toks = []
        # 2-gram 兜底
        compact = re.sub(r"\s+", "", text)
        for i in range(len(compact) - 1):
            toks.append(compact[i:i + 2])
    return {t for t in toks if len(t) >= 2 and t not in _STOPWORDS_CN}


def _tokenize_en(text: str) -> set[str]:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    toks = [t for t in text.split() if len(t) >= 3 and t not in _STOPWORDS_EN]
    # 简单复数归一
    norm = []
    for t in toks:
        if len(t) > 4 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        norm.append(t)
    return set(norm)


def _tokenize(text: str, market: str) -> set[str]:
    return _tokenize_cn(text) if market == "cn" else _tokenize_en(text)


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def _cluster_items(items: list[dict], market: str, threshold: float = 0.30) -> list[list[int]]:
    """
    返回 [[item_idx, ...], ...]，按标题相似度贪心聚类。
    O(N^2) 对 60 条以内可接受。
    """
    n = len(items)
    if n == 0:
        return []
    titles = []
    for it in items:
        t = (it.get("title_cn") or it.get("title") or "") + " " + (it.get("summary") or "")
        titles.append(_tokenize(t, market))
    clusters: list[list[int]] = []
    used = [False] * n
    for i in range(n):
        if used[i]:
            continue
        group = [i]
        used[i] = True
        for j in range(i + 1, n):
            if used[j]:
                continue
            if _jaccard(titles[i], titles[j]) >= threshold:
                group.append(j)
                used[j] = True
        clusters.append(group)
    return clusters


# ── 综合热度评分 ─────────────────────────────────────────────────────────────

def _direction_strength(direction: str) -> float:
    """有明确方向（利好/利空）比 neutral 加分。"""
    return 1.10 if direction in ("positive", "negative") else 0.85


def _item_score(item: dict, market: str) -> float:
    src   = _source_weight(item.get("source", ""))
    fresh = _freshness(item.get("published"))
    text  = (item.get("title_cn") or item.get("title") or "") + " " + (item.get("summary") or "")
    kw    = _keyword_boost(text, market)
    dirf  = _direction_strength(item.get("direction") or "neutral")
    # 基础分 + 关键词加成 + 方向乘数
    return src * fresh * (1.0 + kw) * dirf


def _cluster_summary(group: list[dict]) -> dict:
    """从一组同事件 item 选 representative + 合并 sources/stocks。"""
    # 代表条目：来源权重最高 + 标题最长（更具描述性）
    rep = max(group, key=lambda x: (_source_weight(x.get("source", "")), len(x.get("title_cn") or x.get("title") or "")))
    sources = []
    seen_src = set()
    stocks   = []
    seen_st  = set()
    direction_votes = {"positive": 0, "negative": 0, "neutral": 0}
    one_lines = []
    for it in group:
        s = it.get("source") or ""
        if s and s not in seen_src:
            sources.append(s); seen_src.add(s)
        for st in (it.get("stocks") or []):
            if st and st not in seen_st:
                stocks.append(st); seen_st.add(st)
        direction_votes[it.get("direction") or "neutral"] = direction_votes.get(it.get("direction") or "neutral", 0) + 1
        if it.get("one_line"):
            one_lines.append(it["one_line"])
    # direction 多数投票（neutral 平局时优先非 neutral）
    direction = max(direction_votes, key=lambda k: (direction_votes[k], 0 if k == "neutral" else 1))
    # one_line 取代表条目的；若空则用任一非空
    one_line = rep.get("one_line") or (one_lines[0] if one_lines else "")
    return {
        "title":      rep.get("title_cn") or rep.get("title") or "",
        "title_en":   rep.get("title") if rep.get("title_cn") else "",
        "summary":    rep.get("summary") or "",
        "url":        rep.get("url") or "",
        "published":  rep.get("published") or "",
        "one_line":   one_line,
        "direction":  direction,
        "stocks":     stocks[:6],
        "sources":    sources,
        "source_count": len(sources),
    }


def compute_trending(items: list[dict], market: str, top_n: int = 10,
                     min_hotness: float = 1.0) -> list[dict]:
    """
    返回 top_n 个聚类后的热搜条目，按热度倒序。
    market='cn' | 'intl'
    min_hotness：过滤掉热度极低的（多为 24h+ 旧档案/无关条目）。
    """
    if not items:
        return []
    clusters = _cluster_items(items, market)
    rows: list[dict] = []
    for group_idx in clusters:
        group = [items[i] for i in group_idx]
        # cluster 热度 = max(item_score) × cluster_size 收益（log）
        item_scores = [_item_score(it, market) for it in group]
        base = max(item_scores)
        # 跨源加成：cluster_size>=2 显著加成；同一来源多条不算（按来源去重）
        unique_srcs = {it.get("source") for it in group if it.get("source")}
        cluster_boost = 1.0 + 0.4 * math.log1p(len(unique_srcs))
        hot = base * cluster_boost * 100  # 放大到 0..400 区间，便于人眼读
        if hot < min_hotness:
            continue
        summary = _cluster_summary(group)
        summary["hotness"] = round(hot, 1)
        summary["cluster_size"] = len(group)
        rows.append(summary)
    rows.sort(key=lambda r: r["hotness"], reverse=True)
    for i, r in enumerate(rows[:top_n]):
        r["rank"] = i + 1
    return rows[:top_n]
