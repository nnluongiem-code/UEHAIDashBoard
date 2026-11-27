"""Reason codes: turn SHAP contributions into short, auditable evidence codes.

A code is emitted only when (a) SHAP says the feature pushed the prediction in
that direction for this student AND (b) the raw value actually sits in the
named region. This guard stops codes like "LOW_ATTENDANCE" appearing for a
student with 95% attendance just because of an interaction effect.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# feature -> (support_code, support_guard, positive_code, positive_guard)
TERM_REASON_MAP = {
    "mean_recent_trend": ("RECENT_SCORE_TREND_DECLINED", lambda v: v < -0.3,
                          "RECENT_SCORE_TREND_IMPROVED", lambda v: v > 0.3),
    "sum_mandatory_missing": ("MANDATORY_ASSESSMENT_MISSING", lambda v: v > 0, None, None),
    "sum_missing_or_late": ("MULTIPLE_LATE_OR_MISSING_SUBMISSIONS", lambda v: v >= 3,
                            "SUBMISSIONS_ON_TIME", lambda v: v == 0),
    "mean_attendance_rate": ("LOW_ATTENDANCE", lambda v: v < 0.75,
                             "CONSISTENT_ATTENDANCE", lambda v: v >= 0.9),
    "max_consecutive_absence": ("CONSECUTIVE_ABSENCES", lambda v: v >= 3, None, None),
    "mean_current_score": ("LOW_CURRENT_SCORE", lambda v: v < 5.0,
                           "STRONG_CURRENT_SCORE", lambda v: v >= 7.0),
    "mean_lms_completion": ("LOW_REQUIRED_LMS_COMPLETION", lambda v: v < 0.5,
                            "ACTIVE_REQUIRED_LMS", lambda v: v >= 0.85),
    "prior_cum_gpa": ("PRIOR_GPA_LOW", lambda v: v < 2.0,
                      "STRONG_PRIOR_RECORD", lambda v: v >= 3.2),
    "prior_failed_courses": ("PRIOR_FAILED_COURSES", lambda v: v >= 2, None, None),
    "prior_warning_flag": ("PRIOR_ACADEMIC_WARNING", lambda v: v == 1, None, None),
    "n_courses_p_pass_below_05": ("COURSES_AT_RISK_OF_NOT_PASSING", lambda v: v >= 1,
                                  "ALL_COURSES_LIKELY_PASSED", lambda v: v == 0),
    "term_registered_credits": ("HIGH_CREDIT_LOAD", lambda v: v >= 22, None, None),
}

COURSE_REASON_MAP = {
    "recent_score_trend": TERM_REASON_MAP["mean_recent_trend"],
    "mandatory_missing_count": ("MANDATORY_ASSESSMENT_MISSING", lambda v: v > 0, None, None),
    "missing_or_late_count": ("MULTIPLE_LATE_OR_MISSING_SUBMISSIONS", lambda v: v >= 2,
                              "SUBMISSIONS_ON_TIME", lambda v: v == 0),
    "attendance_rate": TERM_REASON_MAP["mean_attendance_rate"],
    "consecutive_absence_count": TERM_REASON_MAP["max_consecutive_absence"],
    "current_weighted_score": TERM_REASON_MAP["mean_current_score"],
    "lms_required_completion": TERM_REASON_MAP["mean_lms_completion"],
    "prior_cum_gpa": TERM_REASON_MAP["prior_cum_gpa"],
}

REASON_LABELS_VI = {
    "RECENT_SCORE_TREND_DECLINED": "Điểm thành phần gần đây giảm",
    "RECENT_SCORE_TREND_IMPROVED": "Điểm thành phần gần đây cải thiện",
    "MANDATORY_ASSESSMENT_MISSING": "Thiếu thành phần đánh giá bắt buộc",
    "MULTIPLE_LATE_OR_MISSING_SUBMISSIONS": "Nhiều bài nộp trễ hoặc chưa nộp",
    "SUBMISSIONS_ON_TIME": "Nộp bài đầy đủ, đúng hạn",
    "LOW_ATTENDANCE": "Tỷ lệ chuyên cần thấp",
    "CONSISTENT_ATTENDANCE": "Chuyên cần ổn định",
    "CONSECUTIVE_ABSENCES": "Vắng nhiều buổi liên tiếp",
    "LOW_CURRENT_SCORE": "Điểm hiện tại thấp",
    "STRONG_CURRENT_SCORE": "Điểm hiện tại tốt",
    "LOW_REQUIRED_LMS_COMPLETION": "Hoàn thành hoạt động LMS bắt buộc thấp",
    "ACTIVE_REQUIRED_LMS": "Hoàn thành tốt hoạt động LMS bắt buộc",
    "PRIOR_GPA_LOW": "GPA tích lũy trước đó thấp",
    "STRONG_PRIOR_RECORD": "Nền tảng học tập trước đó tốt",
    "PRIOR_FAILED_COURSES": "Có nhiều học phần không đạt trước đây",
    "PRIOR_ACADEMIC_WARNING": "Từng bị cảnh báo học vụ",
    "COURSES_AT_RISK_OF_NOT_PASSING": "Có học phần xác suất đạt dưới 50%",
    "ALL_COURSES_LIKELY_PASSED": "Các học phần đều có khả năng đạt",
    "HIGH_CREDIT_LOAD": "Khối lượng tín chỉ cao",
    "REGISTRATION_INCOMPLETE": "Đăng ký học phần chưa hoàn tất",
    # data quality
    "LOW_GRADE_COVERAGE": "Độ bao phủ điểm thấp",
    "LOW_ATTENDANCE_COVERAGE": "Thiếu dữ liệu chuyên cần",
    "STALE_SOURCE": "Nguồn dữ liệu chưa cập nhật",
    "SOURCE_CONFLICT": "Dữ liệu giữa các nguồn mâu thuẫn",
    "MISSING_REQUIRED_FIELDS": "Thiếu trường dữ liệu bắt buộc",
}


def reason_codes(shap: pd.DataFrame, values: pd.DataFrame, mapping: dict,
                 n_support: int = 3, n_positive: int = 2):
    """Return two lists per row: (positive_codes, support_codes)."""
    feats = [f for f in mapping if f in shap.columns]
    S = shap[feats].to_numpy()
    V = values[feats].to_numpy(dtype=float)
    pos_out, sup_out = [], []
    for r in range(len(S)):
        sup, pos = [], []
        for k in np.argsort(S[r]):  # most negative first
            f, v, s = feats[k], V[r, k], S[r, k]
            code, guard = mapping[f][0], mapping[f][1]
            if s < 0 and not np.isnan(v) and guard(v) and code not in sup:
                sup.append(code)
        for k in np.argsort(-S[r]):  # most positive first
            f, v, s = feats[k], V[r, k], S[r, k]
            code, guard = mapping[f][2], mapping[f][3]
            if code and s > 0 and not np.isnan(v) and guard(v) and code not in pos:
                pos.append(code)
        sup_out.append(sup[:n_support])
        pos_out.append(pos[:n_positive])
    return pos_out, sup_out


def recommended_owner(state: str, support: list[str]) -> str:
    if state == "INSUFFICIENT_EVIDENCE":
        return "DATA_STEWARD"
    if "REGISTRATION_INCOMPLETE" in support:
        return "TRAINING_OFFICE"
    if state in ("ON_TRACK", "PLAN_ADJUSTED") and not support:
        return "NONE"
    if state == "ON_TRACK":
        return "NONE"
    return "ACADEMIC_ADVISOR"
