"""Protect the pre-test explanation workaround for non-symmetric CatBoost trees."""

import numpy as np
import pandas as pd
import pytest
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from wildfire_kz.models import FittedModel
from wildfire_kz.public_explanation import contributions


def test_lossguide_explanation_reconstructs_raw_margin_and_requires_background():
    catboost = pytest.importorskip("catboost")
    pytest.importorskip("shap")
    rng = np.random.default_rng(42)
    frame = pd.DataFrame(rng.normal(size=(200, 3)), columns=["a", "b", "c"])
    label = (frame.a + frame.b * frame.c > 0).astype(int)
    preprocess = StandardScaler().fit(frame)
    estimator = catboost.CatBoostClassifier(
        iterations=5,
        depth=3,
        grow_policy="Lossguide",
        min_data_in_leaf=5,
        random_seed=42,
        thread_count=1,
        verbose=False,
        allow_writing_files=False,
    ).fit(preprocess.transform(frame), label)
    model = FittedModel(
        "catboost",
        list(frame.columns),
        Pipeline([("preprocess", preprocess), ("estimator", estimator)]),
    )
    with pytest.raises(ValueError, match="training-only background"):
        contributions(model, frame.head(12))
    features, values, base, unit = contributions(model, frame.head(12), frame.tail(128))
    expected = estimator.predict(
        preprocess.transform(frame.head(12)), prediction_type="RawFormulaVal"
    )
    assert features == list(frame.columns) and unit == "uncalibrated log-odds"
    np.testing.assert_allclose(base + values.sum(axis=1), expected, atol=1e-10)
