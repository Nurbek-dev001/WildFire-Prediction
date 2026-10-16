"""Stratified probability sampling with explicit Horvitz-Thompson weights."""

import numpy as np
import pandas as pd

from wildfire_kz.config import SamplingConfig


def sample_training(frame: pd.DataFrame, cfg: SamplingConfig, seed: int) -> pd.DataFrame:
    """Keep every positive and sample negatives within month x broad-cover strata.

    Must be called on training rows only, including independently inside each fold.
    """
    data = frame.copy()
    data["q"] = 1.0
    if cfg.mode == "class_weight":
        data["weight"] = 1.0
        return data
    rng = np.random.default_rng(seed)
    pieces = []
    for _, group in data.groupby([pd.to_datetime(data.day).dt.month, "landcover"], observed=True):
        pos, neg = group[group.label == 1].copy(), group[group.label == 0].copy()
        count = min(
            len(neg), max(cfg.minimum_negatives, int(np.ceil(len(pos) * cfg.negative_ratio)))
        )
        if len(neg):
            neg = neg.iloc[rng.choice(len(neg), count, replace=False)].copy()
            neg["q"] = count / len(group[group.label == 0])
        pieces.extend([pos, neg])
    sampled = pd.concat(pieces).sort_index()
    sampled["weight"] = 1 / sampled.q
    return sampled
