"""Auditable A-share decision learning with bounded, validated weight updates."""
from __future__ import annotations

import math
from typing import Any

from db import decision_learning_db


MIN_SAMPLES = 30
UPDATE_INTERVAL = 5
VALIDATION_SIZE = 10

DEFAULT_RISK_WEIGHTS = {
    "breadth_low": 2.0,
    "loss_pressure": 2.0,
    "broken_high": 1.0,
    "size_divergence": 1.0,
    "index_divergence": 1.0,
    "intraday_weakened": 1.0,
}

FACTOR_LABELS = {
    "breadth_low": "个股广度塌陷",
    "loss_pressure": "跌停与亏钱效应",
    "broken_high": "炸板失败代价",
    "size_divergence": "权重与小盘背离",
    "index_divergence": "指数风格分裂",
    "intraday_weakened": "盘中状态转弱",
}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return default if math.isnan(number) or math.isinf(number) else number
    except (TypeError, ValueError):
        return default


def _risk_group(value: str) -> str:
    if value in {"防守", "收缩"}:
        return "risk"
    if value in {"进攻", "试错"}:
        return "attack"
    return "neutral"


def factor_signals(intelligence: dict) -> dict[str, bool]:
    metrics = intelligence.get("metrics") or {}
    path = intelligence.get("intraday_path") or {}
    return {
        "breadth_low": _f(metrics.get("up_ratio")) < 40,
        "loss_pressure": _f(metrics.get("dt")) > max(_f(metrics.get("zt")), 20),
        "broken_high": _f(metrics.get("broken_ratio")) >= 35,
        "size_divergence": _f(metrics.get("size_gap")) >= 2,
        "index_divergence": _f(metrics.get("index_dispersion")) >= 1.5,
        "intraday_weakened": bool(path.get("available")) and _f(path.get("score_delta")) <= -8,
    }


def get_effective_weights() -> tuple[dict[str, float], dict]:
    version = decision_learning_db.latest_effective_version()
    weights = dict(DEFAULT_RISK_WEIGHTS)
    if version:
        for key in weights:
            if key in (version.get("weights") or {}):
                weights[key] = round(_f(version["weights"][key], weights[key]), 3)
    return weights, version or {
        "version": "L0",
        "sample_count": 0,
        "status": "baseline",
        "created_at": "",
        "metrics": {},
        "changes": {},
    }


def _decision_payload(intelligence: dict) -> dict:
    verdict = intelligence.get("verdict") or {}
    plan = intelligence.get("tomorrow_plan") or {}
    return {
        "verdict": verdict,
        "tomorrow_plan": plan,
        "metrics": intelligence.get("metrics") or {},
        "intraday_path": intelligence.get("intraday_path") or {},
        "mainlines": intelligence.get("mainlines") or [],
        "factor_signals": factor_signals(intelligence),
        "risk_group": _risk_group(str(verdict.get("stance") or "")),
    }


def _evaluate(previous: dict, current: dict, outcome_date: str) -> dict:
    previous_day = previous.get("trade_date") or ""
    prior = previous.get("decision") or {}
    prior_verdict = prior.get("verdict") or {}
    prior_plan = prior.get("tomorrow_plan") or {}
    current_verdict = current.get("verdict") or {}
    current_group = _risk_group(str(current_verdict.get("stance") or ""))
    prior_group = str(prior.get("risk_group") or _risk_group(str(prior_verdict.get("stance") or "")))
    cap = int(_f(prior_plan.get("position_cap"), _f(prior_verdict.get("position_cap"), 40)))

    if current_group == "risk":
        budget_score = 100 if cap <= 30 else 55 if cap <= 50 else 15
    elif current_group == "attack":
        budget_score = 100 if cap >= 50 else 60 if cap >= 30 else 35
    else:
        budget_score = 100 if 30 <= cap <= 50 else 60

    current_lines = {row.get("name"): row for row in current.get("mainlines") or []}
    focus = [str(name) for name in prior_plan.get("focus") or [] if name]
    focus_details = []
    for name in focus:
        row = current_lines.get(name) or {}
        followed = row.get("level") == "确认主线" and row.get("state") not in {
            "高位分歧", "资金撤退", "弱势退潮", "假突破"
        }
        focus_details.append({
            "name": name,
            "followed": followed,
            "state": row.get("state") or "掉出主线样本",
            "score": row.get("score"),
        })
    focus_hit_rate = (
        round(sum(1 for row in focus_details if row["followed"]) / len(focus_details) * 100)
        if focus_details else None
    )
    regime_persisted = prior_group == current_group
    regime_score = 100 if regime_persisted else 35
    if focus_hit_rate is None:
        overall = round(budget_score * 0.7 + regime_score * 0.3)
    else:
        overall = round(budget_score * 0.5 + focus_hit_rate * 0.3 + regime_score * 0.2)

    lessons = []
    if current_group == "risk" and cap <= 30:
        lessons.append("昨日低风险预算有效，防守纪律成功覆盖今日风险状态。")
    elif current_group == "risk" and cap > 50:
        lessons.append("昨日风险预算过高，需提高广度、跌停和盘中转弱信号的约束力。")
    elif current_group == "attack" and cap < 30:
        lessons.append("昨日防守过度，错过结构性进攻，需要检查风险信号是否衰减过慢。")
    else:
        lessons.append("昨日仓位预算与今日市场状态基本匹配。")
    if focus_hit_rate is not None:
        lessons.append(
            f"昨日关注方向延续率{focus_hit_rate}%，"
            + ("主线筛选有效。" if focus_hit_rate >= 60 else "主线持续性判断需要降权复核。")
        )
    if not regime_persisted:
        lessons.append("市场状态没有延续，下一轮提高状态切换和失效条件的识别优先级。")

    title = (
        "昨日防守判断有效" if current_group == "risk" and cap <= 30 else
        "昨日风险预算偏高" if current_group == "risk" and cap > 50 else
        "昨日进攻预算有效" if current_group == "attack" and cap >= 50 else
        "昨日判断部分有效，状态发生切换"
    )
    return {
        "decision_date": previous_day,
        "outcome_date": outcome_date,
        "title": title,
        "overall_score": overall,
        "prior_stance": prior_verdict.get("stance") or "待确认",
        "prior_position_cap": cap,
        "actual_stance": current_verdict.get("stance") or "待确认",
        "actual_regime": current_verdict.get("regime") or "待确认",
        "risk_budget_score": budget_score,
        "regime_persisted": regime_persisted,
        "focus_hit_rate": focus_hit_rate,
        "focus_details": focus_details,
        "lessons": lessons,
        "factor_signals": prior.get("factor_signals") or {},
        "target_risk": current_group == "risk",
    }


def _risk_probability(weights: dict[str, float], signals: dict) -> float:
    active = sum(weights.get(key, 0.0) for key, enabled in signals.items() if enabled)
    total = sum(max(value, 0.0) for value in weights.values()) or 1.0
    return min(0.98, max(0.02, active / total * 1.65))


def _metrics(weights: dict[str, float], rows: list[dict]) -> dict:
    if not rows:
        return {"brier": 1.0, "accuracy": 0, "risk_miss_rate": 100}
    squared = 0.0
    correct = 0
    risk_count = 0
    misses = 0
    for row in rows:
        outcome = row.get("outcome") or row
        target = 1.0 if outcome.get("target_risk") else 0.0
        probability = _risk_probability(weights, outcome.get("factor_signals") or {})
        squared += (probability - target) ** 2
        predicted = probability >= 0.5
        correct += int(predicted == bool(target))
        if target:
            risk_count += 1
            misses += int(not predicted)
    return {
        "brier": round(squared / len(rows), 4),
        "accuracy": round(correct / len(rows) * 100),
        "risk_miss_rate": round(misses / risk_count * 100) if risk_count else 0,
    }


def _candidate_weights(current: dict[str, float], train: list[dict]) -> tuple[dict[str, float], dict]:
    targets = [bool((row.get("outcome") or row).get("target_risk")) for row in train]
    baseline = sum(targets) / len(targets) if targets else 0.5
    candidate = dict(current)
    evidence = {}
    for key, base in DEFAULT_RISK_WEIGHTS.items():
        signaled = [
            bool((row.get("outcome") or row).get("target_risk"))
            for row in train
            if (row.get("outcome") or row).get("factor_signals", {}).get(key)
        ]
        if len(signaled) < 5:
            evidence[key] = {"sample_count": len(signaled), "status": "样本不足"}
            continue
        conditional = sum(signaled) / len(signaled)
        lift = conditional - baseline
        desired = base * min(1.2, max(0.8, 1 + lift * 0.4))
        max_step = base * 0.03
        delta = min(max(desired - current[key], -max_step), max_step)
        candidate[key] = round(current[key] + delta, 3)
        evidence[key] = {
            "sample_count": len(signaled),
            "next_day_risk_rate": round(conditional * 100),
            "baseline_risk_rate": round(baseline * 100),
            "delta": round(delta, 3),
        }
    return candidate, evidence


def _maybe_update_weights() -> dict | None:
    rows = decision_learning_db.list_outcomes()
    sample_count = len(rows)
    last_attempt = decision_learning_db.latest_learning_attempt()
    if sample_count < MIN_SAMPLES or sample_count % UPDATE_INTERVAL:
        return last_attempt
    if last_attempt and int(last_attempt.get("sample_count") or 0) == sample_count:
        return last_attempt

    current, effective = get_effective_weights()
    validation_size = min(VALIDATION_SIZE, max(5, sample_count // 3))
    train, validation = rows[:-validation_size], rows[-validation_size:]
    candidate, evidence = _candidate_weights(current, train)
    current_metrics = _metrics(current, validation)
    candidate_metrics = _metrics(candidate, validation)
    improved = (
        candidate_metrics["brier"] < current_metrics["brier"] - 0.001
        and candidate_metrics["risk_miss_rate"] <= current_metrics["risk_miss_rate"]
    )
    status = "promoted" if improved else "rejected"
    version = f"L{sample_count}-{status}"
    changes = {
        key: {
            "label": FACTOR_LABELS[key],
            "before": current[key],
            "after": candidate[key],
            "evidence": evidence.get(key) or {},
        }
        for key in current
        if candidate[key] != current[key]
    }
    decision_learning_db.save_learning_version(
        version,
        sample_count,
        status,
        candidate,
        {
            "effective_version": effective.get("version"),
            "current": current_metrics,
            "candidate": candidate_metrics,
            "validation_size": len(validation),
        },
        changes,
    )
    return decision_learning_db.latest_learning_attempt()


def _factor_learning_summary(rows: list[dict]) -> list[dict]:
    result = []
    for key, label in FACTOR_LABELS.items():
        signaled = [
            bool((row.get("outcome") or row).get("target_risk"))
            for row in rows
            if (row.get("outcome") or row).get("factor_signals", {}).get(key)
        ]
        result.append({
            "key": key,
            "label": label,
            "sample_count": len(signaled),
            "next_day_risk_rate": round(sum(signaled) / len(signaled) * 100) if signaled else None,
        })
    return result


def get_learning_profile() -> dict:
    outcomes = decision_learning_db.list_outcomes()
    weights, effective = get_effective_weights()
    latest = outcomes[-1].get("outcome") if outcomes else None
    attempt = decision_learning_db.latest_learning_attempt()
    count = len(outcomes)
    if count < MIN_SAMPLES:
        state = "collecting"
        label = "学习样本积累中"
        next_action = f"还需{MIN_SAMPLES - count}个有效次日结果，达到门槛后才允许调整权重。"
    elif count % UPDATE_INTERVAL:
        state = "waiting_cycle"
        label = "等待下一次五日学习周期"
        next_action = f"再积累{UPDATE_INTERVAL - count % UPDATE_INTERVAL}个结果后重新验证候选权重。"
    elif attempt and attempt.get("status") == "promoted":
        state = "updated"
        label = "新权重已通过验证并生效"
        next_action = "继续观察新版本，后续若验证表现变差将保持旧有效版本。"
    else:
        state = "rejected"
        label = "候选权重未通过验证"
        next_action = "继续使用原权重，等待下一批样本重新学习。"
    return {
        "state": state,
        "label": label,
        "valid_outcomes": count,
        "minimum_samples": MIN_SAMPLES,
        "progress_pct": min(100, round(count / MIN_SAMPLES * 100)),
        "update_interval": UPDATE_INTERVAL,
        "effective_version": effective.get("version") or "L0",
        "effective_weights": [
            {"key": key, "label": FACTOR_LABELS[key], "weight": value}
            for key, value in weights.items()
        ],
        "latest_audit": latest,
        "latest_attempt": attempt,
        "factor_learning": _factor_learning_summary(outcomes),
        "next_action": next_action,
        "guardrails": [
            "单个因子每次最多调整原始权重的3%。",
            "候选权重必须在留出样本上降低误差且不能增加风险漏判。",
            "AI不能自行修改代码、样本标签或学习门槛。",
        ],
    }


def record_decision_and_learn(trade_date: str, intelligence: dict, source: str = "live") -> dict:
    payload = _decision_payload(intelligence)
    previous = decision_learning_db.previous_decision(trade_date)
    decision_learning_db.save_decision(
        trade_date,
        payload,
        str(intelligence.get("engine") or "postmarket-intelligence-v1"),
        source,
    )
    if previous:
        outcome = _evaluate(previous, intelligence, trade_date)
        decision_learning_db.save_outcome(previous["trade_date"], trade_date, outcome)
    _maybe_update_weights()
    return get_learning_profile()
