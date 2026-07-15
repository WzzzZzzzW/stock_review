"""
涨停板数据采集 (Plan B — 纯数据，无 AI)
- 今日涨停股池 (akshare stock_zt_pool_em)
- 强势涨停股池 (akshare stock_zt_pool_strong_em) → 入选理由
- 个股热门概念  (akshare stock_hot_keyword_em)   → 概念热度
- 按行业+概念分组，附带热度信息
"""
import time
import akshare as ak
import pandas as pd
from datetime import datetime, date


def _safe_float(v, default=0.0) -> float:
    try:
        f = float(v)
        return default if (f != f) else f  # isnan
    except Exception:
        return default


def _symbol_prefix(code: str) -> str:
    """将 6位代码转成 SH600519 / SZ000001 格式"""
    code = str(code).zfill(6)
    return ("SH" if code.startswith("6") else "SZ") + code


# ─────────────────────────────────────────────────────────────────────────────

def fetch_zt_pool(trade_date: str | None = None) -> list[dict]:
    """
    获取涨停股池。trade_date 格式 YYYYMMDD，默认今天。
    返回标准化列表。
    """
    d = trade_date or date.today().strftime("%Y%m%d")
    try:
        df = ak.stock_zt_pool_em(date=d)
    except Exception as e:
        raise RuntimeError(f"涨停股池获取失败: {e}")

    result = []
    for _, row in df.iterrows():
        # 涨停统计格式 "3/5" → 今日连板次数/历史涨停次数
        zt_stat = str(row.get("涨停统计", "1/1"))
        try:
            zt_today, zt_total = zt_stat.split("/")
        except Exception:
            zt_today, zt_total = "1", "1"

        result.append({
            "symbol":       str(row.get("代码", "")).zfill(6),
            "name":         str(row.get("名称", "")),
            "pct":          _safe_float(row.get("涨跌幅")),
            "price":        _safe_float(row.get("最新价")),
            "amount":       _safe_float(row.get("成交额")),    # 元
            "float_mv":     _safe_float(row.get("流通市值")),  # 元
            "total_mv":     _safe_float(row.get("总市值")),
            "turnover":     _safe_float(row.get("换手率")),
            "seal_amount":  _safe_float(row.get("封板资金")),
            "first_seal":   str(row.get("首次封板时间", "")),
            "last_seal":    str(row.get("最后封板时间", "")),
            "open_times":   int(row.get("炸板次数", 0) or 0),
            "zt_today":     int(zt_today),   # 今日是第几板
            "zt_total":     int(zt_total),   # 历史涨停次数
            "industry":     str(row.get("所属行业", "其他")),
        })
    return result


def fetch_dt_pool(trade_date: str | None = None) -> list[dict]:
    """获取跌停股池"""
    d = trade_date or date.today().strftime("%Y%m%d")
    try:
        df = ak.stock_dt_pool_em(date=d)
        result = []
        for _, row in df.iterrows():
            result.append({
                "symbol":   str(row.get("代码", "")).zfill(6),
                "name":     str(row.get("名称", "")),
                "pct":      _safe_float(row.get("涨跌幅")),
                "price":    _safe_float(row.get("最新价")),
                "industry": str(row.get("所属行业", "其他")),
            })
        return result
    except Exception:
        return []


def fetch_zt_pool_strong(trade_date: str | None = None) -> dict[str, str]:
    """
    获取强势涨停股池，返回 {symbol: 入选理由} 字典。
    入选理由示例："60日新高"、"向上突破"、"60日新高 上市首日"
    """
    d = trade_date or date.today().strftime("%Y%m%d")
    try:
        df = ak.stock_zt_pool_strong_em(date=d)
        result: dict[str, str] = {}
        for _, row in df.iterrows():
            sym = str(row.get("代码", "")).zfill(6)
            reason = str(row.get("入选理由", "")).strip()
            result[sym] = reason
        return result
    except Exception:
        return {}


def get_stock_concepts(symbol: str, top_n: int = 3) -> list[tuple[str, float]]:
    """
    获取个股热门概念，返回 [(概念名称, 热度), ...] 按热度降序。
    symbol: 6 位股票代码（内部自动加前缀）。
    """
    try:
        full_sym = _symbol_prefix(symbol)
        df = ak.stock_hot_keyword_em(symbol=full_sym)
        if df is None or df.empty:
            return []
        # columns: 时间 股票代码 概念名称 概念代码 热度
        heat_col    = "热度"    if "热度"    in df.columns else df.columns[-1]
        concept_col = "概念名称" if "概念名称" in df.columns else df.columns[2]
        # 取最新日期的数据
        if "时间" in df.columns:
            latest = df["时间"].max()
            df = df[df["时间"] == latest]
        df = df.sort_values(heat_col, ascending=False)
        results: list[tuple[str, float]] = []
        for _, row in df.head(top_n).iterrows():
            results.append((str(row[concept_col]), _safe_float(row[heat_col])))
        return results
    except Exception:
        return []


def fetch_stock_news_brief(symbol: str, max_items: int = 5) -> list[str]:
    """获取个股近期新闻标题"""
    try:
        df = ak.stock_news_em(symbol=symbol)
        if df is None or df.empty:
            return []
        col = "新闻标题" if "新闻标题" in df.columns else df.columns[1]
        return df[col].head(max_items).tolist()
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────

def group_by_concept(stocks: list[dict], date_fmt: str | None = None) -> list[dict]:
    """
    按行业分组，同时丰富每只股票的概念热度数据。

    返回：
    [
      {
        "concept":  "电力设备",     # 组名（行业）
        "count":    15,
        "stocks":   [              # 每只股票附带 note / concepts / strong_reason
          { ...基础字段...,
            "strong_reason": "60日新高",    # 来自强势池，没入选则 ""
            "concepts":  [("储能", 95.2), ("新能源车", 88.1)],  # 热门概念
            "note":      "数据摘要字符串",
          }, ...
        ],
        "catalyst": "板块数据摘要",
      },
      ...
    ]
    按 count 降序
    """
    from collections import defaultdict

    # ① 强势股池（含入选理由）
    strong_map = fetch_zt_pool_strong(date_fmt)

    # ② 按行业初步分组
    groups: dict[str, list] = defaultdict(list)
    for s in stocks:
        groups[s["industry"]].append(s)

    # ③ 对 **每组最多前5只股票** (按连板数+封板资金排序) 获取概念热度
    #    其余股票不调用，避免超时
    enriched_groups: list[dict] = []

    for industry, members in groups.items():
        # 按连板数降序、封板资金降序排列
        sorted_members = sorted(
            members,
            key=lambda x: (-x["zt_today"], -x["seal_amount"])
        )

        # 获取概念热度（限前 5 只，避免太慢）
        for i, s in enumerate(sorted_members):
            s["strong_reason"] = strong_map.get(s["symbol"], "")
            if i < 5:
                s["concepts"] = get_stock_concepts(s["symbol"], top_n=3)
                time.sleep(0.2)   # 轻微限速
            else:
                s["concepts"] = []
            # 生成每只股票的数据摘要 note
            s["note"] = _build_stock_note(s)

        # 生成板块 catalyst（从数据推断）
        catalyst = _build_catalyst(industry, sorted_members)

        # 汇总组内所有热门概念（用于扩展显示）
        concept_counter: dict[str, float] = {}
        for s in sorted_members:
            for cname, cheat in s["concepts"]:
                concept_counter[cname] = concept_counter.get(cname, 0) + cheat
        top_concepts = sorted(concept_counter.items(), key=lambda x: -x[1])[:3]

        enriched_groups.append({
            "concept":      industry,
            "count":        len(sorted_members),
            "stocks":       sorted_members,
            "catalyst":     catalyst,
            "top_concepts": [c for c, _ in top_concepts],  # 组内热门概念名列表
        })

    return sorted(enriched_groups, key=lambda x: -x["count"])


# ─────────────────────────────────────────────────────────────────────────────
# 模板生成辅助

def _fmt_amount(yuan: float) -> str:
    """元 → 亿/千万 可读字符串"""
    if yuan >= 1e8:
        return f"{yuan/1e8:.2f}亿"
    elif yuan >= 1e7:
        return f"{yuan/1e7:.1f}千万"
    else:
        return f"{yuan/1e6:.0f}百万"


def _fmt_mv(yuan: float) -> str:
    if yuan >= 1e9:
        return f"{yuan/1e8:.0f}亿"
    elif yuan >= 1e8:
        return f"{yuan/1e8:.1f}亿"
    else:
        return f"{yuan/1e7:.0f}千万"


def _build_stock_note(s: dict) -> str:
    """
    为单只股票生成结构化摘要字符串，供前端展示。
    """
    parts = []

    # 封板时间
    fs = s.get("first_seal", "")
    if fs and fs not in ("", "nan", "None"):
        parts.append(f"封板{fs}")

    # 封板资金
    seal = s.get("seal_amount", 0)
    if seal > 0:
        parts.append(f"封资{_fmt_amount(seal)}")

    # 炸板次数
    ot = s.get("open_times", 0)
    if ot > 0:
        parts.append(f"炸板{ot}次")

    # 换手率
    to = s.get("turnover", 0)
    if to > 0:
        parts.append(f"换手{to:.1f}%")

    # 流通市值
    fmv = s.get("float_mv", 0)
    if fmv > 0:
        parts.append(f"流通{_fmt_mv(fmv)}")

    # 强势理由
    reason = s.get("strong_reason", "")
    if reason:
        parts.append(f"【{reason}】")

    # 热门概念（取第一个）
    concepts = s.get("concepts", [])
    if concepts:
        top_c = " / ".join(c for c, _ in concepts[:2])
        parts.append(f"概念:{top_c}")

    return " | ".join(parts)


def _build_catalyst(industry: str, stocks: list[dict]) -> str:
    """
    根据板块数据生成催化剂摘要文本。
    """
    count = len(stocks)
    # 领涨股（连板最多 → 封板资金最大）
    leader = stocks[0] if stocks else None
    parts = [f"今日{count}只涨停"]

    if leader:
        lb = leader["zt_today"]
        seal = leader.get("seal_amount", 0)
        name = leader["name"]
        if lb >= 2:
            parts.append(f"龙头{name}({lb}板，封资{_fmt_amount(seal)})")
        else:
            parts.append(f"领涨{name}(封资{_fmt_amount(seal)})")

    # 最早封板时间（板块联动参考）
    first_seals = [s.get("first_seal", "") for s in stocks
                   if s.get("first_seal", "") not in ("", "nan", "None")]
    if first_seals:
        earliest = sorted(first_seals)[0]
        parts.append(f"最早{earliest}封板")

    # 强势池比例
    strong_count = sum(1 for s in stocks if s.get("strong_reason"))
    if strong_count:
        parts.append(f"强势池{strong_count}只")

    return " | ".join(parts)
