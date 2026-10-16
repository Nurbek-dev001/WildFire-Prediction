"""Bootstrap internals agree with the reference metric implementations."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from wildfire_kz.evaluation.bootstrap import Presorted, paired_block_bootstrap, space_time_blocks
from wildfire_kz.evaluation.metrics import average_precision, roc_auc


def test_presorted_ap_auc_match_reference_with_multiplicities() -> None:
    rng = np.random.default_rng(3)
    n = 500
    y = (rng.random(n) < 0.08).astype(float)
    s = np.round(rng.random(n) + 0.4 * y, 2)  # rounding creates ties
    w = rng.integers(0, 4, n).astype(float)
    ps = Presorted.build(s)
    assert ps.ap(y, w) == pytest.approx(average_precision(y, s, w))
    keep = w > 0
    assert ps.auc(y, w) == pytest.approx(roc_auc(y[keep], s[keep], w[keep]))


def test_space_time_blocks() -> None:
    x = np.array([0, 50_000, 150_000, 0])
    y = np.zeros(4)
    d = pd.Series(pd.to_datetime(["2023-01-01", "2023-01-03", "2023-01-02", "2023-01-09"]))
    b = space_time_blocks(x, y, d, 100, 7)
    assert b[0] == b[1] and b[0] != b[2] and b[0] != b[3]


def test_paired_bootstrap_identical_models_have_zero_difference() -> None:
    rng = np.random.default_rng(0)
    n = 400
    y = (rng.random(n) < 0.1).astype(float)
    p = np.clip(rng.random(n) * 0.3 + 0.2 * y, 0, 1)
    blocks = rng.integers(0, 40, n)
    _, pairs = paired_block_bootstrap(
        y,
        np.ones(n),
        blocks,
        {"a": p, "b": p.copy()},
        np.full(n, y.mean()),
        [("a", "b")],
        50,
        1,
        0.95,
    )
    assert np.allclose(pairs["diff_mean"], 0) and not pairs["ci_excludes_zero"].any()
