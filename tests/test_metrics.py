"""Metrics checked against hand-computed examples."""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.metrics import average_precision_score

from wildfire_kz.evaluation.metrics import (
    average_precision,
    best_f1_threshold,
    brier,
    brier_skill,
    capture_rate,
    confusion,
    expected_calibration_error,
    pr_auc_trapezoid,
    reliability_table,
)


def test_ap_hand_example() -> None:
    # scores sorted: 0.9(1) 0.8(0) 0.7(1) 0.6(0)
    # k=1: P=1, R=.5 ; k=2: P=.5, R=.5 ; k=3: P=2/3, R=1 ; k=4: P=.5, R=1
    # AP = .5*1 + 0*.5 + .5*(2/3) + 0 = 0.8333...
    y = np.array([1, 0, 1, 0])
    s = np.array([0.9, 0.8, 0.7, 0.6])
    assert average_precision(y, s) == pytest.approx(5 / 6)


def test_ap_differs_from_trapezoid() -> None:
    y = np.array([1, 0, 1, 0])
    s = np.array([0.9, 0.8, 0.7, 0.6])
    # trapezoid over (R,P): (0,1)->(.5,1)->(.5,.5)->(1,2/3)->(1,.5)
    expected = 0.5 * 1.0 + 0.5 * (0.5 + 2 / 3) / 2
    assert pr_auc_trapezoid(y, s) == pytest.approx(expected)
    assert pr_auc_trapezoid(y, s) != pytest.approx(average_precision(y, s))


def test_ap_ties_are_one_threshold() -> None:
    y = np.array([1, 0, 1])
    s = np.array([0.5, 0.5, 0.1])
    # threshold .5: P=.5 R=.5 ; threshold .1: P=2/3 R=1 -> AP=.25+.3333
    assert average_precision(y, s) == pytest.approx(0.5 * 0.5 + 0.5 * 2 / 3)


def test_weighted_ap_matches_sklearn_and_replication() -> None:
    rng = np.random.default_rng(0)
    y = (rng.random(300) < 0.1).astype(int)
    s = rng.random(300) + 0.3 * y
    w = rng.integers(1, 5, 300).astype(float)
    assert average_precision(y, s, w) == pytest.approx(average_precision_score(y, s,
                                                                               sample_weight=w))
    rep = np.repeat(np.arange(300), w.astype(int))  # integer weights == replicated rows
    assert average_precision(y, s, w) == pytest.approx(average_precision(y[rep], s[rep]))


def test_brier_and_bss_hand_example() -> None:
    y = np.array([1, 0, 0, 1])
    p = np.array([0.8, 0.1, 0.3, 0.6])
    w = np.array([1.0, 2.0, 1.0, 1.0])
    # weighted squared errors: .04*1 + .01*2 + .09*1 + .16*1 = .31 / 5 = .062
    assert brier(y, p, w) == pytest.approx(0.062)
    ref = np.full(4, 0.4)
    # reference: .36 + .16*2 + .16 + .36 = 1.2 / 5 = .24
    assert brier(y, ref, w) == pytest.approx(0.24)
    assert brier_skill(0.062, 0.24) == pytest.approx(1 - 0.062 / 0.24)


def test_ece_hand_example() -> None:
    y = np.array([0, 0, 1, 1, 1])
    p = np.array([0.05, 0.15, 0.85, 0.95, 0.95])
    # bins [0,.1): pred .05 obs 0; [.1,.2): .15 obs 0; [.8,.9): .85 obs 1; [.9,1]: .95 obs 1
    # ECE = (1*.05 + 1*.15 + 1*.15 + 2*.05)/5 = .09
    assert expected_calibration_error(y, p, n_bins=10) == pytest.approx(0.09)


def test_reliability_counts_and_interval() -> None:
    y = np.array([0, 1, 0, 1])
    p = np.array([0.42, 0.44, 0.46, 0.48])
    t = reliability_table(y, p, n_bins=10)
    row = t[t["n"] > 0].iloc[0]
    assert row["n"] == 4 and row["obs_freq"] == pytest.approx(0.5)
    assert row["obs_lo"] < 0.5 < row["obs_hi"]


def test_confusion_and_rates() -> None:
    y = np.array([1, 1, 0, 0, 0])
    p = np.array([0.9, 0.2, 0.8, 0.1, 0.05])
    m = confusion(y, p, 0.5).as_metrics()
    assert (m["tp_w"], m["fp_w"], m["tn_w"], m["fn_w"]) == (1, 1, 2, 1)
    assert m["precision"] == 0.5 and m["recall"] == 0.5 and m["fpr"] == pytest.approx(1 / 3)
    assert m["fdp"] == 0.5 and m["f1"] == pytest.approx(0.5)


def test_best_f1_threshold() -> None:
    y = np.array([1, 1, 0, 0])
    p = np.array([0.9, 0.7, 0.6, 0.1])
    tau, f1 = best_f1_threshold(y, p)
    assert tau == pytest.approx(0.7) and f1 == pytest.approx(1.0)


def test_capture_rate_pooled_and_daily() -> None:
    y = np.array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0])
    s = np.array([.9, .1, .2, .3, .4, .05, .5, .6, .7, .8])
    c = capture_rate(y, s, 0.10)
    assert c["capture_rate"] == pytest.approx(0.5) and c["flagged_weight"] == 1
    groups = np.array([0] * 5 + [1] * 5)
    d = capture_rate(y, s, 0.20, groups=groups)
    assert d["capture_rate"] == pytest.approx(0.5) and d["flagged_weight"] == 2
