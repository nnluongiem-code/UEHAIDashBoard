"""Fast tests for rule engines, the quality gate and the output contract (spec sections 5-11)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ueh_trajectory import config as C  # noqa: E402
from ueh_trajectory.features import add_course_derived, build_term_frame  # noqa: E402
from ueh_trajectory.models import CalibratedCatBoostClassifier, ConformalQuantileRegressor  # noqa: E402
from ueh_trajectory.quality import course_quality, student_confidence  # noqa: E402
from ueh_trajectory.reasons import TERM_REASON_MAP, reason_codes, recommended_owner  # noqa: E402
from ueh_trajectory.rules import simulate_term, trajectory_state  # noqa: E402
from ueh_trajectory.synthetic import generate, to_grade_point  # noqa: E402


@pytest.fixture(scope="module")
def data():
    return generate(n_students=60, seed=3)


# ------------------------------------------------------------------ R2
def test_low_confidence_overrides_everything():
    assert trajectory_state(0.95, 0, 0.9, 0, "LOW", False) == "INSUFFICIENT_EVIDENCE"


def test_spec_example_is_improving():
    # spec section 11: 0.51 -> 0.63 with a 3.2 credit gap
    assert trajectory_state(0.63, 3.2, 0.51, 4.0, "HIGH", False) == "IMPROVING"


def test_on_track_diverging_fragile():
    assert trajectory_state(0.9, 0.2, None, None, "HIGH", False) == "ON_TRACK"
    assert trajectory_state(0.55, 2.0, 0.75, 1.0, "HIGH", False) == "DIVERGING"
    assert trajectory_state(0.6, 2.0, 0.62, 2.0, "HIGH", False) == "STABLE_FRAGILE"
    assert trajectory_state(0.3, 6.0, None, None, "HIGH", False) == "DIVERGING"


def test_approved_plan_change_is_not_failure():
    assert trajectory_state(0.7, 1.0, 0.7, 1.0, "HIGH", True) == "PLAN_ADJUSTED"
    # but an adjusted plan that is itself in trouble is still surfaced
    assert trajectory_state(0.3, 5.0, 0.5, 2.0, "HIGH", True) == "DIVERGING"


# ------------------------------------------------------------------ R1
def test_grade_points():
    assert list(to_grade_point([9.0, 8.2, 7.0, 6.5, 5.5, 5.0, 4.0, 3.9])) == \
        [4.0, 3.5, 3.0, 2.5, 2.0, 1.5, 1.0, 0.0]


def test_standing_simulation_orders_students():
    def courses(p, score):
        return pd.DataFrame({"course_credits": [3] * 5, "p_course_completion": [p] * 5,
                             "predicted_score_lower": [score - 1] * 5,
                             "predicted_final_score": [score] * 5,
                             "predicted_score_upper": [score + 1] * 5})
    strong = simulate_term(courses(0.98, 8.0), 3.2, 60, 4)
    weak = simulate_term(courses(0.6, 3.5), 1.3, 60, 4)
    assert strong["p_satisfactory_standing"] > 0.95 and strong["predicted_academic_standing"] == "SATISFACTORY"
    assert weak["p_satisfactory_standing"] < 0.5 and weak["predicted_academic_standing"] == "WARNING_LIKELY"
    assert strong["predicted_term_gpa_lower"] <= strong["predicted_term_gpa"] <= strong["predicted_term_gpa_upper"]


# ------------------------------------------------------------------ Q1
def test_quality_gate_flags_bad_records(data):
    df = add_course_derived(data[0].head(200))
    bad = df.copy()
    bad["source_conflict_flag"] = 1
    bad["attendance_data_sessions"] = 0
    bad["required_field_completeness"] = 0.6
    bad["days_since_source_update"] = 30
    assert (course_quality(bad).data_confidence == "LOW").all()
    assert "SOURCE_CONFLICT" in course_quality(bad).quality_issue_codes.iloc[0]
    assert student_confidence(pd.Series(["LOW", "LOW", "HIGH"])) == "LOW"
    assert student_confidence(pd.Series(["HIGH"] * 5)) == "HIGH"


# ------------------------------------------------------------------ semester logic
def test_expected_credits_and_gap_follow_spec(data):
    cp = course_quality(add_course_derived(data[0]))
    one = cp[(cp.student_id_hash == cp.student_id_hash.iloc[0]) & (cp.term_id == cp.term_id.iloc[0])
             & (cp.snapshot_milestone == "WEEK_4")].copy()
    one["approved_withdrawal_flag"] = 0
    one["p_course_completion"] = 0.9
    one["p_course_pass"] = 0.8
    one["predicted_final_score"], one["predicted_score_lower"], one["predicted_score_upper"] = 6, 5, 7
    t = build_term_frame(one).iloc[0]
    assert t.expected_earned_credits == pytest.approx(0.8 * one.course_credits.sum())
    assert t.progress_gap_credits == pytest.approx(t.approved_plan_credits - t.expected_earned_credits)


def test_withdrawal_reduces_plan_not_credits(data):
    cp = course_quality(add_course_derived(data[0]))
    one = cp[(cp.student_id_hash == cp.student_id_hash.iloc[0]) & (cp.term_id == cp.term_id.iloc[0])
             & (cp.snapshot_milestone == "WEEK_4")].copy()
    one["approved_withdrawal_flag"] = 0
    one.iloc[0, one.columns.get_loc("approved_withdrawal_flag")] = 1
    for c, v in [("p_course_completion", .9), ("p_course_pass", 1.0), ("predicted_final_score", 6),
                 ("predicted_score_lower", 5), ("predicted_score_upper", 7)]:
        one[c] = v
    t = build_term_frame(one).iloc[0]
    assert t.withdrawn_credits == one.course_credits.iloc[0]
    assert t.progress_gap_credits == pytest.approx(0)  # remaining courses certain -> no gap


# ------------------------------------------------------------------ models
def test_calibrated_classifier_and_quantiles_are_sane(data):
    df = course_quality(add_course_derived(data[0]))
    df = df[df.term_id != C.CURRENT_TERM]
    df = df[(df.approved_withdrawal_flag == 0) & (df.course_completed_flag == 1)]
    tr, ca = df.iloc[: len(df) // 2], df.iloc[len(df) // 2:]
    from ueh_trajectory.features import CAT_FEATURES, COURSE_FEATURES
    m = CalibratedCatBoostClassifier(COURSE_FEATURES, CAT_FEATURES, iterations=60).fit(tr, tr.course_pass_flag)
    m.calibrate(ca, ca.course_pass_flag)
    p = m.predict_proba(ca)
    assert p.min() >= 0.01 and p.max() <= 0.99
    q = ConformalQuantileRegressor(COURSE_FEATURES, CAT_FEATURES, iterations=60).fit(tr, tr.course_final_score)
    q.calibrate(ca, ca.course_final_score)
    lo, med, hi = q.predict(ca)
    assert (lo <= med).all() and (med <= hi).all()
    assert np.mean((ca.course_final_score >= lo) & (ca.course_final_score <= hi)) >= 0.75


def test_reason_codes_respect_guards():
    shap = pd.DataFrame({"mean_attendance_rate": [-1.0, -1.0], "sum_mandatory_missing": [-0.5, -0.5]})
    vals = pd.DataFrame({"mean_attendance_rate": [0.95, 0.5], "sum_mandatory_missing": [0, 2]})
    pos, sup = reason_codes(shap, vals, {k: TERM_REASON_MAP[k] for k in shap.columns})
    assert sup[0] == []  # high attendance never yields LOW_ATTENDANCE
    assert sup[1] == ["LOW_ATTENDANCE", "MANDATORY_ASSESSMENT_MISSING"]


def test_owner_routing():
    assert recommended_owner("INSUFFICIENT_EVIDENCE", []) == "DATA_STEWARD"
    assert recommended_owner("DIVERGING", ["REGISTRATION_INCOMPLETE"]) == "TRAINING_OFFICE"
    assert recommended_owner("ON_TRACK", []) == "NONE"
    assert recommended_owner("STABLE_FRAGILE", ["LOW_ATTENDANCE"]) == "ACADEMIC_ADVISOR"


# ------------------------------------------------------------------ output contract
SPEC_KEYS = {
    "student_id_hash", "term_id", "snapshot_milestone", "model_version", "p_course_completion",
    "p_course_pass", "predicted_final_score", "predicted_score_lower", "predicted_score_upper",
    "expected_earned_credits", "approved_plan_credits", "p_plan_completion", "progress_gap_credits",
    "previous_p_plan_completion", "trajectory_state", "data_confidence", "positive_reason_codes",
    "support_reason_codes", "recommended_owner", "review_status",
}


def test_exported_records_match_spec_schema():
    path = Path(__file__).resolve().parents[1] / "artifacts" / "output" / "predictions_course.jsonl"
    if not path.exists():
        pytest.skip("run scripts/run_pipeline.py first")
    import json
    with open(path, encoding="utf-8") as f:
        rec = json.loads(f.readline())
    assert SPEC_KEYS <= set(rec)
    assert rec["trajectory_state"] in {"ON_TRACK", "IMPROVING", "STABLE_FRAGILE", "DIVERGING",
                                       "PLAN_ADJUSTED", "INSUFFICIENT_EVIDENCE"}
    assert rec["data_confidence"] in {"HIGH", "MEDIUM", "LOW"}
