"""
今日市场复盘 —— 多维度纯数据生成（零 AI 调用，零成本）

数据源：
  · 全市场实时行情（腾讯，绕代理）→ 涨跌家数 / 涨跌分布 / 涨跌幅榜 / 成交额榜 / 换手榜 / 市值分层 / 两市成交额
  · 涨停/跌停/炸板股池（akshare，按日期）→ 涨停跌停数 / 连板梯队 / 炸板率 / 涨停行业分布
  · 大盘指数（新浪，实时）→ 上证/深证/创业板/沪深300
  · 板块热力（复用 daily_report）→ 涨跌幅前后板块
  · 综合 → 市场情绪温度计

说明：涨跌家数/分布/榜单/指数/板块为"生成时刻"的实时快照——配合每日 15:50 自动生成，
即为当日收盘快照；涨停/跌停/炸板池按日期精确，历史日期亦准确。
"""
import time
import datetime as _dt
from collections import Counter, defaultdict


# ── 全市场行情（复用 api.market 的腾讯数据源 + 缓存）─────────────────────────────

def _get_quotes() -> list[dict]:
    from api.market import _cache as _mkt_cache, _load_quotes, CACHE_TTL
    now = time.time()
    if _mkt_cache["data"] and now - _mkt_cache["ts"] < CACHE_TTL:
        return _mkt_cache["data"]
    data = _load_quotes()
    _mkt_cache["data"] = data
    _mkt_cache["ts"] = now
    return data


# ── 涨停 / 跌停 / 炸板股池（akshare，按日期）─────────────────────────────────────

def _fetch_zt(date_fmt: str) -> list[dict]:
    """复用 limitup_fetcher 的涨停股池（含连板/封板资金/行业等丰富字段）"""
    try:
        from data.limitup_fetcher import fetch_zt_pool
        return fetch_zt_pool(date_fmt)
    except Exception:
        return []


def _safe_float(v, default=0.0) -> float:
    try:
        f = float(v)
        return default if f != f else f
    except Exception:
        return default


def _fetch_dt(date_fmt: str) -> list[dict]:
    """跌停股池（akshare 当前函数名 stock_zt_pool_dtgc_em）"""
    try:
        import akshare as ak
        df = ak.stock_zt_pool_dtgc_em(date=date_fmt)
        out = []
        for _, row in df.iterrows():
            out.append({
                "symbol": str(row.get("代码", "")).zfill(6),
                "name": str(row.get("名称", "")),
                "pct": _safe_float(row.get("涨跌幅")),
                "price": _safe_float(row.get("最新价")),
                "industry": str(row.get("所属行业", "其他")),
                "dt_days": int(row.get("连续跌停", 1) or 1),
            })
        return out
    except Exception:
        return []


def _fetch_zb_count(date_fmt: str) -> int:
    """炸板股池数量（akshare stock_zt_pool_zbgc_em）"""
    try:
        import akshare as ak
        df = ak.stock_zt_pool_zbgc_em(date=date_fmt)
        return 0 if df is None else int(df.shape[0])
    except Exception:
        return 0


# ── 各维度计算 ──────────────────────────────────────────────────────────────────

def _yi(v) -> float:
    """元 → 亿（保留 2 位）"""
    try:
        return round(float(v) / 1e8, 2)
    except Exception:
        return 0.0


def _compute_breadth(valid: list[dict]) -> dict:
    up = sum(1 for q in valid if q["change_pct"] > 0)
    down = sum(1 for q in valid if q["change_pct"] < 0)
    flat = sum(1 for q in valid if q["change_pct"] == 0)
    total = len(valid)
    up_over5 = sum(1 for q in valid if q["change_pct"] >= 5)
    down_over5 = sum(1 for q in valid if q["change_pct"] <= -5)
    return {
        "up": up, "down": down, "flat": flat, "total": total,
        "up_ratio": round(up / total * 100, 1) if total else 0,
        "up_over5": up_over5, "down_over5": down_over5,
    }


# 涨跌分布桶（按涨跌幅，从下到上）
_DIST_BINS = [
    (-1e9, -7, "跌幅>7%", "down"),
    (-7, -5, "-7~-5%", "down"),
    (-5, -3, "-5~-3%", "down"),
    (-3, -1, "-3~-1%", "down"),
    (-1, 0, "-1~0%", "down"),
    (0, 1, "0~1%", "up"),
    (1, 3, "1~3%", "up"),
    (3, 5, "3~5%", "up"),
    (5, 7, "5~7%", "up"),
    (7, 1e9, "涨幅>7%", "up"),
]


def _compute_distribution(valid: list[dict]) -> list[dict]:
    out = []
    for lo, hi, label, side in _DIST_BINS:
        if lo == -1e9:
            cnt = sum(1 for q in valid if q["change_pct"] <= hi)
        elif hi == 1e9:
            cnt = sum(1 for q in valid if q["change_pct"] > lo)
        else:
            cnt = sum(1 for q in valid if lo < q["change_pct"] <= hi)
        out.append({"label": label, "count": cnt, "side": side})
    return out


def _compute_limit_stats(zt: list[dict], dt: list[dict], zb_count: int) -> dict:
    zt_count = len(zt)
    # 连板梯队
    ladder_map: dict[int, list[dict]] = defaultdict(list)
    for s in zt:
        ladder_map[int(s.get("zt_today", 1) or 1)].append(s)
    ladder = []
    for height in sorted(ladder_map.keys(), reverse=True):
        members = sorted(ladder_map[height], key=lambda x: -x.get("seal_amount", 0))
        ladder.append({
            "height": height,
            "count": len(members),
            "names": [m["name"] for m in members[:10]],
        })
    max_continuity = max(ladder_map.keys()) if ladder_map else 0
    # 高度梯队龙头（连板>=2，按连板数→封板资金）
    leaders = sorted(
        [s for s in zt if int(s.get("zt_today", 1) or 1) >= 2],
        key=lambda x: (-int(x.get("zt_today", 1) or 1), -x.get("seal_amount", 0)),
    )
    leaders_out = [
        {
            "symbol": s["symbol"], "name": s["name"],
            "zt_today": int(s.get("zt_today", 1) or 1),
            "industry": s.get("industry", ""),
            "seal_amount": s.get("seal_amount", 0),
        }
        for s in leaders[:10]
    ]
    # 涨停行业分布
    ind_counter = Counter(s.get("industry", "其他") for s in zt)
    zt_by_industry = [
        {"industry": k, "count": v}
        for k, v in ind_counter.most_common(10)
    ]
    broken_ratio = round(zb_count / (zt_count + zb_count) * 100, 1) if (zt_count + zb_count) else 0
    return {
        "zt_count": zt_count,
        "dt_count": len(dt),
        "broken_count": zb_count,
        "broken_ratio": broken_ratio,
        "max_continuity": max_continuity,
        "ladder": ladder,
        "leaders": leaders_out,
        "zt_by_industry": zt_by_industry,
        "dt_stocks": [
            {"symbol": s["symbol"], "name": s["name"], "pct": s["pct"],
             "price": s["price"], "industry": s["industry"], "dt_days": s.get("dt_days", 1)}
            for s in dt[:15]
        ],
    }


def _rank(valid: list[dict], key, reverse: bool, n: int = 15, filt=None) -> list[dict]:
    pool = [q for q in valid if (filt(q) if filt else True)]
    ranked = sorted(pool, key=key, reverse=reverse)[:n]
    out = []
    for q in ranked:
        out.append({
            "symbol": q["symbol"], "name": q["name"],
            "price": q.get("price"),
            "change_pct": q.get("change_pct"),
            "turnover": q.get("turnover"),
            "amount_yi": _yi(q.get("amount")) if q.get("amount") else 0,
        })
    return out


def _compute_rankings(valid: list[dict]) -> dict:
    return {
        "gainers": _rank(valid, key=lambda q: q["change_pct"], reverse=True),
        "losers": _rank(valid, key=lambda q: q["change_pct"], reverse=False),
        "amount": _rank(valid, key=lambda q: q.get("amount") or 0, reverse=True,
                        filt=lambda q: q.get("amount")),
        "turnover": _rank(valid, key=lambda q: q.get("turnover") or 0, reverse=True,
                          filt=lambda q: q.get("turnover")),
    }


# 市值分层（元）
_CAP_TIERS = [
    (1e11, 1e30, "超大盘 >1000亿"),
    (5e10, 1e11, "大盘 500-1000亿"),
    (1e10, 5e10, "中盘 100-500亿"),
    (5e9, 1e10, "中小盘 50-100亿"),
    (0, 5e9, "小盘 <50亿"),
]


def _compute_cap_perf(valid: list[dict]) -> list[dict]:
    buckets = {label: {"count": 0, "sum": 0.0, "up": 0, "down": 0} for *_, label in _CAP_TIERS}
    for q in valid:
        mc = q.get("market_cap")
        if not mc:
            continue
        for lo, hi, label in _CAP_TIERS:
            if lo <= mc < hi:
                b = buckets[label]
                b["count"] += 1
                b["sum"] += q["change_pct"]
                if q["change_pct"] > 0:
                    b["up"] += 1
                elif q["change_pct"] < 0:
                    b["down"] += 1
                break
    out = []
    for *_, label in _CAP_TIERS:
        b = buckets[label]
        out.append({
            "tier": label,
            "count": b["count"],
            "avg_pct": round(b["sum"] / b["count"], 2) if b["count"] else 0,
            "up": b["up"], "down": b["down"],
        })
    return out


def _fetch_indices() -> list[dict]:
    try:
        from api.daily_report import _fetch_indices as _fi
        return _fi()
    except Exception:
        return []


def _fetch_sectors() -> dict:
    try:
        from api.daily_report import _fetch_sectors as _fs
        s = _fs()
        return {"top_up": (s.get("top_up") or [])[:8], "top_down": (s.get("top_down") or [])[:6]}
    except Exception:
        return {"top_up": [], "top_down": []}


# ── 情绪温度计 ──────────────────────────────────────────────────────────────────

def _compute_sentiment(breadth: dict, limit_stats: dict, indices: list[dict]) -> dict:
    up, down = breadth["up"], breadth["down"]
    breadth_comp = (up / (up + down) * 100) if (up + down) else 50

    # 指数均值（上证/深证/创业板）
    keys = {"sh", "sz", "cyb"}
    pcts = [i["pct"] for i in indices if i.get("key") in keys and i.get("pct") is not None]
    index_avg = sum(pcts) / len(pcts) if pcts else 0
    index_comp = max(0.0, min(100.0, (index_avg + 3) / 6 * 100))  # -3%→0, +3%→100

    zt, dt = limit_stats["zt_count"], limit_stats["dt_count"]
    limit_comp = (zt / (zt + dt) * 100) if (zt + dt) else 50

    score = round(0.45 * breadth_comp + 0.30 * index_comp + 0.25 * limit_comp)
    score = max(0, min(100, score))

    if score >= 72:
        label, emoji, color, desc = "过热", "🔥", "red", "市场情绪高涨，赚钱效应强，注意追高风险"
    elif score >= 58:
        label, emoji, color, desc = "偏暖", "📈", "orange", "做多氛围较好，赚钱效应占优"
    elif score >= 42:
        label, emoji, color, desc = "中性", "↔️", "gray", "多空均衡，以震荡结构为主"
    elif score >= 28:
        label, emoji, color, desc = "偏冷", "📉", "cyan", "做多需谨慎，亏钱效应抬头"
    else:
        label, emoji, color, desc = "冰点", "❄️", "blue", "市场情绪低迷，亏钱效应明显"

    return {
        "score": score, "label": label, "emoji": emoji, "color": color, "desc": desc,
        "index_avg": round(index_avg, 2),
    }


def _build_summary(trade_date, breadth, limit_stats, amount, indices, sentiment) -> str:
    sh = next((i for i in indices if i.get("key") == "sh"), None)
    sh_txt = f"沪指{sh['pct']:+.2f}%" if sh else ""
    return (
        f"{trade_date}：全市场 {breadth['up']} 涨 / {breadth['down']} 跌，"
        f"涨停 {limit_stats['zt_count']} 跌停 {limit_stats['dt_count']}，"
        f"最高 {limit_stats['max_continuity']} 连板，炸板率 {limit_stats['broken_ratio']}%，"
        f"两市成交 {amount['total_yi']:.0f} 亿，{sh_txt}，"
        f"情绪 {sentiment['emoji']}{sentiment['label']}（{sentiment['score']}℃）。"
    )


# ── 今日要闻（复用中国财经新闻聚合源）────────────────────────────────────────────

def _fetch_news(trade_date: str, limit: int = 15) -> list[dict]:
    """拉取当日财经要闻。优先取 published 日期 == trade_date 的，不足则用最新。"""
    try:
        from data.cn_news_fetcher import aggregate_cn_news
        items = aggregate_cn_news()
    except Exception:
        return []

    same_day = [it for it in items if str(it.get("published", "")).startswith(trade_date)]
    pool = same_day if len(same_day) >= 5 else items

    out = []
    for it in pool[:limit]:
        out.append({
            "title": it.get("title", ""),
            "summary": (it.get("summary") or it.get("content") or "")[:140],
            "source": it.get("source", ""),
            "published": it.get("published", ""),
            "url": it.get("url", ""),
        })
    return out


# ── AI 复盘点评（喂数据 + 要闻给大模型写文字解读）────────────────────────────────

def _build_data_block(trade_date, breadth, limit_stats, amount, indices, sectors, cap_perf, rankings) -> str:
    idx_txt = " ".join(f"{i['name']}{i['pct']:+.2f}%" for i in indices) if indices else "—"
    ladder_txt = " ".join(
        f"{l['height']}板×{l['count']}({'/'.join(l['names'][:3])})"
        for l in limit_stats.get("ladder", []) if l["height"] >= 2
    ) or "无连板"
    zt_ind = " ".join(f"{x['industry']}{x['count']}" for x in limit_stats.get("zt_by_industry", [])[:6]) or "—"
    up_sec = " ".join(f"{s['name']}{s['pct']:+.1f}%" for s in (sectors.get("top_up") or [])[:6]) or "—"
    dn_sec = " ".join(f"{s['name']}{s['pct']:+.1f}%" for s in (sectors.get("top_down") or [])[:5]) or "—"
    gainers = " ".join(f"{g['name']}{g['change_pct']:+.1f}%" for g in rankings.get("gainers", [])[:6]) or "—"
    cap_txt = " ".join(f"{c['tier'].split(' ')[0]}{c['avg_pct']:+.2f}%" for c in cap_perf) or "—"
    return (
        f"日期：{trade_date}\n"
        f"涨跌家数：{breadth['up']}涨/{breadth['down']}跌/{breadth['flat']}平，"
        f"赚钱效应{breadth['up_ratio']}%，涨超5% {breadth['up_over5']}家，跌超5% {breadth['down_over5']}家\n"
        f"涨停{limit_stats['zt_count']} 跌停{limit_stats['dt_count']} 炸板{limit_stats['broken_count']}（炸板率{limit_stats['broken_ratio']}%），最高{limit_stats['max_continuity']}连板\n"
        f"连板梯队：{ladder_txt}\n"
        f"涨停行业分布：{zt_ind}\n"
        f"两市成交：{amount['total_yi']:.0f}亿\n"
        f"大盘指数：{idx_txt}\n"
        f"市值分层平均涨跌：{cap_txt}\n"
        f"领涨板块：{up_sec}\n"
        f"领跌板块：{dn_sec}\n"
        f"涨幅榜：{gainers}"
    )


def _build_news_block(news: list[dict]) -> str:
    if not news:
        return "（暂无要闻）"
    lines = []
    for i, n in enumerate(news[:12], 1):
        lines.append(f"{i}. [{n.get('source', '')}] {n.get('title', '')}")
    return "\n".join(lines)


def _build_ai_review(data_block: str, news_block: str) -> str:
    """调用大模型生成当日复盘点评。失败返回空串（页面仍可正常展示数据）。"""
    try:
        from services.ai_client import make_client, CHAT_MODEL
        prompt = f"""你是一位资深 A 股复盘分析师。请根据以下「当日量化数据」和「今日要闻」，写一篇简洁专业的《今日市场复盘点评》。

【当日量化数据】
{data_block}

【今日要闻】
{news_block}

写作要求：
- 用中文、markdown 格式，严格按以下小节，每节用 `## 标题`：
  ## 一句话定调
  ## 市场概况
  ## 资金与情绪
  ## 题材主线
  ## 消息面
  ## 明日关注与风险
- 「题材主线」要结合涨停行业/领涨板块/连板梯队，点出今天市场的核心主线；
- 「消息面」结合上面的要闻，简述影响市场的关键消息（没有相关要闻就写"今日无显著消息面催化"）；
- 「明日关注与风险」给 2-3 条要点；
- 全文 400-650 字，基于数据客观陈述，分析逻辑清晰；
- 严禁喊单、荐股、预测涨跌点位或做任何盈利承诺，结尾不需要免责声明。"""

        client = make_client()
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=1600,
            timeout=120,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[market-review] AI 点评生成失败：{e}")
        return ""


# ── 主入口 ──────────────────────────────────────────────────────────────────────

def build_market_review(trade_date: str, progress_cb=None, use_ai: bool = True) -> dict:
    """
    生成指定日期（YYYY-MM-DD）的多维度市场复盘 payload。
    progress_cb(msg) 可选，用于回报进度。
    """
    def _p(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    date_fmt = trade_date.replace("-", "")  # YYYYMMDD
    today = _dt.date.today().isoformat()
    is_today = (trade_date == today)

    # 1. 全市场行情
    _p("采集全市场行情...")
    quotes = _get_quotes()
    valid = [q for q in quotes if q.get("change_pct") is not None and q.get("price")]

    _p(f"行情 {len(valid)} 只，计算涨跌分布...")
    breadth = _compute_breadth(valid)
    distribution = _compute_distribution(valid)
    rankings = _compute_rankings(valid)
    cap_perf = _compute_cap_perf(valid)
    total_amount = sum(q["amount"] for q in valid if q.get("amount"))
    amount = {"total": total_amount, "total_yi": _yi(total_amount)}

    # 2. 涨停/跌停/炸板池
    _p("采集涨停/跌停/炸板股池...")
    zt = _fetch_zt(date_fmt)
    dt = _fetch_dt(date_fmt)
    zb_count = _fetch_zb_count(date_fmt)
    limit_stats = _compute_limit_stats(zt, dt, zb_count)

    # 3. 指数 & 板块
    _p("采集大盘指数与板块热力...")
    indices = _fetch_indices()
    sectors = _fetch_sectors()

    # 4. 情绪
    sentiment = _compute_sentiment(breadth, limit_stats, indices)
    summary = _build_summary(trade_date, breadth, limit_stats, amount, indices, sentiment)

    # 5. 今日要闻（按日期记录）
    _p("拉取今日市场要闻...")
    news = _fetch_news(trade_date)

    # 6. AI 智能点评（信息层面总结，失败则留空、不影响数据复盘）
    ai_review = ""
    if use_ai:
        _p("AI 生成复盘点评（约需 1~2 分钟）...")
        data_block = _build_data_block(
            trade_date, breadth, limit_stats, amount, indices, sectors, cap_perf, rankings
        )
        news_block = _build_news_block(news)
        ai_review = _build_ai_review(data_block, news_block)

    return {
        "trade_date": trade_date,
        "generated_at": _dt.datetime.now().isoformat(),
        "is_today": is_today,
        "breadth": breadth,
        "distribution": distribution,
        "limit_stats": limit_stats,
        "amount": amount,
        "rankings": rankings,
        "cap_perf": cap_perf,
        "indices": indices,
        "sectors": sectors,
        "sentiment": sentiment,
        "summary": summary,
        "news": news,
        "ai_review": ai_review,
    }
