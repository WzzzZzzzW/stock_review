"""
AI 办公室 — Agent 工具集 (OpenAI/DeepSeek function calling 兼容)

每个工具包含：
  - 给 LLM 看的 JSON Schema 描述
  - 实际的 Python 实现
工具按角色归属（每个 agent 只能用合适自己角色的工具）
"""
from __future__ import annotations
import json
import datetime as _dt
import concurrent.futures as _futures
from pathlib import Path


# ── 工具实现 ────────────────────────────────────────────────────────────

def _fmt_short(d: dict, max_chars: int = 1500) -> str:
    """精简 dict 转 JSON，避免给 LLM 灌爆"""
    s = json.dumps(d, ensure_ascii=False, default=str)
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + "...[已截断]"


def _resolve_name(symbol: str) -> str:
    """尽力拿到股票中文名——只查本地，不触发任何网络请求。"""
    try:
        path = Path(__file__).parent.parent / "data" / "portfolio.json"
        if path.exists():
            store = json.loads(path.read_text(encoding="utf-8"))
            for p in store.get("positions", []) + store.get("candidates", []):
                if p.get("symbol") == symbol and p.get("name"):
                    return p["name"]
    except Exception:
        pass
    try:
        from api import stocks as _stocks_api   # 已缓存的全量列表（若被加载过）
        for s in _stocks_api._cache.get("stocks", []):
            if s.get("symbol") == symbol:
                return s.get("name", "")
    except Exception:
        pass
    return ""


def _sina_realtime(symbol: str) -> dict:
    """baostock 取不到时的兜底：用新浪实时行情拿到最新价（无历史指标）。"""
    try:
        from api.watchlist import _fetch_sina_hq
        live = (_fetch_sina_hq([symbol]) or {}).get(symbol, {})
        if not live or live.get("not_found"):
            return {}
        return {
            "name": live.get("name", ""),
            "price": live.get("price"),
            "pct_change": live.get("pct_change"),
            "open": live.get("open"),
            "high": live.get("high"),
            "low": live.get("low"),
            "prev_close": live.get("prev_close"),
            "volume": live.get("volume"),
            "amount": live.get("amount"),
        }
    except Exception:
        return {}


def _quick_row(symbol: str) -> dict:
    """取 fetch_quick_batch 的单行；baostock 失败/为空时补新浪实时兜底。"""
    from data.stock_data import fetch_quick_batch
    rows = fetch_quick_batch([symbol]) or []
    d = rows[0] if rows else {"symbol": symbol, "error": "未找到"}
    # baostock 失败（带 error 或 today 为空）→ 用新浪实时补一个 today，至少有最新价
    if d.get("error") or not d.get("today"):
        live = _sina_realtime(symbol)
        if live:
            d = dict(d)
            d["today"] = live
            d["_fallback"] = "实时价来自新浪，技术指标(MA/RSI/MACD)暂不可用"
    return d


def get_stock_snapshot(symbol: str, days: int = 60) -> str:
    """股票快照：最新行情 + 技术指标 + 趋势信号（走当日缓存，秒级返回）"""
    try:
        d = _quick_row(symbol)
        today = d.get("today", {})
        if not today and not d.get("technical"):
            return (f"❌ 暂时取不到 {symbol} 的行情数据（baostock 与新浪均无返回）。"
                    f"请基于已有信息分析，并向用户说明该数据暂时不可用。")
        compact = {
            "symbol": symbol,
            "name": _resolve_name(symbol) or today.get("name", ""),
            "today": today,
            "technical": d.get("technical", {}),
            "trend": d.get("trend", {}),
        }
        if d.get("_fallback"):
            compact["note"] = d["_fallback"]
        return _fmt_short(compact, 2000)
    except Exception as e:
        return f"❌ 获取股票快照失败: {e}"


def get_kline(symbol: str, days: int = 30) -> str:
    """最新技术面：均线/RSI/MACD/布林带/量比 + 连涨连跌与趋势标签（走当日缓存，秒级）"""
    try:
        d = _quick_row(symbol)
        today = d.get("today", {})
        if not today and not d.get("technical"):
            return (f"❌ 暂时取不到 {symbol} 的K线/指标数据（baostock 与新浪均无返回）。"
                    f"请基于已有信息分析，并向用户说明该数据暂时不可用。")
        out = {
            "symbol": symbol,
            "name": _resolve_name(symbol) or today.get("name", ""),
            "latest": today,
            "indicators": d.get("technical", {}),
            "trend": d.get("trend", {}),
        }
        if d.get("_fallback"):
            out["note"] = d["_fallback"]
        return _fmt_short(out, 2500)
    except Exception as e:
        return f"❌ 获取技术数据失败: {e}"


# 财务数据按 (symbol, 日期) 缓存：同一天重复问不再重复登录 baostock
_financials_cache: dict[str, tuple[str, str]] = {}


def get_financials(symbol: str) -> str:
    """财务数据：近几季的利润/成长性/资产负债/现金流（只走 baostock，跳过慢速辅助接口）"""
    today = _dt.date.today().isoformat()
    cached = _financials_cache.get(symbol)
    if cached and cached[0] == today:
        return cached[1]
    try:
        import baostock as bs
        from data.stock_data import _BS_LOCK, _bs_symbol, _fetch_name_and_industry, _fetch_quarters
        bs_code = _bs_symbol(symbol)
        with _BS_LOCK:
            lg = bs.login()
            if lg.error_code != "0":
                return f"❌ baostock 登录失败: {lg.error_msg}"
            try:
                name, industry = _fetch_name_and_industry(bs_code)
                finance = _fetch_quarters(bs_code)
            finally:
                bs.logout()
        compact = {
            "symbol": symbol,
            "name": name,
            "industry": (industry or {}).get("name", ""),
            "profit_recent":   (finance.get("profit")   or [])[:4],
            "growth_recent":   (finance.get("growth")   or [])[:4],
            "balance_recent":  (finance.get("balance")  or [])[:2],
            "cashflow_recent": (finance.get("cashflow") or [])[:2],
        }
        result = _fmt_short(compact, 3000)
        _financials_cache[symbol] = (today, result)
        return result
    except Exception as e:
        return f"❌ 获取财务数据失败: {e}"


def search_news(query: str = "", limit: int = 8) -> str:
    """搜索最新财经新闻。query为空时返回最新综合财经快讯。"""
    try:
        from data.cn_news_fetcher import aggregate_cn_news
        items = aggregate_cn_news() or []
        if query:
            kw = query.lower().replace(" ", "")
            items = [
                i for i in items
                if kw in (i.get("title", "") + i.get("content", "")).lower().replace(" ", "")
            ]
        results = [
            {
                "title": i.get("title", ""),
                "content": (i.get("content") or i.get("summary") or "")[:300],
                "source": i.get("source", ""),
                "time": i.get("published", ""),
            }
            for i in items[:limit]
        ]
        return _fmt_short({"query": query, "count": len(results), "news": results}, 3000)
    except Exception as e:
        return f"❌ 搜索新闻失败: {e}"


def get_stock_news(symbol: str, limit: int = 6) -> str:
    """获取特定股票的相关新闻（个股新闻）"""
    try:
        from data.stock_data import get_news
        items = get_news(symbol, limit=limit) or []
        return _fmt_short({"symbol": symbol, "news": items[:limit]}, 2500)
    except Exception as e:
        return f"❌ 获取个股新闻失败: {e}"


def get_my_positions() -> str:
    """查询用户当前所有持仓（包含成本/盈亏/持有天数）"""
    try:
        path = Path(__file__).parent.parent / "data" / "portfolio.json"
        if not path.exists():
            return "📭 暂无持仓数据"
        store = json.loads(path.read_text(encoding="utf-8"))
        positions = store.get("positions", [])
        if not positions:
            return "📭 暂无持仓"
        simplified = [
            {
                "symbol": p.get("symbol"),
                "name": p.get("name"),
                "quantity": p.get("quantity"),
                "buy_price": p.get("buy_price"),
                "buy_date": p.get("buy_date"),
                "stop_loss": p.get("stop_loss"),
                "target_price": p.get("target_price"),
                "notes": p.get("notes", "")[:80],
            }
            for p in positions
        ]
        return _fmt_short({"positions": simplified, "count": len(simplified)}, 1500)
    except Exception as e:
        return f"❌ 查询持仓失败: {e}"


def query_brain(question: str, limit: int = 5) -> str:
    """从用户的交易脑库中检索与问题最相关的交易规则"""
    try:
        from db import brain_db
        from services import brain_service
        rules = brain_db.list_rules()
        if not rules:
            return "📭 脑库还是空的，没有可用规则"
        matched = brain_service.match_rules(rules, question)[:limit]
        if not matched:
            return f"❓ 脑库中没有与 '{question}' 相关的规则"
        results = [
            {
                "rule": r.get("rule"),
                "category": r.get("category"),
                "confidence": r.get("confidence"),
                "reason": r.get("reason", ""),
            }
            for r in matched
        ]
        return _fmt_short({"matched_rules": results}, 2000)
    except Exception as e:
        return f"❌ 查询脑库失败: {e}"


def get_limitup_today() -> str:
    """获取今日涨停板列表（按行业分组）"""
    try:
        from data.limitup_fetcher import fetch_zt_pool, group_by_concept
        zt = fetch_zt_pool() or []
        if not zt:
            return "📭 今日尚无涨停股票数据"
        groups = group_by_concept(zt)[:8]   # 取前8个题材组
        summary = [
            {
                "concept": g.get("concept", ""),
                "count": g.get("count", 0),
                "stocks": [
                    {"name": s.get("name"), "symbol": s.get("symbol"), "board": s.get("zt_today")}
                    for s in g.get("stocks", [])[:3]
                ],
            }
            for g in groups
        ]
        return _fmt_short({"total_limitup": len(zt), "top_concepts": summary}, 2500)
    except Exception as e:
        return f"❌ 获取涨停板失败: {e}"


def get_lhb_today() -> str:
    """获取最近交易日龙虎榜（机构/游资席位+净买入）"""
    try:
        import akshare as ak
        from datetime import date
        # 取最近一个交易日
        df = ak.stock_lhb_detail_em(start_date=date.today().strftime("%Y%m%d"),
                                    end_date=date.today().strftime("%Y%m%d"))
        if df is None or df.empty:
            return "📭 今日尚无龙虎榜数据"
        records = []
        for _, row in df.head(15).iterrows():
            records.append({
                "name": str(row.get("名称", "")),
                "symbol": str(row.get("代码", "")),
                "reason": str(row.get("上榜原因", ""))[:50],
                "pct": float(row.get("涨跌幅", 0) or 0),
                "net_buy": str(row.get("龙虎榜净买额", "")),
            })
        return _fmt_short({"date": date.today().isoformat(), "lhb": records}, 2500)
    except Exception as e:
        return f"❌ 获取龙虎榜失败: {e}"


def get_dividend_history(symbol: str) -> str:
    """获取股票的历史分红送转记录"""
    try:
        from services.dividend_adjuster import fetch_dividend_events
        events = fetch_dividend_events(symbol)[-8:]   # 取最近8次
        return _fmt_short({
            "symbol": symbol,
            "recent_dividends": [
                {
                    "ex_date": e["ex_date"].isoformat(),
                    "description": e["description"],
                }
                for e in events
            ]
        }, 1500)
    except Exception as e:
        return f"❌ 获取分红历史失败: {e}"


# ── 工具元数据（给 LLM 看的 schema）────────────────────────────────────────

TOOL_DEFS: dict[str, dict] = {
    "get_stock_snapshot": {
        "schema": {
            "type": "function",
            "function": {
                "name": "get_stock_snapshot",
                "description": "快速获取某只A股的实时快照：最新价/涨跌幅/成交量 + 技术指标(MA5/20/60、RSI、MACD、布林带、量比) + 趋势信号(连涨连跌/是否站上均线/新高新低)。秒级返回，问到具体股票时优先调用。需要财务报表请另调 get_financials。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "6位A股代码，如 600519"},
                        "days": {"type": "integer", "description": "分析天数，默认60天", "default": 60},
                    },
                    "required": ["symbol"],
                },
            },
        },
        "impl": get_stock_snapshot,
    },
    "get_kline": {
        "schema": {
            "type": "function",
            "function": {
                "name": "get_kline",
                "description": "获取某只A股最新技术面：均线(MA5/20/60)及乖离、RSI、MACD及多空状态、布林带位置、量比、连涨连跌天数与趋势标签。做技术分析时调用，秒级返回。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "6位A股代码"},
                        "days": {"type": "integer", "description": "最近N天K线，默认30", "default": 30},
                    },
                    "required": ["symbol"],
                },
            },
        },
        "impl": get_kline,
    },
    "get_financials": {
        "schema": {
            "type": "function",
            "function": {
                "name": "get_financials",
                "description": "获取股票的财务数据：营收/利润/ROE/PE/PB/毛利率/季度趋势。做基本面分析时调用。",
                "parameters": {
                    "type": "object",
                    "properties": {"symbol": {"type": "string"}},
                    "required": ["symbol"],
                },
            },
        },
        "impl": get_financials,
    },
    "search_news": {
        "schema": {
            "type": "function",
            "function": {
                "name": "search_news",
                "description": "搜索最新财经新闻。可按关键词过滤(如'锂电'、'美联储')。query为空则返回最新综合快讯。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "关键词，可空", "default": ""},
                        "limit": {"type": "integer", "description": "最多返回几条，默认8", "default": 8},
                    },
                },
            },
        },
        "impl": search_news,
    },
    "get_stock_news": {
        "schema": {
            "type": "function",
            "function": {
                "name": "get_stock_news",
                "description": "获取某只股票的相关新闻/公告。问到特定股票最近情况时调用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "limit": {"type": "integer", "default": 6},
                    },
                    "required": ["symbol"],
                },
            },
        },
        "impl": get_stock_news,
    },
    "get_my_positions": {
        "schema": {
            "type": "function",
            "function": {
                "name": "get_my_positions",
                "description": "查询用户当前的全部持仓（含成本/止损/目标价）。给操作建议时务必先调用了解持仓情况。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        "impl": get_my_positions,
    },
    "query_brain": {
        "schema": {
            "type": "function",
            "function": {
                "name": "query_brain",
                "description": "查询用户的个人交易脑库，找出与问题最相关的、用户自己积累的交易规则。综合决策前必查。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "问题/情况描述"},
                        "limit": {"type": "integer", "default": 5},
                    },
                    "required": ["question"],
                },
            },
        },
        "impl": query_brain,
    },
    "get_limitup_today": {
        "schema": {
            "type": "function",
            "function": {
                "name": "get_limitup_today",
                "description": "获取今日涨停板情况：题材分组、龙头股、连板数。看市场热点时调用。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        "impl": get_limitup_today,
    },
    "get_lhb_today": {
        "schema": {
            "type": "function",
            "function": {
                "name": "get_lhb_today",
                "description": "获取今日龙虎榜：机构席位/游资席位/净买额。看资金动向时调用。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        "impl": get_lhb_today,
    },
    "get_dividend_history": {
        "schema": {
            "type": "function",
            "function": {
                "name": "get_dividend_history",
                "description": "查询股票的历史分红/送转/派息记录。涉及除权除息时调用。",
                "parameters": {
                    "type": "object",
                    "properties": {"symbol": {"type": "string"}},
                    "required": ["symbol"],
                },
            },
        },
        "impl": get_dividend_history,
    },
}


# ── 每个 agent 可用的工具组 ─────────────────────────────────────────────

AGENT_TOOLS: dict[str, list[str]] = {
    "fundamentals": ["get_stock_snapshot", "get_financials", "get_dividend_history", "get_stock_news"],
    "technical":    ["get_stock_snapshot", "get_kline"],
    "news":         ["search_news", "get_stock_news"],
    "sentiment":    ["get_lhb_today", "get_limitup_today", "get_stock_snapshot"],
    "bull":         ["get_stock_snapshot", "get_financials", "search_news", "get_stock_news"],
    "bear":         ["get_stock_snapshot", "get_financials", "search_news", "get_stock_news"],
    "risk":         ["get_my_positions", "get_stock_snapshot", "get_dividend_history"],
    "trader":       list(TOOL_DEFS.keys()),   # 全部工具
    "copilot":      list(TOOL_DEFS.keys()),   # 页面上下文已自动注入，仍允许按需补查
}


def get_tools_for_agent(agent_id: str) -> list[dict]:
    """返回某 agent 可用的工具 schema 列表"""
    names = AGENT_TOOLS.get(agent_id, [])
    return [TOOL_DEFS[n]["schema"] for n in names if n in TOOL_DEFS]


# 单个工具最长执行时间（秒）。超时即降级返回，保证单聊/开会永远不会被某个慢接口拖死。
_TOOL_TIMEOUT = 30


def execute_tool(name: str, arguments: dict) -> str:
    """执行工具，返回字符串结果（带硬超时，避免慢接口把对话永久卡住）"""
    if name not in TOOL_DEFS:
        return f"❌ 未知工具: {name}"

    def _call() -> str:
        try:
            return TOOL_DEFS[name]["impl"](**arguments)
        except TypeError as e:
            return f"❌ 工具参数错误 ({name}): {e}"
        except Exception as e:
            return f"❌ 工具执行失败 ({name}): {e}"

    try:
        with _futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_call).result(timeout=_TOOL_TIMEOUT)
    except _futures.TimeoutError:
        return (
            f"⏱️ 工具 {name} 查询超时（>{_TOOL_TIMEOUT}秒），已跳过。"
            f"请基于已有信息继续分析，并向用户说明该项数据暂时取不到。"
        )
    except Exception as e:
        return f"❌ 工具执行失败 ({name}): {e}"
