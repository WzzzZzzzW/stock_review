"""
交易脑库 — AI提炼 & 匹配 & Playbook生成
"""
import json
import re
from services.ai_client import make_client, CHAT_MODEL


EXTRACT_SYSTEM = """你是一位专业的A股交易系统构建师，擅长从任意文本中提炼可操作的交易规则。

## 任务
阅读用户提供的文本（可能是论坛帖子、复盘记录、书摘、随想等），提炼出其中包含的交易经验/规则/信号。

## 规则分类
- entry：买入信号/入场条件
- exit：卖出信号/止盈止损
- risk：风险控制/仓位管理
- sector：板块轮动/题材逻辑
- macro：宏观/政策/资金面判断
- psychology：心理/纪律/执行层面
- pattern：技术形态/量价关系

## 输出（严格JSON数组，无其他内容）
[
  {
    "category": "entry",
    "rule": "具体可操作的规则，一句话，15-60字",
    "conditions": ["适用条件1", "适用条件2"],
    "tags": ["标签1", "标签2"],
    "time_frame": "短线/中线/长线/日内",
    "confidence": 0.65,
    "event_date": "",
    "effective_date": ""
  }
]

## 时间字段（重要）
- event_date：该规则关联的政策/消息/事件的「发布时间」。如果原文里写了日期（如"6月20日发布""近日印发"对应的具体日），就填 YYYY-MM-DD；原文只给了月份就填 YYYY-MM；没写就留空字符串 ""。
- effective_date：该政策/消息的「落地/生效/实施时间」。原文明确写了才填（如"7月1日起实施"→2026-07-01，"年内落地"→可填"年内"）；没写就留空 ""。
- 严禁臆造日期。原文没有明确时间信息时，两个字段都必须是 ""。
- 文档每条材料开头可能带有 [发布:日期] 标注，可作为 event_date 的依据。

## 注意
- 只提炼有明确逻辑的规则，过于模糊的忽略
- 每条规则必须是独立可操作的，不要废话
- confidence反映这条规则的普适性（0.5-0.8之间，不要太高）
- 一段文本通常提炼2-6条规则，不要贪多
- 如果文本没有实质性交易内容，返回空数组[]"""


MATCH_SYSTEM = """你是交易规则匹配引擎。给你一组已有的交易规则和当前股票的情况描述，
找出最相关的规则，返回匹配的规则id列表和匹配理由。

输出JSON:
{
  "matches": [
    {"rule_id": "xxx", "relevance": 0.8, "reason": "匹配原因，一句话"}
  ]
}
只返回relevance > 0.5的，最多返回5条。"""


PLAYBOOK_SYSTEM = """你是交易系统架构师。给你一组从实战中积累的交易规则，
帮助用户归纳整理成一套完整的个人交易系统手册（Playbook）。

要求：
- 按类别归纳，发现规律和矛盾
- 每个类别写一段总结性描述（200字以内）
- 找出最核心的3-5条原则
- 如果有矛盾规则，说明各自适用的条件

输出JSON数组:
[
  {
    "category": "entry",
    "title": "买入系统",
    "content": "总结内容...",
    "rule_ids": ["用到的规则id列表"]
  }
]"""


def extract_rules(text: str) -> list[dict]:
    """从任意文本中提炼交易规则"""
    client = make_client()
    resp = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": EXTRACT_SYSTEM},
            {"role": "user", "content": f"请从以下文本中提炼交易规则：\n\n{text[:4000]}"},
        ],
        max_tokens=1500,
        temperature=0.3,
    )
    raw = resp.choices[0].message.content
    # 解析JSON
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
    try:
        rules = json.loads(cleaned)
        if isinstance(rules, list):
            return rules
    except Exception:
        m = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
    return []


def match_rules(rules: list[dict], context: str) -> list[dict]:
    """根据当前股票/市场情况，从规则库中找出最相关的规则"""
    if not rules:
        return []

    client = make_client()

    rules_text = "\n".join(
        f"[{r['id']}] [{r['category']}] {r['rule']} (置信度:{r['confidence']:.2f})"
        for r in rules[:80]  # 最多80条
    )

    resp = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": MATCH_SYSTEM},
            {"role": "user", "content": f"## 当前情况\n{context}\n\n## 规则库\n{rules_text}"},
        ],
        max_tokens=800,
        temperature=0.2,
    )
    raw = resp.choices[0].message.content
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
    try:
        result = json.loads(cleaned)
        return result.get("matches", [])
    except Exception:
        return []


def generate_playbook(rules: list[dict]) -> list[dict]:
    """从所有规则中生成个人交易Playbook"""
    if not rules:
        return []

    client = make_client()

    rules_text = "\n".join(
        f"[{r['id']}] [{r['category']}] {r['rule']} "
        f"(置信度:{r['confidence']:.2f}, 验证赢:{r.get('validated_win',0)}, 验证输:{r.get('validated_loss',0)})"
        for r in rules
    )

    resp = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": PLAYBOOK_SYSTEM},
            {"role": "user", "content": f"请根据以下规则库生成我的个人交易Playbook：\n\n{rules_text[:5000]}"},
        ],
        max_tokens=2000,
        temperature=0.4,
    )
    raw = resp.choices[0].message.content
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
    try:
        items = json.loads(cleaned)
        if isinstance(items, list):
            return items
    except Exception:
        m = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
    return []
