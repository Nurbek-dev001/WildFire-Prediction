"""Weighted evaluation metrics (all accept inverse-inclusion weights).

Average precision follows the step-wise definition AP = sum_k (R_k - R_{k-1}) P_k over
successive distinct score thresholds (identical to scikit-learn's ``average_precision_score``
with ``sample_weight``); it is deliberately distinct from the trapezoidal PR-AUC, which is
reported separately and labelled as such.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score


def _arr(*xs: object) -> list[np.ndarray]:
    return [np.asarray(x, dtype=float) for x in xs]


def _weights(y: np.ndarray, w: np.ndarray | None) -> np.ndarray:
    return np.ones_like(y, dtype=float) if w is None else np.asarray(w, dtype=float)


def precision_recall_steps(y: np.ndarray, score: np.ndarray, w: np.ndarray | None = None
                           ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Weighted precision/recall at each distinct threshold (descending score)."""
    y, score = _arr(y, score)
    w = _weights(y, w)
    order = np.argsort(-score, kind="mergesort")
    s, yy, ww = score[order], y[order], w[order]
    distinct = np.r_[np.flatnonzero(np.diff(s)), len(s) - 1]  # last index of each tie group
    tp = np.cumsum(ww * yy)[distinct]
    fp = np.cumsum(ww * (1 - yy))[distinct]
    total_pos = tp[-1] if len(tp) else 0.0
    with np.errstate(invalid="ignore", divide="ignore"):
        precision = np.where(tp + fp > 0, tp / (tp + fp), 1.0)
        recall = tp / total_pos if total_pos > 0 else np.full_like(tp, np.nan)
    return precision, recall, s[distinct]


def average_precision(y: np.ndarray, score: np.ndarray, w: np.ndarray | None = None) -> float:
    """Step-wise weighted AP = sum_k (R_k - R_{k-1}) P_k."""
    p, r, _ = precision_recall_steps(y, score, w)
    if len(r) == 0 or not np.isfinite(r).all():
        return float("nan")
    return float(np.sum(np.diff(np.r_[0.0, r]) * p))


def pr_auc_trapezoid(y: np.ndarray, score: np.ndarray, w: np.ndarray | None = None) -> float:
    """Trapezoidal area under the PR curve (reported only for contrast with AP)."""
    p, r, _ = precision_recall_steps(y, score, w)
    if len(r) == 0 or not np.isfinite(r).all():
        return float("nan")
    rr = np.r_[0.0, r]
    pp = np.r_[p[0], p]
    return float(np.trapezoid(pp, rr))


def roc_auc(y: np.ndarray, score: np.ndarray, w: np.ndarray | None = None) -> float:
    y = np.asarray(y)
    if len(np.unique(y)) < 2:
        return float("nan")
    return float(roc_auc_score(y, score, sample_weight=w))


def prevalence(y: np.ndarray, w: np.ndarray | None = None) -> float:
    y = np.asarray(y, dtype=float)
    w = _weights(y, w)
    return float(np.sum(w * y) / np.sum(w))


def brier(y: np.ndarray, p: np.ndarray, w: np.ndarray | None = None) -> float:
    y, p = _arr(y, p)
    w = _weights(y, w)
    return float(np.sum(w * (p - y) ** 2) / np.sum(w))


def brier_skill(bs: float, bs_reference: float) -> float:
    return float(1.0 - bs / bs_reference) if bs_reference > 0 else float("nan")


@dataclass
class Confusion:
    tp: float
    fp: float
    tn: float
    fn: float

    def as_metrics(self) -> dict[str, float]:
        tp, fp, tn, fn = self.tp, self.fp, self.tn, self.fn
        nan = float("nan")
        return {
            "precision": tp / (tp + fp) if tp + fp > 0 else nan,
            "recall": tp / (tp + fn) if tp + fn > 0 else nan,
            "f1": 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) > 0 else nan,
            "fpr": fp / (fp + tn) if fp + tn > 0 else nan,
            "fdp": fp / (tp + fp) if tp + fp > 0 else nan,
            "accuracy": (tp + tn) / (tp + fp + tn + fn) if (tp + fp + tn + fn) > 0 else nan,
            "tp_w": tp, "fp_w": fp, "tn_w": tn, "fn_w": fn,
        }


def confusion(y: np.ndarray, p: np.ndarray, tau: float, w: np.ndarray | None = None
              ) -> Confusion:
    """Weighted confusion counts for the rule p >= tau."""
    y, p = _arr(y, p)
    w = _weights(y, w)
    pred = p >= tau
    return Confusion(tp=float(np.sum(w * (y == 1) * pred)), fp=float(np.sum(w * (y == 0) * pred)),
                     tn=float(np.sum(w * (y == 0) * ~pred)), fn=float(np.sum(w * (y == 1) * ~pred)))


def best_f1_threshold(y: np.ndarray, p: np.ndarray, w: np.ndarray | None = None
                      ) -> tuple[float, float]:
    """Threshold maximising weighted F1 over all distinct scores (ties -> higher threshold)."""
    prec, rec, thr = precision_recall_steps(y, p, w)
    with np.errstate(invalid="ignore", divide="ignore"):
        f1 = np.where(prec + rec > 0, 2 * prec * rec / (prec + rec), 0.0)
    f1 = np.nan_to_num(f1)
    best = int(np.argmax(f1))  # thresholds are descending: first max = highest threshold
    return float(thr[best]), float(f1[best])


def wilson_interval(p_hat: np.ndarray, n_eff: np.ndarray, z: float
                    ) -> tuple[np.ndarray, np.ndarray]:
    """Wilson score interval using the Kish effective sample size for weighted data."""
    with np.errstate(invalid="ignore", divide="ignore"):
        denom = 1 + z**2 / n_eff
        centre = (p_hat + z**2 / (2 * n_eff)) / denom
        half = z * np.sqrt(p_hat * (1 - p_hat) / n_eff + z**2 / (4 * n_eff**2)) / denom
    return np.clip(centre - half, 0, 1), np.clip(centre + half, 0, 1)


def reliability_table(y: np.ndarray, p: np.ndarray, w: np.ndarray | None = None,
                      n_bins: int = 10, binning: str = "uniform", z: float = 1.96
                      ) -> pd.DataFrame:
    """Per-bin weighted mean prediction vs. observed frequency, counts and Wilson CI."""
    y, p = _arr(y, p)
    w = _weights(y, w)
    if binning == "uniform":
        edges = np.linspace(0.0, 1.0, n_bins + 1)
    else:
        order = np.argsort(p, kind="mergesort")
        cw = np.cumsum(w[order]) / w.sum()
        qs = np.linspace(0, 1, n_bins + 1)[1:-1]
        inner = p[order][np.searchsorted(cw, qs)]
        edges = np.unique(np.r_[0.0, inner, 1.0])
    idx = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, len(edges) - 2)
    rows = []
    for b in range(len(edges) - 1):
        m = idx == b
        wb = w[m]
        sw = wb.sum()
        n_eff = sw**2 / np.sum(wb**2) if sw > 0 else 0.0
        obs = float(np.sum(wb * y[m]) / sw) if sw > 0 else np.nan
        lo, hi = wilson_interval(np.array(obs), np.array(n_eff), z) if sw > 0 else (np.nan,
                                                                                     np.nan)
        rows.append({"bin": b, "lower": edges[b], "upper": edges[b + 1], "n": int(m.sum()),
                     "weight": float(sw), "n_eff": float(n_eff),
                     "mean_pred": float(np.sum(wb * p[m]) / sw) if sw > 0 else np.nan,
                     "obs_freq": obs, "obs_lo": float(lo), "obs_hi": float(hi)})
    return pd.DataFrame(rows)


def expected_calibration_error(y: np.ndarray, p: np.ndarray, w: np.ndarray | None = None,
                               n_bins: int = 10, binning: str = "uniform") -> float:
    """ECE = sum_b (W_b / W) |obs_b - pred_b| over non-empty bins."""
    t = reliability_table(y, p, w, n_bins, binning)
    t = t[t["weight"] > 0]
    return float(np.sum(t["weight"] / t["weight"].sum() * np.abs(t["obs_freq"] - t["mean_pred"])))


def capture_rate(y: np.ndarray, score: np.ndarray, frac: float, w: np.ndarray | None = None,
                 area_km2: np.ndarray | None = None, groups: np.ndarray | None = None
                 ) -> dict[str, float]:
    """Share of (weighted) event starts in the top ``frac`` of eligible cell-days.

    ``groups`` (e.g. dates) applies the top-fraction rule within each group ("daily" mode);
    otherwise the ranking is pooled over the whole evaluation set.
    """
    y, score = _arr(y, score)
    w = _weights(y, w)
    area = np.ones_like(y) if area_km2 is None else np.asarray(area_km2, dtype=float)
    flagged = np.zeros(len(y), dtype=bool)
    keys = np.zeros(len(y)) if groups is None else np.asarray(groups)
    for _, idx in pd.Series(np.arange(len(y))).groupby(keys).groups.items():
        ii = np.asarray(idx)
        order = ii[np.argsort(-score[ii], kind="mergesort")]
        cw = np.cumsum(w[order])
        k = np.searchsorted(cw, frac * cw[-1], side="left") + 1
        flagged[order[:k]] = True
    pos_w = np.sum(w * y)
    n_groups = len(np.unique(keys))
    return {
        "fraction": frac,
        "capture_rate": float(np.sum(w * y * flagged) / pos_w) if pos_w > 0 else float("nan"),
        "flagged_weight": float(np.sum(w * flagged)),
        "flagged_area_km2_days": float(np.sum(w * area * flagged)),
        "mean_daily_flagged_area_km2": float(np.sum(w * area * flagged) / n_groups),
        "false_alerts_weight": float(np.sum(w * (1 - y) * flagged)),
        "false_alert_share": float(np.sum(w * (1 - y) * flagged) / np.sum(w * flagged)),
    }


def summary_metrics(y: np.ndarray, p: np.ndarray, w: np.ndarray | None, tau: float,
                    p_reference: np.ndarray | None = None, n_bins: int = 10
                    ) -> dict[str, float]:
    """Headline metrics for one model on one evaluation set."""
    out = {"n": float(len(y)), "positives": float(np.sum(y)),
           "weighted_n": float(np.sum(_weights(np.asarray(y), w))),
           "prevalence": prevalence(y, w), "average_precision": average_precision(y, p, w),
           "pr_auc_trapezoid": pr_auc_trapezoid(y, p, w), "roc_auc": roc_auc(y, p, w),
           "brier": brier(y, p, w), "ece_10bin": expected_calibration_error(y, p, w, n_bins),
           "tau": tau}
    out["ap_lift_over_prevalence"] = out["average_precision"] / out["prevalence"] \
        if out["prevalence"] > 0 else float("nan")
    if p_reference is not None:
        out["brier_reference"] = brier(y, p_reference, w)
        out["bss"] = brier_skill(out["brier"], out["brier_reference"])
    out.update(confusion(y, p, tau, w).as_metrics())
    return out
