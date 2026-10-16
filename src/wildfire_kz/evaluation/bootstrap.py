"""Paired space–time block bootstrap for model comparisons.

Evaluation rows are grouped into space–time blocks (``spatial_block_km`` squares x
``temporal_block_days`` periods). A resample draws blocks with replacement; each row then
carries multiplicity = number of times its block was drawn. All models are scored on the
*same* resampled units in every replicate (paired design). Each model's scores are sorted
once, so weighted AP / ROC-AUC per replicate cost O(n) instead of a fresh sort; models are
scored in parallel processes.
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


def _ranking_replicates(
    score: np.ndarray, y: np.ndarray, w: np.ndarray, blocks: np.ndarray, counts: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Weighted AP and ROC-AUC of one model for every replicate (rows of ``counts``).

    Labels, weights and block codes are put in score order once; a replicate only rescales
    the sorted weights by its block multiplicities (a gather into a small array) and takes
    two cumulative sums.
    """
    pre = Presorted.build(score)
    ys, ws, bs, ge = y[pre.order], w[pre.order], blocks[pre.order], pre.group_end
    ap = np.empty(len(counts))
    auc = np.empty(len(counts))
    for r, c in enumerate(counts):
        wb = ws * c[bs]
        tp = np.cumsum(wb * ys)[ge]
        allw = np.cumsum(wb)[ge]
        fp = allw - tp
        P, N = tp[-1], fp[-1]
        if P <= 0:
            ap[r] = auc[r] = np.nan
            continue
        prec = np.where(allw > 0, tp / np.maximum(allw, 1e-300), 1.0)
        ap[r] = np.sum(np.diff(np.r_[0.0, tp / P]) * prec)
        if N <= 0:
            auc[r] = np.nan
            continue
        pos = np.diff(np.r_[0.0, tp])
        neg = np.diff(np.r_[0.0, fp])
        auc[r] = np.sum(pos * (N - fp + 0.5 * neg)) / (P * N)
    return ap, auc


_SHARED: dict[str, np.ndarray] = {}


def _ranking_worker(score: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return _ranking_replicates(
        score, _SHARED["y"], _SHARED["w"], _SHARED["blocks"], _SHARED["counts"]
    )


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
    n_jobs: int = 1,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (per-model CI table, paired difference table) for AP, ROC-AUC, Brier and BSS.

    All replicates' block multiplicities are drawn up front, so every model is scored on
    the same resampled units; models are then processed independently (in ``n_jobs``
    processes). Brier sums are linear in the weights and are computed per block.
    """
    y = np.asarray(y, dtype=float)
    w = np.asarray(w, dtype=float)
    blocks = np.asarray(blocks, dtype=np.int64)
    n_blocks = int(blocks.max()) + 1
    rng = np.random.default_rng(seed)
    counts = np.empty((n_resamples, n_blocks), dtype=np.float64)
    for r in range(n_resamples):
        counts[r] = np.bincount(rng.integers(0, n_blocks, n_blocks), minlength=n_blocks)

    def block_sum(v: np.ndarray) -> np.ndarray:
        return np.bincount(blocks, weights=v, minlength=n_blocks)

    w_rep = counts @ block_sum(w)
    bs_ref = counts @ block_sum(w * (np.asarray(reference, dtype=float) - y) ** 2) / w_rep
    metrics = ("average_precision", "roc_auc", "brier", "bss")
    reps: dict[str, dict[str, np.ndarray]] = {}
    names = list(probs)
    if n_jobs != 1 and len(names) > 1:
        import concurrent.futures as cf
        import multiprocessing as mp
        import os

        cpus = os.cpu_count() or 1
        workers = min(len(names), cpus if n_jobs < 0 else n_jobs)
        _SHARED.update(y=y, w=w, blocks=blocks, counts=counts)
        try:
            with cf.ProcessPoolExecutor(workers, mp_context=mp.get_context("fork")) as ex:
                ranked = list(ex.map(_ranking_worker, [np.asarray(probs[m]) for m in names]))
        finally:
            _SHARED.clear()
    else:
        ranked = [_ranking_replicates(np.asarray(probs[m]), y, w, blocks, counts) for m in names]
    for m, (ap, auc) in zip(names, ranked, strict=True):
        bs = counts @ block_sum(w * (np.asarray(probs[m], dtype=float) - y) ** 2) / w_rep
        with np.errstate(invalid="ignore", divide="ignore"):
            bss = np.where(bs_ref > 0, 1 - bs / bs_ref, np.nan)
        reps[m] = {"average_precision": ap, "roc_auc": auc, "brier": bs, "bss": bss}
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
