"""
卖出指导 —— 持仓逐只「卖点诊断」

把三样东西喂给 AI，输出贴合用户体系的卖出研判：
  1. 持仓面：成本、现价、盈亏%、持有天数、止损/目标价
  2. 技术面：MA 乖离、RSI、MACD、布林位置、量比、连涨连跌、信号标签
  3. 脑库：用户自己的 exit 类（卖出/止盈止损）规则

「会买是徒弟，会卖是师傅」——这个模块专治拿不住和卖飞。
"""
import json
import logging
import re

from services.ai_client import make_client, CHAT_MODEL


logger = logging.getLogger("stock_review.sell_guidance")
SELL_GUIDANCE_MAX_TOKENS = 1800

SYSTEM = """你是一位看盘见长的A股操盘手，专门给持仓做「此刻该不该动」的卖点诊断。

核心原则：**结论由当前走势结构和量能驱动，不是由浮动盈亏驱动。**
浮动盈亏只决定这是一笔「止盈思路」还是「止损思路」的票，它本身不是买卖的触发条件。
绝对禁止用「赚了X%就该减仓 / 亏了X%就该清仓」这种机械收益率档位下结论。

判断顺序（从高到低）：
1. **用户自己的卖出规则**——命中必须点名，优先级最高。
2. **当前走势结构**——均线多空排列、价格站上/跌破关键均线、是在加速段还是滞涨/破位、距支撑压力位远近。
3. **量能与量价关系**——放量突破/放量滞涨/缩量回踩/量价背离/天量见顶；量是验证趋势真假的关键。
4. 技术指标（RSI 超买超卖、MACD 多空、布林位置）作为佐证，只挑最关键的 1-2 个，别堆砌。
5. 浮动盈亏只用来定调（盈利的票看趋势是否走坏/到压力；亏损的票看是否真破位），不作为档位触发。

**summary（一句话结论）必须先讲走势和量能，不准用"盈利X%/亏损X%"开头。**
例：✅「放量滞涨于布林上轨、量价背离，先减仓锁利」「跌破MA20且缩量阴跌，趋势转弱该走」「回踩MA20缩量企稳，趋势未坏可持有」
   ❌「盈利超30%，建议减仓」「亏损超5%，纪律止损」

输出严格 JSON（不要任何额外文字、不要markdown代码块）：
{
  "decision": "清仓" | "减仓" | "持有" | "加仓",
  "urgency": 0到100的整数,
  "summary": "一句话结论（30字以内，先讲走势/量能）",
  "reduce_pct": 0到100的整数,
  "sell_price": 数字或null,
  "stop_price": 数字或null,
  "reasons": ["支撑结论的关键理由（走势/量能优先）", "..."],
  "matched_rules": ["命中的用户卖出规则原文（没有则空数组）"],
  "advice": "一句最关键的执行建议（40字以内）"
}

字段说明：
- urgency：操作紧迫度，由走势/量能的恶化程度决定。趋势健康→低(0-40)；走势转弱/量价背离→中(40-70)；破位放量出货/触发用户纪律→高(70-100)。
- reduce_pct：建议卖出仓位的百分比。清仓=100，持有/加仓=0，减仓填实际比例(如30/50)
- sell_price：建议的止盈/卖出挂单价（持有可给"破位价"作为离场触发，加仓可为null）
- stop_price：建议的止损价（跌破即走，优先用关键均线/支撑位，而非"成本×95%"）
决策口径（均以走势/量能为准）：
- 清仓：趋势明确走坏（跌破关键均线+放量下杀/天量出货）、或命中用户清仓纪律、或冲高见顶背离
- 减仓：上涨趋势未死但出现滞涨/放量不涨/逼近强压力，落袋一部分留底仓
- 持有：均线多头未破、缩量回踩支撑企稳，趋势健康
- 加仓：趋势强且缩量回踩关键支撑、量价配合好、风险收益比极佳

特别注意——**当技术面数据缺失时**：不要仅凭盈亏就下"清仓/减仓"结论（那正是要避免的机械收益率判断）。
此时 decision 给"持有"、urgency 给较低值，summary 说明"技术面数据暂缺，需手动看盘确认"，advice 提示用户自己看一眼当前K线和量能。
"""


def _f(v, default="—"):
    try:
        return round(float(v), 2)
    except Exception:
        return default


def _build_user_msg(pos: dict, tech: dict, exit_rules: list[dict]) -> str:
    name = pos.get("name") or pos.get("symbol")
    cost = pos.get("buy_price", 0)
    cur = pos.get("current_price", 0)
    pnl_pct = pos.get("pnl_pct", 0)
    qty = pos.get("quantity", 0)
    days = pos.get("holding_days", 0)
    sl = pos.get("stop_loss", 0)
    tp = pos.get("target_price", 0)

    lines = [
        f"## 持仓：{name}（{pos.get('symbol')}）",
        f"- 成本价：¥{_f(cost)}　现价：¥{_f(cur)}　浮动盈亏：{'+' if pnl_pct >= 0 else ''}{_f(pnl_pct)}%",
        f"- 持有数量：{qty} 股　持有天数：{days} 天",
        f"- 已设止损价：{('¥' + str(_f(sl))) if sl and sl > 0 else '未设'}　已设目标价：{('¥' + str(_f(tp))) if tp and tp > 0 else '未设'}",
    ]

    t = tech.get("technical", {}) if tech else {}
    tr = tech.get("trend", {}) if tech else {}
    today = tech.get("today", {}) if tech else {}
    if t:
        lines.append("\n## 当前走势结构（最关键，优先据此判断）")
        if t.get("ma5") is not None:
            lines.append(f"- 均线：MA5 ¥{_f(t.get('ma5'))}(乖离{_f(t.get('ma5_pct'))}%)　MA20 ¥{_f(t.get('ma20'))}(乖离{_f(t.get('ma20_pct'))}%)　MA60 ¥{_f(t.get('ma60'))}(乖离{_f(t.get('ma60_pct'))}%)")
        lines.append(
            f"- 价格 vs 均线：站上 MA5 {'✓' if tr.get('above_ma5') else '✗'}　MA20 {'✓' if tr.get('above_ma20') else '✗'}　MA60 {'✓' if tr.get('above_ma60') else '✗'}（判断多空排列与是否破位）"
        )
        streak = tr.get("streak", 0)
        if streak:
            lines.append(f"- 近期K线：{'连涨' if streak > 0 else '连跌'}{abs(streak)}天")
        lines.append(f"- 指标佐证：RSI14 {_f(t.get('rsi14'))}　MACD {t.get('macd_status', '—')}　布林位置 {_f(t.get('bb_pct'))}(0下轨/1上轨)")

        # 量能/量价：单独成块，强调它是验证趋势真假的关键
        vol_ratio = t.get("vol_ratio")
        vol_line = f"- 量比：{_f(vol_ratio)}"
        if isinstance(vol_ratio, (int, float)):
            if vol_ratio >= 1.8:
                vol_line += "（明显放量）"
            elif vol_ratio >= 1.2:
                vol_line += "（温和放量）"
            elif vol_ratio < 0.8:
                vol_line += "（缩量）"
            else:
                vol_line += "（量能平稳）"
        lines.append("\n## 量能 / 量价关系（验证趋势真假，与走势同等重要）")
        lines.append(vol_line)
        if today.get("volume") is not None:
            lines.append(f"- 今日成交量：{_f(today.get('volume'))}　成交额：{_f(today.get('amount'))}")
        lines.append("- 请据此判断：是放量突破/放量滞涨/缩量回踩/量价背离/天量见顶 中的哪一种")

        tags = tr.get("tags", [])
        if tags:
            lines.append(f"\n## 信号标签：{'　'.join(tags)}")
    else:
        lines.append(
            "\n## 技术面：⚠️ 暂时取不到K线/量能数据。"
            "请勿仅凭盈亏机械下清仓/减仓结论；按系统要求给'持有'+低紧迫度，"
            "并提示用户手动看盘确认当前走势与量能。"
        )

    if exit_rules:
        lines.append("\n## 用户自己的卖出规则（最高优先级，命中必须点名）")
        for r in exit_rules[:15]:
            conf = r.get("confidence", 0)
            win = r.get("validated_win", 0)
            loss = r.get("validated_loss", 0)
            lines.append(f"- {r.get('rule', '')}（置信度{conf:.0%}，验证 赢{win}/输{loss}）")
    else:
        lines.append("\n## 用户卖出规则：脑库暂无 exit 类规则，请基于通用纪律给建议，并提醒他去脑库补充自己的卖出规则")

    lines.append(
        "\n请输出这只股票的卖点诊断 JSON。记住：结论由当前走势结构和量能驱动，"
        "summary 先讲走势/量能、不要用盈亏百分比开头；浮动盈亏只用来定调止盈还是止损。"
    )
    return "\n".join(lines)


def _parse(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*", "", raw or "").replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except Exception:
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
    return {}


_VALID_DECISIONS = {"清仓", "减仓", "持有", "加仓"}


def diagnose(pos: dict, tech: dict, exit_rules: list[dict]) -> dict:
    """
    pos: 已 enrich 的持仓（含 current_price/pnl_pct/holding_days）
    tech: fetch_quick_batch 单只结果 {technical, trend, today, ...}，可为 {}
    exit_rules: 脑库 exit 类规则列表
    返回诊断 dict
    """
    user_msg = _build_user_msg(pos, tech, exit_rules)
    client = make_client()

    def _call(previous_raw: str = "") -> tuple[dict, str, str]:
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_msg},
        ]
        if previous_raw:
            messages.extend([
                {"role": "assistant", "content": previous_raw[:6000]},
                {
                    "role": "user",
                    "content": (
                        "上一个回答无法解析。保持原判断，只修复为完整合法的 JSON，"
                        "不要 markdown、解释、前后缀或省略字段。"
                    ),
                },
            ])
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=messages,
            tools=[],
            tool_choice="none",
            thinking={"type": "disabled"},
            max_tokens=SELL_GUIDANCE_MAX_TOKENS,
            temperature=0.3,
        )
        choice = resp.choices[0]
        raw = choice.message.content or ""
        finish_reason = choice.finish_reason or ""
        parsed = {} if finish_reason == "length" else _parse(raw)
        return parsed, raw, finish_reason

    # 解析失败重试一次；仍拿不到合法决策则抛错（绝不静默兜底成「持有」，
    # 否则一次解析失败会被误读成「确定性持有」，对卖出工具是危险的）
    r, raw, finish_reason = _call()
    if r.get("decision") not in _VALID_DECISIONS:
        logger.warning(
            "invalid sell guidance output symbol=%s finish_reason=%s text_chars=%d retry=true",
            pos.get("symbol", ""),
            finish_reason,
            len(raw),
        )
        r, raw, finish_reason = _call(raw)
    if r.get("decision") not in _VALID_DECISIONS:
        logger.error(
            "invalid sell guidance output symbol=%s finish_reason=%s text_chars=%d retry=false",
            pos.get("symbol", ""),
            finish_reason,
            len(raw),
        )
        raise ValueError("AI 返回无法解析为有效卖点结论，请重试")

    decision = r["decision"]

    try:
        urgency = max(0, min(100, int(r.get("urgency", 0))))
    except Exception:
        urgency = 0
    try:
        reduce_pct = max(0, min(100, int(r.get("reduce_pct", 0))))
    except Exception:
        reduce_pct = 0

    def num_or_none(v):
        try:
            f = float(v)
            return round(f, 3)
        except Exception:
            return None

    return {
        "decision": decision,
        "urgency": urgency,
        "summary": r.get("summary", ""),
        "reduce_pct": reduce_pct,
        "sell_price": num_or_none(r.get("sell_price")),
        "stop_price": num_or_none(r.get("stop_price")),
        "reasons": r.get("reasons", []) if isinstance(r.get("reasons"), list) else [],
        "matched_rules": r.get("matched_rules", []) if isinstance(r.get("matched_rules"), list) else [],
        "advice": r.get("advice", ""),
    }
