import os
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import decision_learning_db  # noqa: E402
from services.decision_learning_service import (  # noqa: E402
    DEFAULT_RISK_WEIGHTS,
    _candidate_weights,
    _evaluate,
    _is_next_business_day,
    _maybe_update_weights,
    bootstrap_historical_learning,
    factor_signals,
    get_learning_profile,
)


class DecisionLearningDbTests(unittest.TestCase):
    def test_decision_and_outcome_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "learning.db")
            with patch.object(decision_learning_db, "DB_PATH", path):
                decision_learning_db.init_db()
                decision_learning_db.save_decision(
                    "2026-07-20", {"verdict": {"stance": "防守"}}, "v1"
                )
                decision_learning_db.save_outcome(
                    "2026-07-20", "2026-07-21", {"target_risk": True}
                )

                self.assertEqual(
                    decision_learning_db.get_decision("2026-07-20")["decision"]["verdict"]["stance"],
                    "防守",
                )
                self.assertTrue(
                    decision_learning_db.get_outcome("2026-07-20")["outcome"]["target_risk"]
                )


class DecisionLearningServiceTests(unittest.TestCase):
    def test_factor_signals_use_a_share_structure_not_daily_pct_only(self):
        signals = factor_signals({
            "metrics": {
                "up_ratio": 32.9,
                "zt": 51,
                "dt": 185,
                "broken_ratio": 44,
                "size_gap": 4.64,
                "index_dispersion": 2.24,
            },
            "intraday_path": {"available": True, "score_delta": -11},
        })

        self.assertTrue(all(signals.values()))

    def test_yesterday_defensive_budget_is_rewarded_when_risk_arrives(self):
        previous = {
            "trade_date": "2026-07-20",
            "decision": {
                "verdict": {"stance": "防守"},
                "tomorrow_plan": {"position_cap": 20, "focus": ["保险", "白酒"]},
                "factor_signals": {"breadth_low": True},
                "risk_group": "risk",
            },
        }
        current = {
            "verdict": {"stance": "收缩", "regime": "全面退潮"},
            "mainlines": [
                {"name": "保险", "level": "确认主线", "state": "主线持续", "score": 78},
                {"name": "白酒", "level": "分歧降级", "state": "高位分歧", "score": 62},
            ],
        }

        outcome = _evaluate(previous, current, "2026-07-21")

        self.assertEqual(outcome["risk_budget_score"], 100)
        self.assertEqual(outcome["focus_hit_rate"], 50)
        self.assertTrue(outcome["target_risk"])
        self.assertIn("防守判断有效", outcome["title"])

    def test_historical_replay_is_labeled_and_weekend_counts_as_next_session(self):
        previous = {
            "trade_date": "2026-07-17",
            "source": "historical_replay",
            "decision": {
                "verdict": {"stance": "防守"},
                "tomorrow_plan": {"position_cap": 20},
                "risk_group": "risk",
            },
        }

        outcome = _evaluate(
            previous,
            {"verdict": {"stance": "收缩", "regime": "全面退潮"}},
            "2026-07-20",
        )

        self.assertTrue(_is_next_business_day("2026-07-17", "2026-07-20"))
        self.assertFalse(_is_next_business_day("2026-07-16", "2026-07-20"))
        self.assertEqual(outcome["sample_source_label"], "历史回放")

    def test_bootstrap_replays_saved_adjacent_archives(self):
        def fake_intelligence(trade_date, _market):
            stance = "防守" if trade_date.endswith("20") else "中性"
            return {
                "engine": "test-v1",
                "metrics": {"up_ratio": 35 if stance == "防守" else 55},
                "verdict": {"stance": stance, "regime": stance, "position_cap": 20},
                "tomorrow_plan": {"position_cap": 20, "focus": []},
            }

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "learning.db")
            with (
                patch.object(decision_learning_db, "DB_PATH", path),
                patch("services.decision_learning_service._bootstrap_done", False),
                patch("db.market_review_db.list_dates", return_value=[
                    {"date": "2026-07-21"},
                    {"date": "2026-07-20"},
                    {"date": "2026-07-17"},
                ]),
                patch("db.market_review_db.get_daily", return_value={"breadth": {}}),
                patch(
                    "services.postmarket_intelligence_service.build_postmarket_intelligence",
                    side_effect=fake_intelligence,
                ),
            ):
                decision_learning_db.init_db()
                profile = bootstrap_historical_learning(force=True)

                self.assertEqual(len(decision_learning_db.list_decisions()), 3)
                self.assertEqual(profile["valid_outcomes"], 2)
                self.assertEqual(profile["historical_outcomes"], 2)
                self.assertEqual(profile["live_outcomes"], 0)

    def test_candidate_weight_step_is_bounded_to_three_percent(self):
        rows = []
        for index in range(20):
            risk = index < 10
            rows.append({
                "outcome": {
                    "target_risk": risk,
                    "factor_signals": {key: risk for key in DEFAULT_RISK_WEIGHTS},
                }
            })
        candidate, _ = _candidate_weights(dict(DEFAULT_RISK_WEIGHTS), rows)

        for key, base in DEFAULT_RISK_WEIGHTS.items():
            self.assertLessEqual(abs(candidate[key] - base), base * 0.03 + 1e-9)
            self.assertGreater(candidate[key], base)

    def test_weight_update_promotes_only_after_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "learning.db")
            with patch.object(decision_learning_db, "DB_PATH", path):
                decision_learning_db.init_db()
                for index in range(30):
                    risk = index % 2 == 0
                    decision_learning_db.save_outcome(
                        f"2026-06-{index + 1:02d}",
                        f"2026-07-{index + 1:02d}",
                        {
                            "target_risk": risk,
                            "factor_signals": {
                                "breadth_low": risk,
                                "loss_pressure": False,
                                "broken_high": False,
                                "size_divergence": False,
                                "index_divergence": False,
                                "intraday_weakened": False,
                            },
                        },
                    )

                result = _maybe_update_weights()

                self.assertEqual(result["status"], "promoted")
                self.assertEqual(result["sample_count"], 30)
                self.assertGreater(result["weights"]["breadth_low"], 2.0)

    @patch("services.decision_learning_service.decision_learning_db.latest_learning_attempt", return_value=None)
    @patch("services.decision_learning_service.decision_learning_db.latest_effective_version", return_value=None)
    @patch("services.decision_learning_service.decision_learning_db.list_outcomes", return_value=[])
    def test_profile_refuses_to_learn_before_sample_gate(self, _outcomes, _version, _attempt):
        profile = get_learning_profile()

        self.assertEqual(profile["state"], "collecting")
        self.assertEqual(profile["valid_outcomes"], 0)
        self.assertEqual(profile["minimum_samples"], 30)
        self.assertIn("还需30个", profile["next_action"])


if __name__ == "__main__":
    unittest.main()
