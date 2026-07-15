"""
AI 深度复盘报告生成服务
使用 GLM-4-Flash（智谱AI，完全免费）
六维分析框架：公司画像 / 行业逻辑 / 涨跌归因 / 财务质量 / 技术形态 / 核心矛盾

修复：
- 新增纯算法"财务健康评分"层（A/B/C/D/F），完全基于数据，不依赖AI
- 修改系统提示词：禁止AI在无新闻支撑时臆造催化剂；强制要求对异常指标给出负面判断
- 新增"AI局限性声明"，在报告开头明确标注模型的知识盲区
"""
import math
from services.ai_client import make_client as _make_client, CHAT_MODEL

# ─────────────────────────────────────────────────────────────────────
# 系统提示词（加强版：反幻觉 + 强制客观）
# ─────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """你是一位严谨的A股量化分析师，你的核心原则是：**只说数据支持的结论，不臆造未经证实的信息**。

## 铁律（违反这些规则将导致报告失效）

1. **禁止臆造催化剂**：在"涨跌归因"章节，如果用户数据中"近期相关新闻"和"近期重大公告"均为"暂无"，
   你必须明确写"当日无可查证公告/新闻，以下为基于市场背景的推测（不可作为事实依据）："
   然后再给出推测，且推测内容必须打上【推测】标签。

2. **财务异常必须指出**：对于以下情况，你必须在报告中用明确的负面语言点出，不得用"承压"等软化措辞：
   - 净利率 < 1%：必须写"净利率极低，盈利能力严重不足"
   - ROE < 2%：必须写"ROE极低，股东回报能力堪忧"
   - 连续亏损：必须写"公司连续亏损，存在退市风险"
   - 资产负债率 > 70%：必须写"高杠杆，偿债压力巨大"

3. **不能美化坏公司**：若财务评分（用户数据中已给出）为D或F级，
   报告结论必须是"不建议普通投资者参与，风险极高"，不得给出任何正面投资建议。

4. **区分"知道"和"推测"**：你对该公司的任何了解（非用户提供的数据），
   都必须注明"（基于训练数据，可能有误）"，特别是公司历史事件、管理层信息。

## 六维复盘分析框架

### 一、公司画像与产业链定位
- 主营业务是什么（用一句大白话说清楚，让外行也能理解）
- 在产业链中的位置：上游/中游/下游？是否具备定价权？
- 核心竞争壁垒：品牌/技术/规模/牌照/渠道，哪个是护城河？
- 业绩最核心的驱动因子

### 二、行业背景与景气度
- 所属行业当前处于周期哪个阶段
- 最影响该行业的宏观变量
- 主要竞争格局

### 三、区间涨跌深度归因（最重要）
- 【严格遵守铁律1】针对每个关键异动节点，先标注是否有公告/新闻支撑
- 若有数据支撑：直接引用；若无：打【推测】标签
- 区分"有基本面支撑的上涨"和"情绪驱动的炒作"

### 四、财务质量深度解读
- 【严格遵守铁律2】对异常指标必须给出明确负面判断
- 利润含金量（经营现金流/净利润）
- 增速趋势：加速/减速/反转
- 资产负债健康度

### 五、技术形态与量价信号
- 当前趋势：上行/下行/震荡
- 关键支撑/压力位（用价格说话）
- 量价关系异常信号

### 六、核心矛盾与投资看点
- 【严格遵守铁律3】若评分D/F，结论必须是风险警示
- 用1句话点出当前最关键的"多空核心矛盾"
- 2~3个近期值得跟踪的催化剂或风险事件

## 输出风格（重要）
- 你是**盯盘助手**而非研报写手：每句话都要有信息量，**禁止套话**（如"综合来看""未来可期""值得关注"这类空话一律不许出现）
- 用具体数字和价格说话，不用模糊形容词；能用一句话说清的别写三句
- 每节控制在 3~5 句，宁可短而锐，不要长而空

## 输出规范
- 使用 Markdown，六个章节结构清晰
- 每节核心判断 **加粗**
- 数字必须注明来源（"根据提供的财务数据"）
- 语言：直接说结论，不回避负面
- 结尾必须注明：⚠️ 本报告由 AI 生成，仅供学习研究，不构成任何投资建议。"""


# ─────────────────────────────────────────────────────────────────────
# 纯算法财务健康评分（不依赖AI，完全客观）
# ─────────────────────────────────────────────────────────────────────

def calc_financial_score(finance: dict, price_summary: dict) -> dict:
    """
    纯算法评分，返回:
      grade: A/B/C/D/F
      score: 0-100
      flags: 触发的警告条目列表
      positives: 亮点条目列表
    """
    profit   = finance.get("profit",   [])
    balance  = finance.get("balance",  [])
    cashflow = finance.get("cashflow", [])
    growth   = finance.get("growth",   [])

    score  = 60   # 基础分
    flags  = []   # 风险警告（扣分项）
    positives = []  # 亮点（加分项）

    def sf(val):
        try:
            v = float(val)
            return None if (math.isnan(v) or math.isinf(v)) else v
        except Exception:
            return None

    # ── 盈利能力（40分权重）──────────────────────────────
    if profit:
        p = profit[0]
        npm = sf(p.get("npMargin"))   # 净利率（小数）
        roe = sf(p.get("roeAvg"))     # ROE（小数）
        np_ = sf(p.get("netProfit"))  # 净利润（元）

        # 净利率评判
        if npm is not None:
            npm_pct = npm * 100
            if npm_pct < 0:
                score -= 25
                flags.append(f"净利率 {npm_pct:.1f}%，当期亏损")
            elif npm_pct < 1:
                score -= 18
                flags.append(f"净利率仅 {npm_pct:.2f}%，盈利能力极弱")
            elif npm_pct < 5:
                score -= 8
                flags.append(f"净利率 {npm_pct:.1f}%，偏低")
            elif npm_pct > 20:
                score += 10
                positives.append(f"净利率 {npm_pct:.1f}%，盈利能力优秀")
            elif npm_pct > 10:
                score += 5
                positives.append(f"净利率 {npm_pct:.1f}%，盈利能力良好")

        # ROE 评判
        if roe is not None:
            roe_pct = roe * 100
            if roe_pct < 0:
                score -= 15
                flags.append(f"ROE {roe_pct:.1f}%，股东价值为负")
            elif roe_pct < 2:
                score -= 10
                flags.append(f"ROE 仅 {roe_pct:.2f}%，股东回报极差")
            elif roe_pct < 8:
                score -= 3
                flags.append(f"ROE {roe_pct:.1f}%，低于行业均值")
            elif roe_pct > 20:
                score += 12
                positives.append(f"ROE {roe_pct:.1f}%，创造股东价值能力强")
            elif roe_pct > 15:
                score += 6
                positives.append(f"ROE {roe_pct:.1f}%，股东回报良好")

        # 连续亏损检查
        loss_count = 0
        for pr in profit[:4]:
            np_v = sf(pr.get("netProfit"))
            if np_v is not None and np_v < 0:
                loss_count += 1
        if loss_count >= 3:
            score -= 20
            flags.append(f"近{loss_count}个报告期亏损，存在退市风险")
        elif loss_count == 2:
            score -= 10
            flags.append("近2期亏损，盈利可持续性存疑")

    # ── 成长性（20分权重）───────────────────────────────
    if growth:
        g = growth[0]
        yoy_ni = sf(g.get("YOYNI"))   # 净利润同比（小数）
        yoy_op = sf(g.get("YOYAsset")) # 资产同比（作为规模代理）

        if yoy_ni is not None:
            yoy_pct = yoy_ni * 100
            if yoy_pct < -50:
                score -= 12
                flags.append(f"净利润同比 {yoy_pct:.1f}%，业绩大幅恶化")
            elif yoy_pct < -20:
                score -= 6
                flags.append(f"净利润同比 {yoy_pct:.1f}%，业绩明显下滑")
            elif yoy_pct > 50:
                score += 8
                positives.append(f"净利润同比 +{yoy_pct:.1f}%，高速增长")
            elif yoy_pct > 20:
                score += 4
                positives.append(f"净利润同比 +{yoy_pct:.1f}%，稳健增长")

    # ── 资产负债健康（20分权重）─────────────────────────
    if balance:
        b = balance[0]
        cr  = sf(b.get("currentRatio"))
        la  = sf(b.get("liabilityToAsset"))   # 资产负债率（小数）

        if la is not None:
            la_pct = la * 100
            if la_pct > 80:
                score -= 15
                flags.append(f"资产负债率 {la_pct:.1f}%，高杠杆，偿债风险极高")
            elif la_pct > 70:
                score -= 8
                flags.append(f"资产负债率 {la_pct:.1f}%，偿债压力较大")
            elif la_pct < 30:
                score += 5
                positives.append(f"资产负债率 {la_pct:.1f}%，财务结构稳健")

        if cr is not None:
            if cr < 1.0:
                score -= 10
                flags.append(f"流动比率 {cr:.2f}，短期偿债能力不足（<1.0 存在流动性危机）")
            elif cr < 1.5:
                score -= 3
                flags.append(f"流动比率 {cr:.2f}，短期偿债能力偏弱")
            elif cr > 3:
                score += 4
                positives.append(f"流动比率 {cr:.2f}，短期偿债能力充足")

    # ── 现金流质量（20分权重）───────────────────────────
    if cashflow:
        c = cashflow[0]
        cfo_np = sf(c.get("CFOToNP"))   # 经营现金流/净利润
        cfo_or = sf(c.get("CFOToOR"))   # 经营现金流/营收

        if cfo_np is not None:
            # 若净利润为负，CFO/NP 正值反而是好事（说明经营现金流为正）
            # 这里需要配合净利润符号判断
            np_v = sf(profit[0].get("netProfit")) if profit else None
            if np_v is not None and np_v > 0:
                # 正常情况：利润为正时看含金量
                if cfo_np > 1.5:
                    score += 8
                    positives.append(f"经营现金流/净利润 = {cfo_np:.2f}，利润含金量极高")
                elif cfo_np > 0.8:
                    score += 4
                    positives.append(f"经营现金流/净利润 = {cfo_np:.2f}，利润含金量良好")
                elif cfo_np < 0:
                    score -= 12
                    flags.append(f"经营现金流/净利润 = {cfo_np:.2f}，经营现金流为负，利润可能虚假")
                elif cfo_np < 0.3:
                    score -= 6
                    flags.append(f"经营现金流/净利润 = {cfo_np:.2f}，利润含金量差")

    # ── 技术面修正（±5分）──────────────────────────────
    rsi = price_summary.get("latest_rsi")
    total_return = price_summary.get("total_return", 0)
    if rsi is not None:
        if rsi < 20:
            flags.append(f"RSI={rsi:.1f}，技术面严重超卖")
        elif rsi > 80:
            flags.append(f"RSI={rsi:.1f}，技术面严重超买，注意回调")

    # ── 归一化到 0-100 ──────────────────────────────────
    score = max(0, min(100, score))

    # ── 评级 ────────────────────────────────────────────
    if score >= 80:
        grade = "A"
    elif score >= 65:
        grade = "B"
    elif score >= 50:
        grade = "C"
    elif score >= 35:
        grade = "D"
    else:
        grade = "F"

    return {
        "score": score,
        "grade": grade,
        "flags": flags,
        "positives": positives,
    }


# ─────────────────────────────────────────────────────────────────────
# 数据格式化工具
# ─────────────────────────────────────────────────────────────────────

def _safe_f(val, default="--", dec=2):
    if val is None or val == "":
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f"{f:.{dec}f}"
    except Exception:
        return default


def _pct_str(val, default="--"):
    """小数 → 百分比字符串，如 0.1496 → +14.96%"""
    if val is None or val == "":
        return default
    try:
        f = float(val) * 100
        if math.isnan(f) or math.isinf(f):
            return default
        return f"{f:+.2f}%"
    except Exception:
        return default


def _yi(val, default="--"):
    """元 → 亿元"""
    try:
        return f"{float(val)/1e8:.2f}亿"
    except Exception:
        return default


def _fmt_financial_table(profit_rows: list, growth_rows: list) -> str:
    """生成财务汇总表（近4季度）"""
    if not profit_rows:
        return "暂无财务数据\n"

    growth_map = {r.get("statDate", ""): r for r in (growth_rows or [])}

    lines = ["| 季度 | 主营收入 | 净利润 | 净利率 | ROE | 净利同比 |",
             "|------|---------|-------|-------|-----|---------|"]

    for row in profit_rows[:4]:
        stat = row.get("statDate", "")[:7]
        rev  = _yi(row.get("MBRevenue"))
        np_  = _yi(row.get("netProfit"))
        try:
            npm = f"{float(row['npMargin'])*100:.1f}%" if row.get("npMargin") else "--"
        except Exception:
            npm = "--"
        try:
            roe = f"{float(row['roeAvg'])*100:.1f}%" if row.get("roeAvg") else "--"
        except Exception:
            roe = "--"
        g = growth_map.get(row.get("statDate", ""), {})
        yoy = _pct_str(g.get("YOYNI")) if g else "--"
        lines.append(f"| {stat} | {rev} | {np_} | {npm} | {roe} | {yoy} |")

    return "\n".join(lines) + "\n"


def _fmt_health(balance_rows: list, cashflow_rows: list) -> str:
    """格式化财务健康摘要"""
    parts = []
    if balance_rows:
        b = balance_rows[0]
        cr = _safe_f(b.get("currentRatio"), dec=2)
        ae = _safe_f(b.get("assetToEquity"), dec=2)
        try:
            la_f = float(b.get("liabilityToAsset", 0)) * 100
            la_str = f"{la_f:.1f}%"
        except Exception:
            la_str = "--"
        parts.append(f"- 流动比率 {cr}（>2 为健康）；资产负债率 {la_str}；权益乘数 {ae}")

    if cashflow_rows:
        c = cashflow_rows[0]
        cfo_np = _safe_f(c.get("CFOToNP"), dec=3)
        cfo_or = _safe_f(c.get("CFOToOR"), dec=3)
        try:
            cfo_np_f = float(c.get("CFOToNP", 0))
            quality = "优质" if cfo_np_f > 0.8 else "一般" if cfo_np_f > 0.5 else "较差"
        except Exception:
            quality = "--"
        parts.append(f"- 经营现金流/净利润（利润含金量）= {cfo_np}，含金量{quality}；经营现金流/营收 = {cfo_or}")

    return "\n".join(parts) if parts else "暂无数据"


def _fmt_events(events: list) -> str:
    """格式化关键异动节点表格"""
    if not events:
        return "区间内无显著量价异动节点\n"

    lines = ["| 日期 | 方向 | 涨跌幅 | 成交量倍率 | 收盘价 |",
             "|------|------|-------|----------|-------|"]
    for e in events:
        pct  = f"{e['pct_chg']:+.2f}%"
        vrat = f"{e['vol_ratio']:.1f}x"
        lines.append(f"| {e['date']} | {e['direction']} | {pct} | {vrat} | {e['close']} |")

    lines.append("\n> 注：成交量倍率 = 当日成交量 / 近20日均量，>2x 表示明显放量")
    return "\n".join(lines) + "\n"


def _fmt_news(news: list) -> str:
    if not news:
        return "暂无新闻数据（接口受限）\n"
    return "\n".join(f"- [{n['time']}] {n['title']}" for n in news[:8]) + "\n"


def _fmt_announcements(anns: list) -> str:
    if not anns:
        return "暂无公告数据\n"
    return "\n".join(f"- [{a['date']}] {a['type']} — {a['title']}" for a in anns[:6]) + "\n"


def _fmt_lhb(lhb: list) -> str:
    """格式化龙虎榜上榜记录"""
    if not lhb:
        return "复盘区间内未上龙虎榜\n"
    lines = ["| 日期 | 涨跌幅 | 上榜原因 | 龙虎净买（亿） | 上榜后5日 |",
             "|------|-------|---------|------------|---------|"]
    for r in lhb:
        net_str = f"{r['net_buy']:+.2f}" if r.get('net_buy') is not None else "--"
        lines.append(
            f"| {r['date']} | {r['pct_chg']:+.2f}% | {r['reason'][:30]} | {net_str} | {r.get('after_5d','--')} |"
        )
    lines.append("\n> 龙虎净买为负表示游资/机构合计净卖出")
    return "\n".join(lines) + "\n"


def _fmt_ths_hot(ths_hot: dict) -> str:
    """格式化关键事件日的市场热点题材"""
    if not ths_hot:
        return "暂无数据\n"
    lines = []
    for date, themes in sorted(ths_hot.items()):
        tags = "、".join(themes[:8])
        lines.append(f"- **{date}**：{tags}")
    lines.append("\n> 题材来自同花顺当日强势股概念标签，反映市场资金热点方向")
    return "\n".join(lines) + "\n"


def _fmt_industry_rank(ir: dict) -> str:
    """格式化行业横向对比"""
    if not ir:
        return "暂无数据\n"
    parts = []
    if ir.get("matched"):
        m = ir["matched"]
        parts.append(
            f"- 所属行业「{m['name']}」涨跌幅 **{m['pct']}**，"
            f"在同花顺全部 {m['total']} 个行业中排名第 **{m['rank']}** 位"
        )
        parts.append(
            f"  上涨 {m['up_count']} 家 / 下跌 {m['down_count']} 家，"
            f"净流入 {m['net_in']}亿，领涨股：{m['leader']}"
        )
    if ir.get("top5"):
        top_str = "、".join(f"{i['name']}({i['pct']})" for i in ir["top5"])
        parts.append(f"- 今日涨幅前5行业：{top_str}")
    return "\n".join(parts) + "\n" if parts else "暂无数据\n"


def _fmt_fund_flow(ff: dict) -> str:
    """格式化资金流向摘要"""
    if not ff:
        return "暂无数据\n"
    parts = []
    for period, d in ff.items():
        parts.append(
            f"- {period}：流入 {d.get('inflow','--')}，"
            f"流出 {d.get('outflow','--')}，**净额 {d.get('net','--')}**，"
            f"换手率 {d.get('turnover','--')}"
        )
    return "\n".join(parts) + "\n"


def _fmt_score_for_prompt(fs: dict) -> str:
    """将财务评分转为给AI看的文字摘要"""
    grade = fs["grade"]
    score = fs["score"]
    flags = fs["flags"]
    positives = fs["positives"]

    lines = [f"**财务健康评分：{grade}级（{score}/100分）**"]
    lines.append("")
    if flags:
        lines.append("⚠️ 风险警告（以下问题必须在报告中明确指出）：")
        for f in flags:
            lines.append(f"  - {f}")
    if positives:
        lines.append("")
        lines.append("✅ 亮点：")
        for p in positives:
            lines.append(f"  - {p}")
    if grade in ("D", "F"):
        lines.append("")
        lines.append("【重要指示】该公司财务评分为D/F级，报告结论必须明确警示投资风险，不得给出正面投资建议。")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# 构建 Prompt
# ─────────────────────────────────────────────────────────────────────

def _fmt_valuation(val: dict) -> str:
    if not val:
        return "暂无估值数据（数据源不可用）\n"
    parts = []
    pe, pe_pct = val.get("pe"), val.get("pe_pct")
    pb, pb_pct = val.get("pb"), val.get("pb_pct")
    if pe is not None:
        pct_str = f"，处近年 **{pe_pct:.0f}% 分位**（{'偏低' if pe_pct<=25 else '偏贵' if pe_pct>=80 else '中性'}）" if pe_pct is not None else ""
        parts.append(f"- PE(TTM) = {pe}{pct_str}")
    if pb is not None:
        pct_str = f"，处近年 **{pb_pct:.0f}% 分位**（{'偏低' if pb_pct<=25 else '偏贵' if pb_pct>=80 else '中性'}）" if pb_pct is not None else ""
        parts.append(f"- PB = {pb}{pct_str}")
    if val.get("mv_yi") is not None:
        parts.append(f"- 总市值 ≈ {val['mv_yi']} 亿")
    return ("\n".join(parts) + "\n") if parts else "暂无估值数据\n"


def _fmt_relative(rel: dict) -> str:
    if not rel or rel.get("excess") is None:
        return "暂无相对强弱数据\n"
    name = rel.get("index_name", "大盘")
    ex = rel["excess"]
    verb = "跑赢" if ex > 0 else "跑输" if ex < 0 else "持平"
    return (f"- 区间个股收益 {rel['stock_ret']:+.1f}%，{name} {rel['index_ret']:+.1f}%，"
            f"**{verb}大盘 {abs(ex):.1f}%**（{'强于市场' if ex>=3 else '弱于市场' if ex<=-3 else '与市场同步'}）\n")


def _fmt_verdict_levels(verdict: dict) -> str:
    if not verdict:
        return ""
    pos = verdict.get("position", {})
    return (f"- 当前价 {pos.get('close','--')}，{pos.get('vs_ma','--')}；"
            f"算法测算支撑位 **{verdict.get('support','--')}** / 压力位 **{verdict.get('resistance','--')}**\n"
            f"- 距区间高点 {pos.get('from_high_pct','--')}%，距区间低点 {pos.get('from_low_pct','--')}%\n")


def _build_prompt(data: dict, financial_score: dict) -> str:
    symbol   = data["symbol"]
    name     = data["name"]
    period   = data["period"]
    industry = data.get("industry", {})
    price    = data["price"]
    finance  = data.get("finance", {})

    s = price.get("summary", {})
    events = price.get("key_events", [])

    # 均线状态
    ma_state = s.get("price_vs_ma", "--")

    # MACD 信号
    macd = s.get("latest_macd", None)
    macd_s = s.get("latest_macd_s", None)
    if macd is not None and macd_s is not None:
        macd_signal = "金叉（多头）" if macd > macd_s else "死叉（空头）"
        macd_str = f"MACD={macd:.4f}，信号线={macd_s:.4f}，{macd_signal}"
    else:
        macd_str = "--"

    # RSI 解读
    rsi = s.get("latest_rsi")
    if rsi is not None:
        if rsi > 70:
            rsi_str = f"{rsi:.1f}（超买区，注意回调风险）"
        elif rsi < 30:
            rsi_str = f"{rsi:.1f}（超卖区，可能存在反弹机会）"
        else:
            rsi_str = f"{rsi:.1f}（中性区间）"
    else:
        rsi_str = "--"

    # 财务数据
    profit   = finance.get("profit",   [])
    growth   = finance.get("growth",   [])
    balance  = finance.get("balance",  [])
    cashflow = finance.get("cashflow", [])

    fin_table    = _fmt_financial_table(profit, growth)
    health_str   = _fmt_health(balance, cashflow)
    events_str   = _fmt_events(events)
    news_str     = _fmt_news(data.get("news", []))
    ann_str      = _fmt_announcements(data.get("announcements", []))
    lhb_str      = _fmt_lhb(data.get("lhb", []))
    ths_str      = _fmt_ths_hot(data.get("ths_hot", {}))
    ind_str      = _fmt_industry_rank(data.get("industry_rank", {}))
    ff_str       = _fmt_fund_flow(data.get("fund_flow", {}))
    score_str    = _fmt_score_for_prompt(financial_score)
    val_str      = _fmt_valuation(data.get("valuation", {}))
    rel_str      = _fmt_relative(data.get("relative") or (data.get("_verdict", {}) or {}).get("relative", {}))
    levels_str   = _fmt_verdict_levels(data.get("_verdict", {}))

    # 数据充分性提示
    has_news = bool(data.get("news"))
    has_ann  = bool(data.get("announcements"))
    has_lhb  = bool(data.get("lhb"))
    coverage_parts = []
    if not has_news:
        coverage_parts.append("⚠️ 无个股新闻，涨跌归因涉及新闻催化剂必须打【推测】标签")
    if not has_ann:
        coverage_parts.append("⚠️ 无公告数据，涉及公告事件必须打【推测】标签")
    if has_lhb:
        coverage_parts.append("✅ 龙虎榜数据已提供，可作为归因直接引用（无需打推测标签）")
    if data.get("ths_hot"):
        coverage_parts.append("✅ 关键事件日市场热点题材已提供，可直接引用")
    coverage_notice = "\n".join(coverage_parts) if coverage_parts else "所有数据均已提供。"

    return f"""请对以下股票进行深度复盘分析，按六维框架输出完整报告。

## 基本信息
- **代码**：{symbol}　**名称**：{name}
- **行业**：{industry.get("name", "未知")}（{industry.get("classification", "")}）
- **复盘区间**：{period["start"]} → {period["end"]}

---

## 算法财务健康评分（客观数据，不得篡改）
{score_str}

---

## 区间行情摘要
- 起始价 **{s.get("start_price", "--")}元** → 结束价 **{s.get("end_price", "--")}元**
- 区间涨跌幅：**{s.get("total_return", "--")}%**
- 区间最高：{s.get("max_price", "--")}元　最低：{s.get("min_price", "--")}元
- 上涨天数 / 下跌天数：{s.get("gain_days", "--")} / {s.get("loss_days", "--")}
- 日均成交量：{s.get("avg_volume", "--")}手　最大单日成交量：{s.get("max_volume", "--")}手（{s.get("max_vol_date", "")}）

**技术指标（截至区间末）**
- 均线位置：{ma_state}
- RSI(14)：{rsi_str}
- {macd_str}

**关键技术位（算法测算，归因/操作判断须引用）**
{levels_str}
---

## 📐 估值水位（当前 PE/PB 在近年所处分位）
{val_str}

## 📊 相对大盘强弱（个股 vs {data.get("index_name", "上证综指")}）
{rel_str}
---

## 关键量价异动节点（AI 重点归因对象）
{events_str}

---

## 🔥 龙虎榜记录（区间内是否有游资/机构席位介入）
{lhb_str}

---

## 📡 关键事件日市场热点题材（同花顺）
> 以下是每个关键事件日当天全市场最热的概念标签，可作为判断资金是否因题材共振而流入/流出的依据
{ths_str}

---

## 🏭 所属行业横向对比（当前）
{ind_str}

---

## 💰 近期资金流向
{ff_str}

---

## 近4季度财务数据
{fin_table}
**财务健康度**
{health_str}

---

## 近期重大公告
{ann_str}

## 近期相关新闻
{news_str}

---

## 数据充分性说明
{coverage_notice}

---

请严格按照六维框架（一到六）生成复盘报告。
**核心要求**：
1. **直接从"## 一、公司画像与产业链定位"开始输出，不要重复输出财务评分卡或任何前言，评分卡已由系统单独展示**
2. **不要逐条复述系统已给出的"多空要点速览"**——你的价值在于把这些点**串成因果链**、给出**它们没说的深层归因和操作含义**，而非把要点换句话重抄一遍
3. 第三节"涨跌归因"中必须整合龙虎榜和热点题材数据：若当日有龙虎榜记录，须明确说明是游资还是机构主导，净买额是多少；若当日热点与个股题材重叠，须说明共振效应
4. 第五节"技术形态"**必须引用上面给出的支撑位/压力位/估值分位/相对强弱具体数字**，说清"现在贵不贵、强不强、买在哪、止损看哪"
5. 财务解读中所有触发的风险警告必须明确写出，不得用"承压"等软化词替代
6. 第二节"行业背景"须结合行业横向排名数据说明行业相对强弱
7. 第一节"公司画像"要用大白话，外行读完也能明白这公司靠什么赚钱
8. 若你的训练知识中该公司存在重大负面事件（如造假、诉讼、处罚），必须在第一节末尾用【历史风险事件（基于训练数据）】标注
9. 无数据支撑的推测必须打【推测】标签
10. **第六节结尾必须给出**：① 一句话点明当前最关键的多空核心矛盾；② 2~3 个**具体可跟踪的信号/事件**（如"放量站上 X 元则确认突破""跌破 Y 元支撑则趋势走坏""下季报净利同比能否转正"），让读者知道接下来盯什么"""


# ─────────────────────────────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────────────────────────────

def generate_review_report(stock_data: dict) -> str:
    """
    生成六维深度复盘报告。
    新增：先用纯算法计算财务健康评分，再将评分注入prompt。
    """
    client = _make_client()

    # ① 纯算法评分（不涉及AI）
    financial_score = calc_financial_score(
        finance=stock_data.get("finance", {}),
        price_summary=stock_data["price"].get("summary", {}),
    )

    # ② 构建带评分的 prompt
    prompt = _build_prompt(stock_data, financial_score)

    # ③ 调用 AI
    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=6000,
        temperature=0.4,   # 降温度，减少幻觉
    )

    ai_report = response.choices[0].message.content
    # 去除 AI 可能输出的 ```markdown ... ``` 包裹（影响前端渲染）
    import re as _re
    ai_report = _re.sub(r'^```(?:markdown)?\s*\n', '', ai_report.strip())
    ai_report = _re.sub(r'\n```\s*$', '', ai_report.strip())

    # ④ 将算法评分作为客观前言附加在报告最前面（不可被AI改动）
    grade_emoji = {"A": "🟢", "B": "🔵", "C": "🟡", "D": "🟠", "F": "🔴"}.get(financial_score["grade"], "⚪")
    score_header = _build_score_header(financial_score, grade_emoji)

    return score_header + "\n\n---\n\n" + ai_report


def _build_score_header(fs: dict, emoji: str) -> str:
    """构建显示在报告最前面的客观评分卡（Markdown格式）"""
    grade = fs["grade"]
    score = fs["score"]
    flags = fs["flags"]
    positives = fs["positives"]

    lines = [
        f"## {emoji} 客观财务健康评分：**{grade}级（{score}/100）**",
        "",
        "> 此评分由纯算法计算，基于真实财务数据，不受AI影响。",
        "",
    ]

    if flags:
        lines.append("**⚠️ 风险警告**")
        for f in flags:
            lines.append(f"- {f}")
        lines.append("")

    if positives:
        lines.append("**✅ 财务亮点**")
        for p in positives:
            lines.append(f"- {p}")
        lines.append("")

    grade_desc = {
        "A": "财务状况优秀，基本面扎实",
        "B": "财务状况良好，具备一定投资价值",
        "C": "财务状况一般，需结合行业和估值判断",
        "D": "财务状况较差，风险较高，不建议普通投资者参与",
        "F": "财务状况极差，存在重大风险，极高概率不适合投资",
    }.get(grade, "")

    lines.append(f"**综合评价**：{grade_desc}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# 流式生成 AI 复盘报告（SSE 用）
# ─────────────────────────────────────────────────────────────────────

async def stream_review_report(stock_data: dict):
    """
    流式生成AI复盘报告，yield文本块。
    处理：
    1. 先输出纯算法评分卡（即时，无需等AI）
    2. 过滤AI可能输出的 ```markdown / ``` 包裹
    3. 避免AI重复输出评分卡头部（prompt已要求它从一章开始）
    """
    import asyncio
    import re as _re

    client = _make_client()

    financial_score = calc_financial_score(
        finance=stock_data.get("finance", {}),
        price_summary=stock_data["price"].get("summary", {}),
    )

    prompt = _build_prompt(stock_data, financial_score)

    # ① 先 yield 客观评分卡（瞬间到达）
    grade_emoji = {"A": "🟢", "B": "🔵", "C": "🟡", "D": "🟠", "F": "🔴"}.get(financial_score["grade"], "⚪")
    score_header = _build_score_header(financial_score, grade_emoji)
    yield score_header + "\n\n---\n\n"

    # ② 流式调用 AI
    stream = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=6000,
        temperature=0.4,
        stream=True,
    )

    # ③ 缓冲处理：剥离 ```markdown / ``` 包裹 + 过滤AI重复的评分卡头
    #    策略：把前256字符缓存起来，做一次性清洗后再开始流式输出，
    #    此后逐块直接输出（尾部 ``` 缓冲4字符检测）
    HEAD_BUF_SIZE = 256
    head_buf  = ""
    head_done = False   # 头部清洗完毕
    tail_buf  = ""      # 尾部小缓冲，用来检测结尾 ```

    for chunk in stream:
        text = chunk.choices[0].delta.content or ""
        if not text:
            continue

        if not head_done:
            head_buf += text
            if len(head_buf) >= HEAD_BUF_SIZE:
                # 清洗头部
                cleaned = head_buf
                # 去掉 ```markdown 或 ``` 开头的代码块 fence
                cleaned = _re.sub(r'^```(?:markdown)?\s*\n?', '', cleaned.lstrip())
                # 去掉AI可能重复输出的"客观财务健康评分"段落
                # （因为我们已经在前面 yield 了，AI不应该再重复）
                cleaned = _re.sub(
                    r'^#+\s*[🟢🔵🟡🟠🔴⚪]?\s*客观财务健康评分[^\n]*\n.*?(?=^##\s)',
                    '',
                    cleaned,
                    flags=_re.DOTALL | _re.MULTILINE,
                )
                # 去掉 📊 财务健康评分：X级（xx/100）这样的单行重复标注
                cleaned = _re.sub(r'^📊\s*财务健康评分[^\n]*\n?', '', cleaned, flags=_re.MULTILINE)
                head_done = True
                if cleaned.strip():
                    # 把清洗后的头部内容放入 tail_buf 流水线
                    tail_buf = cleaned
        else:
            tail_buf += text

        # 输出 tail_buf 中除最后4字符外的内容（留缓冲检测结尾 ```）
        if head_done and len(tail_buf) > 4:
            to_yield = tail_buf[:-4]
            tail_buf = tail_buf[-4:]
            if to_yield:
                yield to_yield
                await asyncio.sleep(0)

    # 流结束：处理尾部缓冲，去掉可能的结尾 ```
    if tail_buf:
        tail_cleaned = _re.sub(r'\n?```\s*$', '', tail_buf.rstrip())
        if tail_cleaned:
            yield tail_cleaned


# ─────────────────────────────────────────────────────────────────────
# 对外暴露评分函数（供 API 层直接返回）
# ─────────────────────────────────────────────────────────────────────

def get_financial_score(stock_data: dict) -> dict:
    """直接返回财务健康评分，不需要调用AI"""
    return calc_financial_score(
        finance=stock_data.get("finance", {}),
        price_summary=stock_data["price"].get("summary", {}),
    )


# ─────────────────────────────────────────────────────────────────────
# 昨日复盘（单日聚焦）：「这只票最近一个交易日到底发生了什么」
# ─────────────────────────────────────────────────────────────────────

SINGLE_DAY_SYSTEM = """你是A股盯盘助手。下面给你的是**某只股票最近一个交易日（单日）**的完整数据。
你的任务：**只复盘这一天**——它今天是什么性质的一天、为什么这么走、明天该盯什么。

## 铁律
1. **聚焦单日**：不要长篇大论公司基本面/财务/估值，那是区间复盘的事。这里只讲「今天」。
2. **不臆造**：涉及消息催化但「今日相关新闻/公告」为空时，必须打【推测】标签，不得编造利好利空。
3. **A股惯例**：红涨绿跌；涨跌停按数据给的板块幅度判断。
4. **用数字说话**：开高低收、涨跌幅、振幅、量比、换手、资金净额都要落到具体数。
5. **龙虎榜/资金流如有数据须明确引用**：是游资还是机构、净买多少亿、主力净流入多少。

## 输出格式（Markdown，四小节，简短锐利，每节2-4句，关键判断**加粗**）
### 一、一句话定性
用一句话给今天定性（如：放量涨停打板 / 缩量阴跌洗盘 / 天量长上影见顶 / 超跌反弹 / 横盘整理）。

### 二、量价拆解
开高低收与涨跌幅、振幅；量比与换手（放量/缩量/天量）；收盘在 MA5/MA20/MA60 上方还是下方；是否涨跌停、是否回封/炸板。

### 三、谁在买卖 & 题材
龙虎榜席位（游资/机构、净买额）与主力资金净流入；所属板块今日强弱与排名；今日是否因热点题材共振而异动。无龙虎榜/资金数据则如实说明。

### 四、消息面 & 明日看点
今日相关新闻/公告（无则写"今日无可查证公告/新闻"）；给出**明天具体盯什么**（如"站上X元确认强势 / 跌破Y元支撑走坏 / 看是否连板"）。

结尾一行：⚠️ AI生成，仅供参考，不构成投资建议。"""


def _fmt_yesterday_prompt(data: dict) -> str:
    d   = data.get("daily", {})
    sym = data.get("symbol", "")
    nm  = data.get("name", "")
    ind = data.get("industry", {}) or {}

    def g(v, suf="", dec=2):
        if v is None or v == "":
            return "--"
        try:
            return f"{float(v):.{dec}f}{suf}"
        except Exception:
            return f"{v}{suf}"

    pct = d.get("pct_change")
    pct_str = f"{pct:+.2f}%" if isinstance(pct, (int, float)) else "--"
    limit_tag = ""
    if d.get("is_up_limit"):
        limit_tag = "（涨停）"
    elif d.get("is_dn_limit"):
        limit_tag = "（跌停）"

    vr = d.get("vol_ratio")
    vr_tag = ""
    if isinstance(vr, (int, float)):
        vr_tag = "（明显放量）" if vr >= 1.5 else "（缩量）" if vr <= 0.7 else "（量能正常）"

    # 资金流
    ff = data.get("fund_flow", {}) or {}
    def _yi(v):
        try:
            return f"{float(v)/1e8:+.2f}亿"
        except Exception:
            return "--"
    if ff:
        ff_str = (
            f"- 主力净流入 **{_yi(ff.get('main_net'))}**"
            f"（净占比 {g(ff.get('main_net_pct'),'%')}）；"
            f"超大单 {_yi(ff.get('super_net'))}、大单 {_yi(ff.get('big_net'))}、"
            f"中单 {_yi(ff.get('mid_net'))}、小单 {_yi(ff.get('small_net'))}\n"
        )
    else:
        ff_str = "- 资金流向数据暂无（接口受限）\n"

    # 龙虎榜
    lhb = data.get("lhb", []) or []
    if lhb:
        lhb_lines = []
        for r in lhb:
            net = r.get("net_buy")
            net_s = f"{net:+.2f}亿" if isinstance(net, (int, float)) else "--"
            lhb_lines.append(
                f"  - 上榜原因：{r.get('reason','')[:40]}；龙虎净买 {net_s}；上榜后1日 {r.get('after_1d','--')}"
            )
        lhb_str = "**今日上龙虎榜**：\n" + "\n".join(lhb_lines) + "\n"
    else:
        lhb_str = "今日未上龙虎榜。\n"

    # 行业横向
    ir = data.get("industry_rank", {}) or {}
    ir_str = _fmt_industry_rank(ir)

    # 热点题材
    ths = data.get("ths_hot", {}) or {}
    if ths:
        parts = []
        for dt, themes in ths.items():
            parts.append(f"- {dt}：{('、'.join(themes[:8]))}")
        ths_str = "\n".join(parts) + "\n"
    else:
        ths_str = "今日热点题材数据暂无。\n"

    news_str = _fmt_news(data.get("news", []))
    ann_str  = _fmt_announcements(data.get("announcements", []))

    return f"""请只复盘 **{nm}（{sym}）** 在 **{d.get('date','--')}** 这一个交易日发生了什么。

## 基本信息
- 代码 {sym}　名称 {nm}　行业 {ind.get('name','未知')}
- 交易日：**{d.get('date','--')}**

## 当日量价
- 开 {g(d.get('open'))}　高 {g(d.get('high'))}　低 {g(d.get('low'))}　收 **{g(d.get('close'))}**　昨收 {g(d.get('prev_close'))}
- 涨跌幅 **{pct_str}**{limit_tag}　振幅 {g(d.get('amplitude'),'%')}　（该板块涨跌停幅度 ±{g(d.get('limit_pct'),'%',0)}）
- 成交量 {g((d.get('volume') or 0)/10000,'万手',1)}　量比(vs20日均量) **{g(d.get('vol_ratio'),'x')}**{vr_tag}　换手率 {g(d.get('turn'),'%')}
- 收盘相对均线：{d.get('price_vs_ma','--')}　RSI(14) {g(d.get('rsi'),'',1)}
- 均线：MA5 {g(d.get('ma5'))}　MA20 {g(d.get('ma20'))}　MA60 {g(d.get('ma60'))}

## 当日资金流向
{ff_str}
## 龙虎榜
{lhb_str}
## 所属行业今日表现
{ir_str}
## 今日市场热点题材（同花顺）
{ths_str}
## 今日相关新闻
{news_str}
## 今日相关公告
{ann_str}

请严格按系统提示的四小节输出，聚焦这一天，数字说话，无消息支撑的归因打【推测】。"""


async def stream_yesterday_report(data: dict):
    """流式生成「昨日复盘」AI 叙述（SSE 用）。"""
    import asyncio
    client = _make_client()
    prompt = _fmt_yesterday_prompt(data)

    stream = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": SINGLE_DAY_SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=2000,
        temperature=0.4,
        stream=True,
    )
    for chunk in stream:
        text = chunk.choices[0].delta.content or ""
        if text:
            yield text
            await asyncio.sleep(0)
