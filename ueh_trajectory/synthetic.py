"""Synthetic UEH-like data so the pipeline can run end to end before real data exists.

The generator follows the data contract in spec section 9: one row per
student x course x term x snapshot, plus one row per student x term. Behaviour is
driven by hidden variables (ability, engagement, per-term shocks and a within-term
drift), so later snapshots are more informative than early ones, as they would be
in real data.

Nothing here is real student data. Replace `generate()` with the institutional
extract (SIS + LMS + attendance) once the data-sharing agreement is in place.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from . import config as C

PROGRAMS = ["ECO", "FIN", "ACC", "MKT", "BUS", "ITE", "LAW", "LOG"]
DELIVERY = ["IN_PERSON", "BLENDED", "ONLINE"]


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def to_grade_point(score):
    """Vectorised 10-point -> 4-point conversion (NaN stays NaN)."""
    s = np.asarray(score, dtype=float)
    out = np.full(s.shape, np.nan)
    for lo, gp in reversed(C.GRADE_BANDS):
        out = np.where(s >= lo, gp, out)
    return out


def snapshot_date(term: str, week: int) -> str:
    """Friday of the given teaching week (term start dates live in config)."""
    start = pd.Timestamp(C.TERM_START[term])
    return (start + pd.Timedelta(days=7 * (week - 1) + 4)).date().isoformat()


def _snapshot_specs(term: str):
    """Regular milestones plus weekly monitoring feeds (test + current term only).

    Monitoring rows are what the event detector reads between milestones; only
    the ones that trigger an event become scored EVENT snapshots.
    """
    current = term == C.CURRENT_TERM
    specs = [(ms, C.MILESTONE_WEEK[ms], "REGULAR") for ms in C.MILESTONES
             if not current or ms in C.CURRENT_TERM_MILESTONES]
    if current or term in C.TEST_TERMS:
        specs += [(f"MONITOR_W{w:02d}", w, "MONITOR") for w in C.MONITORING_WEEKS
                  if not current or w <= C.CURRENT_WEEK]
    return sorted(specs, key=lambda x: x[1])


def _hash(i: int) -> str:
    return "S" + hashlib.sha256(f"ueh-demo-{i}".encode()).hexdigest()[:8].upper()


def _course_catalog(rng, n=72):
    df = pd.DataFrame({
        "course_id": [f"{PROGRAMS[i % 8]}{100 + i}" for i in range(n)],
        "course_difficulty": rng.normal(0, 0.5, n),
        "course_credits": rng.choice([2, 3, 3, 3, 4], n),
        "delivery_mode": rng.choice(DELIVERY, n, p=[0.55, 0.35, 0.10]),
    })
    # LMS only counts when the course is actually designed around it (spec 9.4)
    df["lms_designed"] = np.where(df.delivery_mode == "IN_PERSON", rng.random(n) < 0.4, True)
    return df


def generate(n_students: int = 1100, seed: int = 7):
    rng = np.random.default_rng(seed)
    catalog = _course_catalog(rng)
    T = len(C.TERMS)

    stu = pd.DataFrame({
        "sid": np.arange(n_students),
        "program_id": rng.choice(PROGRAMS, n_students),
        "ability": rng.normal(0, 1, n_students),
        "conscientious": rng.normal(0, 1, n_students),
        # index of first term in the window; negatives started before 2023.1
        "start": rng.choice([-4, -2, 0, 2, 4, 6], n_students, p=[.15, .2, .2, .15, .15, .15]),
    })
    stu["student_id_hash"] = [_hash(i) for i in stu.sid]

    # running academic history (credits attempted/earned, quality points ...)
    hist = {k: np.zeros(n_students) for k in
            ["att", "earned", "qp", "qp_cred", "failed", "repeat", "terms", "warn"]}
    last_gpa = np.full(n_students, np.nan)
    # students who started before the window get a synthetic prior record
    pre = stu.start.values < 0
    n_pre_terms = -stu.start.values.clip(max=0)
    base_gpa = np.clip(2.7 + 0.55 * stu.ability.values + 0.2 * stu.conscientious.values
                       + rng.normal(0, .3, n_students), 0.5, 4.0)
    hist["terms"][pre] = n_pre_terms[pre]
    hist["att"][pre] = 17 * n_pre_terms[pre]
    hist["earned"][pre] = hist["att"][pre] * np.clip(0.75 + 0.08 * base_gpa[pre], 0, 1)
    hist["qp"][pre] = base_gpa[pre] * hist["att"][pre]
    hist["qp_cred"][pre] = hist["att"][pre]
    hist["failed"][pre] = rng.poisson(np.clip(2.5 - base_gpa[pre], 0.05, None))
    last_gpa[pre] = np.clip(base_gpa[pre] + rng.normal(0, .3, pre.sum()), 0, 4)

    course_rows, term_rows = [], []
    for t, term in enumerate(C.TERMS):
        active = (stu.start.values <= t) & (t - stu.start.values < 8)
        # approved leave / exchange: no term record, never counted as failure
        on_leave = rng.random(n_students) < 0.03
        active &= ~on_leave
        idx = np.where(active)[0]
        if len(idx) == 0:
            continue
        shock = rng.normal(0, 0.5, n_students)          # life events this term
        drift = rng.normal(0, 0.45, n_students)         # change within the term
        reduced = rng.random(n_students) < 0.05         # approved reduced load
        # record-level sync failure (e.g. program transfer not yet reflected):
        # hits every course of the student at once, as real SIS breakages do
        sync_issue = rng.random(n_students) < 0.03
        # mid-term crisis (illness, family, work): engagement drops from a given week
        crisis = rng.random(n_students) < 0.06
        crisis_week = rng.integers(5, 12, n_students)
        crisis_absent = rng.random(n_students) < 0.75
        # registration not finalised at term start, fixed some weeks later
        reg_incomplete = rng.random(n_students) < 0.015
        reg_fixed_week = rng.integers(5, 13, n_students)

        for i in idx:
            k = rng.integers(3, 5) if reduced[i] else rng.integers(5, 8)
            cidx = rng.choice(len(catalog), k, replace=False)
            courses = catalog.iloc[cidx]
            reg_credits = courses.course_credits.sum()
            prev = dict(
                prior_term_gpa=last_gpa[i],
                prior_cum_gpa=hist["qp"][i] / hist["qp_cred"][i] if hist["qp_cred"][i] else np.nan,
                prior_earned_ratio=hist["earned"][i] / hist["att"][i] if hist["att"][i] else np.nan,
                prior_failed_courses=hist["failed"][i],
                prior_repeat_courses=hist["repeat"][i],
                prior_warning_flag=int(hist["warn"][i] > 0),
                terms_completed=hist["terms"][i],
                prior_attempted_credits=hist["qp_cred"][i],
            )
            a, c = stu.ability.values[i], stu.conscientious.values[i]
            e_term = 0.6 * c + 0.3 * a + shock[i]
            term_earned = term_qp = term_qp_cred = term_failed_cred = wd_credits = 0.0
            n_failed = 0
            for _, crs in courses.iterrows():
                section_attn_cov = rng.choice([1.0, rng.uniform(0.3, 0.7)], p=[0.9, 0.1])
                if sync_issue[i]:
                    section_attn_cov = rng.uniform(0.1, 0.5)
                lecturer_lag = rng.choice([1.0, 0.5], p=[0.85, 0.15])  # late grade entry
                stale = sync_issue[i] or rng.random() < 0.08
                conflict = (sync_issue[i] and rng.random() < 0.7) or rng.random() < 0.03
                e_final = e_term + drift[i] - (1.1 if crisis[i] else 0.0)
                z = 0.8 * a + 0.45 * e_final - crs.course_difficulty + rng.normal(0, 0.35)
                true_score = float(np.clip(6.9 + 1.5 * z + rng.normal(0, 0.7), 0, 10))
                approved_wd = rng.random() < 0.01
                p_drop = _sigmoid(-4.0 - 1.4 * e_final - 0.5 * a)
                completed = (not approved_wd) and (rng.random() > p_drop)
                passed = completed and true_score >= C.PASS_SCORE
                final_score = true_score if completed else np.nan

                for ms, week, stype in _snapshot_specs(term):
                    frac = (week - 4) / 10.0
                    in_crisis = crisis[i] and week >= crisis_week[i]
                    e_m = e_term + drift[i] * frac - (1.6 if in_crisis else 0.0)
                    cov = float(np.clip(np.interp(week, [4, 8, 10, 14], [0.1, 0.4, 0.5, 0.6]) * lecturer_lag
                                        + rng.normal(0, 0.03), 0, 1))
                    noise_sd = 1.9 * (1 - cov) + 0.35
                    partial = true_score - drift[i] * (1 - frac) * 1.2
                    cur_score = np.clip(partial + rng.normal(0, noise_sd), 0, 10) if cov > 0.05 else np.nan
                    if week > 4:
                        trend = drift[i] * 1.5 + rng.normal(0, 0.5) - (1.6 if in_crisis else 0.0)
                    else:
                        trend = np.nan
                    n_assign = int(round(2 + (week - 4) * 0.6))
                    late = rng.binomial(n_assign, _sigmoid(-1.8 - 1.1 * e_m))
                    mand_missing = rng.binomial(1 + (week - 4) // 3, _sigmoid(-3.3 - 1.3 * e_m))
                    att_rate = float(np.clip(_sigmoid(2.1 + 1.2 * e_m + rng.normal(0, .4)), 0, 1))
                    consec = int(rng.poisson(max(0.05, (1 - att_rate) * week * 0.12)))
                    if in_crisis and crisis_absent[i]:
                        consec = max(consec, week - crisis_week[i] + 1)
                    att_cov = float(np.clip(section_attn_cov + rng.normal(0, .02), 0, 1))
                    if crs.lms_designed:
                        lms = float(np.clip(_sigmoid(1.0 + 1.3 * e_m + rng.normal(0, .5)), 0, 1))
                        lms_cov = float(np.clip(rng.normal(0.92, .05), 0, 1))
                    else:
                        lms, lms_cov = np.nan, 0.0
                    row = dict(
                        student_id_hash=stu.student_id_hash.values[i],
                        term_id=term, term_index=t,
                        program_id=stu.program_id.values[i],
                        course_id=crs.course_id,
                        section_id=f"{crs.course_id}-{term}-{rng.integers(1, 4):02d}",
                        snapshot_milestone=ms, snapshot_week=week, snapshot_type=stype,
                        snapshot_date=snapshot_date(term, week),
                        course_credits=int(crs.course_credits),
                        delivery_mode=crs.delivery_mode,
                        **prev,
                        term_registered_credits=int(reg_credits),
                        approved_plan_credits=int(reg_credits),
                        reduced_load_flag=int(reduced[i]),
                        current_weighted_score=cur_score,
                        graded_coverage=cov,
                        missing_or_late_count=late,
                        mandatory_missing_count=mand_missing,
                        recent_score_trend=trend,
                        sessions_held=week,
                        attendance_data_sessions=round(week * att_cov),
                        attendance_rate=att_rate if att_cov > 0.2 else np.nan,
                        consecutive_absence_count=consec,
                        lms_required_completion=lms,
                        lms_data_coverage=lms_cov,
                        days_since_source_update=int(rng.integers(15, 40) if stale else rng.integers(0, 7)),
                        required_field_completeness=float(np.clip(rng.normal(.75 if sync_issue[i] else .97, .05), .5, 1)),
                        source_conflict_flag=int(conflict),
                        registration_incomplete_flag=int(reg_incomplete[i] and week < reg_fixed_week[i]),
                        approved_withdrawal_flag=int(approved_wd),
                    )
                    if term != C.CURRENT_TERM:
                        row.update(course_completed_flag=int(completed),
                                   course_pass_flag=int(passed),
                                   course_final_score=final_score)
                    course_rows.append(row)

                # roll up the realised outcome
                if approved_wd:
                    wd_credits += crs.course_credits
                else:
                    gp = float(to_grade_point([true_score])[0]) if completed else 0.0
                    term_qp += gp * crs.course_credits
                    term_qp_cred += crs.course_credits
                    if passed:
                        term_earned += crs.course_credits
                    else:
                        term_failed_cred += crs.course_credits
                        n_failed += 1

            # an approved withdrawal lowers the plan instead of counting as a shortfall
            plan = reg_credits - wd_credits
            term_gpa = term_qp / term_qp_cred if term_qp_cred else np.nan
            new_cum = (hist["qp"][i] + term_qp) / (hist["qp_cred"][i] + term_qp_cred) \
                if (hist["qp_cred"][i] + term_qp_cred) else np.nan
            year = int(hist["terms"][i] // 2) + 1
            R = C.STANDING_RULES
            term_min = R["term_gpa_min_first_term"] if hist["terms"][i] == 0 else R["term_gpa_min"]
            sat = (term_gpa >= term_min
                   and new_cum >= R["cum_gpa_min_by_year"].get(year, 1.8)
                   and term_failed_cred <= R["max_failed_credit_share"] * reg_credits)
            if term != C.CURRENT_TERM:
                term_rows.append(dict(
                    student_id_hash=stu.student_id_hash.values[i], term_id=term,
                    semester_earned_credits=term_earned, semester_gpa=term_gpa,
                    approved_plan_completed_flag=int(term_earned >= plan),
                    satisfactory_academic_standing_flag=int(sat),
                ))
                # history only advances once a term is closed
                hist["att"][i] += reg_credits
                hist["earned"][i] += term_earned
                hist["qp"][i] += term_qp
                hist["qp_cred"][i] += term_qp_cred
                hist["failed"][i] += n_failed
                hist["repeat"][i] += int(n_failed > 0 and rng.random() < .6)
                hist["terms"][i] += 1
                hist["warn"][i] = 0 if sat else 1
                last_gpa[i] = term_gpa

    course_df = pd.DataFrame(course_rows)
    term_df = pd.DataFrame(term_rows)
    return course_df, term_df
