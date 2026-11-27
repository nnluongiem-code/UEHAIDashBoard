"""End-to-end pipeline: prepare -> train M1-M4 -> validate -> score -> export.

Temporal design (no leakage across terms):
    TRAIN_TERMS        fit CatBoost (with student-grouped out-of-fold predictions
                       for stacking into M4)
    CALIBRATION_TERMS  fit isotonic calibrators and the conformal margin
    TEST_TERMS         untouched; every number on the model card comes from here
    CURRENT_TERM       scored for the dashboard (no labels yet)

Models are trained on the regular milestones only. Weekly monitoring feeds are
turned into event-triggered snapshots (events.py) and scored by the same models,
which take the teaching week as a numeric input.
"""
from __future__ import annotations

import json
import pickle
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

from . import config as C
from . import evaluate as E
from .features import (CAT_FEATURES, COURSE_FEATURES, TERM_CAT_FEATURES, TERM_FEATURES,
                       add_course_derived, build_term_frame)
from .alerts import build_alerts
from .events import EVENT_LABELS_VI, apply_event_snapshots
from .models import CalibratedCatBoostClassifier, ConformalQuantileRegressor
from .quality import course_quality, student_confidence
from .reasons import (COURSE_REASON_MAP, REASON_LABELS_VI, TERM_REASON_MAP,
                      reason_codes, recommended_owner)
from .rules import assign_trajectories, simulate_term


@dataclass
class Bundle:
    m1: CalibratedCatBoostClassifier
    m2: CalibratedCatBoostClassifier
    m3: ConformalQuantileRegressor
    m4: CalibratedCatBoostClassifier
    metrics: dict = field(default_factory=dict)

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path: Path) -> "Bundle":
        with open(path, "rb") as f:
            return pickle.load(f)


def prepare(course_df: pd.DataFrame) -> pd.DataFrame:
    return course_quality(add_course_derived(course_df))


# ------------------------------------------------------------------ course level
def _predict_course(m1, m2, m3, X, raw1=None, raw2=None, q=None) -> pd.DataFrame:
    out = X.copy()
    p1 = m1.apply_calibration(m1.raw_proba(X) if raw1 is None else raw1)
    p2 = m2.apply_calibration(m2.raw_proba(X) if raw2 is None else raw2)
    lo, med, hi = m3.predict(X) if q is None else q
    out["p_course_completion"] = p1
    out["p_course_pass_given_completion"] = p2
    out["p_course_pass"] = np.clip(p1 * p2, 0.01, 0.99)  # spec section 5
    out["predicted_final_score"] = med
    out["predicted_score_lower"] = lo
    out["predicted_score_upper"] = hi
    return out


def _oof_course(train: pd.DataFrame, log) -> pd.DataFrame:
    """Student-grouped out-of-fold course predictions on the training terms."""
    raw1 = np.zeros(len(train)); raw2 = np.zeros(len(train)); q = np.zeros((len(train), 3))
    gkf = GroupKFold(n_splits=C.OOF_FOLDS)
    for k, (tr, va) in enumerate(gkf.split(train, groups=train.student_id_hash)):
        log(f"  OOF fold {k + 1}/{C.OOF_FOLDS}")
        a, b = train.iloc[tr], train.iloc[va]
        a1 = a[a.approved_withdrawal_flag == 0]
        a2 = a1[a1.course_completed_flag == 1]
        f1 = CalibratedCatBoostClassifier(COURSE_FEATURES, CAT_FEATURES).fit(a1, a1.course_completed_flag)
        f2 = CalibratedCatBoostClassifier(COURSE_FEATURES, CAT_FEATURES).fit(a2, a2.course_pass_flag)
        f3 = ConformalQuantileRegressor(COURSE_FEATURES, CAT_FEATURES).fit(a2, a2.course_final_score)
        raw1[va], raw2[va], q[va] = f1.raw_proba(b), f2.raw_proba(b), f3.raw_predict(b)
    return raw1, raw2, q


def _term_with_labels(course_pred, term_labels):
    t = build_term_frame(course_pred)
    return t.merge(term_labels, on=["student_id_hash", "term_id"], how="left")


# ------------------------------------------------------------------ training
def train(course_df: pd.DataFrame, term_df: pd.DataFrame, log=print) -> Bundle:
    df = prepare(course_df)
    if "snapshot_type" not in df.columns:
        df["snapshot_type"] = "REGULAR"
    reg = df[df.snapshot_type == "REGULAR"]
    tr = reg[reg.term_id.isin(C.TRAIN_TERMS)].reset_index(drop=True)
    ca = reg[reg.term_id.isin(C.CALIBRATION_TERMS)].reset_index(drop=True)
    te = reg[reg.term_id.isin(C.TEST_TERMS)].reset_index(drop=True)
    te_all = df[df.term_id.isin(C.TEST_TERMS)].reset_index(drop=True)
    log(f"rows: train={len(tr):,} calibration={len(ca):,} test={len(te):,}")

    log("M1-M3 out-of-fold predictions for stacking ...")
    oof1, oof2, oofq = _oof_course(tr, log)

    log("M1-M3 final fit ...")
    tr1 = tr[tr.approved_withdrawal_flag == 0]; tr2 = tr1[tr1.course_completed_flag == 1]
    m1 = CalibratedCatBoostClassifier(COURSE_FEATURES, CAT_FEATURES).fit(tr1, tr1.course_completed_flag)
    m2 = CalibratedCatBoostClassifier(COURSE_FEATURES, CAT_FEATURES).fit(tr2, tr2.course_pass_flag)
    m3 = ConformalQuantileRegressor(COURSE_FEATURES, CAT_FEATURES).fit(tr2, tr2.course_final_score)
    ca1 = ca[ca.approved_withdrawal_flag == 0]; ca2 = ca1[ca1.course_completed_flag == 1]
    m1.calibrate(ca1, ca1.course_completed_flag, groups=ca1.student_id_hash)
    m2.calibrate(ca2, ca2.course_pass_flag, groups=ca2.student_id_hash)
    m3.calibrate(ca2, ca2.course_final_score)
    log(f"  conformal margin = {m3.conformal_margin:.3f} points")

    # stacked course predictions for each split
    lo, med, hi = (np.clip(oofq[:, 0] - m3.conformal_margin, 0, 10), oofq[:, 1],
                   np.clip(oofq[:, 2] + m3.conformal_margin, 0, 10))
    cp_tr = _predict_course(m1, m2, m3, tr, oof1, oof2, (lo, np.clip(med, lo, hi), hi))
    cp_ca = _predict_course(m1, m2, m3, ca)
    cp_te = _predict_course(m1, m2, m3, te)

    log("M4 plan completion ...")
    t_tr, t_ca, t_te = (_term_with_labels(x, term_df) for x in (cp_tr, cp_ca, cp_te))
    lab = "approved_plan_completed_flag"
    t_tr, t_ca = t_tr.dropna(subset=[lab]), t_ca.dropna(subset=[lab])
    m4 = CalibratedCatBoostClassifier(TERM_FEATURES, TERM_CAT_FEATURES).fit(t_tr, t_tr[lab])
    m4.calibrate(t_ca, t_ca[lab], groups=t_ca.student_id_hash)

    bundle = Bundle(m1, m2, m3, m4)
    log("validating on the test term ...")
    bundle.metrics = validate(bundle, cp_te, t_te)
    bundle.metrics["events"] = validate_events(bundle, te_all, term_df)
    return bundle


# ------------------------------------------------------------------ validation
def validate(b: Bundle, cp: pd.DataFrame, t: pd.DataFrame) -> dict:
    M = {"test_terms": C.TEST_TERMS, "train_terms": C.TRAIN_TERMS,
         "calibration_terms": C.CALIBRATION_TERMS}
    c1 = cp[cp.approved_withdrawal_flag == 0]
    c2 = c1[c1.course_completed_flag == 1]
    M["M1_course_completion"] = E.classifier_metrics(
        c1.course_completed_flag, c1.p_course_completion, b.m1.raw_proba(c1))
    M["M2_course_attainment"] = E.classifier_metrics(
        c2.course_pass_flag, c2.p_course_pass_given_completion, b.m2.raw_proba(c2))
    M["course_pass_overall"] = E.classifier_metrics(c1.course_pass_flag, c1.p_course_pass)
    M["M3_final_score"] = E.quantile_metrics(c2.course_final_score, c2.predicted_score_lower,
                                             c2.predicted_final_score, c2.predicted_score_upper)
    M["M3_by_milestone"] = [
        dict(group=ms, **E.quantile_metrics(d.course_final_score, d.predicted_score_lower,
                                            d.predicted_final_score, d.predicted_score_upper))
        for ms, d in c2.groupby("snapshot_milestone", sort=False)]

    lab = "approved_plan_completed_flag"
    t = t.dropna(subset=[lab]).copy()
    t["p_plan_completion"] = b.m4.predict_proba(t)
    M["M4_plan_completion"] = E.classifier_metrics(t[lab], t.p_plan_completion, b.m4.raw_proba(t))
    M["M4_by_milestone"] = E.by_group(t, "snapshot_milestone", lab, "p_plan_completion")
    M["M4_by_program"] = E.by_group(t, "program_id", lab, "p_plan_completion")
    M["M1_by_program"] = E.by_group(c1, "program_id", "course_completed_flag", "p_course_completion")
    order = {m: i for i, m in enumerate(C.MILESTONES)}
    M["M4_by_milestone"].sort(key=lambda r: order[r["group"]])
    # simple baselines so the gain from the model is visible
    M["M4_baselines"] = {
        "prior_cum_gpa_only_auc": round(float(roc_auc_score(
            t[lab], t.prior_cum_gpa.fillna(t.prior_cum_gpa.median()))), 3),
        "mean_current_score_only_auc": round(float(roc_auc_score(
            t[lab], t.mean_current_score.fillna(t.mean_current_score.median()))), 3),
    }

    # trajectory states on the test term vs what actually happened
    t["data_confidence"] = _student_confidence(cp, t)
    st = assign_trajectories(t)
    M["state_outcomes"] = [
        dict(state=s, n=int(len(d)), plan_completed_rate=round(float(d[lab].mean()), 3),
             mean_p_plan=round(float(d.p_plan_completion.mean()), 3))
        for s, d in st.groupby("trajectory_state")]

    # R1 standing probability vs observed standing (final pre-exam snapshot)
    last = st[st.snapshot_milestone == C.MILESTONES[-1]]
    sims = _simulate(cp, last)
    lab2 = "satisfactory_academic_standing_flag"
    j = last[["student_id_hash", lab2, "semester_gpa"]].join(sims.set_index(last.index))
    j = j.dropna(subset=[lab2])
    M["R1_standing"] = E.classifier_metrics(j[lab2], j.p_satisfactory_standing)
    M["R1_term_gpa"] = dict(
        mae=round(float(np.mean(np.abs(j.semester_gpa - j.predicted_term_gpa))), 3),
        coverage_80=round(float(np.mean((j.semester_gpa >= j.predicted_term_gpa_lower)
                                        & (j.semester_gpa <= j.predicted_term_gpa_upper))), 3))
    M["feature_importance"] = {
        k: {f: round(float(v), 2) for f, v in m.feature_importance().head(12).items()}
        for k, m in [("M1", b.m1), ("M2", b.m2), ("M3", b.m3), ("M4", b.m4)]}
    M["conformal_margin"] = round(b.m3.conformal_margin, 3)
    M["calibration_methods"] = {"M1": b.m1.calibration_method, "M2": b.m2.calibration_method,
                                "M4": b.m4.calibration_method}
    M["calibration_cv"] = {k: getattr(m, "calibration_cv", None)
                           for k, m in [("M1", b.m1), ("M2", b.m2), ("M4", b.m4)]}
    return M


def validate_events(b: Bundle, te_all: pd.DataFrame, term_labels: pd.DataFrame) -> dict:
    """How useful are event-triggered snapshots on the (labelled) test term?"""
    f, info = apply_event_snapshots(te_all)
    if (f.snapshot_type == "EVENT").sum() == 0:
        return {"n_event_snapshots": 0}
    cp = _predict_course(b.m1, b.m2, b.m3, f)
    t = _term_with_labels(cp, term_labels)
    t["p_plan_completion"] = b.m4.predict_proba(t)
    t["data_confidence"] = _student_confidence(cp, t)
    t = assign_trajectories(t)
    lab = "approved_plan_completed_flag"
    ev = t[t.snapshot_type == "EVENT"].dropna(subset=[lab])
    students_ev = set(ev.student_id_hash)
    per_student = t.drop_duplicates("student_id_hash").dropna(subset=[lab])
    with_ev = per_student[per_student.student_id_hash.isin(students_ev)]
    without = per_student[~per_student.student_id_hash.isin(students_ev)]
    codes: dict[str, int] = {}
    for k, v in info.items():
        if k[2].startswith(C.EVENT_LABEL_PREFIX):
            for c in v["new"]:
                codes[c] = codes.get(c, 0) + 1
    # weeks of lead time: event week vs the next regular milestone it precedes
    reg_weeks = sorted(C.MILESTONE_WEEK.values())
    lead = [min([w for w in reg_weeks if w > wk], default=wk + 1) - wk for wk in ev.snapshot_week]
    return {
        "n_event_snapshots": int(len(ev)),
        "n_students_with_event": int(len(students_ev)),
        "share_students_with_event": round(len(students_ev) / max(1, len(per_student)), 3),
        "plan_completed_rate_with_event": round(float(with_ev[lab].mean()), 3) if len(with_ev) else None,
        "plan_completed_rate_without_event": round(float(without[lab].mean()), 3) if len(without) else None,
        "auc_at_event_snapshots": round(float(roc_auc_score(ev[lab], ev.p_plan_completion)), 3)
        if ev[lab].nunique() > 1 else None,
        "mean_delta_p_at_event": round(float(ev.delta_p_plan.mean()), 3),
        "mean_lead_weeks": round(float(np.mean(lead)), 2),
        "codes": codes,
        "by_week": {str(int(w)): int(n) for w, n in ev.snapshot_week.value_counts().sort_index().items()},
    }


def _student_confidence(cp, t):
    conf = cp.groupby(["student_id_hash", "term_id", "snapshot_milestone"]) \
        .data_confidence.apply(student_confidence)
    return t.set_index(["student_id_hash", "term_id", "snapshot_milestone"]).index.map(conf)


def _simulate(cp, term_rows):
    g = {k: d for k, d in cp[cp.approved_withdrawal_flag == 0]
         .groupby(["student_id_hash", "term_id", "snapshot_milestone"])}
    rows = []
    for i, r in enumerate(term_rows.itertuples()):
        d = g[(r.student_id_hash, r.term_id, r.snapshot_milestone)]
        rows.append(simulate_term(d, r.prior_cum_gpa, d.prior_attempted_credits.iloc[0],
                                  r.terms_completed, seed=i))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ scoring
def score(b: Bundle, course_df: pd.DataFrame, term_id: str = C.CURRENT_TERM):
    """Score one term at every available snapshot -> (course_out, student_out)."""
    df = prepare(course_df[course_df.term_id == term_id]).reset_index(drop=True)
    df, event_info = apply_event_snapshots(df)
    cp = _predict_course(b.m1, b.m2, b.m3, df)
    # an approved withdrawal is never scored as a failure
    wd = cp.approved_withdrawal_flag == 1
    cp.loc[wd, ["p_course_completion", "p_course_pass_given_completion", "p_course_pass"]] = np.nan

    # course-level reason codes from the attainment model
    shap2 = b.m2.shap_values(cp) + b.m1.shap_values(cp)
    cp["positive_reason_codes"], cp["support_reason_codes"] = reason_codes(
        shap2, cp, COURSE_REASON_MAP, n_support=2, n_positive=1)

    t = build_term_frame(cp)
    t["p_plan_completion"] = b.m4.predict_proba(t)
    t["data_confidence"] = _student_confidence(cp, t)
    t = assign_trajectories(t).reset_index(drop=True)
    t = pd.concat([t, _simulate(cp, t)], axis=1)

    pos, sup = reason_codes(b.m4.shap_values(t), t, TERM_REASON_MAP)
    reg = cp.groupby(["student_id_hash", "snapshot_milestone"]).registration_incomplete_flag.max()
    keys = list(zip(t.student_id_hash, t.snapshot_milestone))
    sup = [(["REGISTRATION_INCOMPLETE"] if reg.get(k, 0) else []) + s for k, s in zip(keys, sup)]
    t["positive_reason_codes"], t["support_reason_codes"] = pos, sup
    ek = list(zip(t.student_id_hash, t.term_id, t.snapshot_milestone))
    t["critical_event_codes"] = [event_info.get(k, {}).get("active", []) for k in ek]
    t["new_event_codes"] = [event_info.get(k, {}).get("new", []) for k in ek]
    t["recommended_owner"] = [recommended_owner(s, c, e) for s, c, e
                              in zip(t.trajectory_state, sup, t.new_event_codes)]
    t["review_status"] = np.where(t.recommended_owner == "NONE", "NO_ACTION", "NEW")
    q = cp.groupby(["student_id_hash", "snapshot_milestone"]).quality_issue_codes \
        .apply(lambda s: sorted({c for lst in s for c in lst}))
    t["data_quality_issues"] = [q.get(k, []) for k in keys]
    return cp, t


# ------------------------------------------------------------------ export
def _r(x, n=3):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


def course_records(cp: pd.DataFrame, t: pd.DataFrame) -> list[dict]:
    """Flat course-level records in exactly the spec section 11 schema (+course_id)."""
    tt = t.set_index(["student_id_hash", "snapshot_milestone"])
    out = []
    for r in cp.itertuples():
        s = tt.loc[(r.student_id_hash, r.snapshot_milestone)]
        out.append({
            "student_id_hash": r.student_id_hash, "term_id": r.term_id,
            "course_id": r.course_id, "snapshot_milestone": r.snapshot_milestone,
            "snapshot_type": r.snapshot_type, "snapshot_date": r.snapshot_date,
            "model_version": C.MODEL_VERSION,
            "p_course_completion": _r(r.p_course_completion, 2),
            "p_course_pass": _r(r.p_course_pass, 2),
            "predicted_final_score": _r(r.predicted_final_score, 1),
            "predicted_score_lower": _r(r.predicted_score_lower, 1),
            "predicted_score_upper": _r(r.predicted_score_upper, 1),
            "expected_earned_credits": _r(s.expected_earned_credits, 1),
            "approved_plan_credits": int(s.approved_plan_credits),
            "p_plan_completion": _r(s.p_plan_completion, 2),
            "progress_gap_credits": _r(s.progress_gap_credits, 1),
            "previous_p_plan_completion": _r(s.previous_p_plan_completion, 2),
            "trajectory_state": s.trajectory_state,
            "data_confidence": s.data_confidence,
            "critical_event_codes": list(s.critical_event_codes),
            "positive_reason_codes": list(r.positive_reason_codes),
            "support_reason_codes": list(r.support_reason_codes),
            "recommended_owner": s.recommended_owner,
            "review_status": s.review_status,
        })
    return out


def dashboard_payload(b: Bundle, cp: pd.DataFrame, t: pd.DataFrame, alerts: list) -> dict:
    """Compact nested structure for the dashboard: one entry per student."""
    t = t.sort_values(["student_id_hash", "snapshot_week"])
    cg = {k: d for k, d in cp.groupby(["student_id_hash", "snapshot_milestone"])}
    students = {}
    for r in t.itertuples():
        st = students.setdefault(r.student_id_hash, {
            "id": r.student_id_hash, "program": r.program_id,
            "prior_cum_gpa": _r(r.prior_cum_gpa, 2), "terms_completed": int(r.terms_completed),
            "snapshots": {}, "timeline": []})
        st["timeline"].append(r.snapshot_milestone)  # t is sorted by week
        d = cg[(r.student_id_hash, r.snapshot_milestone)]
        st["snapshots"][r.snapshot_milestone] = {
            "week": int(r.snapshot_week), "type": r.snapshot_type, "date": r.snapshot_date,
            "ev": r.critical_event_codes, "ev_new": r.new_event_codes,
            "p_plan": _r(r.p_plan_completion), "prev_p_plan": _r(r.previous_p_plan_completion),
            "exp_credits": _r(r.expected_earned_credits, 1),
            "plan_credits": int(r.approved_plan_credits),
            "gap": _r(r.progress_gap_credits, 1),
            "gpa": _r(r.predicted_term_gpa, 2), "gpa_lo": _r(r.predicted_term_gpa_lower, 2),
            "gpa_hi": _r(r.predicted_term_gpa_upper, 2),
            "p_standing": _r(r.p_satisfactory_standing), "standing": r.predicted_academic_standing,
            "state": r.trajectory_state, "conf": r.data_confidence,
            "pos": r.positive_reason_codes, "sup": r.support_reason_codes,
            "dq": r.data_quality_issues, "owner": r.recommended_owner, "review": r.review_status,
            "courses": [{
                "id": c.course_id, "cr": int(c.course_credits), "mode": c.delivery_mode,
                "wd": int(c.approved_withdrawal_flag),
                "pc": _r(c.p_course_completion, 2), "pp": _r(c.p_course_pass, 2),
                "q50": _r(c.predicted_final_score, 1), "q10": _r(c.predicted_score_lower, 1),
                "q90": _r(c.predicted_score_upper, 1),
                "cur": _r(c.current_weighted_score, 1), "cov": _r(c.graded_coverage, 2),
                "att": _r(c.attendance_rate, 2), "lms": _r(c.lms_required_completion, 2),
                "miss": int(c.mandatory_missing_count), "late": int(c.missing_or_late_count),
                "conf": c.data_confidence, "sup": c.support_reason_codes,
                "pos": c.positive_reason_codes,
            } for c in d.itertuples()],
        }
    milestones = [m for m in C.MILESTONES if m in set(t.snapshot_milestone)]
    return {
        "meta": {"model_name": C.MODEL_NAME, "model_version": C.MODEL_VERSION,
                 "term_id": str(t.term_id.iloc[0]), "generated": date.today().isoformat(),
                 "milestones": milestones, "milestone_labels": C.MILESTONE_LABEL_VI,
                 "milestone_weeks": C.MILESTONE_WEEK, "current_week": int(t.snapshot_week.max()),
                 "as_of_date": str(t.snapshot_date.max()),
                 "synthetic_data": True, "thresholds": C.TRAJECTORY_RULES,
                 "event_rules": C.EVENT_RULES, "alert_rules": C.ALERT_RULES,
                 "pass_score": C.PASS_SCORE},
        "reason_labels": {**REASON_LABELS_VI, **EVENT_LABELS_VI},
        "metrics": b.metrics,
        "alerts": alerts,
        "students": list(students.values()),
    }


def write_outputs(b: Bundle, cp, t, out_dir: Path, dashboard_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    recs = course_records(cp, t)
    with open(out_dir / "predictions_course.jsonl", "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(out_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(b.metrics, f, ensure_ascii=False, indent=2)
    alerts = build_alerts(cp, t)
    with open(out_dir / "alerts.json", "w", encoding="utf-8") as f:
        json.dump(alerts, f, ensure_ascii=False, indent=1)  # input for the future e-mail digest
    payload = dashboard_payload(b, cp, t, alerts)
    with open(out_dir / "dashboard_payload.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    with open(dashboard_dir / "data.js", "w", encoding="utf-8") as f:
        f.write("window.UEH_DATA=")
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")
    return len(recs), len(payload["students"])
