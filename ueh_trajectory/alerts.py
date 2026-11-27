"""Early-warning alerts for managers.

Built in Python, not in the browser, so the same list feeds the dashboard's
"Cảnh báo" tab and, later, the e-mail digest (artifacts/output/alerts.json).

Scopes
    STUDENT  latest snapshot of a student shows a new event, a fall into
             DIVERGING, a sharp drop in p_plan or a newly likely standing warning
    PROGRAM  share of DIVERGING students rises between the last two milestones
    COURSE   a course has an unusual share of students unlikely to pass
    DATA     data-quality problems large enough to undermine the forecasts

Overdue-review alerts are computed in the dashboard, because review status is
recorded there (per browser in the demo; in a shared case system in production).
"""
from __future__ import annotations

import pandas as pd

from . import config as C
from .events import EVENT_LABELS_VI
from .reasons import REASON_LABELS_VI

STATE_VI = {
    "ON_TRACK": "Đúng tiến độ", "IMPROVING": "Đang cải thiện",
    "STABLE_FRAGILE": "Ổn định nhưng mong manh", "DIVERGING": "Lệch khỏi mục tiêu",
    "PLAN_ADJUSTED": "Theo kế hoạch điều chỉnh", "INSUFFICIENT_EVIDENCE": "Chưa đủ bằng chứng",
}
SCOPE_ORDER = {"STUDENT": 0, "PROGRAM": 1, "COURSE": 2, "DATA": 3}


def _label(row) -> str:
    if row.snapshot_type == "EVENT":
        return f"Sự kiện tuần {int(row.snapshot_week)}"
    return C.MILESTONE_LABEL_VI.get(row.snapshot_milestone, row.snapshot_milestone)


def _lower_first(text: str) -> str:
    """Lower-case the first letter only, keeping acronyms such as GPA or LMS."""
    return text if text[:3].isupper() else text[:1].lower() + text[1:]


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:] + "."


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


# ------------------------------------------------------------------ student
def student_alerts(t: pd.DataFrame) -> list[dict]:
    R = C.ALERT_RULES
    out = []
    for sid, g in t.sort_values("snapshot_week").groupby("student_id_hash", sort=False):
        cur = g.iloc[-1]
        prev = g.iloc[-2] if len(g) > 1 else None
        triggers, parts = [], []
        dp = cur.p_plan_completion - prev.p_plan_completion if prev is not None else 0.0
        # an event becomes a *manager* alert only when the forecast shows an impact;
        # otherwise it stays visible in the student's detail and in the queue
        impact = (cur.trajectory_state in ("DIVERGING", "STABLE_FRAGILE")
                  or dp <= R["event_alert_min_drop"]
                  or cur.predicted_academic_standing != "SATISFACTORY")
        if cur.snapshot_type == "EVENT" and impact:
            triggers += list(cur.new_event_codes)
            parts.append("sự kiện: " + ", ".join(_lower_first(EVENT_LABELS_VI[c]) for c in cur.new_event_codes))
        became_div = prev is not None and cur.trajectory_state == "DIVERGING" and prev.trajectory_state != "DIVERGING"
        if became_div:
            triggers.append("BECAME_DIVERGING")
            parts.append(f"chuyển từ “{STATE_VI[prev.trajectory_state]}” sang “Lệch khỏi mục tiêu”")
        if dp <= R["sharp_drop"]:
            triggers.append("SHARP_DROP")
            parts.append(f"XS hoàn thành kế hoạch giảm {abs(dp) * 100:.0f} điểm % "
                         f"({_pct(prev.p_plan_completion)} → {_pct(cur.p_plan_completion)})")
        new_warn = (cur.predicted_academic_standing == "WARNING_LIKELY"
                    and (prev is None or prev.predicted_academic_standing != "WARNING_LIKELY"))
        if new_warn and prev is not None:
            triggers.append("STANDING_WARNING_NEW")
            parts.append(f"mới có nguy cơ cảnh báo học vụ (XS đạt yêu cầu {_pct(cur.p_satisfactory_standing)})")
        if not triggers:
            continue
        high = ((became_div and prev.trajectory_state == "ON_TRACK")
                or dp <= R["severe_drop"]
                or (cur.snapshot_type == "EVENT" and cur.trajectory_state == "DIVERGING" and dp < 0)
                or len(triggers) >= 3)
        out.append({
            "id": f"STUDENT:{sid}:{cur.snapshot_milestone}",
            "severity": "HIGH" if high else "MEDIUM",
            "scope": "STUDENT", "type": triggers[0],
            "title": f"Sinh viên {sid} ({cur.program_id}) – {STATE_VI[cur.trajectory_state]}",
            "detail": _sentence("; ".join(parts)),
            "snapshot": cur.snapshot_milestone, "snapshot_label": _label(cur),
            "week": int(cur.snapshot_week), "date": cur.snapshot_date,
            "owner": cur.recommended_owner if cur.recommended_owner != "NONE" else "ACADEMIC_ADVISOR",
            "students": [sid], "triggers": triggers,
            "metrics": {"p_plan": round(float(cur.p_plan_completion), 3), "delta_p": round(float(dp), 3)},
        })
    return out


# ------------------------------------------------------------------ groups
def _last_two_regular(t):
    weeks = sorted(t.loc[t.snapshot_type == "REGULAR", "snapshot_week"].unique())
    return (weeks[-1], weeks[-2]) if len(weeks) >= 2 else (weeks[-1] if weeks else None, None)


def program_alerts(t: pd.DataFrame) -> list[dict]:
    R = C.ALERT_RULES
    wl, wp = _last_two_regular(t)
    if wp is None:
        return []
    L = t[(t.snapshot_type == "REGULAR") & (t.snapshot_week == wl)]
    P = t[(t.snapshot_type == "REGULAR") & (t.snapshot_week == wp)]
    lrow = L.iloc[0]
    out = []
    for prog, gl in L.groupby("program_id"):
        gp = P[P.program_id == prog]
        if gp.empty:
            continue
        sl, sp = (gl.trajectory_state == "DIVERGING").mean(), (gp.trajectory_state == "DIVERGING").mean()
        nl, np_ = int((gl.trajectory_state == "DIVERGING").sum()), int((gp.trajectory_state == "DIVERGING").sum())
        rise = sl - sp
        if rise < R["program_rise_medium"] or nl - np_ < R["program_min_students"]:
            continue
        prev_div = set(gp.loc[gp.trajectory_state == "DIVERGING", "student_id_hash"])
        newly = [s for s in gl.loc[gl.trajectory_state == "DIVERGING", "student_id_hash"] if s not in prev_div]
        out.append({
            "id": f"PROGRAM:{prog}:{lrow.snapshot_milestone}",
            "severity": "HIGH" if rise >= R["program_rise_high"] else "MEDIUM",
            "scope": "PROGRAM", "type": "PROGRAM_DIVERGING_RISE",
            "title": f"Chương trình {prog}: tỷ lệ “Lệch khỏi mục tiêu” tăng {rise * 100:.0f} điểm %",
            "detail": (f"Từ {_pct(sp)} ({np_} SV) lên {_pct(sl)} ({nl} SV) giữa "
                       f"{C.MILESTONE_LABEL_VI.get(gp.iloc[0].snapshot_milestone)} và {_label(lrow)}; "
                       f"{len(newly)} sinh viên mới chuyển sang trạng thái này."),
            "snapshot": lrow.snapshot_milestone, "snapshot_label": _label(lrow),
            "week": int(wl), "date": lrow.snapshot_date, "owner": "PROGRAM_MANAGER",
            "students": newly, "triggers": ["PROGRAM_DIVERGING_RISE"],
            "metrics": {"share_now": round(float(sl), 3), "share_prev": round(float(sp), 3),
                        "n_now": nl, "n_prev": np_},
        })
    return out


def course_alerts(cp: pd.DataFrame, t: pd.DataFrame) -> list[dict]:
    R = C.ALERT_RULES
    wl, wp = _last_two_regular(t)
    if wl is None:
        return []
    act = cp[(cp.snapshot_type == "REGULAR") & (cp.approved_withdrawal_flag == 0)]
    L, P = act[act.snapshot_week == wl], act[act.snapshot_week == wp] if wp else act.iloc[0:0]
    lrow = t[(t.snapshot_type == "REGULAR") & (t.snapshot_week == wl)].iloc[0]
    out = []
    term_share = max(float((L.p_course_pass < 0.5).mean()), 1e-3)
    for crs, g in L.groupby("course_id"):
        if len(g) < R["course_min_students"]:
            continue
        share = (g.p_course_pass < 0.5).mean()
        n_risk = int((g.p_course_pass < 0.5).sum())
        if (share < R["course_risk_share_floor"] or share < R["course_risk_ratio"] * term_share
                or n_risk < R["course_min_at_risk"]):
            continue
        gp = P[P.course_id == crs]
        prev_share = (gp.p_course_pass < 0.5).mean() if len(gp) else None
        top = pd.Series([c for lst in g.loc[g.p_course_pass < 0.5, "support_reason_codes"] for c in lst])
        top_txt = ", ".join(_lower_first(REASON_LABELS_VI.get(c, c)) for c in top.value_counts().head(2).index)
        trend = f" (snapshot trước: {_pct(prev_share)})" if prev_share is not None else ""
        ratio_txt = f"{share / term_share:.1f}".replace(".", ",")
        out.append({
            "id": f"COURSE:{crs}:{lrow.snapshot_milestone}",
            "severity": "HIGH" if share >= R["course_risk_share_high"] or share >= 5 * term_share else "MEDIUM",
            "scope": "COURSE", "type": "COURSE_RISK_CLUSTER",
            "title": f"Học phần {crs}: {_pct(share)} sinh viên có xác suất đạt dưới 50%",
            "detail": (f"{n_risk}/{len(g)} sinh viên, gấp {ratio_txt} lần mức chung của học kỳ "
                       f"({_pct(term_share)}){trend}."
                       + (f" Lý do phổ biến: {top_txt}." if top_txt else "")
                       + " Nên trao đổi với giảng viên phụ trách về thiết kế đánh giá và hỗ trợ học tập."),
            "snapshot": lrow.snapshot_milestone, "snapshot_label": _label(lrow),
            "week": int(wl), "date": lrow.snapshot_date, "owner": "FACULTY",
            "students": sorted(g.loc[g.p_course_pass < 0.5, "student_id_hash"].unique().tolist()),
            "triggers": ["COURSE_RISK_CLUSTER"],
            "metrics": {"share": round(float(share), 3), "n": int(len(g)), "term_share": round(term_share, 3),
                        "share_prev": None if prev_share is None else round(float(prev_share), 3)},
        })
    return out


def data_alerts(cp: pd.DataFrame, t: pd.DataFrame) -> list[dict]:
    R = C.ALERT_RULES
    wl, _ = _last_two_regular(t)
    if wl is None:
        return []
    L = t[(t.snapshot_type == "REGULAR") & (t.snapshot_week == wl)]
    lrow = L.iloc[0]
    out = []
    ins = L.trajectory_state == "INSUFFICIENT_EVIDENCE"
    if ins.mean() >= R["dq_insufficient_share"]:
        out.append({
            "id": f"DATA:INSUFFICIENT:{lrow.snapshot_milestone}",
            "severity": "HIGH" if ins.mean() >= 2 * R["dq_insufficient_share"] else "MEDIUM",
            "scope": "DATA", "type": "INSUFFICIENT_EVIDENCE_SHARE",
            "title": f"{_pct(ins.mean())} sinh viên chưa đủ bằng chứng để dự báo",
            "detail": f"{int(ins.sum())} sinh viên bị cổng chất lượng Q1 đánh giá mức Thấp; cần kiểm tra đồng bộ dữ liệu.",
            "snapshot": lrow.snapshot_milestone, "snapshot_label": _label(lrow),
            "week": int(wl), "date": lrow.snapshot_date, "owner": "DATA_STEWARD",
            "students": L.loc[ins, "student_id_hash"].tolist(), "triggers": ["INSUFFICIENT_EVIDENCE_SHARE"],
            "metrics": {"share": round(float(ins.mean()), 3)},
        })
    cl = cp[(cp.snapshot_type == "REGULAR") & (cp.snapshot_week == wl)]
    for code in ["STALE_SOURCE", "SOURCE_CONFLICT", "LOW_ATTENDANCE_COVERAGE", "LOW_GRADE_COVERAGE",
                 "MISSING_REQUIRED_FIELDS"]:
        # measured on course enrolments: one lagging gradebook should not count once per student
        row_hit = cl.quality_issue_codes.apply(lambda x: code in x)
        if row_hit.mean() < R["dq_issue_share"]:
            continue
        hit = L.data_quality_issues.apply(lambda x: code in x)
        rows = cl[row_hit]
        top = rows.course_id.value_counts().head(5)
        out.append({
            "id": f"DATA:{code}:{lrow.snapshot_milestone}",
            "severity": "MEDIUM", "scope": "DATA", "type": code,
            "title": f"{REASON_LABELS_VI[code]} ở {_pct(row_hit.mean())} lượt học phần",
            "detail": (f"{int(row_hit.sum())}/{len(cl)} lượt đăng ký học phần, liên quan {int(hit.sum())} sinh viên. "
                       f"Học phần bị ảnh hưởng nhiều nhất (số lượt): {', '.join(f'{c} ({n})' for c, n in top.items())}."),
            "snapshot": lrow.snapshot_milestone, "snapshot_label": _label(lrow),
            "week": int(wl), "date": lrow.snapshot_date, "owner": "DATA_STEWARD",
            "students": L.loc[hit, "student_id_hash"].tolist(), "triggers": [code],
            "metrics": {"share_enrolments": round(float(row_hit.mean()), 3),
                        "share_students": round(float(hit.mean()), 3), "top_courses": top.to_dict()},
        })
    return out


def build_alerts(cp: pd.DataFrame, t: pd.DataFrame) -> list[dict]:
    alerts = student_alerts(t) + program_alerts(t) + course_alerts(cp, t) + data_alerts(cp, t)
    alerts.sort(key=lambda a: (a["severity"] != "HIGH", SCOPE_ORDER[a["scope"]], -len(a["students"])))
    return alerts
