"""
涨停板复盘 —— 纯数据模板生成（Plan B，零 AI 调用，零成本）
"""
from data.limitup_fetcher import _fmt_amount, _fmt_mv


def generate_full_review(
    trade_date: str,
    zt_groups: list[dict],
    dt_stocks: list[dict],
    total_zt: int,
    total_dt: int,
) -> dict:
    """
    生成完整的当日涨停复盘报告（纯数据，无 AI）。
    group_by_concept() 已在 fetcher 中完成数据丰富，这里只做整合。
    """
    # 板块已经带了 catalyst / top_concepts / stocks[].note
    # 只需做最终的结果 schema 整形，保持与前端兼容
    enriched_groups = []
    for g in zt_groups:
        stocks_out = []
        for s in g["stocks"]:
            stocks_out.append({
                **s,
                # 确保 note 字段存在（fetcher 已生成，这里兜底）
                "note": s.get("note", ""),
                # 兼容旧字段（前端可能用到）
                "fund_type": _infer_fund_type(s),
                "strong_reason": s.get("strong_reason", ""),
                "concepts": s.get("concepts", []),
            })

        enriched_groups.append({
            "concept":           g["concept"],
            "count":             g["count"],
            "catalyst":          g.get("catalyst", ""),
            "logic":             _build_group_logic(g),
            "fund_type":         _infer_group_fund_type(g["stocks"]),
            "continuity":        _infer_continuity(g["stocks"]),
            "continuity_reason": _build_continuity_reason(g["stocks"]),
            "top_concepts":      g.get("top_concepts", []),
            "stocks":            stocks_out,
        })

    return {
        "trade_date": trade_date,
        "total_zt":   total_zt,
        "total_dt":   total_dt,
        "groups":     enriched_groups,
        "dt_stocks":  dt_stocks[:10],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 模板推断辅助

def _infer_fund_type(s: dict) -> str:
    """根据个股数据推断资金属性"""
    fmv = s.get("float_mv", 0)
    to  = s.get("turnover", 0)
    # 小市值（< 50 亿）+ 高换手（> 15%）→ 游资
    if fmv < 50e8 and to > 15:
        return "游资"
    # 大市值（> 200 亿）+ 低换手（< 8%）→ 机构
    if fmv > 200e8 and to < 8:
        return "机构"
    return "混合"


def _infer_group_fund_type(stocks: list[dict]) -> str:
    tags = [_infer_fund_type(s) for s in stocks[:5]]
    if tags.count("游资") >= len(tags) * 0.6:
        return "游资主导"
    if tags.count("机构") >= len(tags) * 0.4:
        return "机构主导"
    return "游资+机构混合"


def _infer_continuity(stocks: list[dict]) -> str:
    """根据连板数、封板资金推断持续性"""
    max_board = max((s.get("zt_today", 1) for s in stocks), default=1)
    top_seal   = max((s.get("seal_amount", 0) for s in stocks), default=0)
    strong_cnt = sum(1 for s in stocks if s.get("strong_reason"))

    if max_board >= 3 or (top_seal > 5e8 and strong_cnt > 0):
        return "强"
    if max_board >= 2 or top_seal > 2e8:
        return "中"
    return "弱"


def _build_continuity_reason(stocks: list[dict]) -> str:
    max_board  = max((s.get("zt_today", 1) for s in stocks), default=1)
    strong_cnt = sum(1 for s in stocks if s.get("strong_reason"))
    top_seal   = max((s.get("seal_amount", 0) for s in stocks), default=0)
    open_cnt   = sum(s.get("open_times", 0) for s in stocks)

    parts = []
    if max_board >= 2:
        parts.append(f"最高{max_board}连板")
    if strong_cnt:
        parts.append(f"强势池{strong_cnt}只")
    if top_seal > 1e8:
        parts.append(f"最大封资{_fmt_amount(top_seal)}")
    if open_cnt > 0:
        parts.append(f"合计炸板{open_cnt}次")
    return " | ".join(parts) if parts else "数据不足"


def _build_group_logic(g: dict) -> str:
    """
    为板块生成 60~100 字的数据摘要描述（模板文字）。
    """
    stocks  = g["stocks"]
    count   = g["count"]
    concept = g["concept"]
    top_cs  = g.get("top_concepts", [])

    # 连板分布
    boards = [s.get("zt_today", 1) for s in stocks]
    max_b  = max(boards)
    multi  = sum(1 for b in boards if b >= 2)

    # 封板资金
    seals      = sorted([s.get("seal_amount", 0) for s in stocks], reverse=True)
    total_seal = sum(seals)
    top_seal   = seals[0] if seals else 0

    # 强势股
    strong_cnt = sum(1 for s in stocks if s.get("strong_reason"))

    # 最早封板
    first_seals = sorted(
        [s.get("first_seal", "") for s in stocks
         if s.get("first_seal", "") not in ("", "nan", "None")]
    )
    earliest = first_seals[0] if first_seals else "–"

    lines = []
    lines.append(
        f"{concept}板块今日{count}只涨停，"
        f"最早{earliest}开始封板。"
    )
    if multi:
        lines.append(f"其中{multi}只连板，最高{max_b}连板。")
    if top_cs:
        lines.append(f"热门概念：{'、'.join(top_cs[:3])}。")
    lines.append(
        f"合计封板资金{_fmt_amount(total_seal)}，"
        f"龙头封资{_fmt_amount(top_seal)}。"
    )
    if strong_cnt:
        lines.append(f"强势股池收录{strong_cnt}只，具备历史突破特征。")

    return "".join(lines)
