"""Central configuration for the UEH C1.1.2 Academic Success Trajectory model.

Every threshold here is a *starting value*. Section 7 of the project spec requires
that state thresholds be re-tuned on validation results and on real advisor
capacity, and the academic-standing rules must be confirmed with Ban Đào tạo
before the system is used on real students.
"""
from __future__ import annotations

MODEL_NAME = "UEH Hierarchical Calibrated CatBoost Trajectory Model"
MODEL_VERSION = "1.0.0"

# ---------------------------------------------------------------- snapshots
MILESTONES = ["WEEK_4", "POST_MIDTERM", "WEEK_10", "PRE_FINAL"]
MILESTONE_WEEK = {"WEEK_4": 4, "POST_MIDTERM": 8, "WEEK_10": 10, "PRE_FINAL": 14}
MILESTONE_LABEL_VI = {  # event snapshots are labelled "Sự kiện T<week>" in the UI
    "WEEK_4": "Tuần 4",
    "POST_MIDTERM": "Sau giữa kỳ",
    "WEEK_10": "Tuần 10",
    "PRE_FINAL": "Trước thi cuối kỳ",
}

# ---------------------------------------------------------------- grading
PASS_SCORE = 4.0  # 10-point scale; confirm against the current UEH regulation

# 10-point -> 4-point conversion (lower bound of each band, grade point)
GRADE_BANDS = [
    (8.5, 4.0), (8.0, 3.5), (7.0, 3.0), (6.5, 2.5),
    (5.5, 2.0), (5.0, 1.5), (4.0, 1.0), (0.0, 0.0),
]

# ---------------------------------------------------------------- R1 standing
# Template based on Thông tư 08/2021/TT-BGDĐT (Art. 11). MUST be confirmed with
# Ban Đào tạo and replaced with the UEH regulation in force.
STANDING_RULES = {
    "term_gpa_min_first_term": 0.8,
    "term_gpa_min": 1.0,
    "cum_gpa_min_by_year": {1: 1.2, 2: 1.4, 3: 1.6, 4: 1.8},
    "max_failed_credit_share": 0.5,
    "watch_margin": 0.4,  # GPA within this margin of a threshold -> WATCH
}

# ---------------------------------------------------------------- R2 trajectory
TRAJECTORY_RULES = {
    "on_track_p_plan": 0.80,     # p_plan >= this and small gap -> ON_TRACK
    "on_track_max_gap": 1.0,     # credits
    "fragile_p_plan": 0.50,      # below this and not improving -> DIVERGING
    "delta_p_change": 0.10,      # |Δp| >= this counts as a real change
    "delta_gap_change": 1.5,     # credits; |Δgap| >= this counts as a change
    "plan_adjusted_min_p": 0.50,
}

# ---------------------------------------------------------------- Q1 quality
QUALITY_RULES = {
    "high": 0.75,     # quality score >= high -> HIGH
    "medium": 0.50,   # quality score >= medium -> MEDIUM, else LOW
    "stale_days": 14, # source not refreshed for this long is penalised
    "student_low_share": 0.34,  # share of LOW courses that makes the student LOW
}

# ---------------------------------------------------------------- data split
TERMS = ["2023.1", "2023.2", "2024.1", "2024.2", "2025.1", "2025.2", "2026.1", "2026.2"]
TRAIN_TERMS = ["2023.1", "2023.2", "2024.1", "2024.2", "2025.1"]
CALIBRATION_TERMS = ["2025.2"]
TEST_TERMS = ["2026.1"]
CURRENT_TERM = "2026.2"
CURRENT_TERM_MILESTONES = ["WEEK_4", "POST_MIDTERM", "WEEK_10"]  # snapshots so far
CURRENT_WEEK = 12  # latest teaching week with data in the current term
# first Monday of teaching for each term (snapshot dates are derived from these)
TERM_START = {f"{y}.1": f"{y}-02-16" for y in range(2023, 2027)} | \
             {f"{y}.2": f"{y}-09-07" for y in range(2023, 2027)}

# ---------------------------------------------------------------- event snapshots
# Weekly data feeds checked between milestones (spec section 8, item 5).
MONITORING_WEEKS = [6, 9, 11, 12, 13]
EVENT_RULES = {
    "consecutive_absences": 3,     # any course with >= this many absences in a row
    "mandatory_missing": 2,        # missing mandatory assessments within one course
    "score_trend_drop": -1.3,      # mean recent score trend across courses <= this
    "cooldown_weeks": 4,           # the same condition cannot re-trigger within this window
}
EVENT_LABEL_PREFIX = "EVENT_W"

# ---------------------------------------------------------------- manager alerts
ALERT_RULES = {
    "sharp_drop": -0.15,           # Δp_plan <= this -> student alert
    "severe_drop": -0.25,          # Δp_plan <= this -> HIGH
    "program_rise_medium": 0.05,   # increase in DIVERGING share vs previous milestone
    "program_rise_high": 0.10,
    "program_min_students": 5,     # and at least this many more students
    "course_min_students": 12,
    # a course is flagged when its share of students with p_pass < 0.5 is unusual
    # relative to the whole term: >= ratio x term share AND >= the floor
    "course_risk_ratio": 3.0,
    "course_risk_share_floor": 0.10,
    "course_min_at_risk": 4,
    "course_risk_share_high": 0.20,    # or ratio >= 5 -> HIGH
    "event_alert_min_drop": -0.05,     # event becomes an alert only with impact (see alerts.py)
    "dq_insufficient_share": 0.05,  # share of INSUFFICIENT_EVIDENCE
    "dq_issue_share": 0.10,         # share of course enrolments hit by one data issue code
    "sla_days": {"HIGH": 3, "MEDIUM": 7},  # unreviewed longer than this -> overdue
}

# ---------------------------------------------------------------- CatBoost
CATBOOST_PARAMS = {
    "iterations": 400,
    "learning_rate": 0.06,
    "depth": 6,
    "l2_leaf_reg": 5,
    "random_seed": 42,
    "verbose": False,
    "allow_writing_files": False,
    "thread_count": -1,
}
QUANTILES = [0.10, 0.50, 0.90]
OOF_FOLDS = 3
