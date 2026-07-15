---
created: 2026-06-17
updated: 2026-06-17
tags: [ai, gotcha]
type: world-fact
freshness: stable
related: ["[[Projects/股票分析]]", "[[Notes/数据源与代理坑]]"]
---

# AI模型与办公室

## Summary

项目用两个模型；AI办公室是 8 位 AI 专家 + 工具调用（office_tools）。
DeepSeek V4 思考模式有个会把工具调用标记当正文吐出来的坑，已处理。

## 模型常量 + 自动故障转移（services/ai_client.py）

### 当前聊天模型（2026-07-01 起）

- **DeepSeek V4 Pro**：`MODEL_CHAIN = ["deepseek-v4-pro"]`，OpenAI 兼容端点 `https://api.deepseek.com/v1`，key=`settings.deepseek_api_key`。
- 切换原因：用户提供新的 DeepSeek key，并明确要求换成 dsv4pro。
- 已验证：本机最小调用返回「模型已切换成功」；后端 8002 已重启，`/health` 正常。

- **千问 DashScope** OpenAI 兼容端点 `https://dashscope.aliyuncs.com/compatible-mode/v1`，key=`settings.qwen_api_key`。
- `VISION_MODEL = "glm-4v-flash"` — 智谱 GLM，视觉（截图→结构化条件，免费、单独走 `make_vision_client()`，**不参与转移**）。
- key 在 `backend/.env`：`QWEN_API_KEY`、`GLM_API_KEY`、`DEEPSEEK_API_KEY`（保留备用）。**绝不外泄。**

### 故障转移链（failover）—— 2026-06-17 起，核心机制
- `make_client()` 返回的不再是裸 `OpenAI`，而是 **`FailoverClient`**（鸭子类型，只实现 `chat.completions.create`）。**业务代码零改动**（全后端 20+ 处仍写 `make_client().chat.completions.create(model=CHAT_MODEL, ...)`，传入的 model 被忽略，由链路决定）。
- `MODEL_CHAIN = ["qwen-plus","qwen-max","deepseek-v3","qwen-turbo","qwen-flash","qwen-long"]`（百炼各有独立赠送额度；均实测当前 key 有权限）。
- **逻辑**：当前模型报额度/余额/欠费错（`_is_quota_error`：status 402 或消息含 insufficient/balance/arrear/quota/exhaust/expired/余额/额度/欠费…）→ 自动试下一个；**非额度错（429限流/参数/网络/5xx）直接抛出**，不烧整链。
- **持久化**：当前下标存 `data/ai_model_state.json`（`{idx,date,model}`），重启不丢、不重撞已死模型；**每天重置回链首**重新探（额度可能按周期刷新或已充值）。
- `current_model()` 查当前实际生效模型。
- 改优先级/加模型：直接改 `MODEL_CHAIN`（成员必须 key 有权限，否则会 4xx 而非额度错→中断整链）。
- 切回单一 DeepSeek 直连：把链改成单元素并把 `_raw()` 的 base_url/key 换 DeepSeek（一般没必要）。

### 模型历程（成本敏感，免费/赠送额度优先）
Anthropic → 智谱 GLM → DeepSeek-V4-Flash → **千问 qwen-plus（2026-06-17 起）**。
切千问的直接原因：DeepSeek 余额用尽，卖点诊断等全线报 `402 Insufficient Balance`；阿里百炼有赠送 token，优先消耗。

## Gotcha：402 Insufficient Balance（账户欠费，非代码 bug）

持仓页「卖点诊断失败：Error code: 402 … 'Insufficient Balance'」= 当时 CHAT_MODEL 厂商（DeepSeek）账户**余额用光**，不是程序问题。
排查口诀：看到 402/Insufficient Balance/欠费字样 → 先查 `ai_client.py` 当前用哪个厂商、对应 key 的账户余额，而不是查业务代码。
临时验证某厂商 key 是否可用：`.venv/bin/python -c "from services.ai_client import make_client,CHAT_MODEL; print(make_client().chat.completions.create(model=CHAT_MODEL,messages=[{'role':'user','content':'在吗'}],max_tokens=10).choices[0].message.content)"`

## Gotcha：工具调用标记泄漏（已修）

DeepSeek V4 thinking 偶尔把 `<｜DSML｜tool_calls><｜DSML｜invoke name="...">` 这类标记当**正文**输出，
而代码原来只读 `msg.tool_calls`，导致原始标记泄漏到用户可见输出。

修法（`office_service.py`）：加正则
- `_parse_leaked_tool_calls` 从正文里解析出泄漏的调用
- `_strip_tool_markup` 从首个标记处截断 + 清残留标签
- `_handle_leaked_calls` 执行泄漏调用并以 role:user 喂回继续循环
- 强制收尾路径追加「不要再调用工具，也不要输出任何工具调用标记或 XML 标签」并 strip 输出

## Gotcha：K线「数据接口异常」（已修）

baostock 挂 → office_tools 无数据 → agent 报错。
`office_tools.py:_quick_row` 加 sina 实时兜底（`_sina_realtime` 用 `api.watchlist._fetch_sina_hq`），
`get_stock_snapshot`/`get_kline` 改用 `_quick_row`，兜底时带 `note`。
