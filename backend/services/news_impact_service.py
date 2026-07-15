"""
国际新闻 → A股影响分析服务
使用 GLM-4-Flash-250414（完全免费）输出结构化 JSON
"""
import json
import re
from services.ai_client import make_client as _make_client, CHAT_MODEL


SYSTEM_PROMPT = """你是一位专业的A股量化研究员，专长于分析国际宏观事件对A股市场的传导路径。

## 核心任务
阅读用户提供的国际新闻，识别哪些A股上市公司或板块会受到影响，并给出方向、置信度和推理。

## 输出规则（严格遵守）
- 只输出一个合法的 JSON 对象，不加任何前缀、后缀或 Markdown 代码块
- JSON 结构必须完全符合下方 Schema，字段名不得更改
- direction 只能是 "positive"、"negative"、"neutral" 之一
- confidence 是 0.0~1.0 的浮点数，保留两位小数
- impact_type 只能是 "direct" 或 "indirect"
- affected_stocks 按 confidence 从高到低排序，3~8 条
- 置信度低于 0.50 的个股不纳入结果

## 输出 Schema
{
  "summary": "<50字以内，一句话概括新闻核心事件>",
  "affected_stocks": [
    {
      "symbol": "<6位A股代码，如 600519>",
      "name": "<公司中文简称>",
      "sector": "<所属板块，如 半导体、新能源、消费>",
      "direction": "positive",
      "confidence": 0.85,
      "reasoning": "<1~2句推理，说明传导路径>",
      "impact_type": "direct"
    }
  ],
  "macro_themes": ["<宏观主题关键词，最多5个>"],
  "risk_warning": "本分析由AI生成，仅供参考，不构成任何投资建议"
}

## 分析方法
1. 识别新闻核心事件：贸易政策、大宗商品价格、地缘冲突、技术封锁、汇率变动、利率决策等
2. 梳理A股传导链：原材料涨跌→上下游企业；出口政策→外贸型企业；资本流动→外资重仓龙头
3. 优先选有明确传导逻辑的个股，避免泛泛列举行业
4. 兼顾直接受益/受损（direct）和产业链间接影响（indirect）"""


def _build_prompt(news_text: str, news_source: str = "", news_date: str = "") -> str:
    parts = [f"## 新闻内容\n{news_text[:3000]}"]
    if news_source:
        parts.append(f"## 来源\n{news_source}")
    if news_date:
        parts.append(f"## 发布日期\n{news_date}")
    parts.append("\n请分析以上新闻对A股市场的影响，严格按照 Schema 输出 JSON，不要有任何其他内容。")
    return "\n\n".join(parts)


def _extract_json(raw: str) -> dict:
    """从模型输出中稳健地提取 JSON 对象"""
    # 1. 去掉 markdown 代码块
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
    # 2. 直接尝试解析
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # 3. 提取第一个完整 {...} 块
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError(f"无法从AI返回内容中提取JSON：{raw[:200]}")


def batch_quick_analyze(articles: list[dict]) -> list[dict]:
    """
    批量快速分析多条新闻标题/摘要，一次 AI 调用。
    articles: [{title, summary, source, url, published}]
    返回原始字段 + {relevant, direction, stocks, one_line}
    """
    if not articles:
        return []

    client = _make_client()

    # AI 只对前 AI_LIMIT 条打标签（节省 token）；其余条目原样带过供热搜榜评分
    AI_LIMIT = 25
    numbered = "\n".join(
        f"{i+1}. [{a.get('source','')}] {a['title']}"
        + (f"\n   摘要: {a['summary'][:100]}" if a.get("summary") else "")
        for i, a in enumerate(articles[:AI_LIMIT])
    )

    prompt = f"""你是A股研究员，分析以下国际财经新闻对A股的传导影响。

{numbered}

输出规则（严格遵守）：
- 只输出 JSON 数组，不加任何前缀、后缀或代码块标记
- 数组长度与新闻条数完全一致，index 从 1 开始
- 格式：{{"index":1,"title_cn":"美中贸易战最新进展与关税影响分析","relevant":true,"direction":"negative","stocks":["宁德时代(300750)","比亚迪(002594)"],"one_line":"关税压制新能源出口"}}
- title_cn：将英文标题翻译为中文，去掉来源媒体名，20~40字，简洁准确
- direction 只能是 positive / negative / neutral
- stocks 最多3个，格式"公司名(代码)"，无关联则空数组
- one_line 10字以内核心逻辑，无关联则空字符串
- 评判标准：凡是涉及贸易/关税/大宗商品/利率/科技管制/地缘政治等宏观事件，均标 relevant=true 并推导出最相关的A股
- 只有纯粹的公司个案新闻（非中国）才标 relevant=false"""

    resp = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1200,
        temperature=0.2,
    )

    raw = resp.choices[0].message.content
    try:
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
        results = json.loads(cleaned)
        if not isinstance(results, list):
            m = re.search(r"\[.*\]", cleaned, re.DOTALL)
            results = json.loads(m.group()) if m else []
    except Exception:
        results = []

    output = []
    # 前 AI_LIMIT 条带 AI 翻译/打标
    for i, article in enumerate(articles[:AI_LIMIT]):
        impact = next((r for r in results if r.get("index") == i + 1), {})
        output.append({
            **article,
            "title_cn":  impact.get("title_cn", ""),
            "relevant":  impact.get("relevant", False),
            "direction": impact.get("direction", "neutral"),
            "stocks":    impact.get("stocks", []),
            "one_line":  impact.get("one_line", ""),
        })
    # 剩余原样带过（trending 仍可按关键词/源/新鲜度评分）
    for article in articles[AI_LIMIT:]:
        output.append({
            **article,
            "title_cn":  "",
            "relevant":  False,
            "direction": "neutral",
            "stocks":    [],
            "one_line":  "",
        })
    return output


def batch_quick_analyze_cn(articles: list[dict]) -> list[dict]:
    """
    专门针对中文A股新闻的批量分析。
    与 batch_quick_analyze 不同：这里新闻已是A股相关，
    重点是找出最直接受影响的具体个股，而非判断是否相关。
    """
    if not articles:
        return []

    client = _make_client()

    # 前 25 条交给 AI 打标签（最重要的实时快讯）
    AI_LIMIT = 25
    numbered = "\n".join(
        f"{i+1}. 【{a.get('source', '')}】{a['title']}"
        + (f"\n   {a['summary'][:120]}" if a.get("summary") and a["summary"] != a["title"] else "")
        for i, a in enumerate(articles[:AI_LIMIT])
    )

    prompt = f"""你是A股量化研究员，以下是今日中国财经媒体资讯，请分析每条对具体A股个股的影响。

{numbered}

分析要点：
- 财联社快讯：实时金融事件，常直接影响个股
- 东方财富/同花顺：行业/公司新闻，找具体A股标的
- 央视/CCTV新闻：关注政策受益/受损板块的龙头股
- 富途/新浪：综合性快讯，提取核心影响

输出规则（严格遵守，只输出JSON数组）：
- 数组长度与新闻条数完全一致，index 从 1 开始
- 格式：{{"index":1,"relevant":true,"direction":"positive","stocks":["公司名(代码)"],"one_line":"10字内核心逻辑"}}
- direction 只能是 positive / negative / neutral
- stocks 最多3个，格式"公司名(代码)"；无明确个股则空数组
- relevant=false 仅用于纯时政/娱乐/无金融影响的新闻"""

    resp = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2500,
        temperature=0.2,
    )

    raw = resp.choices[0].message.content
    try:
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
        results = json.loads(cleaned)
        if not isinstance(results, list):
            m = re.search(r"\[.*\]", cleaned, re.DOTALL)
            results = json.loads(m.group()) if m else []
    except Exception:
        results = []

    output = []
    # 前 AI_LIMIT 条带 AI 标签
    for i, article in enumerate(articles[:AI_LIMIT]):
        impact = next((r for r in results if r.get("index") == i + 1), {})
        output.append({
            **article,
            "relevant":  impact.get("relevant", False),
            "direction": impact.get("direction", "neutral"),
            "stocks":    impact.get("stocks", []),
            "one_line":  impact.get("one_line", ""),
        })
    # 剩余的也返回，但不带 AI 分析（节省 token）
    for article in articles[AI_LIMIT:]:
        output.append({
            **article,
            "relevant":  False,
            "direction": "neutral",
            "stocks":    [],
            "one_line":  "",
        })
    return output


def analyze_news_impact(
    news_text: str,
    news_source: str = "",
    news_date: str = "",
) -> dict:
    """调用GLM分析新闻，返回结构化影响报告"""
    client = _make_client()

    prompt = _build_prompt(news_text, news_source, news_date)

    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=2048,
        temperature=0.4,  # 低温确保输出格式稳定
    )

    raw = response.choices[0].message.content
    result = _extract_json(raw)

    # 兜底字段保证
    result.setdefault("summary", "")
    result.setdefault("affected_stocks", [])
    result.setdefault("macro_themes", [])
    result.setdefault("risk_warning", "本分析由AI生成，仅供参考，不构成任何投资建议")

    return result
