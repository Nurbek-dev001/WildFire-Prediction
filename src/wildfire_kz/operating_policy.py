"""Versioned operating points selected exclusively on pre-2023 observations."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_curve


def threshold_curve(frame: pd.DataFrame, probabilities: np.ndarray) -> pd.DataFrame:
    """Reject final years before inspecting labels, probabilities or selection scores."""
    if frame.empty or not frame.day.dt.year.eq(2022).all():
        raise PermissionError("Operating-point selection is restricted to 2022")
    p = np.asarray(probabilities)
    y, w = frame.label.to_numpy(), frame.weight.to_numpy()
    if (
        p.shape != y.shape
        or not np.isfinite(p).all()
        or ((p < 0) | (p > 1)).any()
        or not np.isfinite(w).all()
        or (w <= 0).any()
        or set(np.unique(y)) != {0, 1}
    ):
        raise ValueError("Finite probabilities, positive design weights and both labels required")
    precision, recall, thresholds = precision_recall_curve(y, p, sample_weight=w)
    precision, recall = precision[:-1], recall[:-1]
    # If a threshold lies above every positive score, PR precision is zero; include
    # the actual all-negative alert mass rather than incorrectly reporting zero.
    order = np.argsort(p, kind="stable")
    cumulative = np.r_[0.0, np.cumsum(w[order])]
    alerts = w.sum() - cumulative[np.searchsorted(p[order], thresholds, side="left")]
    result = pd.DataFrame(
        {
            "threshold": thresholds,
            "precision": precision,
            "recall": recall,
            "alert_fraction": alerts / w.sum(),
        }
    )
    for beta in [1, 2, 3]:
        b2 = beta**2
        result[f"f{beta}"] = np.divide(
            (1 + b2) * precision * recall,
            b2 * precision + recall,
            out=np.zeros_like(precision),
            where=b2 * precision + recall > 0,
        )
    return result


def choose_threshold(curve: pd.DataFrame, beta: int = 2, minimum_recall: float = 0) -> pd.Series:
    """Maximize weighted F-beta with a declared recall floor; exact ties alert less."""
    eligible = curve.loc[curve.recall >= minimum_recall]
    if eligible.empty:
        raise ValueError("Requested recall floor is unattainable")
    objective = f"f{beta}"
    best = eligible[objective].max()
    return eligible.loc[eligible[objective] == best].sort_values("threshold").iloc[-1]
