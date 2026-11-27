"""Event-triggered snapshots (spec section 8, item 5).

Between the fixed milestones the system receives weekly data feeds
(`snapshot_type == "MONITOR"`). A feed becomes a scored EVENT snapshot only when
a critical condition appears that was *not* already present at the student's
previous scored snapshot, and that has not triggered an event within the
cooldown window, so a persisting or flickering problem does not re-trigger
every week.

Critical conditions (student x week, aggregated over courses):
    EVT_CONSECUTIVE_ABSENCES   absence streak in any course
    EVT_MANDATORY_MISSING      several mandatory assessments missing in one course
    EVT_SCORE_DECLINE          recent component scores fall sharply across courses
    EVT_REGISTRATION_INCOMPLETE registration still not finalised
    EVT_SOURCE_CONFLICT        sources disagree for this student
"""
from __future__ import annotations

import pandas as pd

from . import config as C

EVENT_LABELS_VI = {
    "EVT_CONSECUTIVE_ABSENCES": "Vắng học liên tiếp",
    "EVT_MANDATORY_MISSING": "Nhiều bài bắt buộc chưa hoàn thành",
    "EVT_SCORE_DECLINE": "Điểm thành phần suy giảm rõ rệt",
    "EVT_REGISTRATION_INCOMPLETE": "Đăng ký học phần chưa hoàn tất",
    "EVT_SOURCE_CONFLICT": "Dữ liệu giữa các nguồn mâu thuẫn",
}
BEHAVIOURAL_EVENTS = {"EVT_CONSECUTIVE_ABSENCES", "EVT_MANDATORY_MISSING", "EVT_SCORE_DECLINE"}


def event_codes(df: pd.DataFrame) -> pd.Series:
    """Active critical conditions per (student, term, snapshot label)."""
    R = C.EVENT_RULES
    keys = ["student_id_hash", "term_id", "snapshot_milestone"]
    g = df.groupby(keys, sort=False).agg(
        consec=("consecutive_absence_count", "max"),
        miss=("mandatory_missing_count", "max"),
        trend=("recent_score_trend", "mean"),
        reg=("registration_incomplete_flag", "max"),
        conflict=("source_conflict_flag", "max"),
    )
    out = {}
    for k, r in g.iterrows():
        codes = []
        if r.consec >= R["consecutive_absences"]:
            codes.append("EVT_CONSECUTIVE_ABSENCES")
        if r.miss >= R["mandatory_missing"]:
            codes.append("EVT_MANDATORY_MISSING")
        if pd.notna(r.trend) and r.trend <= R["score_trend_drop"]:
            codes.append("EVT_SCORE_DECLINE")
        if r.reg:
            codes.append("EVT_REGISTRATION_INCOMPLETE")
        if r.conflict:
            codes.append("EVT_SOURCE_CONFLICT")
        out[k] = codes
    return pd.Series(out, dtype=object)


def apply_event_snapshots(df: pd.DataFrame):
    """Keep regular snapshots + triggered monitoring rows (relabelled EVENT_Wxx).

    Returns (filtered_df, info) where info maps (student, term, label) to
    {"active": [...codes], "new": [...codes that triggered]}.
    """
    if "snapshot_type" not in df.columns:
        df = df.assign(snapshot_type="REGULAR")
    codes = event_codes(df)
    snaps = (df[["student_id_hash", "term_id", "snapshot_milestone", "snapshot_week", "snapshot_type"]]
             .drop_duplicates(["student_id_hash", "term_id", "snapshot_milestone"])
             .sort_values(["student_id_hash", "term_id", "snapshot_week"]))
    keep, rename, info = set(), {}, {}
    prev_key = None
    prev_codes: set[str] = set()
    last_fired: dict[str, int] = {}
    cool = C.EVENT_RULES["cooldown_weeks"]
    for r in snaps.itertuples(index=False):
        k = (r.student_id_hash, r.term_id, r.snapshot_milestone)
        if prev_key is None or prev_key[:2] != k[:2]:
            prev_codes, last_fired = set(), {}  # new student-term: start clean
        active = codes.get(k, [])
        if r.snapshot_type == "REGULAR":
            keep.add(k)
            info[k] = {"active": active, "new": []}
            prev_codes = set(active)
        else:
            wk = int(r.snapshot_week)
            new = [c for c in active if c not in prev_codes
                   and wk - last_fired.get(c, -99) >= cool]
            if new:
                for c in new:
                    last_fired[c] = wk
                label = f"{C.EVENT_LABEL_PREFIX}{int(r.snapshot_week):02d}"
                keep.add(k)
                rename[k] = label
                info[(k[0], k[1], label)] = {"active": active, "new": new}
                prev_codes = set(active)
        prev_key = k

    idx = list(zip(df.student_id_hash, df.term_id, df.snapshot_milestone))
    mask = [k in keep for k in idx]
    out = df[mask].copy()
    out_idx = [k for k, m in zip(idx, mask) if m]
    out["snapshot_milestone"] = [rename.get(k, k[2]) for k in out_idx]
    out.loc[[k in rename for k in out_idx], "snapshot_type"] = "EVENT"
    return out.reset_index(drop=True), info
