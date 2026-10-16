"""Representative sigmoid calibration and frozen operating points."""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.special import logit
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_curve


@dataclass
class SigmoidCalibration:
    estimator: LogisticRegression

    def predict(self, probabilities: np.ndarray) -> np.ndarray:
        return self.estimator.predict_proba(
            logit(np.clip(probabilities, 1e-7, 1 - 1e-7)).reshape(-1, 1)
        )[:, 1]


def fit_sigmoid(
    frame: pd.DataFrame, probabilities: np.ndarray, calibration_year: int
) -> tuple[SigmoidCalibration, float]:
    """Use only the reserved year for sigmoid parameters and weighted-F1 threshold."""
    if not frame.day.dt.year.eq(calibration_year).all():
        raise PermissionError("Calibration/threshold selection is restricted to calibration year")
    if frame.label.nunique() != 2:
        raise ValueError("Calibration requires both outcomes")
    weights = frame.get("weight", pd.Series(1.0, index=frame.index)).to_numpy()
    estimator = LogisticRegression(C=1e10, solver="lbfgs", max_iter=2000)
    estimator.fit(
        logit(np.clip(probabilities, 1e-7, 1 - 1e-7)).reshape(-1, 1),
        frame.label,
        sample_weight=weights,
    )
    calibration = SigmoidCalibration(estimator)
    calibrated = calibration.predict(probabilities)
    precision, recall, thresholds = precision_recall_curve(
        frame.label, calibrated, sample_weight=weights
    )
    f1 = 2 * precision[:-1] * recall[:-1] / np.maximum(precision[:-1] + recall[:-1], 1e-15)
    # Deterministic ties choose the highest threshold, reducing alert burden.
    index = int(np.flatnonzero(np.isclose(f1, f1.max()))[-1])
    return calibration, float(thresholds[index])


def map_boundaries(
    probabilities: np.ndarray, quantiles: list[float], weights: np.ndarray
) -> list[float]:
    """Freeze weighted calibration quantiles, retaining continuous probabilities."""
    order = np.argsort(probabilities)
    cumulative = np.cumsum(weights[order]) / weights.sum()
    return sorted(set(float(np.interp(q, cumulative, probabilities[order])) for q in quantiles))
