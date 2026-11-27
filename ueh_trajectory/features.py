"""Feature definitions for course-level (M1-M3) and semester-level (M4) models.

Only information available *at the snapshot date* is used. Identifiers such as
student_id_hash or section_id are never model inputs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Time enters as the teaching week (numeric), not as a milestone category, so the
# same models can score an event-triggered snapshot in any week (spec section 8).
CAT_FEATURES = ["program_id", "course_id", "delivery_mode"]

COURSE_NUM_FEATURES = [
    "snapshot_week", "course_credits",
    # history (spec 9.2)
    "prior_term_gpa", "prior_cum_gpa", "prior_earned_ratio", "prior_failed_courses",
    "prior_repeat_courses", "prior_warning_flag", "terms_completed",
    # current term (9.3)
    "term_registered_credits", "approved_plan_credits", "reduced_load_flag",
    "current_weighted_score", "graded_coverage", "missing_or_late_count",
    "mandatory_missing_count", "recent_score_trend",
    # attendance & LMS (9.4)
    "attendance_rate", "attendance_coverage", "consecutive_absence_count",
    "lms_required_completion", "lms_data_coverage",
    # data quality (9.5)
    "data_quality_score",
]
COURSE_FEATURES = CAT_FEATURES + COURSE_NUM_FEATURES

# Semester-level inputs: course-model outputs aggregated + history + plan.
TERM_CAT_FEATURES = ["program_id"]
TERM_NUM_FEATURES = [
    "snapshot_week", "n_courses", "approved_plan_credits", "term_registered_credits",
    "reduced_load_flag",
    "prior_term_gpa", "prior_cum_gpa", "prior_earned_ratio", "prior_failed_courses",
    "prior_warning_flag", "terms_completed",
    "expected_earned_credits", "progress_gap_credits", "progress_gap_share",
    "mean_p_pass", "min_p_pass", "n_courses_p_pass_below_05", "mean_p_completion",
    "mean_pred_score", "mean_score_interval",
    "mean_current_score", "mean_attendance_rate", "sum_mandatory_missing",
    "sum_missing_or_late", "mean_recent_trend", "mean_lms_completion",
    "max_consecutive_absence", "mean_data_quality",
]
TERM_FEATURES = TERM_CAT_FEATURES + TERM_NUM_FEATURES


def add_course_derived(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["attendance_coverage"] = (out.attendance_data_sessions
                                  / out.sessions_held.replace(0, np.nan)).clip(0, 1)
    for c in CAT_FEATURES:
        out[c] = out[c].astype(str)
    return out


def build_term_frame(course_pred: pd.DataFrame) -> pd.DataFrame:
    """Aggregate course rows that already carry p_course_* predictions."""
    keys = ["student_id_hash", "term_id", "snapshot_milestone"]
    active = course_pred[course_pred.approved_withdrawal_flag == 0]
    g = active.assign(
        _cp=active.course_credits * active.p_course_pass,
        _low=(active.p_course_pass < 0.5).astype(int),
        _int=active.predicted_score_upper - active.predicted_score_lower,
    ).groupby(keys, sort=False)
    t = g.agg(
        program_id=("program_id", "first"),
        snapshot_week=("snapshot_week", "first"),
        snapshot_type=("snapshot_type", "first"),
        snapshot_date=("snapshot_date", "first"),
        n_courses=("course_id", "count"),
        approved_plan_credits=("approved_plan_credits", "first"),
        term_registered_credits=("term_registered_credits", "first"),
        reduced_load_flag=("reduced_load_flag", "first"),
        prior_term_gpa=("prior_term_gpa", "first"),
        prior_cum_gpa=("prior_cum_gpa", "first"),
        prior_earned_ratio=("prior_earned_ratio", "first"),
        prior_failed_courses=("prior_failed_courses", "first"),
        prior_warning_flag=("prior_warning_flag", "first"),
        terms_completed=("terms_completed", "first"),
        expected_earned_credits=("_cp", "sum"),
        mean_p_pass=("p_course_pass", "mean"),
        min_p_pass=("p_course_pass", "min"),
        n_courses_p_pass_below_05=("_low", "sum"),
        mean_p_completion=("p_course_completion", "mean"),
        mean_pred_score=("predicted_final_score", "mean"),
        mean_score_interval=("_int", "mean"),
        mean_current_score=("current_weighted_score", "mean"),
        mean_attendance_rate=("attendance_rate", "mean"),
        sum_mandatory_missing=("mandatory_missing_count", "sum"),
        sum_missing_or_late=("missing_or_late_count", "sum"),
        mean_recent_trend=("recent_score_trend", "mean"),
        mean_lms_completion=("lms_required_completion", "mean"),
        max_consecutive_absence=("consecutive_absence_count", "max"),
        mean_data_quality=("data_quality_score", "mean"),
    ).reset_index()
    # an approved withdrawal reduces the plan instead of counting as a shortfall
    wd = course_pred[course_pred.approved_withdrawal_flag == 1].groupby(keys).course_credits.sum()
    t = t.merge(wd.rename("withdrawn_credits"), on=keys, how="left")
    t["withdrawn_credits"] = t.withdrawn_credits.fillna(0)
    t["approved_plan_credits"] = t.approved_plan_credits - t.withdrawn_credits
    t["progress_gap_credits"] = t.approved_plan_credits - t.expected_earned_credits
    t["progress_gap_share"] = t.progress_gap_credits / t.approved_plan_credits.replace(0, np.nan)
    for c in TERM_CAT_FEATURES:
        t[c] = t[c].astype(str)
    return t
