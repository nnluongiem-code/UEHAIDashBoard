"""Tests for event-triggered snapshots and manager alerts."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ueh_trajectory.alerts import course_alerts, student_alerts  # noqa: E402
from ueh_trajectory.events import apply_event_snapshots  # noqa: E402


def _feed(rows):
    """rows: (label, week, type, consec, missing, trend) for one student, one course."""
    base = dict(student_id_hash="S1", term_id="2026.2", registration_incomplete_flag=0,
                source_conflict_flag=0)
    return pd.DataFrame([{**base, "snapshot_milestone": l, "snapshot_week": w, "snapshot_type": t,
                          "consecutive_absence_count": c, "mandatory_missing_count": m,
                          "recent_score_trend": tr} for l, w, t, c, m, tr in rows])


def test_new_condition_triggers_event_and_persisting_one_does_not():
    df = _feed([
        ("WEEK_4", 4, "REGULAR", 0, 0, None),
        ("MONITOR_W06", 6, "MONITOR", 4, 0, 0.0),     # new absence streak -> EVENT
        ("POST_MIDTERM", 8, "REGULAR", 5, 0, 0.0),
        ("MONITOR_W09", 9, "MONITOR", 6, 0, 0.0),     # same streak still there -> nothing
        ("WEEK_10", 10, "REGULAR", 0, 0, 0.0),
        ("MONITOR_W11", 11, "MONITOR", 0, 3, 0.0),    # new: missing mandatory work -> EVENT
    ])
    out, info = apply_event_snapshots(df)
    labels = list(out.snapshot_milestone)
    assert labels == ["WEEK_4", "EVENT_W06", "POST_MIDTERM", "WEEK_10", "EVENT_W11"]
    assert info[("S1", "2026.2", "EVENT_W06")]["new"] == ["EVT_CONSECUTIVE_ABSENCES"]
    assert info[("S1", "2026.2", "EVENT_W11")]["new"] == ["EVT_MANDATORY_MISSING"]
    assert set(out.loc[out.snapshot_milestone.str.startswith("EVENT"), "snapshot_type"]) == {"EVENT"}


def test_cooldown_blocks_flickering_condition():
    df = _feed([
        ("WEEK_4", 4, "REGULAR", 0, 0, None),
        ("MONITOR_W06", 6, "MONITOR", 3, 0, 0.0),     # fires
        ("POST_MIDTERM", 8, "REGULAR", 0, 0, 0.0),    # gone
        ("MONITOR_W09", 9, "MONITOR", 3, 0, 0.0),     # back after 3 weeks -> still cooling down
    ])
    out, _ = apply_event_snapshots(df)
    assert "EVENT_W09" not in set(out.snapshot_milestone)


def _term_rows(states, ps, types=None, events=None, standing=None):
    n = len(states)
    return pd.DataFrame({
        "student_id_hash": ["S1"] * n, "program_id": ["FIN"] * n, "term_id": ["2026.2"] * n,
        "snapshot_milestone": [f"M{i}" for i in range(n)], "snapshot_week": [4 + 2 * i for i in range(n)],
        "snapshot_type": types or ["REGULAR"] * n, "snapshot_date": ["2026-10-01"] * n,
        "trajectory_state": states, "p_plan_completion": ps,
        "new_event_codes": events or [[] for _ in range(n)],
        "predicted_academic_standing": standing or ["SATISFACTORY"] * n,
        "p_satisfactory_standing": [0.9] * n, "recommended_owner": ["ACADEMIC_ADVISOR"] * n,
    })


def test_fall_from_on_track_is_high_alert():
    a = student_alerts(_term_rows(["ON_TRACK", "DIVERGING"], [0.85, 0.40]))
    assert len(a) == 1 and a[0]["severity"] == "HIGH"
    assert {"BECAME_DIVERGING", "SHARP_DROP"} <= set(a[0]["triggers"])


def test_event_without_forecast_impact_is_not_a_manager_alert():
    t = _term_rows(["ON_TRACK", "ON_TRACK"], [0.90, 0.91], types=["REGULAR", "EVENT"],
                   events=[[], ["EVT_MANDATORY_MISSING"]])
    assert student_alerts(t) == []
    t2 = _term_rows(["STABLE_FRAGILE", "DIVERGING"], [0.60, 0.42], types=["REGULAR", "EVENT"],
                    events=[[], ["EVT_CONSECUTIVE_ABSENCES"]])
    a = student_alerts(t2)
    assert a and "EVT_CONSECUTIVE_ABSENCES" in a[0]["triggers"] and a[0]["severity"] == "HIGH"


def test_course_alert_is_relative_to_the_term():
    rows = []
    for c, n_risk in [("HARD101", 8), ("EASY", 1), ("EASY2", 1), ("EASY3", 0)]:
        for i in range(30):
            rows.append(dict(course_id=c, student_id_hash=f"{c}{i}", snapshot_type="REGULAR",
                             snapshot_week=10, approved_withdrawal_flag=0,
                             p_course_pass=0.3 if i < n_risk else 0.9, support_reason_codes=[]))
    cp = pd.DataFrame(rows)
    t = pd.DataFrame([dict(snapshot_type="REGULAR", snapshot_week=10, snapshot_milestone="WEEK_10",
                           snapshot_date="2026-11-13")])
    a = course_alerts(cp, t)
    assert [x["title"].split(":")[0] for x in a] == ["Học phần HARD101"]
