"""Paired space–time block bootstrap for model comparisons.

Evaluation rows are grouped into space–time blocks (``spatial_block_km`` squares x
``temporal_block_days`` periods). A resample draws blocks with replacement; each row then
carries multiplicity = number of times its block was drawn. All models are scored on the
*same* resampled units in every replicate (paired design). Each model's scores are sorted
once, so weighted AP / ROC-AUC per replicate cost O(n) instead of a fresh sort.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def space_time_blocks(
    x: np.ndarray, y: np.ndarray, dates: pd.Series, spatial_km: float, temporal_days: int
) -> np.ndarray:
    """Integer block code per row."""
    b = spatial_km * 1000.0
    d = pd.to_datetime(dates)
    t = ((d - d.min()).dt.days // temporal_days).to_numpy()
    key = pd.DataFrame(
        {
            "bx": np.floor(np.asarray(x) / b).astype(np.int64),
            "by": np.floor(np.asarray(y) / b).astype(np.int64),
            "t": t,
        }
    )
    return key.groupby(["bx", "by", "t"], sort=True).ngroup().to_numpy()


@dataclass
class Presorted:
    """A model's scores sorted descending, with tie-group boundaries."""

    order: np.ndarray
    group_end: np.ndarray  # last index (in sorted order) of each distinct-score group

    @classmethod
    def build(cls, score: np.ndarray) -> Presorted:
        order = np.argsort(-np.asarray(score), kind="mergesort")
        s = np.asarray(score)[order]
        return cls(order=order, group_end=np.r_[np.flatnonzero(np.diff(s)), len(s) - 1])

    def ap(self, y: np.ndarray, w: np.ndarray) -> float:
        yy, ww = y[self.order], w[self.order]
        tp = np.cumsum(ww * yy)[self.group_end]
        fp = np.cumsum(ww * (1 - yy))[self.group_end]
        if tp[-1] <= 0:
            return float("nan")
        prec = np.where(tp + fp > 0, tp / np.maximum(tp + fp, 1e-300), 1.0)
        rec = tp / tp[-1]
        return float(np.sum(np.diff(np.r_[0.0, rec]) * prec))

    def auc(self, y: np.ndarray, w: np.ndarray) -> float:
        yy, ww = y[self.order], w[self.order]
        pos = np.diff(np.r_[0.0, np.cumsum(ww * yy)[self.group_end]])
        neg = np.diff(np.r_[0.0, np.cumsum(ww * (1 - yy))[self.group_end]])
        P, N = pos.sum(), neg.sum()
        if P <= 0 or N <= 0:
            return float("nan")
        neg_below = N - np.cumsum(neg)
        return float(np.sum(pos * (neg_below + 0.5 * neg)) / (P * N))


def _brier(y: np.ndarray, p: np.ndarray, w: np.ndarray) -> float:
    return float(np.sum(w * (p - y) ** 2) / np.sum(w))


def paired_block_bootstrap(
    y: np.ndarray,
    w: np.ndarray,
    blocks: np.ndarray,
    probs: dict[str, np.ndarray],
    reference: np.ndarray,
    pairs: list[tuple[str, str]],
    n_resamples: int,
    seed: int,
    ci_level: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (per-model CI table, paired difference table) for AP, ROC-AUC, Brier and BSS."""
    y = np.asarray(y, dtype=float)
    w = np.asarray(w, dtype=float)
    n_blocks = int(blocks.max()) + 1
    pre = {m: Presorted.build(p) for m, p in probs.items()}
    rng = np.random.default_rng(seed)
    metrics = ("average_precision", "roc_auc", "brier", "bss")
    reps = {m: {k: np.empty(n_resamples) for k in metrics} for m in probs}
    for r in range(n_resamples):
        counts = np.bincount(rng.integers(0, n_blocks, n_blocks), minlength=n_blocks)
        wb = w * counts[blocks]
        bs_ref = _brier(y, reference, wb)
        for m, p in probs.items():
            reps[m]["average_precision"][r] = pre[m].ap(y, wb)
            reps[m]["roc_auc"][r] = pre[m].auc(y, wb)
            bs = _brier(y, p, wb)
            reps[m]["brier"][r] = bs
            reps[m]["bss"][r] = 1 - bs / bs_ref if bs_ref > 0 else np.nan
    alpha = (1 - ci_level) / 2
    model_rows = []
    for m in probs:
        for k in metrics:
            v = reps[m][k]
            model_rows.append(
                {
                    "model": m,
                    "metric": k,
                    "ci_lo": np.nanquantile(v, alpha),
                    "ci_hi": np.nanquantile(v, 1 - alpha),
                    "bootstrap_sd": np.nanstd(v, ddof=1),
                }
            )
    pair_rows = []
    for a, b in pairs:
        for k in metrics:
            d = reps[a][k] - reps[b][k]
            lo, hi = np.nanquantile(d, alpha), np.nanquantile(d, 1 - alpha)
            better_is_higher = k != "brier"
            pair_rows.append(
                {
                    "model_a": a,
                    "model_b": b,
                    "metric": k,
                    "diff_mean": float(np.nanmean(d)),
                    "ci_lo": float(lo),
                    "ci_hi": float(hi),
                    "share_a_better": float(
                        np.nanmean(d > 0) if better_is_higher else np.nanmean(d < 0)
                    ),
                    "ci_excludes_zero": bool(lo > 0 or hi < 0),
                }
            )
    return pd.DataFrame(model_rows), pd.DataFrame(pair_rows)
