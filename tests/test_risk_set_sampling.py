"""48 h past-only exclusion and inverse-inclusion sampling weights."""

from __future__ import annotations

import numpy as np
import pandas as pd

from wildfire_kz.config.schema import Config
from wildfire_kz.sampling.design import allocate_training, stratified_sample
from wildfire_kz.sampling.risk_set import excluded_cell_days


def _ex(times: list[str], hours: float = 48.0) -> set[tuple[int, pd.Timestamp]]:
    df = excluded_cell_days(np.array([7] * len(times)), pd.to_datetime(times), hours)
    return {(int(c), pd.Timestamp(d)) for c, d in zip(df["cell_id"], df["date"], strict=True)}


def test_detection_excludes_the_following_two_days_only() -> None:
    ex = _ex(["2020-06-10 13:30"])
    days = sorted(d for _, d in ex)
    # cutoffs 06-11 00:00 and 06-12 00:00 are within 48 h after the detection; 06-13 is not
    assert days == [pd.Timestamp("2020-06-11"), pd.Timestamp("2020-06-12")]


def test_exclusion_is_past_only() -> None:
    ex = _ex(["2020-06-10 13:30"])
    assert (7, pd.Timestamp("2020-06-10")) not in ex  # same-day detection is not "past"


def test_exactly_48h_before_cutoff_is_excluded() -> None:
    ex = _ex(["2020-06-10 00:00"])
    assert (7, pd.Timestamp("2020-06-12")) in ex
    assert (7, pd.Timestamp("2020-06-13")) not in ex


def test_outside_grid_detections_are_ignored() -> None:
    df = excluded_cell_days(np.array([-1]), pd.to_datetime(["2020-06-10 13:30"]), 48)
    assert df.empty


def test_configurable_exclusion_window() -> None:
    assert len(_ex(["2020-06-10 13:30"], hours=24)) == 1


def _risk_set(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = 6000
    return pd.DataFrame(
        {
            "year": 2019,
            "month": rng.integers(1, 4, n),
            "lc_group": rng.choice(["a", "b"], n),
            "label": (rng.random(n) < 0.02).astype(int),
            "attr": rng.gamma(2.0, 3.0, n),
        }
    )


def test_training_weights_reproduce_stratum_totals_exactly() -> None:
    cfg = Config()
    rs = _risk_set()
    inc, q, _ = stratified_sample(rs, ["year", "month", "lc_group"], "train", cfg)
    w = np.where(inc, 1.0 / q, 0.0)
    assert np.isclose(w.sum(), len(rs))
    for key, g in rs.groupby(["year", "month", "lc_group"]):
        assert np.isclose(w[g.index].sum(), len(g)), key
    assert (q[rs["label"] == 1] == 1.0).all()  # all positives retained


def test_weighted_totals_unbiased_in_expectation() -> None:
    """Horvitz–Thompson totals of an arbitrary attribute are unbiased over repeated draws."""
    rs = _risk_set(1)
    truth = rs["attr"].sum()
    est = []
    for s in range(200):
        cfg = Config.model_validate({"project": {"seed": s}})
        inc, q, _ = stratified_sample(rs, ["year", "month", "lc_group"], "train", cfg)
        est.append(float((rs["attr"][inc] / q[inc]).sum()))
    est_arr = np.asarray(est)
    se = est_arr.std(ddof=1) / np.sqrt(len(est_arr))
    assert abs(est_arr.mean() - truth) < 4 * se + 1e-9


def test_minimum_allocation_for_strata_without_fires() -> None:
    assert allocate_training(n_neg=1000, n_pos=0, ratio=10, minimum=50) == 50
    assert allocate_training(n_neg=1000, n_pos=7, ratio=10, minimum=50) == 70
    assert allocate_training(n_neg=30, n_pos=7, ratio=10, minimum=50) == 30


def test_evaluation_design_complete_when_fraction_is_one() -> None:
    cfg = Config()
    rs = _risk_set(2)
    inc, q, _ = stratified_sample(rs, ["year", "month", "lc_group"], "eval", cfg)
    assert inc.all() and np.allclose(q, 1.0)


def test_evaluation_design_probability_sample_keeps_all_positives() -> None:
    cfg = Config.model_validate({"sampling": {"eval_negative_fraction": 0.3}})
    rs = _risk_set(3)
    inc, q, _ = stratified_sample(rs, ["year", "month", "lc_group"], "eval", cfg)
    assert inc[rs["label"] == 1].all()
    assert np.isclose((1.0 / q[inc]).sum(), len(rs))
