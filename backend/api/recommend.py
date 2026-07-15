"""
推荐系统 v3 ── 新闻消息面驱动 + DeepSeek 分析
─────────────────────────────────────────────────────────────────────────────
流程：
  1. 抓取最新财经快讯（财联社/东方财富/同花顺，~4s）
  2. DeepSeek flash 提取股票催化剂（~3s，成本极低）
  3. 解析股票代码 + 实时行情过滤（~2s）
  4. 叠加龙虎榜/北向资金/技术指标评分

GET /api/recommend/today     今日推荐（5分钟缓存，与前端轮询同步）
GET /api/recommend/tomorrow  明日预判（收盘后，8小时缓存）
POST /api/recommend/refresh  强制刷新
"""
import json
import re
import time
import akshare as ak
from datetime import date, datetime
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/recommend", tags=["推荐v3"])

_TODAY_CACHE    = {"data": [], "ts": 0.0, "date": "", "at": "", "themes": [], "sentiment": "中性", "news_latest": ""}
_TOMORROW_CACHE = {"data": [], "ts": 0.0, "date": "", "themes": [], "sentiment": "中性", "news_latest": ""}

# 重建并发锁：避免「页面刷新 + 定时器」同时触发两次 AI 调用
import threading as _threading
_TODAY_REBUILD_LOCK    = _threading.Lock()
_TOMORROW_REBUILD_LOCK = _threading.Lock()
_TODAY_TTL    = 300       # 5 分钟（与前端 refetchInterval 一致，文案"5分钟更新"名副其实）
_TOMORROW_TTL = 3600 * 8  # 8 小时

# 喂给 AI 的新闻条数上限；news_idx 回查发布时间时也以此为界
_AI_NEWS_LIMIT = 25


def _safe(v, d=0.0):
    try:
        f = float(v)
        return d if (f != f) else f
    except Exception:
        return d


def _fmt_news_time(pub: str) -> str:
    """
    从新闻 published 字段提取可读时间。
    今日的消息只显示 HH:MM；非今日则显示 MM-DD HH:MM；解析不出时间返回空串。
    """
    if not pub:
        return ""
    s = str(pub).strip()
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})[ T]+(\d{1,2}):(\d{2})", s)
    if m:
        y, mo, d, h, mi = m.groups()
        if f"{int(y):04d}-{int(mo):02d}-{int(d):02d}" == date.today().isoformat():
            return f"{int(h):02d}:{mi}"
        return f"{int(mo):02d}-{int(d):02d} {int(h):02d}:{mi}"
    m = re.search(r"(\d{1,2}):(\d{2})", s)   # 只有时间
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return ""


# ── 新闻采集 ─────────────────────────────────────────────────────────────────

def _fetch_recent_news(n: int = 30) -> list[dict]:
    """
    拉取最新财经快讯（带5分钟缓存）。
    返回字段：title, content/summary, published, source
    """
    try:
        from data.cn_news_fetcher import aggregate_cn_news
        items = aggregate_cn_news()
        # 取最新 n 条，只保留标题+摘要
        result = []
        for it in items[:n]:
            title   = str(it.get("title", "")).strip()
            summary = str(it.get("summary", it.get("content", ""))).strip()[:150]
            pub     = str(it.get("published", ""))
            source  = str(it.get("source", ""))
            if title:
                result.append({"title": title, "summary": summary,
                                "published": pub, "source": source})
        return result
    except Exception:
        return []


# ── DeepSeek 分析 ─────────────────────────────────────────────────────────────

_AI_SYSTEM = """你是A股专业投资分析师，擅长从财经新闻中识别对上市公司的催化剂。

分析原则：
- 只关注对具体A股上市公司有直接影响的消息（政策、业绩、行业变化、并购等）
- 优先识别"直接受益股"，而非泛泛受益
- 强催化剂：业绩大增/政策明确指向/重大合同/并购重组
- 中催化剂：行业利好/产品提价/新技术落地
- 弱催化剂：概念关注/模糊表述/海外消息间接影响

输出严格JSON，不加任何markdown，不加代码块：
{
  "stocks": [
    {
      "name": "上市公司简称（如：宁德时代）",
      "sector": "所属板块主题（如：储能/AI算力/消费）",
      "catalyst_type": "催化剂类型（政策利好/业绩利好/行业景气/资金关注/事件驱动）",
      "strength": "强/中/弱",
      "reason": "30字内说明为何看好该股",
      "news_ref": "触发该判断的新闻关键词（10字内）",
      "news_idx": 触发该判断的新闻在上方列表中的序号（整数，必须真实对应某一条，无法对应则填0）
    }
  ],
  "hot_themes": ["今日最热主题1", "主题2", "主题3"],
  "market_sentiment": "偏多/中性/偏空"
}"""

_AI_PROMPT_TODAY = """以下是今日最新财经快讯（按时间倒序，最新在前）：

{news_text}

请分析：
1. 哪些A股上市公司今日有明确利好催化剂（政策/业绩/行业/事件）？
2. 当前市场最热的3-5个主题是什么？
3. 整体市场情绪如何？

注意：
- 优先关注今日最新的消息，而非昨日旧闻
- 已经涨停的股票不需要推荐（我会过滤）
- 重点找「有催化剂但还没大涨」的股票
- 最多提取8只股票，宁少勿滥"""

_AI_PROMPT_TOMORROW = """以下是今日收盘前后的财经快讯：

{news_text}

请分析明日（下一个交易日）值得重点关注的股票：
1. 今日有催化剂但股价反应不充分的（涨幅<3%但消息很强）
2. 盘后发布的重大公告（业绩/并购/分红等）
3. 今日热点主题中的补涨龙头（今日未涨停但所属板块强势）

注意：
- 强调"明日可以布局"的逻辑，而不是今日追高
- 重点关注今日收盘后或盘中发布的最新消息
- 最多8只，宁少勿滥"""


def _loads_json_lenient(raw: str) -> dict:
    """
    从 LLM 输出里尽量解析出 JSON 对象。容忍：markdown 代码块包裹、
    JSON 前后多余的解释文字、以及结尾被 max_tokens 轻微截断的情况。
    解析不出来返回 {}，由调用方决定降级行为。
    """
    if not raw:
        return {}
    s = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    # 退一步：截取第一个 { 到最后一个 } 再试（去掉前后噪声/轻微截断）
    a, b = s.find("{"), s.rfind("}")
    if a != -1 and b > a:
        try:
            return json.loads(s[a:b + 1])
        except Exception:
            pass
    return {}


def _ai_extract_catalysts(news_items: list[dict], mode: str) -> dict:
    """
    调用 DeepSeek flash 分析新闻，提取股票催化剂。
    成本极低（每次约 0.002元）。
    """
    if not news_items:
        return {"stocks": [], "hot_themes": [], "market_sentiment": "中性"}

    # 格式化新闻（编号与 _build_recommendations 里 news_idx 回查保持一致）
    news_text = ""
    for i, it in enumerate(news_items[:_AI_NEWS_LIMIT], 1):
        t = it.get("title", "")
        s = it.get("summary", "")
        pub = it.get("published", "")[-8:] if it.get("published") else ""
        src = it.get("source", "")
        line = f"{i}. [{pub} {src}] {t}"
        if s and s != t and len(s) > 10:
            line += f"\n   摘要：{s[:80]}"
        news_text += line + "\n"

    prompt_tmpl = _AI_PROMPT_TODAY if mode == "today" else _AI_PROMPT_TOMORROW
    prompt = prompt_tmpl.format(news_text=news_text)

    try:
        from services.ai_client import make_client, CHAT_MODEL
        client = make_client()
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": _AI_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            # deepseek-v4-flash 是推理模型，思考过程(reasoning)先吃 token，
            # 4000 才够「推理 + JSON 答案」都写完；给小了会 finish_reason=length、
            # content 为空导致整个推荐被清空。
            max_tokens=4000,
            temperature=0.2,
        )
        choice = resp.choices[0]
        data = _loads_json_lenient(choice.message.content or "")
        if not data.get("stocks") and choice.finish_reason == "length":
            print("[recommend] AI输出被 max_tokens 截断（推理占满预算），本次无推荐")
        if "stocks" not in data:
            data = {"stocks": [], "hot_themes": [], "market_sentiment": "中性"}
        return data
    except Exception as e:
        print(f"[recommend] AI分析失败: {e}")
        return {"stocks": [], "hot_themes": [], "market_sentiment": "中性", "error": str(e)}


# ── 股票代码解析 ──────────────────────────────────────────────────────────────

def _names_to_codes(names: list[str]) -> dict[str, str]:
    """股票名称 → 6位代码（新浪搜索接口）"""
    try:
        from api.watchlist import _name_to_code
        return _name_to_code(names)
    except Exception:
        return {}


def _get_sina_hq(symbols: list[str]) -> dict:
    from api.watchlist import _fetch_sina_hq
    return _fetch_sina_hq(symbols)


# ── 辅助数据（快速，不依赖 baostock）────────────────────────────────────────

def _get_lhb_net_buy() -> dict[str, float]:
    """龙虎榜净买入 {symbol: net_亿}（有缓存则直接用）"""
    result: dict[str, float] = {}
    try:
        df = ak.stock_lhb_ggtj_sina(symbol="5")
        for _, r in df.iterrows():
            sym = str(r.get("股票代码", r.get("代码", ""))).strip().zfill(6)
            net = _safe(r.get("净额"))
            if len(sym) == 6 and sym != "000000" and net > 0:
                result[sym] = round(net / 1e8, 2)
    except Exception:
        pass
    return result


def _get_north_flow_signal() -> tuple[float, str]:
    """北向资金 (signal, 描述)"""
    try:
        sh = ak.stock_em_hsgt_north_net_flow_in_em(symbol="沪股通")
        sz = ak.stock_em_hsgt_north_net_flow_in_em(symbol="深股通")

        def _get(df):
            if df is None or df.empty: return 0.0
            row = df.iloc[-1]
            for col in df.columns:
                if "净" in str(col):
                    v = _safe(row[col])
                    return v / 1e8 if abs(v) > 1e6 else v
            return 0.0

        net = _get(sh) + _get(sz)
        if net > 30:   return 1.0,  f"北向今日大幅净流入 {net:.0f}亿"
        if net > 5:    return 0.5,  f"北向净流入 {net:.0f}亿"
        if net >= 0:   return 0.1,  f"北向小幅净流入"
        if net > -10:  return -0.2, f"北向小幅净流出 {abs(net):.0f}亿"
        return -0.6, f"北向今日净流出 {abs(net):.0f}亿，情绪偏空"
    except Exception:
        return 0.0, ""


def _get_hot_sectors_map() -> dict[str, float]:
    """热门概念板块 {name: pct_num}"""
    try:
        from api.sector import _cache as sc, _fetch_sina_concepts
        if not sc["data"] or time.time() - sc["ts"] > 120:
            sc["data"] = _fetch_sina_concepts()
            sc["ts"] = time.time()
        return {c.get("name", ""): c.get("pct_num", 0) for c in sc["data"][:30]}
    except Exception:
        return {}


def _get_simple_technicals(symbol: str, price: float) -> dict:
    """
    极简技术面：不调 baostock，只用当日行情估算信号。
    返回 {signal: "强/中/弱", note: str}
    """
    pct = 0.0
    try:
        hq_map = _get_sina_hq([symbol])
        hq = hq_map.get(symbol, {})
        pct = hq.get("pct_change", 0)
    except Exception:
        pass

    # 简单规则
    if pct > 5:
        return {"signal": "弱", "note": f"今日已大涨{pct:.1f}%，追高需谨慎"}
    if 1 <= pct <= 5:
        return {"signal": "强", "note": f"今日上涨{pct:.1f}%，趋势向好"}
    if -1 < pct < 1:
        return {"signal": "中", "note": "今日横盘蓄力"}
    return {"signal": "弱", "note": f"今日回调{pct:.1f}%，等待止跌信号"}


# ── 脑库规则匹配（把用户私人交易规则套到候选股上）────────────────────────────

_RULE_MATCH_SYSTEM = """你是"私人交易规则匹配引擎"。给你一批今日候选股和用户自己沉淀的交易规则，
判断每只候选股命中了哪些规则，以及该规则对这只股是利好、利空还是应当规避。

判定方向：
- 利好：规则逻辑支持买入/看多这只股（如"半导体大厂涨价→买功率龙头"命中功率半导体股）
- 利空：规则提示该股短期有风险（减分，但不一定剔除）
- 规避：规则明确指向应当回避/剔除这类股（如"股东大比例减持→规避该股"）

宁缺勿滥，只输出确有逻辑关联的命中，不要硬凑。严格JSON，无markdown，无代码块：
{
  "hits": [
    {"name": "候选股名称（必须与给定列表完全一致）", "rule_idx": 规则编号(整数), "direction": "利好/利空/规避", "note": "12字内命中说明"}
  ]
}
没有任何命中则返回 {"hits": []}"""


def _apply_brain_rules(candidates: list[dict], hot_themes: list[str], sentiment: str) -> list[dict]:
    """
    用用户脑库里的交易规则给候选股加分/扣分/剔除，并写入 rule_hits 与 reasons。
    脑库为空或任何异常都安全跳过（绝不影响推荐主流程）。
    """
    if not candidates:
        return candidates
    try:
        from db import brain_db
        rules = brain_db.list_rules()  # 已按置信度降序
    except Exception:
        return candidates
    if not rules:
        return candidates

    rules = rules[:40]
    rules_text = "\n".join(
        f"{i}. [{r.get('category','')}] {r.get('rule','')}"
        for i, r in enumerate(rules, 1)
    )
    cand_text = "\n".join(
        f"- {c['name']}（板块:{c.get('sector','') or '未知'}｜催化:{c.get('catalyst_type','') or '未知'}｜今日{c.get('pct_change',0):+.1f}%）"
        for c in candidates
    )
    themes_text = "、".join(hot_themes) if hot_themes else "无"
    prompt = (
        f"今日热点主题：{themes_text}｜市场情绪：{sentiment}\n\n"
        f"## 候选股\n{cand_text}\n\n"
        f"## 我的交易规则\n{rules_text}\n\n"
        f"请判断每只候选股命中了哪些规则及方向。"
    )

    try:
        from services.ai_client import make_client, CHAT_MODEL
        client = make_client()
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": _RULE_MATCH_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            # 同样是推理模型：900 会被思考过程吃光，导致规则永远匹配不上（静默失效）
            max_tokens=3000,
            temperature=0.2,
        )
        choice = resp.choices[0]
        if choice.finish_reason == "length":
            print("[recommend] 脑库匹配输出被 max_tokens 截断，本次跳过规则")
        hits = _loads_json_lenient(choice.message.content or "").get("hits", [])
    except Exception as e:
        print(f"[recommend] 脑库匹配失败: {e}")
        return candidates

    by_name = {c["name"]: c for c in candidates}
    vetoed: set[str] = set()
    for c in candidates:        # 统一契约：每只候选都带 rule_hits 键（无命中则空列表）
        c.setdefault("rule_hits", [])

    for h in hits:
        name = h.get("name", "")
        idx  = h.get("rule_idx", 0)
        direction = h.get("direction", "")
        note = (h.get("note", "") or "").strip()
        c = by_name.get(name)
        if not c or not isinstance(idx, int) or not (1 <= idx <= len(rules)):
            continue
        rule = rules[idx - 1]
        conf = float(rule.get("confidence", 0.6))
        rtext = rule.get("rule", "")

        if direction == "利好":
            bonus = round(conf * 12, 1)
            c["score"] = min(98, c["score"] + bonus)
            c["rule_hits"].append({"direction": "利好", "note": note, "rule": rtext, "confidence": round(conf, 2)})
            c["reasons"].insert(0, f"🧠 命中规则·{note or rtext[:16]}（+{bonus:.0f}）")
        elif direction == "规避":
            if conf >= 0.55:
                vetoed.add(name)
                c["rule_hits"].append({"direction": "规避", "note": note, "rule": rtext, "confidence": round(conf, 2)})
            else:
                pen = round(conf * 15, 1)
                c["score"] = max(5, c["score"] - pen)
                c["rule_hits"].append({"direction": "利空", "note": note, "rule": rtext, "confidence": round(conf, 2)})
                c["reasons"].insert(0, f"🧠 规则警示·{note or rtext[:16]}（-{pen:.0f}）")
        else:  # 利空
            pen = round(conf * 15, 1)
            c["score"] = max(5, c["score"] - pen)
            c["rule_hits"].append({"direction": "利空", "note": note, "rule": rtext, "confidence": round(conf, 2)})
            c["reasons"].insert(0, f"🧠 规则警示·{note or rtext[:16]}（-{pen:.0f}）")

        c["reasons"] = c["reasons"][:6]

    if vetoed:
        print(f"[recommend] 脑库规则剔除: {vetoed}")

    return [c for c in candidates if c["name"] not in vetoed]


# ── 主推荐流程 ────────────────────────────────────────────────────────────────

def _build_recommendations(mode: str) -> tuple[list[dict], list[str], str, str]:
    """
    构建推荐列表，返回 (stocks, hot_themes, market_sentiment, news_latest)
    news_latest = 本次所用最新一条新闻的发布时间（消息面截止时间）
    """
    # ① 获取新闻
    news_items = _fetch_recent_news(n=30)
    # 消息面截止时间 = 最新一条新闻的发布时间（news_items 已按时间倒序）
    news_latest = _fmt_news_time(news_items[0].get("published", "")) if news_items else ""

    # ② AI 分析催化剂（核心驱动）
    ai_result = _ai_extract_catalysts(news_items, mode)
    ai_stocks  = ai_result.get("stocks") or []
    hot_themes = ai_result.get("hot_themes") or []
    sentiment  = ai_result.get("market_sentiment") or "中性"   # 兜住 None/空串（LLM 偶发返回 null）

    if not ai_stocks:
        return [], hot_themes, sentiment, news_latest

    # ③ 解析股票代码
    names    = [s["name"] for s in ai_stocks]
    code_map = _names_to_codes(names)

    # ④ 获取辅助数据（并行会更好，这里串行保持简单）
    import threading
    lhb_data: dict[str, float] = {}
    north_data: tuple[float, str] = (0.0, "")
    sectors_data: dict[str, float] = {}

    def _fetch_lhb():
        nonlocal lhb_data
        lhb_data = _get_lhb_net_buy()

    def _fetch_north():
        nonlocal north_data
        north_data = _get_north_flow_signal()

    def _fetch_sectors():
        nonlocal sectors_data
        sectors_data = _get_hot_sectors_map()

    threads = [
        threading.Thread(target=_fetch_lhb, daemon=True),
        threading.Thread(target=_fetch_north, daemon=True),
        threading.Thread(target=_fetch_sectors, daemon=True),
    ]
    for t in threads: t.start()
    for t in threads: t.join(timeout=8)

    north_signal, north_note = north_data

    # ⑤ 批量获取行情
    valid_codes = [c for c in code_map.values() if c and len(c) == 6]
    hq_map = _get_sina_hq(valid_codes) if valid_codes else {}

    # ⑥ 组装结果
    results: list[dict] = []
    seen_syms: set[str] = set()

    for ai_stock in ai_stocks:
        name     = ai_stock.get("name", "")
        sym      = code_map.get(name, "")
        if not sym or sym in seen_syms:
            continue
        seen_syms.add(sym)

        hq = hq_map.get(sym)
        if not hq or hq.get("not_found") or hq.get("price", 0) <= 0:
            continue

        pct   = hq.get("pct_change", 0)
        price = hq.get("price", 0)

        # 基本过滤
        if mode == "today":
            if pct >= 9.5:  continue   # 已涨停，不追
            if pct < -3:    continue   # 今日大跌，避开
        else:
            if pct >= 9.5:  continue   # 明日有开板风险
            if pct < -4:    continue   # 今日大跌趋势不好

        # ⑦ 评分（新闻AI强度 + 辅助加成）
        strength = ai_stock.get("strength", "弱")
        base_score = {"强": 65, "中": 45, "弱": 28}.get(strength, 30)

        # 加成项
        bonus_tags: list[str] = []

        # 龙虎榜
        lhb_amt = lhb_data.get(sym, 0)
        if lhb_amt > 0:
            base_score += min(12, lhb_amt * 4)
            bonus_tags.append(f"🐉 龙虎榜净买入{lhb_amt:.1f}亿")

        # 北向
        if north_signal > 0.3:
            base_score += 6
            if north_note:
                bonus_tags.append(f"📡 {north_note}")

        # 板块热度
        sector = ai_stock.get("sector", "")
        sec_pct = sectors_data.get(sector, 0)
        if sec_pct > 1:
            base_score += min(8, sec_pct * 2)
            bonus_tags.append(f"🔥 {sector}板块今日涨{sec_pct:.1f}%")

        # 今日涨幅加成（适度上涨最好，已大涨扣分）
        if 1 <= pct < 5:
            base_score += 5
        elif pct >= 5:
            base_score -= 5

        score = min(98, round(base_score, 1))

        # ⑧ 入场策略
        strategy = _entry_strategy(mode, pct, price, strength)

        # 拼装理由（AI 原因 + 加成标签）
        ai_reason = ai_stock.get("reason", "")
        news_ref  = ai_stock.get("news_ref", "")
        # 用 AI 给的 news_idx 回查这条触发新闻的真实发布时间
        news_idx  = ai_stock.get("news_idx", 0)
        news_time = ""
        if isinstance(news_idx, int) and 1 <= news_idx <= min(_AI_NEWS_LIMIT, len(news_items)):
            news_time = _fmt_news_time(news_items[news_idx - 1].get("published", ""))
        reasons: list[str] = []
        if ai_reason:
            reasons.append(f"📰 {ai_reason}")
        if news_ref:
            reasons.append(f"触发新闻：{news_ref}" + (f"（{news_time}）" if news_time else ""))
        reasons.extend(bonus_tags)
        # 今日价格行情
        if pct >= 9.5:
            reasons.append(f"⚠️ 今日已涨停，等开板机会")
        elif pct >= 5:
            reasons.append(f"⚠️ 今日已大涨{pct:.1f}%，追高风险")
        elif 1 <= pct < 5:
            reasons.append(f"✅ 今日上涨{pct:.1f}%，强势未过热")
        elif -0.5 < pct < 1:
            reasons.append(f"今日横盘({pct:+.1f}%)，等待方向选择")
        else:
            reasons.append(f"⚠️ 今日回调{pct:.1f}%，需确认止跌")

        results.append({
            "symbol":        sym,
            "name":          name,
            "price":         round(price, 2),
            "pct_change":    round(pct, 2),
            "score":         score,
            "max_score":     100,
            "catalyst_type": ai_stock.get("catalyst_type", ""),
            "strength":      strength,
            "reasons":       reasons[:5],
            "strategy":      strategy,
            "sector":        sector,
            "news_time":     news_time,
            "lhb_amt":       lhb_amt,
            "north_signal":  north_signal,
            "tags": _build_tags(ai_stock, lhb_amt, north_signal, sec_pct),
        })

    results = _apply_brain_rules(results, hot_themes, sentiment)
    results.sort(key=lambda x: -x["score"])
    final = results[:8]

    # 落库：每次真正重算都把当批推荐快照存入历史（缓存命中不会走到这里，所以不会重复刷）
    try:
        from db import recommend_db
        recommend_db.save_batch(date.today().isoformat(), mode, final)
    except Exception as e:
        print(f"[recommend] 历史记录保存失败: {e}")

    return final, hot_themes, sentiment, news_latest


def _build_tags(ai_stock: dict, lhb_amt: float, north_signal: float, sec_pct: float) -> list[str]:
    """生成显示标签"""
    tags = []
    cat = ai_stock.get("catalyst_type", "")
    if cat:
        tags.append(cat)
    if lhb_amt > 0:
        tags.append("龙虎榜净买入")
    if north_signal > 0.3:
        tags.append("北向流入")
    if sec_pct > 1:
        tags.append(f"{ai_stock.get('sector','')}领涨" if ai_stock.get("sector") else "板块领涨")
    return tags[:3]


def _entry_strategy(mode: str, pct: float, price: float, strength: str) -> str:
    """生成一句话入场策略"""
    if mode == "today":
        if pct >= 7:
            return "今日已大涨，如消息持续发酵可等回调至日内均价附近轻仓介入，严格止损"
        if 2 <= pct < 5:
            return "当前为较佳入场窗口，可标准仓位入场，以今日最低价为止损参考"
        if 0 <= pct < 2:
            return "横盘蓄力，若盘中放量突破当日高点可跟进，止损设今日低点"
        return "今日偏弱，建议等待股价企稳回升信号再入场，不要抄底"
    else:
        if pct >= 5:
            return "今日大涨，明日若高开>3%可先观望，低开后快速拉升是较好入场机会"
        if 1 <= pct < 5:
            return "今日收涨，明日可在集合竞价阶段观察，若以昨收±1%开盘可正常入场"
        if -1 < pct < 1:
            return "今日横盘，明日关注是否放量突破，突破则跟进，量能不足则继续观望"
        return "今日偏弱，明日需确认止跌信号（如低开后快速翻红）再考虑入场"


# ── API 路由 ──────────────────────────────────────────────────────────────────

def warm_today_cache(force: bool = False) -> bool:
    """
    后台预热「今日推荐」缓存。
    - 启动补跑 / 定时器 / stale-while-revalidate 全部走这里
    - 锁 + force=False 时若缓存仍新则跳过，避免并发重复跑 AI
    返回 True=已重建，False=跳过
    """
    now = time.time()
    today = date.today().isoformat()
    if not force and _TODAY_CACHE["date"] == today and now - _TODAY_CACHE["ts"] < _TODAY_TTL:
        return False
    if not _TODAY_REBUILD_LOCK.acquire(blocking=False):
        return False
    try:
        stocks, themes, sentiment, news_latest = _build_recommendations("today")
        _TODAY_CACHE.update({
            "data": stocks, "themes": themes, "ts": time.time(),
            "date": today, "at": datetime.now().strftime("%H:%M:%S"),
            "sentiment": sentiment, "news_latest": news_latest,
        })
        return True
    except Exception as e:
        print(f"[recommend] 今日缓存重建失败: {e}")
        return False
    finally:
        _TODAY_REBUILD_LOCK.release()


def warm_tomorrow_cache(force: bool = False) -> bool:
    """后台预热「明日预判」缓存，与 warm_today_cache 同口径。"""
    now = time.time()
    today = date.today().isoformat()
    if not force and _TOMORROW_CACHE["date"] == today and now - _TOMORROW_CACHE["ts"] < _TOMORROW_TTL:
        return False
    if not _TOMORROW_REBUILD_LOCK.acquire(blocking=False):
        return False
    try:
        stocks, themes, sentiment, news_latest = _build_recommendations("tomorrow")
        _TOMORROW_CACHE.update({
            "data": stocks, "themes": themes, "ts": time.time(),
            "date": today, "sentiment": sentiment, "news_latest": news_latest,
        })
        return True
    except Exception as e:
        print(f"[recommend] 明日缓存重建失败: {e}")
        return False
    finally:
        _TOMORROW_REBUILD_LOCK.release()


@router.get("/today")
def get_today_recommend():
    """
    今日推荐 —— stale-while-revalidate：
      · 有缓存（即使过期）→ 立即返回旧数据（cached=true / stale 标志）
                            + 后台异步重建（不阻塞响应）
      · 无任何缓存 → 同步生成（首次冷启动；正常情况启动补跑会提前填好）
    """
    now   = time.time()
    today = date.today().isoformat()
    has_cache = _TODAY_CACHE["data"] and _TODAY_CACHE["date"] == today
    is_fresh  = has_cache and now - _TODAY_CACHE["ts"] < _TODAY_TTL

    # 有当日缓存（无论是否过期）→ 立即返回；若过期则后台异步刷新
    if has_cache:
        if not is_fresh:
            _threading.Thread(target=warm_today_cache, daemon=True,
                              name="recommend-today-revalidate").start()
        return JSONResponse({
            "stocks":     _TODAY_CACHE["data"],
            "hot_themes": _TODAY_CACHE["themes"],
            "market_sentiment": _TODAY_CACHE.get("sentiment", "中性"),
            "updated_at": _TODAY_CACHE["at"],
            "news_latest": _TODAY_CACHE.get("news_latest", ""),
            "date":       today,
            "cached":     True,
            "stale":      not is_fresh,
        })

    # 冷启动：无缓存（启动补跑还没跑完或失败）→ 同步生成
    stocks, themes, sentiment, news_latest = _build_recommendations("today")
    at = datetime.now().strftime("%H:%M:%S")
    _TODAY_CACHE.update({
        "data": stocks, "themes": themes, "ts": time.time(),
        "date": today, "at": at, "sentiment": sentiment, "news_latest": news_latest
    })
    return JSONResponse({
        "stocks": stocks, "hot_themes": themes,
        "market_sentiment": sentiment,
        "updated_at": at, "news_latest": news_latest,
        "date": today, "cached": False,
    })


@router.get("/tomorrow")
def get_tomorrow_recommend():
    """明日预判（stale-while-revalidate，与 today 同口径；8h TTL）"""
    now   = time.time()
    today = date.today().isoformat()
    has_cache = _TOMORROW_CACHE["data"] and _TOMORROW_CACHE["date"] == today
    is_fresh  = has_cache and now - _TOMORROW_CACHE["ts"] < _TOMORROW_TTL

    if has_cache:
        if not is_fresh:
            _threading.Thread(target=warm_tomorrow_cache, daemon=True,
                              name="recommend-tomorrow-revalidate").start()
        return JSONResponse({
            "stocks":     _TOMORROW_CACHE["data"],
            "hot_themes": _TOMORROW_CACHE["themes"],
            "market_sentiment": _TOMORROW_CACHE.get("sentiment", "中性"),
            "news_latest": _TOMORROW_CACHE.get("news_latest", ""),
            "date":       today,
            "cached":     True,
            "stale":      not is_fresh,
        })

    stocks, themes, sentiment, news_latest = _build_recommendations("tomorrow")
    _TOMORROW_CACHE.update({
        "data": stocks, "themes": themes, "ts": time.time(), "date": today,
        "sentiment": sentiment, "news_latest": news_latest
    })
    return JSONResponse({
        "stocks": stocks, "hot_themes": themes,
        "market_sentiment": sentiment,
        "news_latest": news_latest,
        "date": today, "cached": False,
    })


@router.post("/refresh")
def force_refresh():
    """强制清缓存重新生成"""
    _TODAY_CACHE["ts"] = 0
    _TOMORROW_CACHE["ts"] = 0
    return get_today_recommend()


@router.get("/history")
def get_recommend_history(symbol: str = "", mode: str = "", days: int = 30):
    """
    推荐历史：回看过去推荐过哪些股、当时的推荐逻辑。
    symbol: 按股票名/代码模糊搜索（如"中远海控"或"601919"）
    mode:   today / tomorrow，留空则两者都返回
    days:   最近多少天，默认30
    """
    from db import recommend_db
    rows = recommend_db.list_history(symbol=symbol.strip(), mode=mode.strip(), days=days)
    return {
        "history": rows,
        "count": len(rows),
        "dates": recommend_db.list_dates(),
        "stats": recommend_db.stats(),
    }
