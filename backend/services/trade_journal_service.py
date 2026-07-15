"""
今日操作记录 —— AI 操作分析 + 评分

给定一笔买卖操作（含理由、当时价格、当前持仓上下文），
让 AI 给出 0-100 的操作得分 + 简短点评。
"""
import json
import re

from services.ai_client import make_client, CHAT_MODEL

SYSTEM = """你是一位资深A股交易复盘教练。用户会告诉你一笔刚刚完成的买入或卖出操作，
包括股票、方向、数量、成交价、操作理由，以及操作前后的持仓背景。

请你客观评估这笔操作的质量，从以下角度思考：
- 操作理由是否充分、有逻辑（是基于计划/信号，还是情绪化追涨杀跌？）
- 仓位管理是否合理（单笔下注大小、是否过度集中）
- 买卖时机与价格（相对成本、相对当前价位）
- 风险控制意识（有没有止损/目标的概念）

输出严格的 JSON（不要任何额外文字、不要markdown代码块）：
{
  "score": 0到100的整数,
  "grade": "A" | "B" | "C" | "D",
  "summary": "一句话总评（30字以内）",
  "pros": ["做得好的点", "..."],
  "cons": ["可改进的点", "..."],
  "advice": "一条最关键的建议（40字以内）"
}

评分参考：
- 90-100 (A): 纪律严明、逻辑清晰、风控到位的优秀操作
- 75-89 (B): 整体合理，有小瑕疵
- 60-74 (C): 有明显问题或赌博成分，需警惕
- 0-59 (D): 情绪化/无计划/高风险的危险操作
"""


def _parse(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
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


def analyze_trade(trade: dict, context: dict | None = None) -> dict:
    """
    trade: {symbol, name, action(buy/sell), quantity, price, reason}
    context: 可选，{position_before, position_after, total_value, ...}
    返回 {score, grade, summary, pros, cons, advice}
    """
    action_cn = "买入" if trade.get("action") == "buy" else "卖出"
    amount = trade.get("price", 0) * trade.get("quantity", 0)

    lines = [
        f"股票：{trade.get('name') or trade.get('symbol')}（{trade.get('symbol')}）",
        f"方向：{action_cn}",
        f"数量：{trade.get('quantity')} 股",
        f"成交价：¥{trade.get('price')}",
        f"成交金额：¥{round(amount, 2)}",
        f"操作理由：{trade.get('reason') or '（未填写理由）'}",
    ]

    if context:
        pb = context.get("position_before")
        pa = context.get("position_after")
        if pb:
            lines.append(
                f"操作前该股持仓：{pb.get('quantity', 0)} 股，成本价 ¥{pb.get('buy_price', 0)}"
            )
        else:
            lines.append("操作前该股持仓：无（这是一只新建仓的股票）")
        if pa:
            lines.append(
                f"操作后该股持仓：{pa.get('quantity', 0)} 股，成本价 ¥{pa.get('buy_price', 0)}"
            )
        if context.get("total_value"):
            lines.append(f"当前账户总市值约 ¥{round(context['total_value'], 2)}")

    user_msg = "请评估这笔操作：\n\n" + "\n".join(lines)

    client = make_client()
    resp = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=900,
        temperature=0.4,
    )
    raw = resp.choices[0].message.content or ""
    result = _parse(raw)

    # 兜底：保证字段齐全
    score = result.get("score", 0)
    try:
        score = int(score)
    except Exception:
        score = 0
    score = max(0, min(100, score))

    grade = result.get("grade") or (
        "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D"
    )

    return {
        "score": score,
        "grade": grade,
        "summary": result.get("summary", ""),
        "pros": result.get("pros", []) if isinstance(result.get("pros"), list) else [],
        "cons": result.get("cons", []) if isinstance(result.get("cons"), list) else [],
        "advice": result.get("advice", ""),
    }
