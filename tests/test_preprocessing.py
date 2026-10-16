"""Preprocessing is fitted on training partitions only (no test statistics used)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from wildfire_kz.config.schema import Config
from wildfire_kz.models.pipelines import ModelSpec, SeasonalLandcoverBaseline, fit_model


def _data(seed: int, shift: float, n: int = 2000) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x = rng.normal(shift, 1.0 + shift, n)
    x[rng.random(n) < 0.3] = np.nan
    return pd.DataFrame(
        {
            "x": x,
            "z": rng.normal(shift, 1, n),
            "lc_group": rng.choice(["forest", "cropland"], n),
            "label": (rng.random(n) < 0.1).astype(int),
        }
    )


@pytest.fixture()
def cfg() -> Config:
    return Config.model_validate({"models": {"n_jobs": 1}})


def test_imputer_and_scaler_use_training_statistics_only(cfg: Config) -> None:
    train, test = _data(0, 0.0), _data(1, 50.0)
    spec = ModelSpec("lr", "logistic", ["x", "z", "lc_group"], ["lc_group"], {"C": 1.0})
    fm = fit_model(spec, cfg, 0, train, train["label"].to_numpy(), np.ones(len(train)))
    num = fm.preprocessor.named_steps["encode"].named_transformers_["num"]  # type: ignore[union-attr]
    imp, scaler = num.named_steps["impute"], num.named_steps["scale"]
    assert imp.statistics_[0] == pytest.approx(np.nanmedian(train["x"]))
    assert imp.statistics_[0] != pytest.approx(np.nanmedian(pd.concat([train, test])["x"]))
    xi = train["x"].fillna(np.nanmedian(train["x"]))
    assert scaler.mean_[0] == pytest.approx(xi.mean())
    before = (imp.statistics_.copy(), scaler.mean_.copy())
    fm.predict_proba(test)  # transforming test rows must not refit anything
    assert np.allclose(before[0], imp.statistics_) and np.allclose(before[1], scaler.mean_)


def test_feature_screening_decided_on_training_rows(cfg: Config) -> None:
    train = _data(0, 0.0)
    train["empty_in_train"] = np.nan
    test = _data(1, 0.0)
    test["empty_in_train"] = 1.0  # informative only in test -> must still be dropped
    spec = ModelSpec(
        "xgb",
        "xgboost",
        ["x", "z", "empty_in_train", "lc_group"],
        ["lc_group"],
        {"n_estimators": 10},
    )
    fm = fit_model(spec, cfg, 0, train, train["label"].to_numpy(), np.ones(len(train)))
    screen = fm.preprocessor.named_steps["screen"].named_transformers_["screen"]  # type: ignore[union-attr]
    assert "empty_in_train" in screen.dropped_ and screen.train_stats_["n_rows"] == len(train)
    assert "empty_in_train" not in fm.transform(test).columns


def test_unseen_category_in_test_is_ignored(cfg: Config) -> None:
    train, test = _data(0, 0.0), _data(1, 0.0)
    test["lc_group"] = "shrubland"
    spec = ModelSpec("lr", "logistic", ["x", "z", "lc_group"], ["lc_group"], {"C": 1.0})
    fm = fit_model(spec, cfg, 0, train, train["label"].to_numpy(), np.ones(len(train)))
    cols = fm.transform(test).columns
    assert "lc_group_shrubland" not in cols
    assert np.isfinite(fm.predict_proba(test)).all()


def test_seasonal_baseline_smoothing() -> None:
    X = pd.DataFrame({"lc_group": ["a"] * 4 + ["b"] * 4, "month": [1] * 8})
    y = np.array([1, 0, 0, 0, 0, 0, 0, 0])
    m = SeasonalLandcoverBaseline(alpha=4.0).fit(X, y, sample_weight=np.ones(8))
    overall = 1 / 8
    p = m.predict_proba(pd.DataFrame({"lc_group": ["a", "b", "zz"], "month": [1, 1, 7]}))[:, 1]
    assert p[0] == pytest.approx((1 + 4 * overall) / (4 + 4))
    assert p[1] == pytest.approx((0 + 4 * overall) / (4 + 4))
    assert p[2] == pytest.approx(overall)  # unseen stratum falls back to overall rate
