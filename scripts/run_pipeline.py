"""Generate (or load) data, train M1-M4, validate, score the current term, export.

Usage:
    python scripts/run_pipeline.py                 # synthetic demo data
    python scripts/run_pipeline.py --course-csv course.csv --term-csv term.csv
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ueh_trajectory import config as C  # noqa: E402
from ueh_trajectory.pipeline import Bundle, score, train, write_outputs  # noqa: E402
from ueh_trajectory.synthetic import generate  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--course-csv", help="student x course x term x snapshot extract")
    ap.add_argument("--term-csv", help="student x term labels for closed terms")
    ap.add_argument("--students", type=int, default=1100, help="synthetic cohort size")
    ap.add_argument("--skip-train", action="store_true", help="reuse artifacts/models/bundle.pkl")
    args = ap.parse_args()
    t0 = time.time()

    if args.course_csv:
        course_df, term_df = pd.read_csv(args.course_csv), pd.read_csv(args.term_csv)
    else:
        print(f"generating synthetic data for {args.students} students ...")
        course_df, term_df = generate(args.students)
        data_dir = ROOT / "artifacts" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        course_df.to_csv(data_dir / "synthetic_course_snapshots.csv", index=False)
        term_df.to_csv(data_dir / "synthetic_term_labels.csv", index=False)

    model_path = ROOT / "artifacts" / "models" / "bundle.pkl"
    if args.skip_train:
        bundle = Bundle.load(model_path)
    else:
        bundle = train(course_df, term_df)
        bundle.save(model_path)

    print(f"scoring current term {C.CURRENT_TERM} ...")
    cp, t = score(bundle, course_df, C.CURRENT_TERM)
    n_rec, n_stu = write_outputs(bundle, cp, t, ROOT / "artifacts" / "output", ROOT / "dashboard")
    m = bundle.metrics
    print(f"\nwrote {n_rec:,} course records, {n_stu:,} students  ({time.time() - t0:.0f}s)")
    print(f"M1 AUC {m['M1_course_completion']['auc']}  ECE {m['M1_course_completion']['ece']}")
    print(f"M2 AUC {m['M2_course_attainment']['auc']}  ECE {m['M2_course_attainment']['ece']}")
    print(f"M3 MAE {m['M3_final_score']['mae_median']}  80% coverage {m['M3_final_score']['coverage_80']}")
    print(f"M4 AUC {m['M4_plan_completion']['auc']}  ECE {m['M4_plan_completion']['ece']}  "
          f"baselines {m['M4_baselines']}")
    print(f"R1 standing AUC {m['R1_standing']['auc']}  GPA {m['R1_term_gpa']}")
    print("state distribution (current term):")
    print(t.groupby(['snapshot_milestone', 'trajectory_state']).size().unstack(fill_value=0))


if __name__ == "__main__":
    main()
