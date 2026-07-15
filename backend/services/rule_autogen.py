"""
每日推送规则自动生成 —— 读当日新闻 + 行业涨幅榜，让 AI 产出几条「可直接选股」的规则。

产出两类规则（与用户自建规则分区展示，source='auto'）：
  · kind='numeric' 策略规则：纯数值条件（情绪火热→强势小盘进攻 / 退潮→低估蓝筹防御…）
  · kind='theme'   题材规则：theme=某同花顺行业名，点开即看该题材成分股（叠加可选数值条件）

每天整批刷新（replace_auto_rules）：旧推送被清掉，用户想长期保留某条→点「保存为我的」转成 user 规则。
成本：每次 1 次 deepseek-flash 调用。
"""
import os
import json
import threading
from datetime import datetime

from services import screen_service
from db import screen_rule_db as db

_STATUS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "rule_autogen_status.json")

_lock = threading.Lock()
_status: dict = {"running": False, "progress": ""}


# ── 状态持久化 ─────────────────────────────────────────────────────────────────

def _load_last_run() -> dict | None:
    try:
        with open(_STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_last_run(payload: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_STATUS_FILE), exist_ok=True)
        with open(_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception:
        pass


def get_status() -> dict:
    last = _load_last_run()
    return {**_status, "last_run": last}


def generated_today() -> bool:
    last = _load_last_run()
    if not last or not last.get("ok"):
        return False
    return (last.get("at", "")[:10]) == datetime.now().strftime("%Y-%m-%d")


# ── 输入采集 ───────────────────────────────────────────────────────────────────

def _news_block(trade_date: str) -> str:
    try:
        from services.market_review_service import _fetch_news
        news = _fetch_news(trade_date, limit=12)
    except Exception:
        news = []
    if not news:
        return "（今日暂无要闻）"
    return "\n".join(f"- {n['title']}" for n in news if n.get("title"))[:1800]


def _industry_block() -> tuple[str, list[str]]:
    """返回 (供AI看的行业涨幅榜文本, 全部可用行业名列表)。"""
    names: list[str] = screen_service.list_themes()
    top_txt = "—"
    try:
        from api.industry import industry_summary
        data = industry_summary()
        inds = data.get("industries", []) if isinstance(data, dict) else []
        top = inds[:12]
        bottom = inds[-5:] if len(inds) > 12 else []
        parts = [f"{x['name']}{x['pct']}" for x in top]
        if bottom:
            parts.append("…领跌：" + " ".join(f"{x['name']}{x['pct']}" for x in bottom))
        top_txt = " ".join(parts) if parts else "—"
    except Exception:
        pass
    return top_txt, names


# ── AI 生成 ────────────────────────────────────────────────────────────────────

def _build_prompt(trade_date, news_txt, industry_txt, theme_names) -> str:
    fields_doc = screen_service._fields_doc()
    themes_doc = "、".join(theme_names) if theme_names else "（暂不可用）"
    return f"""你是 A 股盘后选股助手。根据今天（{trade_date}）的要闻和行业表现，生成 5~6 条「明天可直接用来选股」的规则。

【今日要闻】
{news_txt}

【今日行业涨跌幅榜】
{industry_txt}

请输出两类规则各 2~3 条：

A. 策略规则 kind="numeric"：纯数值条件，捕捉当下市场风格。可用字段：
{fields_doc}
运算符 op：gt(大于) gte(大于等于) lt(小于) lte(小于等于) between(区间,需value+value2) eq(等于)
数值用字段单位：市值/成交额用「亿」，涨跌幅/换手/振幅用「%」，股价用「元」。

B. 题材规则 kind="theme"：theme 必须从下面这份行业名单里「精确选一个」当下有新闻或资金催化的方向（不要自己造名字）：
{themes_doc}
题材规则可不带 conditions，或带少量数值条件（如排除太小市值）。

每条规则给：
- name：<=10字 简短名字
- why：一句话理由，点明依据（哪条新闻/哪个行业领涨/什么市场情绪）
- kind / 以及对应的 conditions(数值) 或 theme(行业名)
- logic：AND 或 OR（一般 AND）
- universe：可选排除项，按需设 true —— exclude_st(排除ST) exclude_688(排除科创板) exclude_300(排除创业板) exclude_bj(排除北交所)
- sort_field / sort_dir：结果排序字段(同上字段key)与方向(desc/asc)，默认 change_pct desc

只输出 JSON，不要任何解释、不要 markdown 代码块：
{{"rules":[
  {{"kind":"numeric","name":"强势小盘进攻","why":"今日赚钱效应高、题材活跃，资金偏好小盘","conditions":[{{"field":"market_cap","op":"lt","value":100}},{{"field":"turnover","op":"gt","value":8}},{{"field":"change_pct","op":"between","value":3,"value2":9}}],"logic":"AND","universe":{{"exclude_st":true}},"sort_field":"change_pct","sort_dir":"desc"}},
  {{"kind":"theme","name":"半导体跟踪","why":"国产替代消息催化，半导体板块领涨","theme":"半导体","conditions":[{{"field":"market_cap","op":"gt","value":50}}],"logic":"AND","universe":{{"exclude_st":true}},"sort_field":"change_pct","sort_dir":"desc"}}
]}}"""


def _validate_rules(raw_rules, theme_names) -> list[dict]:
    valid_names = set(theme_names or [])
    out: list[dict] = []
    for r in raw_rules or []:
        kind = "theme" if str(r.get("kind")) == "theme" else "numeric"
        name = (r.get("name") or "").strip()[:20]
        why = (r.get("why") or "").strip()[:120]
        if not name:
            continue
        # 数值条件清洗
        conds = []
        for c in r.get("conditions") or []:
            if c.get("field") in screen_service.FIELD_MAP and c.get("op") in screen_service._OP_KEYS:
                cc = {"field": c["field"], "op": c["op"], "value": c.get("value")}
                if c["op"] == "between":
                    cc["value2"] = c.get("value2")
                conds.append(cc)
        logic = "OR" if str(r.get("logic", "AND")).upper() == "OR" else "AND"
        uni_raw = r.get("universe") or {}
        universe = {k: True for k in screen_service._UNIVERSE_KEYS if uni_raw.get(k)}
        sort_field = r.get("sort_field") if r.get("sort_field") in screen_service.FIELD_MAP else "change_pct"
        sort_dir = "asc" if str(r.get("sort_dir", "desc")).lower() == "asc" else "desc"

        theme = ""
        if kind == "theme":
            t = (r.get("theme") or "").strip()
            if t in valid_names:
                theme = t
            else:                       # 模糊匹配：包含关系兜底
                cand = [n for n in valid_names if t and (t in n or n in t)]
                if cand:
                    theme = cand[0]
            if not theme:
                continue               # 题材对不上有效行业 → 丢弃，避免点开空结果

        out.append({
            "kind": kind, "name": name, "why": why,
            "conditions": conds, "logic": logic, "universe": universe,
            "theme": theme, "sort_field": sort_field, "sort_dir": sort_dir,
        })
    return out


def run_autogen() -> dict:
    """执行一次推送规则生成（整批替换）。线程安全。"""
    if not _lock.acquire(blocking=False):
        return {"ok": False, "message": "正在生成中，请稍候", **get_status()}
    try:
        _status.update(running=True, progress="采集今日新闻与行业表现...")
        trade_date = datetime.now().strftime("%Y-%m-%d")
        news_txt = _news_block(trade_date)
        industry_txt, theme_names = _industry_block()

        _status.update(progress="AI 生成推送规则中（约 1 分钟）...")
        from services.ai_client import make_client, CHAT_MODEL
        prompt = _build_prompt(trade_date, news_txt, industry_txt, theme_names)
        client = make_client()
        resp = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=2200,
            timeout=150,
        )
        data = screen_service._loads_json_lenient(resp.choices[0].message.content or "")
        rules = _validate_rules(data.get("rules", []), theme_names)

        if not rules:
            summary = {"ok": False, "at": datetime.now().isoformat(timespec="seconds"),
                       "count": 0, "message": "AI 未产出有效规则，请稍后重试"}
            _status.update(progress=summary["message"])
            _save_last_run(summary)
            return summary

        n = db.replace_auto_rules(rules, auto_date=trade_date)
        n_theme = sum(1 for r in rules if r["kind"] == "theme")
        summary = {
            "ok": True,
            "at": datetime.now().isoformat(timespec="seconds"),
            "count": n,
            "theme_count": n_theme,
            "numeric_count": n - n_theme,
            "message": f"已推送 {n} 条规则（策略 {n - n_theme} + 题材 {n_theme}）",
        }
        _status.update(progress=summary["message"])
        _save_last_run(summary)
        return summary
    except Exception as e:
        summary = {"ok": False, "at": datetime.now().isoformat(timespec="seconds"),
                   "count": 0, "message": f"生成失败：{e}"}
        _status.update(progress=summary["message"])
        _save_last_run(summary)
        return summary
    finally:
        _status.update(running=False)
        _lock.release()
