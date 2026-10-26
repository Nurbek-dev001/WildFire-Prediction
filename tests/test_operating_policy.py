"""Meaningful time-boundary and design-weight checks for the alert revision."""

import numpy as np
import pandas as pd
import pytest

from wildfire_kz.operating_policy import choose_threshold, threshold_curve


def test_policy_refuses_test_dates_before_reading_probabilities():
    frame = pd.DataFrame({"day": pd.to_datetime(["2022-12-31", "2023-01-01"], utc=True)})
    with pytest.raises(PermissionError, match="2022"):
        threshold_curve(frame, None)


def test_probability_weights_change_f2_choice_and_counts_match_directly():
    frame = pd.DataFrame(
        {
            "day": pd.to_datetime(["2022-01-01"] * 4, utc=True),
            "label": [1, 0, 1, 0],
            "weight": [1.0, 100.0, 1.0, 1000.0],
        }
    )
    p = np.array([0.9, 0.8, 0.7, 0.1])
    curve = threshold_curve(frame, p)
    weighted = choose_threshold(curve, 2)
    unweighted = choose_threshold(threshold_curve(frame.assign(weight=1.0), p), 2)
    assert weighted.threshold == 0.9 and unweighted.threshold == 0.7
    for row in curve.itertuples():
        selected = p >= row.threshold
        tp = float((frame.weight * frame.label * selected).sum())
        mass = float((frame.weight * selected).sum())
        assert row.alert_fraction == pytest.approx(mass / frame.weight.sum())
        assert row.recall == pytest.approx(tp / 2)
        assert row.precision == pytest.approx(tp / mass)
    assert choose_threshold(curve, 2, 0.8).recall >= 0.8


def test_equal_objectives_choose_higher_threshold():
    curve = pd.DataFrame({"threshold": [0.1, 0.2], "f2": [0.5, 0.5], "recall": [0.9, 0.8]})
    assert choose_threshold(curve).threshold == 0.2
