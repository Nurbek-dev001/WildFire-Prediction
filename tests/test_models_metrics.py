import numpy as np
import pandas as pd
import pytest

from wildfire_kz.calibration import fit_sigmoid
from wildfire_kz.config import Config
from wildfire_kz.evaluation import metrics
from wildfire_kz.models import fit_model


def test_hand_metrics():
    y = np.array([1, 0, 1, 0])
    p = np.array([0.9, 0.8, 0.4, 0.1])
    result = metrics(y, p, np.ones(4), 0.5, np.full(4, 0.5))
    assert result["average_precision"] == pytest.approx((1 + 2 / 3) / 2)
    assert result["brier"] == pytest.approx((0.01 + 0.64 + 0.36 + 0.01) / 4)
    assert result["bss"] == pytest.approx(1 - 0.255 / 0.25)
    assert result["ece"] == pytest.approx((0.1 + 0.8 + 0.6 + 0.1) / 4)
    assert result["f1"] == 0.5


def test_preprocessing_train_only():
    train = pd.DataFrame(
        {
            "x1": [0.0, 2.0, np.nan, 4.0],
            "label": [0, 0, 1, 1],
            "day": pd.to_datetime(["2018-01-01"] * 4),
            "landcover": "grassland",
        }
    )
    model = fit_model("logistic", train, ["x1"], Config())
    imputer = model.pipeline.named_steps["preprocess"].named_steps["impute"]
    assert imputer.statistics_[0] == 2
    test = pd.DataFrame({"x1": [1000000.0, np.nan]})
    model.predict(test)
    assert imputer.statistics_[0] == 2


def test_calibration_year_guard():
    frame = pd.DataFrame({"day": pd.to_datetime(["2023-01-01"] * 2), "label": [0, 1]})
    with pytest.raises(PermissionError):
        fit_sigmoid(frame, np.array([0.2, 0.8]), 2022)
