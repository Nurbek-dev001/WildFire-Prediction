import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from wildfire_kz.config import SamplingConfig
from wildfire_kz.features import asof_join, assert_no_leakage, vegetation_available, weather_daily
from wildfire_kz.sampling import sample_training
from wildfire_kz.splits import spatial_folds


def test_composite_lag_and_max_fill():
    observations = pd.DataFrame(
        {
            "cell_id": ["a"],
            "interval_end": ["2020-01-17"],
            "available_at": ["2020-01-17"],
            "qa": [0],
            "ndvi": [0.5],
            "evi": [0.3],
        }
    )
    target = pd.DataFrame(
        {
            "cell_id": ["a"] * 4,
            "day": pd.to_datetime(
                ["2020-01-18", "2020-01-19", "2020-01-20", "2020-03-01"], utc=True
            ),
        }
    )
    result = asof_join(
        target, vegetation_available(observations, 2), ["ndvi", "evi"], maximum_age_days=32
    )
    assert result.ndvi.isna().tolist() == [True, True, False, True]
    assert_no_leakage(result, ["ndvi", "evi"])


def test_leakage_fails_closed():
    frame = pd.DataFrame({"day": pd.to_datetime(["2020-01-01"], utc=True), "ndvi": [1.0]})
    with pytest.raises(ValueError):
        assert_no_leakage(frame, ["ndvi"])
    frame["ndvi__asof"] = frame.day
    with pytest.raises(ValueError):
        assert_no_leakage(frame, ["ndvi"])
    with pytest.raises(ValueError):
        assert_no_leakage(frame, ["detection_count"])


def test_era5_midnight_is_previous_days_total():
    times = pd.date_range("2020-01-01", periods=49, freq="h", tz="UTC")
    h = pd.DataFrame(
        {
            "cell_id": "a",
            "timestamp": times,
            "available_at": times,
            "t2m": 293.15,
            "d2m": 283.15,
            "u10": 3,
            "v10": 4,
            "swvl1": 0.2,
            "tp": [(t.hour or 24) * 0.001 for t in times],
        }
    )
    result = weather_daily(h, "era5_land_cumulative", 0)
    assert result.iloc[0].precip == pytest.approx(24)
    assert result.iloc[0].wind == 5
    assert result.iloc[0].tmax == pytest.approx(20)
    assert result.iloc[0].available_at >= times[24]


def test_ht_sampling_totals_and_zero_fire_stratum():
    data = pd.DataFrame(
        {
            "day": pd.to_datetime(["2020-01-01"] * 101 + ["2020-02-01"] * 100),
            "landcover": "grassland",
            "label": [1] + [0] * 200,
        }
    )
    estimates = []
    for seed in range(30):
        sampled = sample_training(data, SamplingConfig(minimum_negatives=5), seed)
        assert sampled.label.sum() == 1
        assert sampled.loc[sampled.day.dt.month == 2, "q"].eq(0.05).all()
        estimates.append(sampled.weight.sum())
    assert np.mean(estimates) == pytest.approx(len(data))


def test_spatial_buffers_and_whole_blocks():
    data = pd.DataFrame(
        {
            "cell_id": list("abcde"),
            "x": np.arange(5) * 300000 + 2500,
            "y_coord": 2500,
            "cell_wkt": [box(x, 0, x + 5000, 5000).wkt for x in np.arange(5) * 300000],
        }
    )
    for _, train, valid in spatial_folds(data, 100000, 5, 25000):
        assert not set(train) & set(valid)
        assert min(abs(data.iloc[t].x - data.iloc[v].x) for t in train for v in valid) >= 25000
