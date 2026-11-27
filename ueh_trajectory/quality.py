"""Q1 Data Quality Gate.

Scores how much trustworthy evidence stands behind each prediction. A LOW
result sends the record to INSUFFICIENT_EVIDENCE instead of letting the
model speak with confidence it has not earned.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C


def course_quality(df: pd.DataFrame) -> pd.DataFrame:
    """Add `data_quality_score`, `data_confidence` and `quality_issue_codes`."""
    R = C.QUALITY_RULES
    att_cov = (df.attendance_data_sessions / df.sessions_held.replace(0, np.nan)).fillna(0).clip(0, 1)
    # graded coverage is judged against what is *expected* at this milestone
    expected_cov = df.snapshot_index.map({0: 0.10, 1: 0.40, 2: 0.50, 3: 0.60}).fillna(0.5)
    score_cov = (df.graded_coverage / expected_cov).clip(0, 1)
    lms_relevant = df.lms_data_coverage > 0
    lms_cov = np.where(lms_relevant, df.lms_data_coverage, 1.0)  # not penalised if LMS not designed in
    fresh = np.where(df.days_since_source_update > R["stale_days"], 0.4, 1.0)

    q = (0.30 * score_cov + 0.25 * att_cov + 0.10 * lms_cov
         + 0.20 * df.required_field_completeness + 0.15 * fresh)
    q = q * np.where(df.source_conflict_flag == 1, 0.6, 1.0)

    out = df.copy()
    out["data_quality_score"] = q.round(3)
    out["data_confidence"] = np.select([q >= R["high"], q >= R["medium"]], ["HIGH", "MEDIUM"], "LOW")

    issues = []
    for sc, ac, f, cf, cmp_ in zip(score_cov, att_cov, fresh, df.source_conflict_flag,
                                   df.required_field_completeness):
        codes = []
        if sc < 0.6:
            codes.append("LOW_GRADE_COVERAGE")
        if ac < 0.6:
            codes.append("LOW_ATTENDANCE_COVERAGE")
        if f < 1:
            codes.append("STALE_SOURCE")
        if cf:
            codes.append("SOURCE_CONFLICT")
        if cmp_ < 0.85:
            codes.append("MISSING_REQUIRED_FIELDS")
        issues.append(codes)
    out["quality_issue_codes"] = issues
    return out


def student_confidence(course_conf: pd.Series) -> str:
    """Roll course-level confidence up to the student x snapshot level."""
    share_low = (course_conf == "LOW").mean()
    if share_low >= C.QUALITY_RULES["student_low_share"]:
        return "LOW"
    if share_low > 0 or (course_conf == "MEDIUM").mean() >= 0.5:
        return "MEDIUM"
    return "HIGH"
