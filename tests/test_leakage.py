"""Temporal leakage guarantees: as-of timestamps, MODIS lag, ERA5 accumulation, detections."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from wildfire_kz.config.schema import Config, ModisVISource
from wildfire_kz.features.era5 import daily_precip_from_accumulated, relative_humidity
from wildfire_kz.features.fire_history import fire_history_counts
from wildfire_kz.features.leakage import LeakageError, check_no_leakage
from wildfire_kz.features.modis import composite_dates, vegetation_features, vegetation_regimes
from wildfire_kz.features.registry import feature_specs

# ----------------------------------------------------------------------------- leakage check


def _frame(asof_weather: str, date: str = "2020-07-10") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [pd.Timestamp(date)],
            "t2m_max_c": [30.0],
            "asof_weather": [pd.Timestamp(asof_weather)],
        }
    )


def test_leakage_check_accepts_prior_day() -> None:
    rep = check_no_leakage(_frame("2020-07-09"), feature_specs(Config()))
    assert rep["passed"]


@pytest.mark.parametrize("asof", ["2020-07-10", "2020-07-11"])
def test_leakage_check_rejects_same_or_future_day(asof: str) -> None:
    with pytest.raises(LeakageError):
        check_no_leakage(_frame(asof), feature_specs(Config()))


def test_leakage_check_rejects_values_without_asof() -> None:
    df = _frame("2020-07-09")
    df["asof_weather"] = pd.NaT
    with pytest.raises(LeakageError):
        check_no_leakage(df, feature_specs(Config()))


# ----------------------------------------------------------------------------- ERA5-Land


def test_era5_land_accumulation_convention() -> None:
    """Daily total of D is the 00 UTC value of D+1 (accumulation resets at 00 UTC)."""
    times = pd.date_range("2020-07-01 00:00", "2020-07-03 00:00", freq="h")
    hourly_mm = np.zeros(len(times))
    hourly_mm[(times.day == 1) & (times.hour.isin([3, 4]))] = 2.5  # 5 mm on Jul 1
    hourly_mm[(times.day == 2) & (times.hour == 10)] = 1.0  # 1 mm on Jul 2
    acc = np.zeros(len(times))
    day = times.normalize()
    for i, t in enumerate(times):
        if t.hour == 0:  # 00 UTC holds the complete total of the previous UTC day
            acc[i] = hourly_mm[(day == t - pd.Timedelta(days=1)) & (times.hour >= 1)].sum()
        else:  # accumulation since 00 UTC of the same day
            acc[i] = hourly_mm[
                (day == t.normalize()) & (times.hour >= 1) & (times.hour <= t.hour)
            ].sum()
    tp = xr.DataArray(acc / 1000.0, coords={"valid_time": times}, dims="valid_time")
    daily = daily_precip_from_accumulated(tp)
    got = daily.to_series()
    assert got[pd.Timestamp("2020-07-01")] == pytest.approx(5.0)
    assert got[pd.Timestamp("2020-07-02")] == pytest.approx(1.0)
    assert pd.Timestamp("2020-07-03") not in got.index  # needs 00 UTC of Jul 4


def test_relative_humidity_bounds() -> None:
    assert relative_humidity(np.array(20.0), np.array(20.0)) == pytest.approx(100.0)
    assert 0 < relative_humidity(np.array(30.0), np.array(5.0)) < 30


# ----------------------------------------------------------------------------- MODIS lag


def _composites(values: dict[int, float]) -> tuple[pd.DataFrame, ModisVISource]:
    src = ModisVISource(source_id="x", publication_lag_days=10)
    rows = []
    for doy, val in values.items():
        c = composite_dates(2020, doy, src)
        rows.append(
            {
                "cell_idx": 0,
                "start": pd.Timestamp(c.start),
                "end": pd.Timestamp(c.end),
                "available": pd.Timestamp(c.available),
                "ndvi": val,
                "evi": val / 2,
            }
        )
    return pd.DataFrame(rows), src


def test_composite_usable_only_after_interval_end_plus_lag() -> None:
    comp, src = _composites({161: 0.5})  # 2020-06-09 .. 2020-06-24
    c = composite_dates(2020, 161, src)
    assert c.end == dt.date(2020, 6, 24) and c.available == dt.date(2020, 7, 5)
    reg = vegetation_regimes(comp, 1, src.max_gap_fill_days)
    dates = pd.to_datetime(["2020-06-24", "2020-07-05", "2020-07-06"]).to_numpy()
    feats = vegetation_features(reg, np.zeros(3, dtype=int), dates)
    # t=07-05 -> t-1=07-04 < availability: not usable; t=07-06 -> usable
    assert np.isnan(feats["ndvi"].iloc[0]) and np.isnan(feats["ndvi"].iloc[1])
    assert feats["ndvi"].iloc[2] == pytest.approx(0.5)
    assert (feats["asof_vegetation"].dropna() < pd.Timestamp("2020-07-06")).all()


def test_gap_fill_limited_to_32_days_then_nan() -> None:
    # valid at doy 161, invalid (NaN) at 177, 193, 209
    comp, src = _composites({161: 0.6, 177: np.nan, 193: np.nan, 209: np.nan})
    reg = vegetation_regimes(comp, 1, src.max_gap_fill_days)
    avail = {d: composite_dates(2020, d, src).available for d in (177, 193, 209)}
    t = [pd.Timestamp(avail[d]) + pd.Timedelta(days=1) for d in (177, 193, 209)]
    f = vegetation_features(reg, np.zeros(3, dtype=int), np.array(t, dtype="datetime64[ns]"))
    assert f["ndvi"].iloc[0] == pytest.approx(0.6)  # 16 days stale -> filled
    assert f["ndvi"].iloc[1] == pytest.approx(0.6)  # 32 days stale -> filled
    assert np.isnan(f["ndvi"].iloc[2])  # 48 days stale -> NaN preserved


# ----------------------------------------------------------------------------- detections


def test_later_detections_never_enter_predictors() -> None:
    det_cell = np.array([5, 5, 5])
    det_time = pd.to_datetime(["2020-07-01 08:00", "2020-07-03 20:00", "2020-07-04 08:00"])
    rows_cell = np.array([5])
    target = np.array(["2020-07-04"], dtype="datetime64[D]")
    base = fire_history_counts(det_cell, det_time, rows_cell, target, 365)
    # add later detections (same day and after) of the event: result unchanged
    more_cell = np.r_[det_cell, [5, 5, 5]]
    more_time = det_time.append(
        pd.to_datetime(["2020-07-04 20:00", "2020-07-05 08:00", "2020-08-01 08:00"])
    )
    after = fire_history_counts(more_cell, more_time, rows_cell, target, 365)
    assert base[0] == after[0] == 2  # Jul 1 and Jul 3 only (Jul 4 is the target day)
