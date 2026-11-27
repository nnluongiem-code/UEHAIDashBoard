"""Validation metrics for the model card: discrimination, calibration, intervals, subgroups."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score


def ece(y, p, bins=10):
    y, p = np.asarray(y), np.asarray(p)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    return float(sum(abs(y[idx == b].mean() - p[idx == b].mean()) * (idx == b).mean()
                     for b in range(bins) if (idx == b).any()))


def reliability(y, p, bins=10):
    y, p = np.asarray(y), np.asarray(p)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    return [dict(bin=b, mean_pred=round(float(p[idx == b].mean()), 3),
                 observed=round(float(y[idx == b].mean()), 3), n=int((idx == b).sum()))
            for b in range(bins) if (idx == b).sum() >= 10]


def classifier_metrics(y, p, raw=None):
    y, p = np.asarray(y), np.asarray(p)
    out = dict(
        n=int(len(y)), base_rate=round(float(y.mean()), 3),
        auc=round(float(roc_auc_score(y, p)), 3) if len(set(y)) > 1 else None,
        brier=round(float(brier_score_loss(y, p)), 4),
        log_loss=round(float(log_loss(y, np.clip(p, 1e-6, 1 - 1e-6))), 4),
        ece=round(ece(y, p), 4),
        reliability=reliability(y, p),
    )
    if raw is not None:
        out["ece_uncalibrated"] = round(ece(y, raw), 4)
        out["brier_uncalibrated"] = round(float(brier_score_loss(y, raw)), 4)
    return out


def pinball(y, q, a):
    d = np.asarray(y) - np.asarray(q)
    return float(np.mean(np.maximum(a * d, (a - 1) * d)))


def quantile_metrics(y, lo, med, hi):
    y = np.asarray(y)
    return dict(
        n=int(len(y)),
        mae_median=round(float(np.mean(np.abs(y - med))), 3),
        pinball_q10=round(pinball(y, lo, .1), 4),
        pinball_q50=round(pinball(y, med, .5), 4),
        pinball_q90=round(pinball(y, hi, .9), 4),
        coverage_80=round(float(np.mean((y >= lo) & (y <= hi))), 3),
        mean_interval_width=round(float(np.mean(hi - lo)), 2),
    )


def by_group(df: pd.DataFrame, group: str, y: str, p: str):
    rows = []
    for g, d in df.groupby(group):
        if d[y].nunique() < 2 or len(d) < 30:
            continue
        rows.append(dict(group=str(g), n=int(len(d)),
                         observed=round(float(d[y].mean()), 3),
                         mean_pred=round(float(d[p].mean()), 3),
                         auc=round(float(roc_auc_score(d[y], d[p])), 3),
                         brier=round(float(brier_score_loss(d[y], d[p])), 4)))
    return rows
