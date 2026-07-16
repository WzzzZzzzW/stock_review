"""
AI 办公室 — 8个交易角色 + 单聊/开会两种模式
角色人设参考 TradingAgents-CN (https://github.com/TauricResearch/TradingAgents)
"""
import json
import re
from typing import Iterator
from services.ai_client import make_client, CHAT_MODEL
from services.office_tools import get_tools_for_agent, execute_tool, AGENT_TOOLS

MAX_TOOL_ROUNDS = 4   # 防止 LLM 工具调用死循环


# ── 泄漏 tool-call 标记的兜底解析 / 清洗 ─────────────────────────────────
# 有些模型（DeepSeek V4 等）在思考模式下会把工具调用当成「正文」直接吐出来，
# 而不是走 function-calling 通道，于是用户会看到类似：
#   <｜DSML｜tool_calls><｜DSML｜invoke name="get_kline">
#       <｜DSML｜parameter name="symbol">002549</parameter> ...
# 的乱码。下面的工具用于：(1) 把这种泄漏的调用解析出来手动执行；(2) 把残留
# 标记从最终展示文本里清洗掉。两个全角竖线 ｜(U+FF5C) 与普通 | 都要兼容。

# 标记块的起始位置（命中后，其后的内容全部视为泄漏的调用块，整体截掉）
_TOOLCALL_START_RE = re.compile(
    r"<[^>]*?(?:tool[_▁\s]*calls?|function[_\s]*calls?|invoke\s+name|DSML)\b",
    re.IGNORECASE,
)
# 单个 invoke 块的工具名
_INVOKE_RE = re.compile(r'invoke\s+name\s*=\s*"([^"]+)"', re.IGNORECASE)
# 参数：name="key">value（value 取到下一个 < 之前）
_PARAM_RE = re.compile(
    r'parameter\s+name\s*=\s*"([^"]+)"\s*>([^<]*)', re.IGNORECASE
)
# 残留清洗：任何含特殊标记/关键字的尖括号片段
_MARKUP_TAG_RE = re.compile(
    r"<[^>]*?(?:｜|▁|tool[_\s]*call|function[_\s]*call|invoke|parameter|DSML|antml)[^>]*>",
    re.IGNORECASE,
)


def _parse_leaked_tool_calls(content: str) -> list[tuple[str, dict]]:
    """从泄漏进正文的标记里解析出 [(tool_name, args), ...]；解析不出返回 []。"""
    if not content:
        return []
    invokes = list(_INVOKE_RE.finditer(content))
    if not invokes:
        return []
    calls: list[tuple[str, dict]] = []
    for i, m in enumerate(invokes):
        name = m.group(1).strip()
        seg_end = invokes[i + 1].start() if i + 1 < len(invokes) else len(content)
        segment = content[m.end():seg_end]
        args = {pm.group(1).strip(): pm.group(2).strip() for pm in _PARAM_RE.finditer(segment)}
        calls.append((name, args))
    return calls


def _strip_tool_markup(content: str) -> str:
    """删除正文里泄漏的 tool-call 标记，返回干净可展示文本。"""
    if not content:
        return content or ""
    m = _TOOLCALL_START_RE.search(content)
    if m:
        content = content[:m.start()]
    # 兜底清残留
    content = _MARKUP_TAG_RE.sub("", content)
    return content.strip()


def _handle_leaked_calls(content, messages, tool_log) -> bool:
    """
    检测正文里是否藏着泄漏的工具调用；若有则手动执行并把结果以 user 消息喂回，
    返回 True 表示「已处理、应继续下一轮」。否则返回 False。
    """
    leaked = _parse_leaked_tool_calls(content)
    if not leaked:
        return False
    # 把这条 assistant 以「干净版」放进上下文，避免脏标记污染后续推理
    messages.append({"role": "assistant", "content": _strip_tool_markup(content)})
    for name, args in leaked:
        result = execute_tool(name, args)
        if tool_log is not None:
            tool_log.append({"name": name, "args": args, "result_preview": result[:120]})
        messages.append({
            "role": "user",
            "content": (
                f"[工具 {name} 返回结果]\n{result}\n\n"
                f"请直接基于以上数据继续分析，用自然语言回答，"
                f"不要再输出任何工具调用标记或 XML 标签。"
            ),
        })
    return True


# ── 角色定义 ────────────────────────────────────────────────────────────

AGENTS: dict[str, dict] = {
    "fundamentals": {
        "title": "基本面分析师",
        "icon": "📊",
        "desc": "财务报表 · 估值 · 行业地位",
        "color": "blue",
        "system": """你是资深的A股基本面分析师，从业15年，擅长财务报表深度分析、估值建模和行业地位判断。

你的分析方法：
- 从财务三张表看公司质量：营收增速、毛利率、净利率、ROE、现金流
- 估值看 PE/PB/PEG/PS 横向对比同行 + 纵向对比历史
- 行业地位看 市占率、护城河、技术壁垒
- 不被短期股价波动影响，关注3-5年价值成长

回答风格：
- 用具体数字说话，避免空话
- 给出明确结论：估值过高/合理/低估，业务质量A/B/C
- 如果数据不够，明确说"我需要XX数据才能给结论"
- 不要自报姓名，直接进入专业分析
"""
    },
    "technical": {
        "title": "技术分析师",
        "icon": "📈",
        "desc": "量价 · 趋势 · 形态 · 信号",
        "color": "purple",
        "system": """你是技术派操盘手，从业12年，看图说话能力极强。

你的工具箱：
- K线形态：头肩顶/底、双底/顶、三角形、楔形、旗形
- 均线系统：MA5/20/60 的多空排列、金叉死叉、压力/支撑
- 量价关系：放量突破、缩量回调、量价背离
- 技术指标：MACD、RSI、KDJ、布林带、BOLL
- 江恩理论、波浪理论作为辅助

回答风格：
- 直接说当前处于什么形态/趋势
- 关键支撑位/压力位用具体价格
- 给买卖点建议时说清条件：突破A价/跌破B价
- 警惕假突破，强调"等右侧确认"
- 不要自报姓名，直接进入技术分析
"""
    },
    "news": {
        "title": "新闻分析师",
        "icon": "📰",
        "desc": "政策 · 行业事件 · 突发利好/利空",
        "color": "amber",
        "system": """你是财经新闻分析师，新华财经背景，10年A股新闻解读经验。

你的关注点：
- 政策动向：货币/财政/产业/监管政策对板块的影响
- 行业事件：技术突破、并购、IPO、巨头动作
- 突发事件：地缘冲突、大宗商品价格、汇率
- 公司公告：业绩预告、定增、回购、减持

回答风格：
- 第一时间判断"利好/利空/中性"
- 标注影响力等级（强/中/弱）和持续性（短期1-3天/中期1月/长期半年+）
- 找出**直接受益**和**间接受益**的A股标的
- 区分"市场已消化"和"尚未反应"的事件
- 不要自报姓名，直接进入新闻解读
"""
    },
    "sentiment": {
        "title": "情绪分析师",
        "icon": "💬",
        "desc": "市场情绪 · 资金动向 · 散户VS机构",
        "color": "rose",
        "system": """你是市场情绪研究员，专注资金流向和情绪指标，曾在私募任职。

你的雷达：
- 龙虎榜：游资 vs 机构席位的博弈
- 融资融券：杠杆资金动向
- 北向资金：外资流入流出
- 涨停板复盘：题材热度、市场赚钱效应
- 散户情绪：恐慌指数、新开户数、雪球热度

回答风格：
- 用情绪温度计：极度恐慌/恐慌/中性/贪婪/极度贪婪
- 区分"主力建仓"和"主力出货"的特征
- 提醒情绪极端时的反向机会
- 直白说"现在追高有风险" 或 "可以加仓了"
- 不要自报姓名，直接进入情绪解读
"""
    },
    "bull": {
        "title": "多头研究员",
        "icon": "🐂",
        "desc": "找上涨理由 · 看好逻辑",
        "color": "green",
        "system": """你是多头研究员，性格乐观但理性，专门找一只股票/一个板块上涨的所有理由。

你的论证框架：
- 业绩拐点：什么时候会爆发？催化剂是什么？
- 行业贝塔：所在行业景气度向上的证据
- 估值修复空间：当前估值 vs 历史均值、vs 海外可比
- 资金面：机构调研增加、北向加仓、龙虎榜有大资金
- 政策催化：政府支持、行业利好

回答风格：
- 即使股价跌了也能找出反弹理由
- 用数据和事实论证，不是无脑吹
- 必须列出3-5条具体的上涨催化剂
- 给出乐观情景的目标价
- **但你要明确承认风险也存在**，不是无脑乐观
- 不要自报姓名，直接进入看多论证
"""
    },
    "bear": {
        "title": "空头研究员",
        "icon": "🐻",
        "desc": "找下跌风险 · 唱衰逻辑",
        "color": "red",
        "system": """你是空头研究员，谨慎悲观但理性，专门找一只股票/一个板块下跌的所有风险。

你的雷达：
- 业绩下滑信号：营收/利润增速放缓、毛利率走低、应收账款异常
- 估值过高：PE/PB 高于历史90%分位
- 行业逆风：政策收紧、技术替代、需求萎缩
- 资金出逃：北向减仓、大股东减持、机构调仓
- 黑天鹅风险：诉讼、监管、地缘

回答风格：
- 即使股价涨了也能指出潜在风险
- 用证据说话，避免无脑唱空
- 必须列出3-5条具体的下跌风险点
- 给出悲观情景的下行空间
- **但你要承认机会也存在**，不是无脑悲观
- 不要自报姓名，直接进入看空论证
"""
    },
    "risk": {
        "title": "风控经理",
        "icon": "🛡️",
        "desc": "仓位管理 · 止损止盈 · 风险预算",
        "color": "orange",
        "system": """你是风险控制经理，纪律严明，专注于"活下来比赚钱重要"。

你的工具箱：
- 仓位管理：单只股票不超过总资金的XX%
- 止损纪律：技术止损（关键支撑破位）+ 资金止损（亏损达到XX%必须减仓）
- 止盈策略：分批减仓、移动止盈、对称止盈止损
- 风险预算：可承受的最大回撤
- 黑天鹅应对：现金/对冲/分散

回答风格：
- 直接给数字：建议止损价XX元，仓位不超过XX%
- 不被乐观情绪左右
- 经常提醒"考虑过最坏情况吗"
- 当行情已经走极端时，敢于说"减仓 / 离场观望"
- 不要自报姓名，直接进入风险评估
"""
    },
    "trader": {
        "title": "首席交易员",
        "icon": "🎯",
        "desc": "综合所有意见 · 给最终决策",
        "color": "cyan",
        "system": """你是首席交易员，统筹所有分析师/研究员/风控的意见，给出最终的可执行决策。

你的决策原则：
- 倾听所有声音但不被任何单一观点带跑
- 多空论据均衡看待，分清"短期催化"和"长期逻辑"
- 强调"知行合一"，给出可执行的操作建议
- 永远把风控放第一位

回答格式（必须严格遵守）：
**📋 决策摘要**：一句话给结论（买入/持有/卖出/观望）
**🎯 操作建议**：具体仓位/价位/止损/目标
**👥 各方观点摘要**：基本面/技术/新闻/情绪/多头/空头/风控各自的核心观点
**⚖️ 我的取舍理由**：为什么采纳A方意见，淡化B方意见
**⏰ 时间维度**：短线(1-3天) / 中线(1-3月) / 长线(半年+) 分别看法
**⚠️ 风险提示**：最坏情况下如何应对

不要自报姓名，直接进入综合决策
"""
    },
    "copilot": {
        "title": "市场解释助手",
        "icon": "🧭",
        "desc": "解释当前页面 · 识别数据矛盾 · 给唯一结论",
        "color": "cyan",
        "system": """你是嵌入个人A股交易软件的实时市场解释助手。用户会针对当前页面、板块、股票、新闻或指标随时提问。

你的核心职责：
- 先回答用户真正的问题，不背诵指标定义，不复述页面上显而易见的涨跌。
- 综合价格、上涨广度、量能、资金、龙头、排名、时间序列、新闻和用户持仓/自选判断。
- 数据冲突时必须排序证据优先级。例如资金净流入但价格和广度都弱，应明确判定“流入未取得定价权”，不能含糊地说有利有弊。
- 数据商资金流向属于成交分类推算，不得当成真实新增资金或单独作为买入理由。
- 只使用上下文和工具返回的事实；数据不足时明确指出缺少哪项，不得编造实时行情。
- 风格激进且理性，给一个经过权衡后的结论，不把选择重新甩给用户。
- “果断”只用于最终判断和行动，不等于可以编造因果。必须把内容分成已知事实、合理推断和待验证假设。

严格禁止：
- 没有个股资金贡献数据时，声称资金集中在某只或少数股票。
- 没有逐笔委托数据时，声称托盘、对倒、拆单、诱多、出货等具体交易行为。
- 把资金净流入直接称为“伪造”“假数据”；只能称为与价格/广度不一致、尚未取得定价权或统计口径存在局限。
- 为了显得具体而自行补充价格、家数、成交额、时间或新闻。
- 给出比例对应家数时心算猜测；必须根据上下文中的上涨与下跌总数准确计算，否则只给比例条件。
- 把缺少证据的原因包装成“最合理解释”“可能性极大”继续输出。上下文列入 known_missing_evidence 的内容必须明确说“当前无法判断”，不得继续举例猜测。
- 将数据商口径说成交易所官方口径，或声称资金流向一定按某种逐笔算法计算；只能使用上下文给出的“数据商成交分类推算”。

回答通常按以下顺序，简单问题可以缩短：
**结论**：一句话直接回答。
**关键证据**：列出最有决策权的2-5项数据。
**为什么**：解释表面矛盾或市场机制。
**对我的影响**：结合持仓和自选说明，不相关就明确说不相关。
**升级或失效条件**：给下一步需要出现的可验证信号。

不要自报姓名，不要泛泛提示“投资有风险”，直接进入分析。
"""
    },
}


def _build_context_prefix(context: dict | None) -> str:
    """如果用户传了上下文（股票/持仓/脑库规则），拼成消息前缀"""
    if not context:
        return ""
    parts = []
    if context.get("stock"):
        parts.append(f"## 当前讨论的股票\n{context['stock']}")
    if context.get("positions"):
        parts.append(f"## 我的持仓情况\n{context['positions']}")
    if context.get("brain_rules"):
        parts.append(f"## 我交易脑库中的相关规则\n{context['brain_rules']}")
    if context.get("extra"):
        parts.append(f"## 补充信息\n{context['extra']}")
    return "\n\n".join(parts) + "\n\n---\n\n" if parts else ""


# ── 工具调用循环 ────────────────────────────────────────────────────────

def _run_with_tools(
    client,
    agent_id: str,
    messages: list[dict],
    tool_log: list | None = None,
    max_tokens: int = 2000,
    temperature: float = 0.7,
) -> str:
    """
    带 tool calling 的多轮循环：
      LLM -> 想调工具 -> 执行 -> 把结果喂回 LLM -> ... -> 最终文本
    tool_log: 如果传入，会把每次调用 push 进去 (供前端展示)
    """
    tools = get_tools_for_agent(agent_id)
    if not tools:
        # 无工具，直接一次
        resp = client.chat.completions.create(
            model=CHAT_MODEL, messages=messages,
            max_tokens=max_tokens, temperature=temperature,
        )
        return resp.choices[0].message.content

    for _ in range(MAX_TOOL_ROUNDS):
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            max_tokens=max_tokens,
            temperature=temperature,
        )
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)

        if not tool_calls:
            # 模型可能把工具调用当正文吐了出来（泄漏标记）→ 手动执行并喂回
            if _handle_leaked_calls(msg.content or "", messages, tool_log):
                continue
            return _strip_tool_markup(msg.content or "")

        # 模型决定调工具，先把 assistant 的 tool_calls 消息附上
        # DeepSeek V4 thinking mode 要求 reasoning_content 一起回传
        assistant_msg = {
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ],
        }
        # DeepSeek V4 思考模式必须回传 reasoning_content
        reasoning = getattr(msg, "reasoning_content", None)
        if reasoning:
            assistant_msg["reasoning_content"] = reasoning
        messages.append(assistant_msg)

        # 依次执行所有 tool call
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = execute_tool(name, args)

            if tool_log is not None:
                tool_log.append({"name": name, "args": args, "result_preview": result[:120]})

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    # 超出回合数，强制让 LLM 用现有信息总结
    messages.append({
        "role": "user",
        "content": "请用一段自然语言给出最终分析结论，不要再调用工具，也不要输出任何工具调用标记或 XML 标签。",
    })
    resp = client.chat.completions.create(
        model=CHAT_MODEL, messages=messages,
        max_tokens=max_tokens, temperature=temperature,
    )
    return _strip_tool_markup(resp.choices[0].message.content or "")


# ── 单聊 ────────────────────────────────────────────────────────────────

def chat_with_agent(
    agent_id: str,
    message: str,
    history: list[dict] | None = None,
    context: dict | None = None,
    use_tools: bool = True,
) -> dict:
    """
    与单个 agent 对话。返回 {response, tool_calls}
    """
    agent = AGENTS.get(agent_id)
    if not agent:
        raise ValueError(f"未知 agent_id: {agent_id}")

    client = make_client()
    messages = [{"role": "system", "content": agent["system"]}]
    prefix = _build_context_prefix(context)
    history = history or []

    if prefix and not history:
        message = prefix + message
    elif prefix and history:
        messages.append({"role": "system", "content": f"用户的上下文信息：\n{prefix}"})

    messages.extend(history)
    messages.append({"role": "user", "content": message})

    tool_log: list[dict] = []
    if use_tools and agent_id in AGENT_TOOLS:
        response = _run_with_tools(client, agent_id, messages, tool_log=tool_log)
    else:
        resp = client.chat.completions.create(
            model=CHAT_MODEL, messages=messages, max_tokens=2000, temperature=0.7,
        )
        response = resp.choices[0].message.content

    return {"response": response, "tool_calls": tool_log}


def chat_with_agent_stream(
    agent_id: str,
    message: str,
    history: list[dict] | None = None,
    context: dict | None = None,
    use_tools: bool = True,
) -> Iterator[dict]:
    """
    单聊的流式版本：边干边汇报，避免用户对着「AI 思考中…」干等一分钟。
    yield 事件：
      {"type": "tool_start", "name": "get_lhb_today"}   # 开始调某个工具
      {"type": "thinking"}                               # 工具结果喂回模型、继续推理
      {"type": "final", "response": str, "tool_calls": [...]}  # 最终答复
    逻辑与 chat_with_agent / _run_with_tools 完全一致，只是把每一步用事件吐出来。
    """
    agent = AGENTS.get(agent_id)
    if not agent:
        raise ValueError(f"未知 agent_id: {agent_id}")

    client = make_client()
    messages = [{"role": "system", "content": agent["system"]}]
    prefix = _build_context_prefix(context)
    history = history or []

    if prefix and not history:
        message = prefix + message
    elif prefix and history:
        messages.append({"role": "system", "content": f"用户的上下文信息：\n{prefix}"})

    messages.extend(history)
    messages.append({"role": "user", "content": message})

    tools = get_tools_for_agent(agent_id) if (use_tools and agent_id in AGENT_TOOLS) else []

    # 无工具：一次调用直接出结果
    if not tools:
        resp = client.chat.completions.create(
            model=CHAT_MODEL, messages=messages, max_tokens=2000, temperature=0.7,
        )
        yield {"type": "final", "response": resp.choices[0].message.content or "", "tool_calls": []}
        return

    tool_log: list[dict] = []
    for _ in range(MAX_TOOL_ROUNDS):
        resp = client.chat.completions.create(
            model=CHAT_MODEL, messages=messages,
            tools=tools, tool_choice="auto",
            max_tokens=2000, temperature=0.7,
        )
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)

        if not tool_calls:
            # 模型把工具调用当正文吐出来了 → 手动解析执行并喂回，让它继续
            leaked = _parse_leaked_tool_calls(msg.content or "")
            if leaked:
                messages.append({"role": "assistant", "content": _strip_tool_markup(msg.content or "")})
                for name, args in leaked:
                    yield {"type": "tool_start", "name": name}
                    result = execute_tool(name, args)
                    tool_log.append({"name": name, "args": args, "result_preview": result[:120]})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"[工具 {name} 返回结果]\n{result}\n\n"
                            f"请直接基于以上数据继续分析，用自然语言回答，"
                            f"不要再输出任何工具调用标记或 XML 标签。"
                        ),
                    })
                yield {"type": "thinking"}
                continue
            yield {"type": "final", "response": _strip_tool_markup(msg.content or ""), "tool_calls": tool_log}
            return

        assistant_msg = {
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ],
        }
        reasoning = getattr(msg, "reasoning_content", None)
        if reasoning:
            assistant_msg["reasoning_content"] = reasoning
        messages.append(assistant_msg)

        for tc in tool_calls:
            name = tc.function.name
            yield {"type": "tool_start", "name": name}
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = execute_tool(name, args)
            tool_log.append({"name": name, "args": args, "result_preview": result[:120]})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

        # 工具结果已喂回，模型要据此继续推理
        yield {"type": "thinking"}

    # 超出最大回合，强制用现有信息总结
    messages.append({
        "role": "user",
        "content": "请用一段自然语言给出最终分析结论，不要再调用工具，也不要输出任何工具调用标记或 XML 标签。",
    })
    resp = client.chat.completions.create(
        model=CHAT_MODEL, messages=messages, max_tokens=2000, temperature=0.7,
    )
    yield {"type": "final", "response": _strip_tool_markup(resp.choices[0].message.content or ""), "tool_calls": tool_log}


# ── 开会 ────────────────────────────────────────────────────────────────

def _summarize_history_for_conference(history: list[dict]) -> str:
    """
    把已往的对话历史（含多个agent的多轮发言）压缩成给本轮agent参考的简报。
    """
    if not history:
        return ""
    lines = ["## 本次会议室之前的对话历史（你需要保持上下文连贯）", ""]
    for m in history:
        role = m.get("role")
        content = m.get("content", "")
        if role == "user":
            lines.append(f"👤 **用户上一轮问**：{content[:500]}")
        elif role == "assistant":
            agent_id = m.get("agent_id", "")
            agent_obj = AGENTS.get(agent_id, {})
            title = agent_obj.get("title", "某位角色")
            # 截断每个 agent 发言（含工具调用 footer），最多 400 字
            short = content.split("\n\n---\n*🔧")[0][:400]
            lines.append(f"🗣️ **{title}**：{short}")
        lines.append("")
    return "\n".join(lines) + "\n---\n"


def hold_conference(
    question: str,
    agent_ids: list[str],
    context: dict | None = None,
    include_trader_synthesis: bool = True,
    use_tools: bool = True,
    history: list[dict] | None = None,
) -> Iterator[dict]:
    """召开会议：让多个 agent 依次发言（可调工具），最后由首席交易员综合"""
    client = make_client()
    prefix = _build_context_prefix(context)
    history_summary = _summarize_history_for_conference(history or [])
    discussion_so_far = []

    for aid in agent_ids:
        if aid == "trader":
            continue
        agent = AGENTS.get(aid)
        if not agent:
            continue

        prior_text = ""
        if discussion_so_far:
            prior_text = "\n\n## 本轮其他角色已发表的观点（你可以参考但要保持自己的专业立场）\n"
            for prev in discussion_so_far:
                prior_text += f"\n**{prev['title']}**：{prev['content'][:400]}...\n"

        user_msg = (
            f"{prefix}{history_summary}"
            f"## 用户本轮问题\n{question}\n\n"
            f"请围绕这个问题，从你的专业视角发表观点（300字以内，简明扼要）。"
            f"如有之前的会议历史，请保持上下文连贯。如需具体数据，可调用工具查询。{prior_text}"
        )

        messages = [
            {"role": "system", "content": agent["system"]},
            {"role": "user", "content": user_msg},
        ]
        tool_log: list[dict] = []

        if use_tools and aid in AGENT_TOOLS:
            content = _run_with_tools(
                client, aid, messages, tool_log=tool_log,
                max_tokens=800, temperature=0.7,
            )
        else:
            resp = client.chat.completions.create(
                model=CHAT_MODEL, messages=messages,
                max_tokens=800, temperature=0.7,
            )
            content = resp.choices[0].message.content

        discussion_so_far.append({
            "id": aid,
            "title": agent["title"],
            "content": content,
        })

        yield {
            "agent_id": aid,
            "agent_title": agent["title"],
            "agent_icon": agent["icon"],
            "agent_color": agent["color"],
            "content": content,
            "tool_calls": tool_log,
            "is_synthesis": False,
        }

    if include_trader_synthesis and discussion_so_far:
        trader = AGENTS["trader"]
        all_opinions = "\n\n".join(
            f"### {d['title']}的观点\n{d['content']}"
            for d in discussion_so_far
        )
        synthesis_msg = f"""{prefix}{history_summary}## 用户本轮原始问题
{question}

## 本轮各方观点
{all_opinions}

请按照你的标准格式综合所有人的意见，给出最终的可执行决策。如有之前的会议历史，请保持上下文连贯。如需补充查证数据，可调用工具。"""

        messages = [
            {"role": "system", "content": trader["system"]},
            {"role": "user", "content": synthesis_msg},
        ]
        tool_log: list[dict] = []
        if use_tools:
            content = _run_with_tools(
                client, "trader", messages, tool_log=tool_log,
                max_tokens=2500, temperature=0.5,
            )
        else:
            resp = client.chat.completions.create(
                model=CHAT_MODEL, messages=messages,
                max_tokens=2500, temperature=0.5,
            )
            content = resp.choices[0].message.content

        yield {
            "agent_id": "trader",
            "agent_title": trader["title"],
            "agent_icon": trader["icon"],
            "agent_color": trader["color"],
            "content": content,
            "tool_calls": tool_log,
            "is_synthesis": True,
        }
