"""M1-M4 model wrappers.

* Classifiers (M1, M2, M4): CatBoost + post-hoc calibration fitted on a held-out
  calibration term, so a predicted 0.70 means roughly 70 of 100 similar cases
  succeed. Isotonic regression is used when the calibration set is large; Platt
  (logistic) scaling otherwise, because isotonic overfits small sets. The
  calibrator is kept only if student-grouped cross-validation on the
  calibration term shows it beats the raw probabilities (Brier score);
  otherwise the raw CatBoost output is used.
  Calibrated probabilities are bounded to [P_MIN, 1-P_MIN]: a model should never
  tell an advisor that an outcome is certain.
* Regressor (M3): CatBoost MultiQuantile (Q10/Q50/Q90), then conformalised on the
  calibration term (CQR) so the Q10-Q90 band really covers about 80% of outcomes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, CatBoostRegressor, Pool
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss
from sklearn.model_selection import GroupKFold

from . import config as C


def _pool(X: pd.DataFrame, cat_features, y=None):
    return Pool(X, label=y, cat_features=[c for c in cat_features if c in X.columns])


P_MIN = 0.01
ISOTONIC_MIN_ROWS = 5000


def _logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p)).reshape(-1, 1)


class CalibratedCatBoostClassifier:
    def __init__(self, features, cat_features, **params):
        self.features = list(features)
        self.cat_features = list(cat_features)
        self.params = {**C.CATBOOST_PARAMS, "loss_function": "Logloss", **params}
        self.model = CatBoostClassifier(**self.params)
        self.calibrator = None
        self.calibration_method = None

    def fit(self, X, y):
        self.model.fit(_pool(X[self.features], self.cat_features, y))
        return self

    def raw_proba(self, X):
        return self.model.predict_proba(_pool(X[self.features], self.cat_features))[:, 1]

    @staticmethod
    def _fit_calibrator(method, raw, y):
        if method == "isotonic":
            return IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw, y)
        return LogisticRegression(C=1e4).fit(_logit(raw), y)

    @staticmethod
    def _apply(method, cal, raw):
        return cal.predict(raw) if method == "isotonic" else cal.predict_proba(_logit(raw))[:, 1]

    def calibrate(self, X, y, groups=None, method: str = "auto"):
        raw, y = self.raw_proba(X), np.asarray(y)
        if method == "auto":
            method = "isotonic" if len(y) >= ISOTONIC_MIN_ROWS else "platt"
        self.calibration_cv = None
        if groups is not None:
            # guard: does calibration help out-of-sample, with students kept apart?
            cal_pred = np.zeros(len(y))
            for tr, va in GroupKFold(n_splits=5).split(raw, y, groups):
                c = self._fit_calibrator(method, raw[tr], y[tr])
                cal_pred[va] = self._apply(method, c, raw[va])
            b_raw, b_cal = brier_score_loss(y, raw), brier_score_loss(y, cal_pred)
            self.calibration_cv = {"brier_raw": round(float(b_raw), 5), "brier_calibrated": round(float(b_cal), 5)}
            if b_cal >= b_raw:
                self.calibrator, self.calibration_method = None, "none (raw better in CV)"
                return self
        self.calibrator = self._fit_calibrator(method, raw, y)
        self.calibration_method = method
        return self

    def apply_calibration(self, raw):
        raw = np.asarray(raw, dtype=float)
        if self.calibrator is None:
            p = raw
        else:
            p = self._apply(self.calibration_method, self.calibrator, raw)
        return np.clip(p, P_MIN, 1 - P_MIN)

    def predict_proba(self, X):
        return self.apply_calibration(self.raw_proba(X))

    def shap_values(self, X):
        """Per-row SHAP contributions (log-odds), last column dropped (bias)."""
        sv = self.model.get_feature_importance(
            _pool(X[self.features], self.cat_features), type="ShapValues")
        return pd.DataFrame(sv[:, :-1], columns=self.features, index=X.index)

    def feature_importance(self):
        return pd.Series(self.model.get_feature_importance(), index=self.features) \
            .sort_values(ascending=False)


class ConformalQuantileRegressor:
    def __init__(self, features, cat_features, quantiles=C.QUANTILES, **params):
        self.features = list(features)
        self.cat_features = list(cat_features)
        self.q = list(quantiles)
        alpha = ",".join(str(a) for a in self.q)
        self.params = {**C.CATBOOST_PARAMS, "loss_function": f"MultiQuantile:alpha={alpha}", **params}
        self.model = CatBoostRegressor(**self.params)
        self.conformal_margin = 0.0

    def fit(self, X, y):
        self.model.fit(_pool(X[self.features], self.cat_features, y))
        return self

    def raw_predict(self, X):
        p = self.model.predict(_pool(X[self.features], self.cat_features))
        return np.sort(p, axis=1)  # guard against quantile crossing

    def calibrate(self, X, y):
        """Split-conformal margin on the calibration term (CQR, Romano et al. 2019)."""
        p = self.raw_predict(X)
        y = np.asarray(y)
        scores = np.maximum(p[:, 0] - y, y - p[:, -1])
        target = self.q[-1] - self.q[0]  # 0.80
        n = len(scores)
        level = min(1.0, np.ceil((n + 1) * target) / n)
        self.conformal_margin = float(np.quantile(scores, level))
        return self

    def predict(self, X):
        p = self.raw_predict(X)
        lo = np.clip(p[:, 0] - self.conformal_margin, 0, 10)
        hi = np.clip(p[:, -1] + self.conformal_margin, 0, 10)
        med = np.clip(p[:, 1], lo, hi)
        return lo, med, hi

    def feature_importance(self):
        return pd.Series(self.model.get_feature_importance(), index=self.features) \
            .sort_values(ascending=False)
