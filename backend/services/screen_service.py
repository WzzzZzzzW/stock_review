"""
选股引擎 —— 按结构化条件实时筛选全市场股票（零 AI、即时、可复现）。
数据源：api.market 的腾讯全市场快照（~5200 只，3 分钟缓存，绕代理）。
另提供 parse_nl()：把一句话选股描述用大模型翻译成结构化条件。
"""
import re
import json
import time


# ── 可筛选字段（key / 中文名 / 单位 / 原始值→用户单位的缩放）────────────────────
# scale: 原始数据 ÷ scale = 用户输入/展示单位。例如总市值原始为「元」，÷1e8 = 「亿」。
FIELDS = [
    {"key": "change_pct",   "label": "涨跌幅",      "unit": "%",  "scale": 1,    "decimals": 2},
    {"key": "turnover",     "label": "换手率",      "unit": "%",  "scale": 1,    "decimals": 2},
    {"key": "volume_ratio", "label": "量比",        "unit": "",   "scale": 1,    "decimals": 2},
    {"key": "amplitude",    "label": "振幅",        "unit": "%",  "scale": 1,    "decimals": 2},
    {"key": "price",        "label": "股价",        "unit": "元", "scale": 1,    "decimals": 2},
    {"key": "pe",           "label": "市盈率(TTM)", "unit": "倍", "scale": 1,    "decimals": 1},
    {"key": "pb",           "label": "市净率",      "unit": "倍", "scale": 1,    "decimals": 2},
    {"key": "market_cap",   "label": "总市值",      "unit": "亿", "scale": 1e8,  "decimals": 1},
    {"key": "float_cap",    "label": "流通市值",    "unit": "亿", "scale": 1e8,  "decimals": 1},
    {"key": "amount",       "label": "成交额",      "unit": "亿", "scale": 1e8,  "decimals": 2},
    {"key": "volume",       "label": "成交量",      "unit": "手", "scale": 1,    "decimals": 0},
]
FIELD_MAP = {f["key"]: f for f in FIELDS}

OPERATORS = [
    {"key": "gt",      "label": "大于 >"},
    {"key": "gte",     "label": "大于等于 ≥"},
    {"key": "lt",      "label": "小于 <"},
    {"key": "lte",     "label": "小于等于 ≤"},
    {"key": "between", "label": "区间"},
    {"key": "eq",      "label": "等于 ="},
]
_OP_KEYS = {o["key"] for o in OPERATORS}

_UNIVERSE_KEYS = ("exclude_st", "exclude_688", "exclude_300", "exclude_bj")

# 形态开关（存在 universe 字典里，但非「全市场快照」可判定 —— 需历史日线，做后置过滤）
# key 必须与 data.stock_data.PATTERN_KEYS 一一对应。label/hint 供前端展示。
PATTERNS = [
    {"key": "vol_uptrend", "label": "成交量温和放大",
     "hint": "近 5 日成交量台阶式逐步放大（温和、无暴量）—— 多日量能趋势"},
    {"key": "ma_bullish", "label": "均线多头排列",
     "hint": "MA5 > MA20 > MA60，且收盘站上 MA5（趋势向上）"},
    {"key": "above_ma20", "label": "站上20日线",
     "hint": "最新收盘价在 20 日均线之上（中期偏强）"},
    {"key": "macd_golden", "label": "MACD金叉",
     "hint": "今日 MACD 由负转正（DIF 上穿 DEA）"},
    {"key": "new_high_60", "label": "创60日新高",
     "hint": "最新收盘价创近 60 个交易日新高"},
    {"key": "streak_up", "label": "连涨3天以上",
     "hint": "最近连续 3 个交易日收阳（连涨）"},
]
_PATTERN_KEYS = tuple(p["key"] for p in PATTERNS)
# 写入规则 / 解析时允许保留的 universe 键
_UNIVERSE_ALLOWED = _UNIVERSE_KEYS + _PATTERN_KEYS
# 形态后置过滤最多处理的候选数（保护性能：逐只拉历史日线串行，必须先收敛候选集）
# 首次运行需逐只 baostock 拉日线（约 0.7s/只），故上限设 120 以把最坏首跑控制在 ~90s 内。
_PATTERN_MAX_CANDIDATES = 120


# ── 全市场行情（复用 api.market 缓存）────────────────────────────────────────────

def _get_quotes() -> list[dict]:
    from api.market import _cache as _mkt_cache, _load_quotes, CACHE_TTL
    now = time.time()
    if _mkt_cache["data"] and now - _mkt_cache["ts"] < CACHE_TTL:
        return _mkt_cache["data"]
    data = _load_quotes()
    _mkt_cache["data"] = data
    _mkt_cache["ts"] = now
    return data


# ── 单股取值 / 条件判定 ─────────────────────────────────────────────────────────

def _field_value(q: dict, field: str):
    """返回该字段「原始单位」的值（None 表示缺失）。"""
    if field == "amplitude":
        hi, lo, pc = q.get("high"), q.get("low"), q.get("prev_close")
        if hi is None or lo is None or not pc:
            return None
        return (hi - lo) / pc * 100
    return q.get(field)


def _passes(q: dict, cond: dict) -> bool:
    field = cond.get("field")
    op = cond.get("op")
    meta = FIELD_MAP.get(field)
    if not meta or op not in _OP_KEYS:
        return True  # 无效条件直接忽略（不据此剔除股票）
    raw = _field_value(q, field)
    if raw is None:
        return False  # 该股缺这个字段（如亏损股无 PE）→ 视为不满足
    val = raw / meta["scale"]
    try:
        v = float(cond.get("value"))
    except (TypeError, ValueError):
        return True
    if op == "gt":
        return val > v
    if op == "gte":
        return val >= v
    if op == "lt":
        return val < v
    if op == "lte":
        return val <= v
    if op == "eq":
        return abs(val - v) < 1e-6
    if op == "between":
        try:
            v2 = float(cond.get("value2"))
        except (TypeError, ValueError):
            return True
        lo, hi = (v, v2) if v <= v2 else (v2, v)
        return lo <= val <= hi
    return True


def _universe_ok(q: dict, uni: dict) -> bool:
    sym = q.get("symbol", "") or ""
    name = (q.get("name", "") or "").upper()
    if uni.get("exclude_st") and "ST" in name:
        return False
    if uni.get("exclude_688") and sym.startswith("688"):
        return False
    if uni.get("exclude_300") and sym.startswith("300"):
        return False
    if uni.get("exclude_bj") and (sym.startswith("8") or sym.startswith("4") or sym.startswith("92")):
        return False
    return True


def _yi(v):
    return round(v / 1e8, 2) if v else None


# ── 题材成分（行业成分股 → symbol 集合，带缓存）──────────────────────────────────
# 数据源复用 api.industry 的同花顺行业成分（在本机环境稳定，东财概念时有失败）。
_theme_cache: dict = {}          # {theme_name: (ts, set[symbol])}
_THEME_TTL = 600                 # 成分股 10 分钟缓存


def theme_symbols(theme: str) -> set[str]:
    """返回某行业/题材的成分股 6 位代码集合。失败/无此题材 → 空集合。"""
    name = (theme or "").strip()
    if not name:
        return set()
    now = time.time()
    hit = _theme_cache.get(name)
    if hit and now - hit[0] < _THEME_TTL:
        return hit[1]
    syms: set[str] = set()
    try:
        from api.industry import _fetch_ths_industry_stocks
        rows = _fetch_ths_industry_stocks(name) or []
        syms = {(r.get("symbol") or "").strip() for r in rows if r.get("symbol")}
    except Exception:
        syms = set()
    if syms:                     # 仅缓存成功结果，失败下次再试
        _theme_cache[name] = (now, syms)
    return syms


def list_themes() -> list[str]:
    """可用题材（同花顺行业名）列表，供 AI 推送时选择。失败回退空表。"""
    try:
        from api.industry import _get_industry_code, _code_cache
        _get_industry_code("__warm__")          # 触发一次拉取，填充 _code_cache
        return list(_code_cache.get("data", {}).keys())
    except Exception:
        return []


def _format(q: dict) -> dict:
    hi, lo, pc = q.get("high"), q.get("low"), q.get("prev_close")
    amp = round((hi - lo) / pc * 100, 2) if (hi is not None and lo is not None and pc) else None
    return {
        "symbol":     q.get("symbol", ""),
        "name":       q.get("name", ""),
        "price":      q.get("price"),
        "change_pct": q.get("change_pct"),
        "turnover":   q.get("turnover"),
        "pe":         q.get("pe"),
        "pb":         q.get("pb"),
        "market_cap": _yi(q.get("market_cap")),   # 亿
        "float_cap":  _yi(q.get("float_cap")),     # 亿
        "amount":     _yi(q.get("amount")),        # 亿
        "amplitude":  amp,
        "volume":     q.get("volume"),
        "volume_ratio": q.get("volume_ratio"),     # 量比
    }


# ── 主筛选 ──────────────────────────────────────────────────────────────────────

def run_screen(conditions: list, logic: str = "AND", universe: dict | None = None,
               sort_field: str = "change_pct", sort_dir: str = "desc",
               limit: int = 300, kind: str = "numeric", theme: str = "") -> dict:
    """
    返回 {total, stocks, generated_at, theme?, theme_ok?}。
    total = 符合条件的全部只数；stocks = 排序后前 limit 只（已转为用户单位）。
    kind='theme' 时先把候选股限定为该题材(行业)成分股，再叠加数值条件。
    """
    quotes = _get_quotes()
    uni = universe or {}
    conds = [c for c in (conditions or []) if c.get("field") in FIELD_MAP]
    logic = "OR" if str(logic).upper() == "OR" else "AND"

    # 题材规则：限定候选为成分股集合
    theme_set: set[str] | None = None
    theme_ok = True
    if kind == "theme":
        theme_set = theme_symbols(theme)
        theme_ok = bool(theme_set)        # 成分股拉取失败 → 标记，前端可提示稍后刷新

    out: list[dict] = []
    for q in quotes:
        if q.get("price") is None:        # 停牌/无价
            continue
        if theme_set is not None and (q.get("symbol") or "") not in theme_set:
            continue
        if not _universe_ok(q, uni):
            continue
        if conds:
            checks = [_passes(q, c) for c in conds]
            ok = all(checks) if logic == "AND" else any(checks)
        else:
            ok = True
        if ok:
            out.append(_format(q))

    sf = sort_field if sort_field in FIELD_MAP else "change_pct"
    reverse = (str(sort_dir).lower() != "asc")
    have = [x for x in out if x.get(sf) is not None]
    none = [x for x in out if x.get(sf) is None]
    have.sort(key=lambda x: x[sf], reverse=reverse)
    ordered = have + none      # 缺失值永远排最后

    # 形态后置过滤：均线 / MACD / 新高 / 连涨 / 量能等多日形态。
    # 全市场单张快照无法判断多日趋势，故对已收敛、按排序取前列的候选集，
    # 逐只拉历史日线一次算齐所有形态（按交易日缓存）。多个形态取「与」(AND)。
    # 候选过多时先截断以保护性能。
    active_patterns = [k for k in _PATTERN_KEYS if uni.get(k)]
    pattern_applied = False
    if active_patterns and ordered:
        try:
            from data.stock_data import fetch_patterns_batch
            cand = ordered[:_PATTERN_MAX_CANDIDATES]
            pat = fetch_patterns_batch([s["symbol"] for s in cand])
            ordered = [
                s for s in cand
                if all(pat.get(s["symbol"], {}).get(k) for k in active_patterns)
            ]
            pattern_applied = True
        except Exception:
            pass   # 历史数据不可用 → 保留数值筛选结果，不因形态条件清空

    shown = ordered[: max(1, int(limit or 300))]
    # 行业列：用当日缓存的「代码→行业」映射（非阻塞，缓存未就绪则留空，由详情下拉兜底）
    try:
        from data.stock_data import get_industry_map
        imap = get_industry_map(block=False)
        if imap:
            for s in shown:
                s["industry"] = imap.get(s["symbol"]) or None
    except Exception:
        pass

    res = {
        "total": len(ordered),
        "stocks": shown,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if active_patterns:
        res["pattern_applied"] = pattern_applied
        res["patterns"] = active_patterns
        res["vol_uptrend"] = pattern_applied   # 向后兼容旧前端字段
    if kind == "theme":
        res["theme"] = theme
        res["theme_ok"] = theme_ok
    return res


# ── 单股详情（结果表下拉懒加载：行业 / 主营业务 / 最近表现）──────────────────────

def _shape_recent(q: dict | None) -> dict | None:
    """把 fetch_quick_batch 的一条结果整形成下拉「最近表现」结构。"""
    if not q or q.get("error"):
        return None
    tech = q.get("technical", {}) or {}
    trend = q.get("trend", {}) or {}
    today = q.get("today", {}) or {}
    return {
        "date":        today.get("date"),
        "pct_change":  today.get("pct_change"),
        "tags":        trend.get("tags", []),
        "streak":      trend.get("streak"),
        "above_ma5":   trend.get("above_ma5"),
        "above_ma20":  trend.get("above_ma20"),
        "above_ma60":  trend.get("above_ma60"),
        "ma5_pct":     tech.get("ma5_pct"),
        "ma20_pct":    tech.get("ma20_pct"),
        "ma60_pct":    tech.get("ma60_pct"),
        "macd_status": tech.get("macd_status"),
        "rsi14":       tech.get("rsi14"),
        "vol_ratio":   tech.get("vol_ratio"),
    }


def stock_detail(symbol: str) -> dict:
    """聚合单只股票的下拉详情：
    - industry：当日行业映射（缓存，秒级）
    - business：同花顺主营介绍（akshare，约 0.5s，按天缓存）
    - recent：技术面快速复盘（baostock 一次日线，含均线/MACD/连涨/标签）
    任一来源失败不影响其他字段。
    """
    symbol = (symbol or "").strip()
    out: dict = {"symbol": symbol, "industry": None, "business": None, "recent": None}
    if not symbol:
        return out

    # 行业（非阻塞取缓存）
    try:
        from data.stock_data import get_industry_map
        out["industry"] = get_industry_map(block=False).get(symbol) or None
    except Exception:
        pass

    # 主营业务（同花顺主营介绍）
    try:
        from data.stock_data import fetch_main_business
        biz = fetch_main_business(symbol)
        if biz and (biz.get("business") or biz.get("scope")):
            out["business"] = biz
    except Exception:
        pass

    # 最近表现（技术面快速复盘）
    try:
        from data.stock_data import fetch_quick_batch
        rows = fetch_quick_batch([symbol])
        out["recent"] = _shape_recent(rows[0] if rows else None)
    except Exception:
        pass

    return out


def stock_detail_batch(symbols: list[str], limit: int = 40) -> dict:
    """
    批量聚合下拉详情，供「筛选完成即预取」用。
    关键效率点：
    - 最近表现：fetch_quick_batch 一次 baostock 会话拉完所有股票（单锁、按天缓存）
    - 行业：get_industry_map 取一次缓存
    - 主营业务：akshare 逐只抓取，用线程池并行（不走 baostock 锁，按天缓存）
    返回 {symbol: {symbol, industry, business, recent}}，封顶 limit 只防止压垮 baostock。
    """
    syms = [(s or "").strip() for s in (symbols or []) if (s or "").strip()]
    # 去重保序
    seen: set[str] = set()
    uniq: list[str] = []
    for s in syms:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    uniq = uniq[:max(0, limit)]
    out: dict[str, dict] = {s: {"symbol": s, "industry": None, "business": None, "recent": None} for s in uniq}
    if not uniq:
        return out

    # 行业（一次缓存）
    imap: dict = {}
    try:
        from data.stock_data import get_industry_map
        imap = get_industry_map(block=False) or {}
    except Exception:
        imap = {}
    for s in uniq:
        out[s]["industry"] = imap.get(s) or None

    # 最近表现（一次 baostock 会话批量）
    try:
        from data.stock_data import fetch_quick_batch
        rows = fetch_quick_batch(uniq)
        for q in rows or []:
            sym = q.get("symbol")
            if sym in out:
                out[sym]["recent"] = _shape_recent(q)
    except Exception:
        pass

    # 主营业务（akshare 并行，按天缓存命中后极快）
    try:
        from concurrent.futures import ThreadPoolExecutor
        from data.stock_data import fetch_main_business

        def _one_biz(sym: str):
            try:
                biz = fetch_main_business(sym)
                if biz and (biz.get("business") or biz.get("scope")):
                    return sym, biz
            except Exception:
                pass
            return sym, None

        with ThreadPoolExecutor(max_workers=6) as ex:
            for sym, biz in ex.map(_one_biz, uniq):
                if biz and sym in out:
                    out[sym]["business"] = biz
    except Exception:
        pass

    return out


# ── 自然语言 → 结构化条件（AI）─────────────────────────────────────────────────

def _loads_json_lenient(raw: str) -> dict:
    if not raw:
        return {}
    s = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    a, b = s.find("{"), s.rfind("}")
    if a != -1 and b > a:
        try:
            return json.loads(s[a:b + 1])
        except Exception:
            pass
    return {}


def _fields_doc() -> str:
    return "\n".join(f'- {f["key"]}: {f["label"]}（单位：{f["unit"]}）' for f in FIELDS)


def _extract_prompt(text: str) -> str:
    """构造严格的「文字 → 结构化选股条件」提示词（parse_nl 与截图识别共用）。"""
    return f"""你是严谨的 A 股选股助手。把下面这段文字里能落地的「选股数值条件」提取成结构化 JSON。

可用字段（field: 含义 单位）：
{_fields_doc()}

字段同义词对照（文字里常见说法 → field）：
- 涨幅 / 涨跌幅 / 当日涨幅 → change_pct
- 换手 / 换手率 → turnover
- 量比 → volume_ratio
- 振幅 → amplitude
- 股价 / 价格 / 现价 → price
- 市盈率 / PE / 市盈 → pe
- 市净率 / PB → pb
- 总市值 → market_cap
- 流通市值 / 流通盘 / 流通 → float_cap
- 成交额 / 成交金额 → amount（单位亿）
- 成交量 → volume（单位手）

运算符 op：gt(大于) gte(大于等于) lt(小于) lte(小于等于) between(区间) eq(等于)

提取规则（务必遵守）：
1. 区间一律用 between，并同时给 value 和 value2（小值在前）。例：
   「涨幅卡在 3%-5%」→ {{"field":"change_pct","op":"between","value":3,"value2":5}}
   「换手率 5%-10%」→ {{"field":"turnover","op":"between","value":5,"value2":10}}
   「流通市值 50 亿-200 亿」→ {{"field":"float_cap","op":"between","value":50,"value2":200}}
2. 「大于/超过/高于/＞」用 gt，「小于/低于/＜」用 lt，「以上/不低于」用 gte，「以下/不高于」用 lte。
   例：「量比 > 1」→ {{"field":"volume_ratio","op":"gt","value":1}}
3. 单位换算到字段要求的单位：市值/成交额用「亿」（「50亿」→50，「3000万」→0.3），成交量用「手」（「2万手」→20000）。
4. 只提取「能用上面字段表达、且有明确数字阈值」的条件。下列内容【绝对不要】提取，直接忽略：
   · 买卖时间点 / 时间段（如「下午2:30后买入」「9:30-10:00」「尾盘」）——这是时间，不是选股字段。
   · 分时图、走势描述（如「分时跑赢大盘」「回踩不破」）这类无法量化的，忽略。
     例外：下方 universe 形态类列出的多日形态（均线/MACD/新高/连涨/温和放量），用对应开关表达，不要忽略。
   · 概率/胜率/仓位/纪律/心态等（如「胜率六成」「高开八成」「100%必涨」「半小时内出局」「空仓」）。
   · 没有具体数字、或数字无法对应到上面任一字段的话。
5. 严禁臆造：文字没有明确写出的字段或数字，绝对不要出现在结果里。宁可返回空，也不要编造。
   如果整段文字找不到任何可量化的选股条件，必须返回 {{"conditions":[],"logic":"AND","universe":{{}},"name":""}}。

universe 可选项（文字明确提到才写，否则不写）：
  排除类：exclude_st(排除ST股) exclude_688(排除科创板) exclude_300(排除创业板) exclude_bj(排除北交所)
  形态类（多日 K 线/均线/量能形态，文字明确描述对应走势才设 true）：
  - vol_uptrend：成交量像台阶一样放大 / 温和放量 / 逐步(一步步)放量 / 成交量温和上涨 / 量能阶梯式抬高。
                注意：只有「逐步放大 / 台阶式 / 一步步往上爬」这种多日趋势才算；单纯「放量」「量比>1」不要设。
  - ma_bullish：均线多头排列 / 多头排列 / MA5在MA20上方在MA60上方 / 短中长期均线向上发散。
  - above_ma20：站上20日线 / 站上月线 / 收盘价在20日均线之上。
  - macd_golden：MACD金叉 / DIF上穿DEA / 红柱由绿转红。
  - new_high_60：创新高 / 创60日新高 / 创阶段新高 / 突破前高。
  - streak_up：连涨3天 / 连续上涨 / 多连阳 / 连续收红。

只输出 JSON，不要任何解释、不要 markdown 代码块。示例（仅示意格式）：
{{"conditions":[{{"field":"change_pct","op":"between","value":3,"value2":5}},{{"field":"volume_ratio","op":"gt","value":1}},{{"field":"turnover","op":"between","value":5,"value2":10}}],
  "logic":"AND","universe":{{"vol_uptrend":true}},"name":"尾盘选股"}}

name 为这条规则起一个 <=8 字的简短名字（可用文字标题）。logic 一般用 AND（同时满足）。

待解析文字：
{text}"""


def _extract_conditions(text: str) -> dict:
    """用 DeepSeek 文本模型把一段文字抽取成结构化条件（更强的推理 + 更不易臆造）。"""
    from services.ai_client import make_client, CHAT_MODEL
    client = make_client()
    resp = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": _extract_prompt(text)}],
        temperature=0.0,
        max_tokens=1500,
        timeout=90,
    )
    data = _loads_json_lenient(resp.choices[0].message.content or "")
    return _normalize_parsed(data)


def parse_nl(text: str) -> dict:
    """
    把一句话选股描述翻译成结构化条件。
    返回 {conditions, logic, universe, name}；失败抛异常由上层兜底。
    """
    return _extract_conditions(text)


def _normalize_parsed(data: dict) -> dict:
    """把 AI 产出的原始 JSON 清洗成 {conditions, logic, universe, name}。"""
    conds = []
    for c in (data.get("conditions") or []):
        if c.get("field") in FIELD_MAP and c.get("op") in _OP_KEYS:
            cc = {"field": c["field"], "op": c["op"], "value": c.get("value")}
            if c["op"] == "between":
                cc["value2"] = c.get("value2")
            conds.append(cc)

    logic = data.get("logic", "AND")
    logic = "OR" if str(logic).upper() == "OR" else "AND"

    uni_raw = data.get("universe") or {}
    universe = {k: bool(uni_raw.get(k)) for k in _UNIVERSE_ALLOWED if uni_raw.get(k)}

    return {
        "conditions": conds,
        "logic": logic,
        "universe": universe,
        "name": (data.get("name") or "").strip()[:12],
    }


# ── 截图 → 结构化条件（视觉 AI）─────────────────────────────────────────────────

def _transcribe_image(data_uri: str) -> str:
    """
    第一阶段：用视觉模型把截图里的文字「逐字转录」成纯文本。
    视觉模型擅长 OCR、不擅长结构化推理；故只让它读字，结构化交给更强的文本模型。
    """
    from services.ai_client import make_vision_client, VISION_MODEL
    prompt = (
        "请把这张图片里出现的所有文字，按从上到下的顺序原样转录出来。"
        "保留数字、百分号、区间（如 3%-5%、50亿-200亿）、大于小于号等符号，逐字照抄。"
        "不要解释、不要总结、不要翻译、不要补充图里没有的内容，只输出图中的文字。"
    )
    client = make_vision_client()
    resp = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ]}],
        temperature=0.0,
        max_tokens=1024,   # glm-4v-flash 上限 1024
        timeout=90,
    )
    return (resp.choices[0].message.content or "").strip()


def parse_image(data_uri: str) -> dict:
    """
    识别一张选股截图（攻略文字/选股软件设置/聊天记录等），翻译成结构化筛选条件。
    两阶段流水线：① 视觉模型 OCR 转录文字 → ② DeepSeek 文本模型严格抽取条件。
    比让视觉模型一步到位更准、更不易臆造。
    返回 {conditions, logic, universe, name}；失败抛异常由上层兜底。
    """
    text = _transcribe_image(data_uri)
    if len(text) < 2:
        return {"conditions": [], "logic": "AND", "universe": {}, "name": ""}
    return _extract_conditions(text)
