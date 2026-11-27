"""R1 Academic Standing and R2 Trajectory State rule engines.

Rules are deterministic and readable, so advisors and Ban Đào tạo can audit
exactly why a state was assigned. Neither engine makes academic decisions; they
only route cases for human review.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from .synthetic import to_grade_point

Z90 = 1.2815515655446004  # standard-normal 90th percentile


# ------------------------------------------------------------------ R1
def simulate_term(courses: pd.DataFrame, prior_cum_gpa: float, prior_credits: float,
                  terms_completed: float, n_draws: int = 400, seed: int = 0) -> dict:
    """Monte Carlo over course outcomes -> GPA band and P(satisfactory standing).

    Each course: completion ~ Bernoulli(p_course_completion); score drawn from a
    split-normal through (Q10, Q50, Q90). Courses are treated as independent, so
    the GPA band is a little narrower than reality (documented limitation).
    """
    rng = np.random.default_rng(seed)
    cr = courses.course_credits.to_numpy(float)
    pc = courses.p_course_completion.to_numpy(float)
    lo, med, hi = (courses[c].to_numpy(float) for c in
                   ["predicted_score_lower", "predicted_final_score", "predicted_score_upper"])
    z = rng.standard_normal((n_draws, len(cr)))
    sd = np.where(z < 0, (med - lo) / Z90, (hi - med) / Z90)
    score = np.clip(med + z * sd, 0, 10)
    done = rng.random((n_draws, len(cr))) < pc
    gp = np.where(done, to_grade_point(score), 0.0)
    passed = done & (score >= C.PASS_SCORE)
    tot = cr.sum()
    term_gpa = (gp * cr).sum(1) / tot
    failed_share = ((~passed) * cr).sum(1) / tot

    R = C.STANDING_RULES
    term_min = R["term_gpa_min_first_term"] if terms_completed == 0 else R["term_gpa_min"]
    year = int(terms_completed // 2) + 1
    cum_min = R["cum_gpa_min_by_year"].get(year, 1.8)
    if prior_credits and not np.isnan(prior_cum_gpa):
        cum = (prior_cum_gpa * prior_credits + term_gpa * tot) / (prior_credits + tot)
    else:
        cum = term_gpa
    sat = (term_gpa >= term_min) & (cum >= cum_min) & (failed_share <= R["max_failed_credit_share"])
    p_sat = float(sat.mean())
    margin = float(np.median(np.minimum(term_gpa - term_min, cum - cum_min)))
    if p_sat < 0.5:
        standing = "WARNING_LIKELY"
    elif p_sat < 0.8 or margin < R["watch_margin"]:
        standing = "WATCH"
    else:
        standing = "SATISFACTORY"
    return dict(
        predicted_term_gpa=round(float(term_gpa.mean()), 2),
        predicted_term_gpa_lower=round(float(np.quantile(term_gpa, 0.10)), 2),
        predicted_term_gpa_upper=round(float(np.quantile(term_gpa, 0.90)), 2),
        p_satisfactory_standing=round(p_sat, 3),
        predicted_academic_standing=standing,
    )


# ------------------------------------------------------------------ R2
def trajectory_state(p_plan: float, gap: float, prev_p: float | None, prev_gap: float | None,
                     confidence: str, plan_adjusted: bool) -> str:
    """Assign one of the six states in spec section 7. Order of checks matters."""
    R = C.TRAJECTORY_RULES
    if confidence == "LOW":
        return "INSUFFICIENT_EVIDENCE"
    if plan_adjusted and p_plan >= R["plan_adjusted_min_p"]:
        return "PLAN_ADJUSTED"
    has_prev = prev_p is not None and not np.isnan(prev_p)
    dp = (p_plan - prev_p) if has_prev else 0.0
    dgap = (gap - prev_gap) if has_prev else 0.0
    on_track = p_plan >= R["on_track_p_plan"] and gap <= R["on_track_max_gap"]
    if has_prev and (dp <= -R["delta_p_change"] or dgap >= R["delta_gap_change"]) and not on_track:
        return "DIVERGING"
    if on_track:
        return "ON_TRACK"
    if has_prev and (dp >= R["delta_p_change"] or dgap <= -R["delta_gap_change"]):
        return "IMPROVING"
    if p_plan >= R["fragile_p_plan"]:
        return "STABLE_FRAGILE"
    return "DIVERGING"


def assign_trajectories(term: pd.DataFrame) -> pd.DataFrame:
    """Add previous-snapshot values, Δp and trajectory_state to a term frame."""
    t = term.sort_values(["student_id_hash", "term_id", "snapshot_week"]).copy()
    g = t.groupby(["student_id_hash", "term_id"], sort=False)
    t["previous_p_plan_completion"] = g.p_plan_completion.shift(1)
    t["previous_progress_gap_credits"] = g.progress_gap_credits.shift(1)
    t["delta_p_plan"] = t.p_plan_completion - t.previous_p_plan_completion
    t["trajectory_state"] = [
        trajectory_state(p, gp, pp, pg, conf, bool(adj))
        for p, gp, pp, pg, conf, adj in zip(
            t.p_plan_completion, t.progress_gap_credits, t.previous_p_plan_completion,
            t.previous_progress_gap_credits, t.data_confidence,
            (t.reduced_load_flag == 1) | (t.withdrawn_credits > 0))
    ]
    return t
