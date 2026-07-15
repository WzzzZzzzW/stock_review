"""
持仓管理 + 候选池
GET  /api/portfolio                   持仓列表（含实时行情）
POST /api/portfolio                   新增/更新持仓
DELETE /api/portfolio/{symbol}        删除持仓
GET  /api/portfolio/candidates        候选池列表
POST /api/portfolio/candidates        加入候选池
DELETE /api/portfolio/candidates/{symbol}  移出候选池
POST /api/portfolio/parse-screenshot  截图识别持仓（PaddleOCR）
POST /api/portfolio/batch             批量导入持仓
"""
import base64
import json
import math
import re
import threading
import uuid
import requests
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/portfolio", tags=["持仓"])

_STORE_PATH = Path(__file__).parent.parent / "data" / "portfolio.json"

# ── OCR API 配置 ──────────────────────────────────────────────────────────────
_OCR_API_URL = "https://8e5ff1q6gbiaf5i0.aistudio-app.com/layout-parsing"
_OCR_TOKEN   = "0c245f042b17cb6b1573a45e477361c074f88d0e"

# 非股票关键词：表头、汇总行、App 功能词等
_SKIP_WORDS = {
    # 列标题
    '股票', '市值', '持仓', '可用', '现价', '成本', '盈亏', '收益',
    '涨跌', '仓位', '操作', '证券', '名称', '代码', '数量', '价格',
    '买入', '卖出', '账户', '资产', '浮动', '今日', '比例', '均价',
    '标的', '持有', '合计', '总计', '委托', '成交', '分时', '批量',
    # 东方财富 App 特有词
    '加仓', '理财', '昨日', '普通', '信用', '期权', '模拟', '期货',
    '港股通', '超级', '天天宝', '当日', '可取', '总资产', '可用余额',
    '参考', '理财资产', '升级', '完成', '快取', '额度', '共有',
    # 汇总字段
    '持仓盈亏', '当日盈亏', '证券市值', '总资产', '参考市值',
}

# 东方财富持仓表格的结束标志（注意：委托成交是顶部Tab，不在此处）
_TABLE_END_MARKERS = {'批量加仓', '批量卖出', '共有', '条持仓', '暂无持仓'}


def _load_store() -> dict:
    if _STORE_PATH.exists():
        try:
            return json.loads(_STORE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"positions": [], "candidates": []}


def _save_store(store: dict):
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe(v, default=0.0) -> float:
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return default


def _fetch_quotes(symbols: list[str]) -> dict:
    if not symbols:
        return {}
    from api.watchlist import _fetch_sina_hq
    return _fetch_sina_hq(symbols)


# ── OCR 解析辅助 ──────────────────────────────────────────────────────────────

def _is_valid_stock_name(name: str) -> bool:
    """验证是否是合法的股票名称（2-5个汉字，不含表头/汇总关键词）"""
    if not (2 <= len(name) <= 5):
        return False
    # 不能整体等于跳过词
    if name in _SKIP_WORDS:
        return False
    # 不能包含功能性词语
    for skip in _SKIP_WORDS:
        if len(skip) >= 2 and skip in name:
            return False
    return True


def _is_stock_price(v: float) -> bool:
    """A 股有效价格范围：0.5 ~ 3000 元"""
    return 0.5 <= v <= 3000.0


def _is_qty(v: float) -> bool:
    """
    有效持股数量：正整数，1 ~ 500000。
    ⚠️ 不强制「100 的整数倍」——A股买入虽以 100 股(1手)为单位，但送转股、
    部分卖出后会留下零股（如 140、333 股）。旧规则 %100==0 会把这类持仓
    整条漏掉（典型：泛微网络 140 股被丢弃）。
    """
    return v == int(v) and 1 <= v <= 500_000


def _pick_qty(nums: list[float]) -> int:
    """
    从一组数字里挑出「持股数量」。
    东方财富持仓行里 持仓==可用，数量通常出现两次；而市值/盈亏一般只出现一次。
    放开零股后，整数型的市值(如 3939.00)也会混进候选，于是按
    「出现次数多优先、出现位置靠前优先(持仓列在前)」来挑，稳妥避开市值。
    返回 0 表示这一组没有有效数量（如已清仓的 0 股行）。
    """
    int_cands = [int(n) for n in nums if _is_qty(n)]
    if not int_cands:
        return 0
    counts: dict[int, int] = {}
    first_pos: dict[int, int] = {}
    for idx, v in enumerate(int_cands):
        counts[v] = counts.get(v, 0) + 1
        first_pos.setdefault(v, idx)
    return min(set(int_cands), key=lambda v: (-counts[v], first_pos[v]))


def _extract_nums(text: str) -> list[float]:
    """从文本中提取数字，先去掉百分比，再提取浮点/整数"""
    pct_re = re.compile(r'[-+]?\d+\.?\d*%')
    num_re = re.compile(r'[-+]?\d+\.?\d*')
    clean = pct_re.sub(' ', text)
    result = []
    for s in num_re.findall(clean):
        try:
            result.append(float(s))
        except ValueError:
            pass
    return result


def _best_price_pair(nums: list[float], qty: int) -> tuple[float, float]:
    """
    从数字列表中找出【现价, 成本价】对。
    规则：
    - 排除 qty、market_val (>3000)、盈亏金额（绝对值 > qty * 最高合理价）
    - 找差值比例 < 50% 且最接近的两个数
    - 若只有一个，则现价=成本价=同一个
    """
    # 排除：qty本身、>3000（市值）、负数
    candidates = [n for n in nums
                  if n != qty and 0.5 <= n <= 3000 and n != int(n)]
    # 整数但不是qty且<100的也可能是价格（低价股）
    candidates += [n for n in nums
                   if n != qty and 0.5 <= n < 100 and n == int(n) and n not in candidates]
    # 去重并保序
    seen_c: set = set()
    uniq = []
    for n in candidates:
        if n not in seen_c:
            seen_c.add(n)
            uniq.append(n)
    candidates = uniq

    if not candidates:
        return (0.0, 0.0)
    if len(candidates) == 1:
        return (candidates[0], candidates[0])

    # 找差值比例最小的两个（现价和成本价应该接近）
    best_pair = (candidates[0], candidates[1])
    best_diff = float('inf')
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            a, b = candidates[i], candidates[j]
            ratio = abs(a - b) / max(a, b)
            if ratio < best_diff:
                best_diff = ratio
                best_pair = (a, b)

    # 第一个出现的通常是现价（东方财富按现价/成本顺序显示）
    a, b = best_pair
    idx_a = next((k for k, v in enumerate(candidates) if v == a), 0)
    idx_b = next((k for k, v in enumerate(candidates) if v == b), 1)
    if idx_a <= idx_b:
        return (a, b)   # a=现价, b=成本
    return (b, a)


def _parse_brokerage_markdown(md: str) -> list[dict]:
    """
    从 PaddleOCR 返回的 Markdown 文本解析持仓数据。

    支持三种 OCR 格式：
    A. 横向两行（东方财富常见）:
       行1: 股票名  持仓量  现价   盈亏金额
       行2: 市值    可用量  成本价  盈亏%
    B. 竖向（每字段独占一行）:
       泛微网络 / 200 / 200 / 9380.00 / 46.900 / 44.545 / ...
    C. Markdown 表格（| 分隔）
    """
    zh_re = re.compile(r'[一-鿿]{2,5}')

    lines = [l.strip() for l in md.splitlines() if l.strip()]
    results: list[dict] = []
    seen: set[str] = set()

    # ── Step 1：定位持仓表格区域 ─────────────────────────────────────────────
    # 找表头（含≥3个持仓关键字）
    table_start = -1
    table_end   = len(lines)

    for i, line in enumerate(lines):
        flat = line.replace(' ', '').replace('|', '').replace('/', '')
        kw_hits = sum(1 for kw in ('股票', '持仓', '现价', '成本', '可用') if kw in flat)
        if kw_hits >= 3 and table_start < 0:
            table_start = i + 1

    if table_start > 0:
        for i in range(table_start, len(lines)):
            flat = lines[i].replace(' ', '')
            if any(marker in flat for marker in _TABLE_END_MARKERS):
                table_end = i
                break

    # 表格区域行（若未找到表头则用全部行）
    scope = lines[table_start:table_end] if table_start >= 0 else lines

    # ── Step 2A：Markdown 表格格式（| 分隔）───────────────────────────────────
    pipe_lines = [l for l in scope if '|' in l and not re.match(r'^\|[\s\-:|]+\|', l)]
    if len(pipe_lines) >= 2:
        for row in pipe_lines:
            cols = [c.strip() for c in row.split('|') if c.strip()]
            # 找含中文名的列
            name = ""
            for c in cols:
                m = zh_re.search(c)
                if m and _is_valid_stock_name(m.group()):
                    name = m.group()
                    break
            if not name or name in seen:
                continue

            # 收集所有列的数字
            all_nums = _extract_nums(" ".join(cols))
            qty = _pick_qty(all_nums)
            if qty <= 0:
                continue
            cur, cost = _best_price_pair(all_nums, qty)
            if cur > 0 or cost > 0:
                seen.add(name)
                results.append({"name": name, "symbol": "", "quantity": qty,
                                 "current_price": round(cur, 4), "cost_price": round(cost, 4)})

    # ── Step 2B：竖向 / 两行混合格式 ─────────────────────────────────────────
    # 按名称分组：遇到下一个有效中文名则开始新组
    if not results:
        groups: list[tuple[str, list[float]]] = []   # [(name, [nums...])]
        current_name = ""
        current_nums: list[float] = []

        for line in scope:
            m = zh_re.search(line)
            if m and _is_valid_stock_name(m.group()) and m.group() not in seen:
                # 保存上一组
                if current_name:
                    groups.append((current_name, current_nums))
                current_name = m.group()
                current_nums = _extract_nums(line)   # 同一行可能也有数字
            elif current_name:
                # 纯数字行 / 混合行：累积到当前组
                current_nums.extend(_extract_nums(line))

        if current_name:
            groups.append((current_name, current_nums))

        for name, nums in groups:
            if name in seen:
                continue
            qty = _pick_qty(nums)
            if qty <= 0:
                continue
            cur, cost = _best_price_pair(nums, qty)
            if cur > 0 or cost > 0:
                seen.add(name)
                results.append({"name": name, "symbol": "", "quantity": qty,
                                 "current_price": round(cur, 4), "cost_price": round(cost, 4)})

    # ── Step 3：兜底全文扫描（表格未定位时）──────────────────────────────────
    if not results:
        for i, line in enumerate(lines):
            m = zh_re.search(line)
            if not m:
                continue
            name = m.group()
            if not _is_valid_stock_name(name) or name in seen:
                continue
            # 扩大上下文窗口：本行 + 后续8行（覆盖竖向格式）
            ctx_nums = _extract_nums("\n".join(lines[i: i + 9]))
            qty = _pick_qty(ctx_nums)
            if qty <= 0:
                continue
            cur, cost = _best_price_pair(ctx_nums, qty)
            if cur > 0 or cost > 0:
                seen.add(name)
                results.append({"name": name, "symbol": "", "quantity": qty,
                                 "current_price": round(cur, 4), "cost_price": round(cost, 4)})

    return results


# ── Pydantic Models ───────────────────────────────────────────────────────────

class PositionIn(BaseModel):
    symbol: str
    name: str = ""
    buy_date: str           # YYYY-MM-DD
    buy_price: float        # 成本价
    quantity: float         # 持股数量（股）
    stop_loss: float = 0.0  # 止损价（0=不设）
    target_price: float = 0.0  # 目标价（0=不设）
    notes: str = ""

class CandidateIn(BaseModel):
    symbol: str
    name: str = ""
    reason: str = ""        # 关注理由
    target_entry: float = 0.0  # 目标入场价


# ── 持仓 ──────────────────────────────────────────────────────────────────────

def _enrich_position(p: dict, q: dict) -> dict:
    """用实时行情填充计算字段"""
    current   = _safe(q.get("price", 0))
    prev_close = _safe(q.get("prev_close", 0))
    pct       = _safe(q.get("pct_change", 0))

    cost_val  = p["buy_price"] * p["quantity"]
    curr_val  = current * p["quantity"] if current > 0 else cost_val
    pnl_amt   = curr_val - cost_val
    pnl_pct   = (pnl_amt / cost_val * 100) if cost_val > 0 else 0.0
    today_pnl = (current - prev_close) * p["quantity"] if prev_close > 0 and current > 0 else 0.0

    try:
        buy_dt       = date.fromisoformat(p["buy_date"])
        holding_days = (date.today() - buy_dt).days
    except Exception:
        holding_days = 0

    sl = _safe(p.get("stop_loss", 0))
    tp = _safe(p.get("target_price", 0))

    at_stop   = sl > 0 and current > 0 and current <= sl
    near_stop = sl > 0 and current > 0 and current <= sl * 1.05 and not at_stop
    at_target = tp > 0 and current > 0 and current >= tp

    # 止损/目标进度条百分比（基于成本价 → 止损/目标区间）
    stop_progress  = 0.0
    target_progress = 0.0
    if sl > 0 and p["buy_price"] > sl:
        stop_progress = max(0.0, min(1.0, (current - sl) / (p["buy_price"] - sl)))
    if tp > 0 and tp > p["buy_price"]:
        target_progress = max(0.0, min(1.0, (current - p["buy_price"]) / (tp - p["buy_price"])))

    return {
        **p,
        "name":            q.get("name") or p.get("name", p["symbol"]),
        "current_price":   round(current, 4),
        "pct_change":      round(pct, 2),
        "prev_close":      round(prev_close, 4),
        "cost_value":      round(cost_val, 2),
        "current_value":   round(curr_val, 2),
        "pnl_amount":      round(pnl_amt, 2),
        "pnl_pct":         round(pnl_pct, 2),
        "today_pnl":       round(today_pnl, 2),
        "holding_days":    holding_days,
        "at_stop_loss":    at_stop,
        "near_stop_loss":  near_stop,
        "at_target":       at_target,
        "stop_progress":   round(stop_progress, 4),
        "target_progress": round(target_progress, 4),
    }


@router.get("")
def get_positions():
    """获取所有持仓（含实时行情、技术结构和统一多维裁决）"""
    store     = _load_store()
    positions = store.get("positions", [])

    if not positions:
        return JSONResponse({
            "positions": [],
            "summary": _empty_summary(),
            "updated_at": datetime.now().strftime("%H:%M:%S"),
        })

    symbols = [p["symbol"] for p in positions]
    quotes  = _fetch_quotes(symbols)
    tech_map: dict[str, dict] = {}
    industry_map: dict[str, str] = {}
    sector_decisions: dict[str, dict] = {}
    market_pct = None
    try:
        from data.stock_data import fetch_quick_batch, get_industry_map
        tech_map = {
            str(row.get("symbol")): row
            for row in fetch_quick_batch(symbols)
            if row.get("symbol")
        }
        industry_map = get_industry_map(block=False)
        from api.industry import industry_summary
        sector_decisions = {
            row.get("name", ""): row.get("decision") or {}
            for row in industry_summary().get("industries", [])
        }
        from api.daily_report import _fetch_indices
        pcts = [i.get("pct") for i in _fetch_indices() if i.get("pct") is not None]
        market_pct = sum(pcts) / len(pcts) if pcts else None
    except Exception as e:
        print(f"[portfolio] 多维数据补充失败，将降低结论置信度: {e}")

    enriched        = []
    total_cost      = 0.0
    total_value     = 0.0
    total_today_pnl = 0.0
    alerts          = []

    for p in positions:
        sym = p["symbol"]
        q   = quotes.get(sym, {})
        ep  = _enrich_position(p, q)
        industry = industry_map.get(sym, "")
        ep["industry"] = industry
        ep["tech"] = tech_map.get(sym) or {}
        try:
            from services.verdict_service import compute_quick_decision
            ep["decision"] = compute_quick_decision(
                q,
                ep["tech"],
                {
                    "market_pct": market_pct,
                    "sector": industry,
                    "sector_decision": sector_decisions.get(industry) or {},
                    "stop_loss": p.get("stop_loss"),
                    "target_price": p.get("target_price"),
                },
                purpose="position",
            )
        except Exception as e:
            ep["decision_error"] = str(e)
        enriched.append(ep)

        total_cost      += ep["cost_value"]
        total_value     += ep["current_value"]
        total_today_pnl += ep["today_pnl"]

        if ep["at_stop_loss"]:
            alerts.append({"symbol": sym, "name": ep["name"], "type": "stop_loss",
                           "message": f"⚠️ {ep['name']} 已触及止损价 ¥{p.get('stop_loss')}"})
        elif ep["at_target"]:
            alerts.append({"symbol": sym, "name": ep["name"], "type": "target",
                           "message": f"🎯 {ep['name']} 已达目标价 ¥{p.get('target_price')}"})

    total_pnl = total_value - total_cost

    summary = {
        "total_cost":       round(total_cost, 2),
        "total_value":      round(total_value, 2),
        "total_pnl_amount": round(total_pnl, 2),
        "total_pnl_pct":    round(total_pnl / total_cost * 100 if total_cost > 0 else 0, 2),
        "today_pnl":        round(total_today_pnl, 2),
        "position_count":   len(enriched),
    }

    return JSONResponse({
        "positions":  enriched,
        "summary":    summary,
        "alerts":     alerts,
        "updated_at": datetime.now().strftime("%H:%M:%S"),
    })


@router.post("")
async def upsert_position(pos: PositionIn):
    """新增或更新持仓（同一symbol覆盖写入）"""
    store     = _load_store()
    positions = store.get("positions", [])

    existing = next((p for p in positions if p["symbol"] == pos.symbol), None)
    pos_dict = pos.model_dump()
    now_iso  = datetime.now().isoformat()

    if existing:
        pos_dict["created_at"] = existing.get("created_at", now_iso)
        positions[positions.index(existing)] = pos_dict
    else:
        pos_dict["created_at"] = now_iso
        positions.append(pos_dict)

    pos_dict["updated_at"] = now_iso
    store["positions"] = positions
    _save_store(store)
    return JSONResponse({"ok": True, "symbol": pos.symbol})


@router.delete("/{symbol}")
async def delete_position(symbol: str):
    """删除持仓"""
    store  = _load_store()
    before = len(store.get("positions", []))
    store["positions"] = [p for p in store.get("positions", []) if p["symbol"] != symbol]
    _save_store(store)
    return JSONResponse({"ok": True, "removed": before - len(store["positions"])})


# ── 今日操作记录（交易日志 + AI 评分） ──────────────────────────────────────────

# 写 store 时加锁，避免后台 AI 线程与主请求并发写覆盖
_store_lock = threading.Lock()


class TradeIn(BaseModel):
    symbol: str
    name: str = ""
    action: str             # buy / sell
    quantity: float         # 股数
    price: float            # 成交价
    reason: str = ""        # 操作理由
    trade_date: str = ""    # YYYY-MM-DD，空=今天
    update_position: bool = True   # 是否实时同步到持仓


def _apply_trade_to_positions(store: dict, trade: dict) -> dict:
    """
    把一笔成交应用到持仓上，返回 {position_before, position_after}。
    BUY：加权平均成本 + 增加股数（无则新建）。
    SELL：减少股数（清零则删除持仓），成本价不变。
    """
    positions = store.get("positions", [])
    sym = trade["symbol"]
    qty = float(trade["quantity"])
    price = float(trade["price"])
    now_iso = datetime.now().isoformat()

    existing = next((p for p in positions if p["symbol"] == sym), None)
    before = dict(existing) if existing else None

    if trade["action"] == "buy":
        if existing:
            old_qty = float(existing.get("quantity", 0))
            old_cost = float(existing.get("buy_price", 0))
            new_qty = old_qty + qty
            new_cost = ((old_qty * old_cost) + (qty * price)) / new_qty if new_qty > 0 else price
            existing["quantity"] = new_qty
            existing["buy_price"] = round(new_cost, 4)
            existing["updated_at"] = now_iso
        else:
            positions.append({
                "symbol": sym,
                "name": trade.get("name", ""),
                "buy_date": trade.get("trade_date") or date.today().isoformat(),
                "buy_price": round(price, 4),
                "quantity": qty,
                "stop_loss": 0.0,
                "target_price": 0.0,
                "notes": trade.get("reason", ""),
                "created_at": now_iso,
                "updated_at": now_iso,
            })
    else:  # sell
        if existing:
            new_qty = float(existing.get("quantity", 0)) - qty
            if new_qty <= 0:
                positions[:] = [p for p in positions if p["symbol"] != sym]
            else:
                existing["quantity"] = new_qty
                existing["updated_at"] = now_iso

    store["positions"] = positions
    after = next((dict(p) for p in positions if p["symbol"] == sym), None)
    return {"position_before": before, "position_after": after}


def _run_trade_ai(trade_id: str, trade: dict, context: dict):
    """后台线程：调用 AI 评分，写回 trade 记录的 ai_* 字段。"""
    from services.trade_journal_service import analyze_trade
    try:
        result = analyze_trade(trade, context)
        with _store_lock:
            store = _load_store()
            for t in store.get("trades", []):
                if t.get("id") == trade_id:
                    t["ai_status"] = "done"
                    t["ai"] = result
                    break
            _save_store(store)
    except Exception as e:
        with _store_lock:
            store = _load_store()
            for t in store.get("trades", []):
                if t.get("id") == trade_id:
                    t["ai_status"] = "error"
                    t["ai_error"] = str(e)
                    break
            _save_store(store)


@router.get("/trades")
async def get_trades(trade_date: str = ""):
    """操作记录列表。trade_date 传 YYYY-MM-DD 只看那天；空=今天。"""
    store = _load_store()
    trades = store.get("trades", [])
    day = trade_date or date.today().isoformat()
    today_trades = [t for t in trades if t.get("trade_date") == day]
    today_trades.sort(key=lambda t: t.get("at", ""), reverse=True)

    # 当日操作小结
    buy_amt = sum(t["price"] * t["quantity"] for t in today_trades if t.get("action") == "buy")
    sell_amt = sum(t["price"] * t["quantity"] for t in today_trades if t.get("action") == "sell")
    scored = [t["ai"]["score"] for t in today_trades if t.get("ai")]
    avg_score = round(sum(scored) / len(scored), 1) if scored else None

    return JSONResponse({
        "trades": today_trades,
        "date": day,
        "summary": {
            "count": len(today_trades),
            "buy_amount": round(buy_amt, 2),
            "sell_amount": round(sell_amt, 2),
            "avg_score": avg_score,
        },
    })


@router.post("/trades")
async def add_trade(body: TradeIn):
    """
    记录一笔操作。可选实时更新持仓，并后台触发 AI 评分。
    """
    if body.action not in ("buy", "sell"):
        return JSONResponse({"ok": False, "error": "action 必须是 buy 或 sell"}, status_code=400)
    if body.quantity <= 0 or body.price <= 0:
        return JSONResponse({"ok": False, "error": "数量和价格必须大于0"}, status_code=400)

    with _store_lock:
        store = _load_store()
        trades = store.get("trades", [])

        now = datetime.now()
        trade_id = uuid.uuid4().hex[:12]
        trade = {
            "id": trade_id,
            "symbol": body.symbol,
            "name": body.name,
            "action": body.action,
            "quantity": body.quantity,
            "price": body.price,
            "reason": body.reason,
            "trade_date": body.trade_date or date.today().isoformat(),
            "at": now.isoformat(),
            "ai_status": "processing",
            "ai": None,
        }

        # 实时同步到持仓
        context = {}
        if body.update_position:
            ctx = _apply_trade_to_positions(store, trade)
            trade["position_synced"] = True
            context.update(ctx)
        else:
            trade["position_synced"] = False

        trades.insert(0, trade)
        store["trades"] = trades
        _save_store(store)

    # 后台 AI 评分
    threading.Thread(
        target=_run_trade_ai, args=(trade_id, trade, context), daemon=True
    ).start()

    return JSONResponse({"ok": True, "trade": trade})


@router.post("/trades/{trade_id}/reanalyze")
async def reanalyze_trade(trade_id: str):
    """重新生成某笔操作的 AI 评分。"""
    with _store_lock:
        store = _load_store()
        trade = next((t for t in store.get("trades", []) if t.get("id") == trade_id), None)
        if not trade:
            return JSONResponse({"ok": False, "error": "未找到该操作记录"}, status_code=404)
        trade["ai_status"] = "processing"
        trade["ai"] = None
        trade.pop("ai_error", None)
        _save_store(store)

    threading.Thread(
        target=_run_trade_ai, args=(trade_id, dict(trade), {}), daemon=True
    ).start()
    return JSONResponse({"ok": True})


@router.delete("/trades/{trade_id}")
async def delete_trade(trade_id: str):
    """删除一条操作记录（不会回滚已同步的持仓）。"""
    with _store_lock:
        store = _load_store()
        before = len(store.get("trades", []))
        store["trades"] = [t for t in store.get("trades", []) if t.get("id") != trade_id]
        _save_store(store)
    return JSONResponse({"ok": True, "removed": before - len(store.get("trades", []))})


# ── 卖出指导：持仓逐只卖点诊断 ──────────────────────────────────────────────────

class SellGuidanceIn(BaseModel):
    symbols: list[str] = []   # 空 = 诊断全部持仓


def _diagnose_worker(symbols: list[str]):
    """后台线程：批量取技术面 + 脑库卖出规则，逐只让 AI 出卖点诊断。"""
    from data.stock_data import fetch_quick_batch
    from db import brain_db
    from services.sell_guidance_service import diagnose

    # 脑库卖出规则（全批共用，取一次）
    try:
        exit_rules = brain_db.list_rules(category="exit", limit=30)
    except Exception:
        exit_rules = []

    # 技术面（批量，按日缓存）
    try:
        tech_results = fetch_quick_batch(symbols)
        tech_map = {r.get("symbol"): r for r in tech_results}
    except Exception:
        tech_map = {}

    # 实时行情用于 enrich
    quotes = _fetch_quotes(symbols)

    for sym in symbols:
        try:
            store = _load_store()
            pos = next((p for p in store.get("positions", []) if p["symbol"] == sym), None)
            if not pos:
                _update_guidance(sym, "error", error="持仓中已无此股")
                continue
            enriched = _enrich_position(pos, quotes.get(sym, {}))
            result = diagnose(enriched, tech_map.get(sym, {}), exit_rules)
            _update_guidance(sym, "done", data=result, name=enriched.get("name", sym))
        except Exception as e:
            _update_guidance(sym, "error", error=str(e))


def _update_guidance(symbol: str, status: str, data: dict | None = None,
                     error: str = "", name: str = ""):
    with _store_lock:
        store = _load_store()
        g = store.setdefault("sell_guidance", {})
        entry = g.get(symbol, {})
        entry["status"] = status
        entry["at"] = datetime.now().isoformat()
        if name:
            entry["name"] = name
        if data is not None:
            entry["data"] = data
        entry["error"] = error
        g[symbol] = entry
        _save_store(store)


@router.get("/sell-guidance")
async def get_sell_guidance():
    """返回已存的卖点诊断（按 symbol）。"""
    store = _load_store()
    return JSONResponse({"guidance": store.get("sell_guidance", {})})


@router.post("/sell-guidance")
async def run_sell_guidance(body: SellGuidanceIn):
    """
    触发卖点诊断。symbols 为空则诊断全部当前持仓。
    立即返回（后台逐只生成），前端轮询 GET /sell-guidance 取结果。
    """
    store = _load_store()
    held = [p["symbol"] for p in store.get("positions", [])]
    symbols = [s for s in (body.symbols or held) if s in held]
    if not symbols:
        return JSONResponse({"ok": False, "error": "没有可诊断的持仓"}, status_code=400)

    # 标记处理中
    for sym in symbols:
        _update_guidance(sym, "processing")

    threading.Thread(target=_diagnose_worker, args=(symbols,), daemon=True).start()
    return JSONResponse({"ok": True, "symbols": symbols})


# ── 除权除息自动调整 ────────────────────────────────────────────────────────────

@router.get("/pending-adjustments")
async def pending_adjustments():
    """
    检测但不应用 —— 返回每个持仓待应用的除权除息事件清单，含调整后的预览数据。
    用户在前端确认后再调用 /apply-adjustments 应用。
    """
    from services.dividend_adjuster import pending_events_for_position, apply_event
    from copy import deepcopy

    store = _load_store()
    positions = store.get("positions", [])
    result = []
    for pos in positions:
        events = pending_events_for_position(pos)
        if not events:
            continue
        # 复制一份做模拟调整，预览结果
        preview = deepcopy(pos)
        event_details = []
        for e in events:
            detail = apply_event(preview, e)
            event_details.append({
                "ex_date": detail["ex_date"],
                "description": detail["description"],
                "qty_before": detail["qty_before"],
                "qty_after": detail["qty_after"],
                "cost_before": detail["cost_before"],
                "cost_after": detail["cost_after"],
                "cash_received": detail["cash_received"],
            })
        result.append({
            "symbol": pos.get("symbol", ""),
            "name": pos.get("name", ""),
            "buy_date": pos.get("buy_date", ""),
            "events": event_details,
            "final_qty": preview["quantity"],
            "final_cost": preview["buy_price"],
        })
    return JSONResponse({"pending": result, "total": sum(len(r["events"]) for r in result)})


class ApplyAdjustmentsIn(BaseModel):
    symbols: list[str]   # 只对这些股票应用调整（用户在前端勾选过的）


@router.post("/apply-adjustments")
async def apply_adjustments(body: ApplyAdjustmentsIn):
    """
    用户确认后应用除权除息调整。仅对 body.symbols 里的股票应用。
    """
    from services.dividend_adjuster import check_and_apply

    store = _load_store()
    all_positions = store.get("positions", [])
    targets = [p for p in all_positions if p.get("symbol") in body.symbols]
    if not targets:
        return JSONResponse({"applied": [], "message": "未找到指定持仓"})

    try:
        adjustments = check_and_apply(targets)
    except Exception as e:
        return JSONResponse({"applied": [], "error": str(e)}, status_code=500)

    _save_store(store)
    return JSONResponse({
        "applied": adjustments,
        "count": len(adjustments),
        "message": f"已应用 {len(adjustments)} 项调整" if adjustments else "无变化",
    })


@router.post("/skip-adjustments")
async def skip_adjustments(body: ApplyAdjustmentsIn):
    """
    用户在前端拒绝调整（如实际买入日不准导致）——
    把这些股票的 last_adjusted_date 标记为今天，避免下次再提示。
    """
    from datetime import date as _date
    store = _load_store()
    today_iso = _date.today().isoformat()
    affected = 0
    for pos in store.get("positions", []):
        if pos.get("symbol") in body.symbols:
            pos["last_adjusted_date"] = today_iso
            affected += 1
    _save_store(store)
    return JSONResponse({"skipped": affected, "message": f"已忽略 {affected} 项"})


# ── 候选池 ────────────────────────────────────────────────────────────────────

@router.get("/candidates")
async def get_candidates():
    """获取候选池（含实时行情）"""
    store      = _load_store()
    candidates = store.get("candidates", [])

    if not candidates:
        return JSONResponse({"candidates": [], "updated_at": datetime.now().strftime("%H:%M:%S")})

    symbols = [c["symbol"] for c in candidates]
    quotes  = _fetch_quotes(symbols)

    enriched = []
    for c in candidates:
        sym = c["symbol"]
        q   = quotes.get(sym, {})
        enriched.append({
            **c,
            "name":          q.get("name") or c.get("name", sym),
            "current_price": round(_safe(q.get("price", 0)), 4),
            "pct_change":    round(_safe(q.get("pct_change", 0)), 2),
        })

    return JSONResponse({"candidates": enriched, "updated_at": datetime.now().strftime("%H:%M:%S")})


@router.post("/candidates")
async def add_candidate(c: CandidateIn):
    """加入候选池"""
    store      = _load_store()
    candidates = store.get("candidates", [])

    existing = next((x for x in candidates if x["symbol"] == c.symbol), None)
    c_dict   = c.model_dump()
    c_dict["added_at"] = datetime.now().isoformat()[:10]

    if existing:
        candidates[candidates.index(existing)] = c_dict
    else:
        candidates.append(c_dict)

    store["candidates"] = candidates
    _save_store(store)
    return JSONResponse({"ok": True})


@router.delete("/candidates/{symbol}")
async def remove_candidate(symbol: str):
    """移出候选池"""
    store = _load_store()
    store["candidates"] = [c for c in store.get("candidates", []) if c["symbol"] != symbol]
    _save_store(store)
    return JSONResponse({"ok": True})


def _empty_summary() -> dict:
    return {
        "total_cost": 0, "total_value": 0,
        "total_pnl_amount": 0, "total_pnl_pct": 0,
        "today_pnl": 0, "position_count": 0,
    }


# ── 截图识别（PaddleOCR Layout Parsing API）──────────────────────────────────

@router.post("/parse-screenshot")
async def parse_screenshot(file: UploadFile = File(...)):
    """
    上传持仓截图（东方财富/同花顺/华泰等），
    用 PaddleOCR Layout API 识别文字，解析持仓信息，
    返回结构化数据供用户确认后批量导入。
    """
    img_bytes = await file.read()
    if len(img_bytes) > 20 * 1024 * 1024:
        return JSONResponse({"error": "图片太大，请压缩后上传（限制 20MB）"}, status_code=400)

    img_b64 = base64.standard_b64encode(img_bytes).decode("ascii")

    headers = {
        "Authorization": f"token {_OCR_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "file":                      img_b64,
        "fileType":                  1,       # 1 = 图片
        "useDocOrientationClassify": False,
        "useDocUnwarping":           False,
        "useChartRecognition":       False,
    }

    try:
        resp = requests.post(_OCR_API_URL, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        ocr_data = resp.json()
    except requests.RequestException as e:
        return JSONResponse({"error": f"OCR 请求失败：{str(e)}"}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": f"OCR 响应解析失败：{str(e)}"}, status_code=500)

    # 拼接所有 markdown 文本块
    layout_results = ocr_data.get("result", {}).get("layoutParsingResults", [])
    md_parts = []
    for block in layout_results:
        text = block.get("markdown", {}).get("text", "")
        if text:
            md_parts.append(text)
    full_md = "\n".join(md_parts)

    if not full_md.strip():
        return JSONResponse({"error": "OCR 未识别到文字，请确认图片清晰且为持仓截图"}, status_code=400)

    # 解析 markdown → 持仓列表
    positions = _parse_brokerage_markdown(full_md)

    if not positions:
        return JSONResponse({
            "error": "未能从截图中识别出持仓数据，请确认截图包含股票名称、数量和价格信息",
            "debug_md": full_md[:500],  # 调试用，返回部分 OCR 文本
        }, status_code=400)

    # ① 用名称查询股票代码
    names_no_sym = [p["name"] for p in positions if not p["symbol"]]
    if names_no_sym:
        try:
            from api.watchlist import _name_to_code
            name_map = _name_to_code(names_no_sym)
            for p in positions:
                if not p["symbol"] and p["name"] in name_map:
                    p["symbol"] = name_map[p["name"]]
        except Exception:
            pass

    # ② 拉取实时行情，用真实现价替换 OCR 识别的价格
    symbols_with_code = [p["symbol"] for p in positions if p["symbol"]]
    if symbols_with_code:
        try:
            quotes = _fetch_quotes(symbols_with_code)
            for p in positions:
                sym = p.get("symbol", "")
                if sym and sym in quotes:
                    q = quotes[sym]
                    realtime_price = _safe(q.get("price", 0))
                    if realtime_price > 0:
                        p["current_price"] = round(realtime_price, 4)
                    # 用行情中的股票名补充（若 OCR 有时识别名称不完整）
                    q_name = q.get("name", "")
                    if q_name:
                        p["name"] = q_name
        except Exception:
            pass  # 行情获取失败不影响主流程，前端展示 OCR 值

    return JSONResponse({
        "positions": positions,
        "count":     len(positions),
        "message":   f"识别到 {len(positions)} 支持仓（现价已更新为实时行情）",
        "debug_md":  full_md,   # 调试：OCR 原始文本，上线后可删除
    })


# ── 批量导入 ──────────────────────────────────────────────────────────────────

class BatchImportItem(BaseModel):
    symbol: str
    name: str = ""
    buy_date: str
    buy_price: float
    quantity: float
    stop_loss: float = 0.0
    target_price: float = 0.0
    notes: str = ""

class BatchImportIn(BaseModel):
    positions: list[BatchImportItem]

@router.post("/batch")
async def batch_import(data: BatchImportIn):
    """批量导入持仓（从截图识别确认后调用）"""
    store = _load_store()
    positions = store.get("positions", [])
    now_iso = datetime.now().isoformat()

    imported = 0
    for item in data.positions:
        pos_dict = item.model_dump()
        existing = next((p for p in positions if p["symbol"] == item.symbol), None)
        pos_dict["updated_at"] = now_iso
        if existing:
            pos_dict["created_at"] = existing.get("created_at", now_iso)
            positions[positions.index(existing)] = pos_dict
        else:
            pos_dict["created_at"] = now_iso
            positions.append(pos_dict)
        imported += 1

    store["positions"] = positions
    _save_store(store)
    return JSONResponse({"ok": True, "imported": imported})
