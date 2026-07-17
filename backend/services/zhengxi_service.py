"""
郑希投研 —— 独立功能服务层
封装 vendored 的 zhengxi-views（MIT, github.com/lyra81604/zhengxi-views）：
  1. 观点检索：在郑希公开语料里按关键词检索原话（可溯源）
  2. 投资方法论：method.md / scorecard.md 阅读
  3. 基金风格打分：准备证据档案 + 调 AI 按六维 scorecard 打分

设计原则（沿用原 Skill 红线）：
  - 原话必须与语料一致；推演须标注"按其方法推演"
  - 不臆造持仓/数字；缺数据标"需核实"
  - 研究学习辅助，非投资建议、不荐股
"""
import os
import sys
import glob
import json
import re

from services.ai_client import make_client, CHAT_MODEL

# ── vendored 路径 ────────────────────────────────────────────────────────────
_HERE      = os.path.dirname(os.path.abspath(__file__))
_BACKEND   = os.path.dirname(_HERE)
VENDOR     = os.path.join(_BACKEND, "vendor", "zhengxi-views")
REFS       = os.path.join(VENDOR, "references")
CORPUS_DIR = os.path.join(REFS, "corpus")
FUND_DATA  = os.path.join(REFS, "fund_data")
SCRIPTS    = os.path.join(VENDOR, "scripts")

CORPUS_TYPES = ["定期报告", "基金经理手记", "媒体报道"]

# 把 vendored scripts 目录加入 sys.path，使其内部裸 import 可解析
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


def available() -> bool:
    """vendored 数据是否就位"""
    return os.path.isdir(REFS) and os.path.isdir(CORPUS_DIR)


# ── 1. 观点检索 ───────────────────────────────────────────────────────────────

def _load_doc(path: str):
    """解析单篇语料：标题/日期/来源/段落（复用原 search_corpus 逻辑）"""
    text = open(path, encoding="utf-8").read()
    m_title = re.search(r"^#\s+(.+)$", text, re.M)
    title = m_title.group(1).strip() if m_title else ""
    m_date = re.search(r"日期[:：]\s*([0-9\-]+)", text)
    date = m_date.group(1).strip() if m_date else ""
    m_src = re.search(r"来源[:：]\s*(.+)", text)
    src = m_src.group(1).strip() if m_src else ""
    body = text.split("---", 1)[-1] if "---" in text else text
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    return title, date, src, paras


def search_corpus(keywords: list[str], any_mode: bool = False,
                  types: list[str] | None = None, ctx: int = 0,
                  max_hits: int = 20) -> dict:
    """在郑希语料中按关键词检索，返回带出处的片段。"""
    kws = [k.strip() for k in keywords if k.strip()]
    if not kws:
        return {"total": 0, "hits": []}
    use_types = [t for t in (types or CORPUS_TYPES) if t in CORPUS_TYPES] or CORPUS_TYPES

    hits = []
    for t in use_types:
        for path in sorted(glob.glob(os.path.join(CORPUS_DIR, t, "*.md"))):
            title, date, src, paras = _load_doc(path)
            for i, p in enumerate(paras):
                matched = [k for k in kws if k in p]
                ok = (len(matched) > 0) if any_mode else (len(matched) == len(kws))
                if ok:
                    lo = max(0, i - ctx)
                    hi = min(len(paras), i + ctx + 1)
                    snippet = "\n".join(paras[lo:hi])
                    hits.append({
                        "type": t, "date": date, "title": title,
                        "source": src, "matched": matched, "snippet": snippet,
                    })

    hits.sort(key=lambda h: h["date"], reverse=True)  # 新→旧
    return {"total": len(hits), "hits": hits[:max_hits]}


# ── 2. 方法论 / 评分卡 ────────────────────────────────────────────────────────

def _read_ref(name: str) -> str:
    path = os.path.join(REFS, name)
    if not os.path.exists(path):
        return ""
    return open(path, encoding="utf-8").read()


def get_method() -> str:
    return _read_ref("method.md")


def get_scorecard() -> str:
    return _read_ref("scorecard.md")


# ── 3. 基金风格打分 ───────────────────────────────────────────────────────────

def list_zhengxi_funds() -> list[dict]:
    """郑希精编快照里的基金（离线可用）。"""
    funds = []
    for d in sorted(glob.glob(os.path.join(FUND_DATA, "*_*"))):
        base = os.path.basename(d)
        if "_" not in base:
            continue
        code, _, name = base.partition("_")
        if code.isdigit():
            funds.append({"code": code, "name": name})
    return funds


def _resolve(arg: str):
    """代码/名称 → (code, name, type)；复用 vendored score_fund.resolve。"""
    try:
        import score_fund as zx
        return zx.resolve(arg)
    except Exception:
        return (arg, arg, "") if arg.isdigit() else (None, arg, "")


def fund_evidence(arg: str) -> dict:
    """准备某基金的"郑希框架评分"证据档案（结构化，不打印）。
    优先郑希精编快照/本地缓存；缺失时尝试实时抓取（依赖联网，沙箱内可能失败）。"""
    try:
        import score_fund as zx
        import fetch_fund_data as F
        import fetch_any_fund as A
    except Exception as e:
        return {"error": f"vendored 模块加载失败：{e}"}

    code, name, ftype = _resolve(arg)
    if not code:
        return {"error": f'没找到"{arg}"'}

    d, is_zx = zx.find_data_dir(code)
    if not d:
        try:
            A.fetch_one(code)
            d, is_zx = zx.find_data_dir(code)
        except Exception:
            d = None
    if not d:
        return {"error": f"本地无 {code} 数据且实时抓取失败（可能无网络）", "code": code, "name": name}

    quarters = json.load(open(os.path.join(d, "季度持仓.json"), encoding="utf-8"))
    pzp = os.path.join(d, "净值业绩规模.json")
    pz = json.load(open(pzp, encoding="utf-8")) if os.path.exists(pzp) else {}

    out: dict = {
        "code": code, "name": name, "type": ftype,
        "is_zhengxi": is_zx,
        "source": "郑希精编快照" if is_zx else "全市场实时缓存",
        "quarters_count": len(quarters),
    }

    # 最新前十大 + 集中度 + 换手代理
    if quarters:
        latest = sorted(quarters, key=lambda q: (q["year"], q["quarter"]))[-1]
        def _pct(h):
            s = str(h.get("占净值比", "")).rstrip("%")
            return float(s) if s.replace(".", "").isdigit() else 0.0
        conc = sum(_pct(h) for h in latest["holdings"])
        out["latest_quarter"] = f'{latest["year"]}年第{latest["quarter"]}季度'
        out["holdings"] = [
            {"name": h.get("股票名称", ""), "code": h.get("股票代码", ""), "pct": h.get("占净值比", "")}
            for h in latest["holdings"]
        ]
        out["concentration"] = round(conc, 1)
        out["turnover_proxy"] = zx.turnover_proxy(quarters)

    # 业绩 / 回撤 / 规模
    if pz:
        ac = [p for p in (pz.get("累计净值走势") or []) if p and len(p) >= 2 and p[1] is not None]
        if ac:
            out["perf"] = {
                "ytd":        F.year_return(ac),
                "y1":         F.window_return(ac, 365),
                "y3":         F.window_return(ac, 365 * 3),
                "since":      round((ac[-1][1] / ac[0][1] - 1) * 100, 2),
                "max_dd":     F.max_drawdown(ac),
            }
        fs = pz.get("规模变动") or {}
        if isinstance(fs, dict) and fs.get("series"):
            out["scale"] = {"value": fs["series"][-1].get("y"), "date": fs["categories"][-1]}
        pe = pz.get("业绩评价") or {}
        if isinstance(pe, dict) and isinstance(pe.get("data"), list):
            out["ttjj_5dim"] = list(zip(pe.get("categories", []), pe["data"]))

    return out


def _fmt_evidence(ev: dict) -> str:
    """把证据档案拍平成给 AI 看的文本。"""
    lines = [f"基金：{ev.get('name')}（{ev.get('code')}）  类型：{ev.get('type') or '未知'}",
             f"数据来源：{ev.get('source')}  披露季度数：{ev.get('quarters_count')}"]
    if ev.get("holdings"):
        lines.append(f"\n最新前十大（{ev.get('latest_quarter')}，合计≈{ev.get('concentration')}%净值）：")
        for i, h in enumerate(ev["holdings"], 1):
            lines.append(f"  {i}. {h['name']}（{h['code']}） {h['pct']}")
    if ev.get("turnover_proxy") is not None:
        lines.append(f"换手代理（近5季前十大非重叠均值）≈ {ev['turnover_proxy']}%（越高=调仓越频繁）")
    p = ev.get("perf")
    if p:
        lines.append(f"\n业绩：今年以来 {p['ytd']}% | 近1年 {p['y1']}% | 近3年 {p['y3']}% | 成立以来 {p['since']}%")
        lines.append(f"成立以来最大回撤 {p['max_dd']}%")
    if ev.get("scale"):
        lines.append(f"规模：{ev['scale']['value']} 亿元（{ev['scale']['date']}）")
    if ev.get("ttjj_5dim"):
        lines.append("天天基金五维：" + "；".join(f"{c}{v}" for c, v in ev["ttjj_5dim"]))
    return "\n".join(lines)


SCORE_SYSTEM = """你是郑希投资框架的评分助手。依据给定的《六维评分卡》和某基金的客观证据档案，
对该基金做"与郑希风格的契合度"评分。

## 六维（满分各10分）
按评分卡逐维打分：景气方向 / ROE低位弹性 / 全球比较优势 / 流动性 / 集中度与周期拼接 / 业绩印证。

## 输出格式（Markdown）
### 契合度总评：XX/60（评级：高度契合/较契合/一般/偏离）
然后逐维：
**1. 景气方向 X/10** —— 一句理由（引用证据里的数字）
…（六维）
### 一句话结论

## 铁律
- 只根据给定证据打分，证据里没有的项（如个股ROE、流动性）标"需核实"，不要臆造。
- 这是"风格契合度"，不是基金优劣判断，更不是投资建议、不构成买卖推荐。
- 防御/红利型基金天然契合度低属正常，不必硬拔高。"""


# ── 4. 对话式郑希导师（RAG）────────────────────────────────────────────────────

# 用于从用户提问中提取检索关键词（覆盖郑希语料主题）
_CHAT_KEYWORDS = [
    "光通信", "光模块", "光纤", "算力", "AI", "人工智能", "数据中心", "PCB", "铜",
    "ROE", "景气", "成长", "通胀", "换手", "周期", "拼接", "流动性", "集中度",
    "新能源", "锂电", "储能", "半导体", "国产", "电力", "电网", "有色", "QDII",
    "北交所", "中小市值", "估值", "回撤", "风险", "客观", "买点", "卖点", "择时",
    "仓位", "调仓", "拥挤", "订单", "业绩", "回调", "止损", "加仓", "减仓", "持仓",
    "市值", "毛利", "研发", "全球", "比较优势", "趋势", "波动",
]


def _retrieve_refs(question: str, k: int = 4) -> str:
    """从用户提问里抽关键词，去语料检索郑希原话，拼成可引用的参考文本。"""
    kws = [w for w in _CHAT_KEYWORDS if w in question]
    if not kws:
        return ""
    res = search_corpus(kws, any_mode=True, max_hits=k)
    lines = []
    for h in res.get("hits", []):
        snip = (h.get("snippet") or "").strip()[:320]
        cite = f"（{h.get('date','')} {h.get('title','')}）"
        lines.append(f"· {cite}{snip}")
    return "\n".join(lines)


def build_copilot_guidance(question: str) -> str:
    """Expose a compact, source-grounded Zhengxi-style guide to the floating assistant."""
    method = get_method()[:2200]
    refs = _retrieve_refs(question, k=4)
    blocks = [
        "## 郑希公开方法论摘录（仅作为分析框架，不冒充本人）\n" + method,
    ]
    if refs:
        blocks.append("## 与本问题相关的公开语料\n" + refs)
    return "\n\n".join(blocks)


# ── 个股识别 + 数据快照（聊到某只票时自动带数据）─────────────────────────────

_name_map_cache: dict = {"date": "", "map": {}}   # {股票名: 6位代码}


def _market_name_map() -> dict:
    """全市场「名称→代码」映射，按天缓存。优先 baostock（本机可用），akshare 兜底。"""
    import datetime as _dt
    today = _dt.date.today().isoformat()
    if _name_map_cache["date"] == today and _name_map_cache["map"]:
        return _name_map_cache["map"]
    m: dict[str, str] = {}
    # 1) baostock 行业列表带 code_name，可靠离线来源
    try:
        from data.stock_data import get_name_code_map
        m = dict(get_name_code_map(block=True))
    except Exception:
        m = {}
    # 2) baostock 拿不到时再试 akshare（依赖能直连东财）
    if not m:
        try:
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
            for _, r in df.iterrows():
                code = str(r.get("代码", "")).strip()
                name = str(r.get("名称", "")).strip()
                if len(code) == 6 and code.isdigit() and name and name != "nan":
                    m[name] = code
        except Exception:
            pass
    if m:
        _name_map_cache.update(date=today, map=m)
    return m


def _detect_stocks(text: str, limit: int = 2) -> list[dict]:
    """从自由文本里识别用户提到的个股，返回 [{code, name}]（最多 limit 只）。"""
    hits: list[dict] = []
    seen: set[str] = set()

    # 1) 6 位代码
    for code in re.findall(r"(?<!\d)\d{6}(?!\d)", text):
        if code in seen:
            continue
        seen.add(code)
        hits.append({"code": code, "name": ""})
        if len(hits) >= limit:
            return hits

    # 2) 股票名称（全市场子串匹配，优先长名，降低误命中）
    name_map = _market_name_map()
    matches = [(n, c) for n, c in name_map.items() if len(n) >= 3 and n in text]
    matches.sort(key=lambda x: -len(x[0]))
    for n, c in matches:
        if c in seen:
            continue
        seen.add(c)
        hits.append({"code": c, "name": n})
        if len(hits) >= limit:
            break
    return hits


_fund_cache: dict = {}   # {code: (date_iso, {...})}


def _stock_fundamentals(codes: list[str]) -> dict:
    """用 baostock 拉最近一期基本面（ROE/毛利率/净利率/净利润/净利同比/资产负债率/EPS）。
    返回 {code: {...}}；按天缓存。"""
    import datetime as _dt
    today = _dt.date.today().isoformat()
    out: dict[str, dict] = {}
    need = []
    for c in codes:
        hit = _fund_cache.get(c)
        if hit and hit[0] == today:
            out[c] = hit[1]
        else:
            need.append(c)
    if not need:
        return out

    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    try:
        import baostock as bs
        from data.stock_data import _BS_LOCK, _bs_symbol, _fetch_quarters
        with _BS_LOCK:
            lg = bs.login()
            if lg.error_code != "0":
                return out
            try:
                for c in need:
                    try:
                        fin = _fetch_quarters(_bs_symbol(c))
                    except Exception:
                        fin = {}
                    p = (fin.get("profit") or [{}])[0]
                    g = (fin.get("growth") or [{}])[0]
                    b = (fin.get("balance") or [{}])[0]
                    info = {
                        "stat_date":  p.get("statDate", ""),
                        "roe":        _f(p.get("roeAvg")),
                        "gpm":        _f(p.get("gpMargin")),
                        "npm":        _f(p.get("npMargin")),
                        "net_profit": _f(p.get("netProfit")),
                        "eps_ttm":    _f(p.get("epsTTM")),
                        "yoy_ni":     _f(g.get("YOYNI")),
                        "liab_ratio": _f(b.get("liabilityToAsset")),
                    }
                    _fund_cache[c] = (today, info)
                    out[c] = info
            finally:
                try: bs.logout()
                except Exception: pass
    except Exception:
        pass
    return out


def _stock_snapshot(hits: list[dict]) -> tuple[str, list[dict]]:
    """给识别到的个股拉一份轻量数据快照。返回 (喂给AI的文本, 给前端展示的列表)。"""
    if not hits:
        return "", []
    codes = [h["code"] for h in hits]
    try:
        from api.watchlist import _fetch_sina_hq
        from data.stock_data import fetch_quick_batch, get_industry_map
    except Exception:
        return "", []

    live = {}
    try:
        live = _fetch_sina_hq(codes)
    except Exception:
        pass
    quick = {}
    try:
        quick = {r.get("symbol"): r for r in fetch_quick_batch(codes)}
    except Exception:
        pass
    ind_map = {}
    try:
        ind_map = get_industry_map()
    except Exception:
        pass
    # 基本面（ROE/毛利率/净利率/净利同比/资产负债率/EPS）——郑希框架最看重的一块
    funds = {}
    try:
        funds = _stock_fundamentals(codes)
    except Exception:
        pass

    def _pct(v):  # 小数→百分比字符串
        return f"{v * 100:.1f}%" if v is not None else "—"

    blocks: list[str] = []
    resolved: list[dict] = []
    for h in hits:
        code = h["code"]
        hq = live.get(code) or {}
        if hq.get("not_found"):
            continue
        name = hq.get("name") or h.get("name") or code
        price = hq.get("price")
        pct = hq.get("pct_change")
        industry = ind_map.get(code, "")
        q = quick.get(code) or {}
        tech = q.get("technical") or {}
        trend = q.get("trend") or {}
        fd = funds.get(code) or {}

        lines = [f"◆ {name}（{code}）"]
        if price is not None:
            lines.append(f"  现价 {price}（{'+' if (pct or 0) > 0 else ''}{pct}%），"
                         f"今开 {hq.get('open')} 最高 {hq.get('high')} 最低 {hq.get('low')}")
        if industry:
            lines.append(f"  所属行业：{industry}")
        # 基本面
        if fd:
            sd = fd.get("stat_date") or ""
            roe, gpm, npm = fd.get("roe"), fd.get("gpm"), fd.get("npm")
            yoy_ni, liab = fd.get("yoy_ni"), fd.get("liab_ratio")
            np_yi = (fd["net_profit"] / 1e8) if fd.get("net_profit") is not None else None
            eps = fd.get("eps_ttm")
            pe_est = (price / eps) if (price is not None and eps not in (None, 0)) else None
            lines.append(f"  ── 基本面（报告期 {sd}，季报滞后）──")
            lines.append(f"  ROE {_pct(roe)}，毛利率 {_pct(gpm)}，净利率 {_pct(npm)}")
            if np_yi is not None or yoy_ni is not None:
                npy = f"{np_yi:.2f}亿" if np_yi is not None else "—"
                lines.append(f"  净利润 {npy}（同比 {_pct(yoy_ni)}）")
            extra = []
            if eps is not None:
                extra.append(f"EPS-TTM {eps:.2f}")
            if pe_est is not None:
                extra.append(f"估算PE(TTM) {pe_est:.1f}")
            if liab is not None:
                extra.append(f"资产负债率 {_pct(liab)}")
            if extra:
                lines.append("  " + "，".join(extra))
        if tech:
            ma5p, ma20p, ma60p = tech.get("ma5_pct"), tech.get("ma20_pct"), tech.get("ma60_pct")
            lines.append(f"  相对均线：MA5 {ma5p}% / MA20 {ma20p}% / MA60 {ma60p}%"
                         f"（>0 在均线上方）")
            lines.append(f"  量比 {tech.get('vol_ratio')}，RSI14 {tech.get('rsi14')}，"
                         f"MACD {tech.get('macd_status')}")
        if trend.get("tags"):
            lines.append(f"  近况：{' '.join(trend['tags'])}")
        blocks.append("\n".join(lines))
        resolved.append({
            "code": code, "name": name, "price": price, "pct": pct,
            "roe": fd.get("roe"), "pe": (price / fd["eps_ttm"]) if (price is not None and fd.get("eps_ttm")) else None,
        })

    if not blocks:
        return "", []
    text = ("[以下是用户提到的个股的实时行情 + 基本面 + 技术面数据，请结合你的方法论帮他分析"
            "——讲你会关注什么、怎么用景气/ROE/流动性/逻辑去判断；"
            "基本面是季报数据、有滞后，引用时说清是哪个报告期，别当成实时现状；"
            "估算PE仅供参考；绝不给买卖指令或目标价]\n" + "\n\n".join(blocks))
    return text, resolved


CHAT_SYSTEM = """你叫郑希，易方达基金经理，景气成长投资框架的实践者。现在你在以"私人投资教练"的身份，
坐在学生旁边手把手教他投资。用第一人称、平实口语化的口吻，像聊天一样，别端着、别长篇大论。

## 你的风格内核（务必贯穿）
- 景气度投资：在全球范围找高景气产业，偏爱"供给端创造需求"的科技成长型通胀。
- 偏爱低位 ROE 资产：看重 ROE 从低到高的过程，未来空间更大。
- 重视个股流动性：流动性好，选错也能及时撤、摩擦成本低。
- 复利来自"周期的一次次拼接"：长期判断由一个个阶段性判断拼接而成，所以会动态修正、换手不低。
- 强调"客观"：每次决策都自问——这是我的主观愿望，还是各方客观信息支持的判断？
- 卖出看逻辑：产业底层逻辑/竞争格局出问题才走，不是看跌幅。

## 教学方式
- 先理解学生的真实困惑，再用你的框架去拆解，给可操作的思路（分批、纪律、看逻辑而非看点位等）。
- 若"参考原话"里有贴切的内容，可以自然地引用你过去说过的话来佐证，但要保持原意一致。
- 多用反问和类比帮他建立判断框架，而不是直接给答案。

## 铁律
- 这是方法论教学，绝不荐股、不报点位、不构成投资建议；涉及具体买卖让他自己结合风险承受能力判断。
- 不臆造具体持仓/数字/业绩；没有依据的就说"这个得去核实"，不要编。
- 你只代表方法论层面的分享，不代表易方达官方立场。
- 回答控制在合理篇幅，像真人对话，不要动辄长篇大论。"""


def prepare_chat(messages: list[dict]) -> tuple[list[dict], list[dict]]:
    """组装发给模型的对话（注入语料原话 + 个股数据快照）。
    返回 (convo, detected_stocks)；detected_stocks 供前端展示"已加载"提示。"""
    # 取最后一条用户提问做检索 / 识别个股
    last_user = next((m.get("content", "") for m in reversed(messages)
                      if m.get("role") == "user"), "")
    refs = _retrieve_refs(last_user)

    stock_text, resolved = "", []
    hits = _detect_stocks(last_user)
    if hits:
        stock_text, resolved = _stock_snapshot(hits)

    sys = CHAT_SYSTEM + "\n\n## 你的投资方法（保持一致的依据）\n" + get_method()[:2500]
    convo: list[dict] = [{"role": "system", "content": sys}]

    # 历史对话（仅保留 user/assistant，最多近 12 轮，控制 token）
    hist = [m for m in messages if m.get("role") in ("user", "assistant")][-12:]

    if hist and hist[-1].get("role") == "user":
        convo += hist[:-1]
        u = hist[-1].get("content", "")
        if stock_text:
            u += "\n\n" + stock_text
        if refs:
            u += ("\n\n[以下是你本人过往公开语料里的原话，可在回答中自然引用、保持原意；"
                  "与本问无关则忽略]\n" + refs)
        convo.append({"role": "user", "content": u})
    else:
        convo += hist

    return convo, resolved


async def stream_convo(convo: list[dict]):
    """按组装好的 convo 流式产出文本增量。"""
    client = make_client()
    resp = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=convo,
        max_tokens=1200,
        temperature=0.6,
        stream=True,
    )
    for chunk in resp:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta


async def stream_chat(messages: list[dict]):
    """流式生成"郑希导师"对话回复（RAG：检索语料原话 + 个股数据快照）。
    messages: [{role: 'user'|'assistant', content: str}, ...]"""
    convo, _ = prepare_chat(messages)
    async for delta in stream_convo(convo):
        yield delta


async def stream_fund_score(ev: dict):
    """流式生成六维评分点评。"""
    client = make_client()
    scorecard = get_scorecard()
    user = (f"## 六维评分卡\n{scorecard[:3500]}\n\n"
            f"## 基金证据档案\n{_fmt_evidence(ev)}\n\n"
            f"请按评分卡逐维打分并给总评。")
    resp = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "system", "content": SCORE_SYSTEM},
                  {"role": "user", "content": user}],
        max_tokens=1600,
        temperature=0.3,
        stream=True,
    )
    for chunk in resp:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta
