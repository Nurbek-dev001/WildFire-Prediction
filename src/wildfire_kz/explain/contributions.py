"""Per-row additive contributions to a model's uncalibrated score, for any production model.

* tree models (XGBoost, CatBoost): TreeSHAP on the raw log-odds margin;
* Random Forest: TreeSHAP on the probability scale (sklearn exposes no log-odds);
* L2 logistic regression: coefficient x standardised value (exact log-odds decomposition
  relative to the training mean);
* log-odds-averaging ensemble: the mean of its members' contributions (exact, by additivity).

Contributions are mapped back to source feature names (one-hot columns and missing-value
indicators are summed into their parent feature). They are predictive associations of the
model, not causal effects.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import shap

from wildfire_kz.models.pipelines import EnsembleModel, FittedModel


@dataclass
class Contributions:
    values: pd.DataFrame  # rows x source features
    base_value: float
    scale: str


def _base_feature(col: str, categorical: list[str]) -> str:
    for c in categorical:
        if col.startswith(f"{c}_"):
            return c
    if col.startswith("missingindicator_"):
        return col[len("missingindicator_") :]
    return col


def _to_source(values: pd.DataFrame, categorical: list[str]) -> pd.DataFrame:
    groups: dict[str, list[str]] = {}
    for col in values.columns:
        groups.setdefault(_base_feature(str(col), categorical), []).append(str(col))
    return pd.DataFrame({g: values[cols].sum(axis=1) for g, cols in groups.items()})


def contributions(fm: FittedModel, X: pd.DataFrame) -> Contributions:
    """Additive contributions of each source feature to the uncalibrated score."""
    if isinstance(fm, EnsembleModel):
        parts = [contributions(m, X) for m in fm.members]
        cols = list(dict.fromkeys(c for p in parts for c in p.values.columns))
        stacked = np.stack(
            [p.values.reindex(columns=cols, fill_value=0.0).to_numpy() for p in parts]
        )
        mean = pd.DataFrame(stacked.mean(axis=0), columns=cols, index=X.index)
        scales = {p.scale for p in parts}
        return Contributions(
            values=mean,
            base_value=float(np.mean([p.base_value for p in parts])),
            scale=scales.pop() if len(scales) == 1 else "mixed",
        )
    est = fm.spec.estimator
    if est in ("xgboost", "catboost", "random_forest"):
        Xt = fm.transform(X)
        if est == "random_forest":
            expl = shap.TreeExplainer(fm.estimator)
            vals = expl.shap_values(Xt, check_additivity=False)
            vals = vals[..., 1] if np.ndim(vals) == 3 else vals[1]
            base = np.atleast_1d(expl.expected_value)[-1]
            scale = "probability"
        else:
            expl = shap.TreeExplainer(fm.estimator, model_output="raw")
            vals = expl.shap_values(Xt, check_additivity=False)
            base = np.atleast_1d(expl.expected_value)[0]
            scale = "log-odds"
        df = pd.DataFrame(np.asarray(vals), columns=Xt.columns, index=X.index)
        return Contributions(_to_source(df, fm.spec.categorical), float(base), scale)
    if est == "logistic":
        Xt = fm.transform(X)
        coef = fm.estimator.coef_[0]
        df = pd.DataFrame(Xt.to_numpy() * coef, columns=Xt.columns, index=X.index)
        return Contributions(
            _to_source(df, fm.spec.categorical), float(fm.estimator.intercept_[0]), "log-odds"
        )
    raise NotImplementedError(f"no contribution method for estimator '{est}'")


def top_drivers(c: Contributions, row: int, n: int) -> list[dict[str, float | str]]:
    """The n largest-magnitude contributions for one row."""
    s = c.values.iloc[row]
    s = s.reindex(s.abs().sort_values(ascending=False).index)[:n]
    return [{"feature": str(k), "contribution": float(v)} for k, v in s.items()]
