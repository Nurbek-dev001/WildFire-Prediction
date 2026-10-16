"""Design-weighted discrimination, calibration, burden and paired cluster intervals."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score


def reliability(y: np.ndarray, p: np.ndarray, w: np.ndarray, bins: int = 10) -> pd.DataFrame:
    """Equal-width bins, including empty bins and probability one."""
    assigned = np.minimum((p * bins).astype(int), bins - 1)
    rows = []
    for b in range(bins):
        mask = assigned == b
        weight = float(w[mask].sum())
        rows.append(
            {
                "bin": b,
                "lower": b / bins,
                "upper": (b + 1) / bins,
                "count": int(mask.sum()),
                "weight": weight,
                "predicted": float(np.average(p[mask], weights=w[mask])) if weight else None,
                "observed": float(np.average(y[mask], weights=w[mask])) if weight else None,
            }
        )
    return pd.DataFrame(rows)


def metrics(
    y: np.ndarray,
    p: np.ndarray,
    w: np.ndarray,
    threshold: float,
    reference: np.ndarray,
    bins: int = 10,
) -> dict[str, float | None]:
    """AP uses recall increments (sklearn AP), never trapezoidal PR-AUC."""
    y, p, w, reference = map(np.asarray, (y, p, w, reference))
    if not len(y) or w.sum() <= 0 or not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ValueError("Metrics require finite probabilities, rows and positive total weight")
    predicted = p >= threshold
    tp = float(w[(y == 1) & predicted].sum())
    fp = float(w[(y == 0) & predicted].sum())
    fn = float(w[(y == 1) & ~predicted].sum())
    tn = float(w[(y == 0) & ~predicted].sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    brier = float(np.average((p - y) ** 2, weights=w))
    ref_brier = float(np.average((reference - y) ** 2, weights=w))
    rel = reliability(y, p, w, bins)
    ece = float((rel.weight * (rel.predicted - rel.observed).abs()).sum() / w.sum())
    two = len(np.unique(y[w > 0])) == 2
    return {
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "fpr": fp / (fp + tn) if fp + tn else None,
        "false_discovery_proportion": fp / (tp + fp) if tp + fp else None,
        "accuracy": float((tp + tn) / float(w.sum())),
        "average_precision": float(average_precision_score(y, p, sample_weight=w)) if two else None,
        "roc_auc": float(roc_auc_score(y, p, sample_weight=w)) if two else None,
        "prevalence": float(np.average(y, weights=w)),
        "brier": brier,
        "bss": 1 - brier / ref_brier if ref_brier else None,
        "ece": ece,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "weighted_rows": float(w.sum()),
    }


@dataclass
class ClusterDraws:
    """Store cluster counts rather than a resamples x rows matrix."""

    codes: np.ndarray
    multiplicities: np.ndarray

    def __len__(self) -> int:
        return len(self.multiplicities)

    def __iter__(self) -> Iterator[np.ndarray]:
        for counts in self.multiplicities:
            yield counts[self.codes]


def cluster_draws(
    frame: pd.DataFrame, resamples: int, block_m: int, block_days: int, seed: int
) -> ClusterDraws:
    """Multiplicities for paired resampling of identical space-time units."""
    units = pd.MultiIndex.from_arrays(
        [
            np.floor(frame.x / block_m).astype(int),
            np.floor(frame.y_coord / block_m).astype(int),
            (frame.day.dt.as_unit("ns").astype("int64") // (86400 * 10**9 * block_days)).astype(
                int
            ),
        ]
    )
    codes, unique = pd.factorize(units)
    rng = np.random.default_rng(seed)
    counts = np.array(
        [
            np.bincount(rng.integers(0, len(unique), len(unique)), minlength=len(unique))
            for _ in range(resamples)
        ],
        dtype=np.int32,
    )
    return ClusterDraws(codes, counts)


def paired_intervals(
    y: np.ndarray,
    predictions: dict[str, np.ndarray],
    w: np.ndarray,
    thresholds: dict[str, float],
    reference: np.ndarray,
    draws: ClusterDraws | list[np.ndarray],
    confidence: float,
) -> pd.DataFrame:
    """Pairwise model differences with percentile CIs on the same resampled units."""
    from itertools import combinations

    alpha = (1 - confidence) / 2
    keys = ["average_precision", "brier", "bss", "f1", "roc_auc"]
    cached = {
        name: [metrics(y, p, w * draw, thresholds[name], reference) for draw in draws]
        for name, p in predictions.items()
    }
    point = {name: metrics(y, p, w, thresholds[name], reference) for name, p in predictions.items()}
    rows = []
    for a, b in combinations(predictions, 2):
        for key in keys:
            values = [
                cast(float, ra[key]) - cast(float, rb[key])
                for ra, rb in zip(cached[a], cached[b], strict=True)
                if isinstance(ra[key], float) and isinstance(rb[key], float)
            ]
            rows.append(
                {
                    "model_a": a,
                    "model_b": b,
                    "metric": key,
                    "difference": cast(float, point[a][key]) - cast(float, point[b][key])
                    if values
                    and isinstance(point[a][key], float)
                    and isinstance(point[b][key], float)
                    else None,
                    "lower": float(np.quantile(values, alpha)) if values else None,
                    "upper": float(np.quantile(values, 1 - alpha)) if values else None,
                    "valid_resamples": len(values),
                    "requested_resamples": len(draws),
                }
            )
    return pd.DataFrame(rows)


def top_capture(
    frame: pd.DataFrame, probabilities: np.ndarray, fractions: list[float]
) -> pd.DataFrame:
    """Select daily ranked cells up to an area budget and report false-alert burden."""
    data = frame.assign(probability=probabilities).sort_values(
        ["day", "probability", "cell_id"], ascending=[True, False, True]
    )
    area = data.area_km2 * data.weight
    cumulative_before = area.groupby(data.day).cumsum() - area
    daily_area = area.groupby(data.day).transform("sum")
    positives = float((data.label * data.weight).sum())
    total_area = float(area.sum())
    rows = []
    for fraction in fractions:
        alerts = data.loc[cumulative_before < fraction * daily_area]
        false = alerts[alerts.label == 0]
        rows.append(
            {
                "nominal_fraction": fraction,
                "capture_rate": float((alerts.label * alerts.weight).sum() / positives)
                if positives
                else None,
                "area_km2_days": float((alerts.area_km2 * alerts.weight).sum()),
                "actual_area_fraction": float((alerts.area_km2 * alerts.weight).sum() / total_area),
                "false_alert_cell_days": float(false.weight.sum()),
                "false_alert_km2_days": float((false.area_km2 * false.weight).sum()),
                "alert_cell_days": float(alerts.weight.sum()),
            }
        )
    return pd.DataFrame(rows)


def reliability_intervals(
    y: np.ndarray,
    p: np.ndarray,
    w: np.ndarray,
    draws: ClusterDraws | list[np.ndarray],
    bins: int,
    confidence: float,
) -> pd.DataFrame:
    """Space-time block bootstrap uncertainty for observed frequency in each bin."""
    table = reliability(y, p, w, bins)
    samples = pd.DataFrame([reliability(y, p, w * d, bins).observed for d in draws])
    alpha = (1 - confidence) / 2
    table["ci_lower"] = samples.quantile(alpha).to_numpy()
    table["ci_upper"] = samples.quantile(1 - alpha).to_numpy()
    table["valid_resamples"] = samples.count().to_numpy()
    return table
