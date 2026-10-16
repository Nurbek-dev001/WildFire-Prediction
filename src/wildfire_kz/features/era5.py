"""ERA5-Land hourly -> daily -> per-cell prior-day and antecedent weather features.

ERA5-Land conventions handled here:

* instantaneous fields (t2m, d2m, u10, v10, swvl1) at valid times 00..23 UTC of day D are
  aggregated to day D;
* ``tp`` is *accumulated from 00 UTC* within each day; the 00 UTC step of day D+1 holds the
  complete total of day D. Daily totals are therefore read from the 00 UTC step of D+1 and
  assigned to D (observation day D), never differenced across the daily reset.

Features for target day t use observation days <= t-1 only. Daily fields are computed on
the native ERA5 grid first and then interpolated to cell centroids (interpolation adds no
meteorological detail beyond ~9 km).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
import xarray as xr

from wildfire_kz.config.schema import Config
from wildfire_kz.utils.runtime import get_logger

log = get_logger("features.era5")

MAGNUS_A = 17.625
MAGNUS_B = 243.04  # °C (Alduchov & Eskridge 1996)


def relative_humidity(
    t_c: xr.DataArray | np.ndarray, td_c: xr.DataArray | np.ndarray
) -> xr.DataArray | np.ndarray:
    """RH (%) from air temperature and dewpoint (°C) via the Magnus formula, capped at 100."""
    rh = (
        100.0
        * np.exp(MAGNUS_A * td_c / (MAGNUS_B + td_c))
        / np.exp(MAGNUS_A * t_c / (MAGNUS_B + t_c))
    )
    return np.minimum(rh, 100.0)


def daily_precip_from_accumulated(tp: xr.DataArray, time_dim: str = "valid_time") -> xr.DataArray:
    """Daily totals (mm) from ERA5-Land accumulations: total(D) = tp(D+1 00 UTC)."""
    t = pd.DatetimeIndex(tp[time_dim].values)
    at00 = tp.sel({time_dim: t[t.hour == 0]})
    obs_day = pd.DatetimeIndex(at00[time_dim].values) - pd.Timedelta(days=1)
    out = (at00 * 1000.0).assign_coords({time_dim: obs_day}).rename({time_dim: "date"})
    return out.clip(min=0.0)


def _open_one(path: Path) -> xr.Dataset:
    ds = xr.open_dataset(path, engine="netcdf4")
    if "time" in ds.dims and "valid_time" not in ds.dims:
        ds = ds.rename({"time": "valid_time"})
    return ds.sortby("valid_time").sortby("latitude")


def _instantaneous_daily(ds: xr.Dataset, steps_per_day: int = 24) -> xr.Dataset:
    """Daily aggregates of instantaneous fields; incomplete days (< steps_per_day) are NaN."""
    t2m = ds["t2m"] - 273.15
    d2m = ds["d2m"] - 273.15
    rh = xr.DataArray(relative_humidity(t2m, d2m))
    wspd = xr.DataArray(np.hypot(ds["u10"], ds["v10"]))
    daily = xr.Dataset(
        {
            "t2m_max_c": t2m.resample(valid_time="1D").max(),
            "t2m_min_c": t2m.resample(valid_time="1D").min(),
            "t2m_mean_c": t2m.resample(valid_time="1D").mean(),
            "d2m_mean_c": d2m.resample(valid_time="1D").mean(),
            "rh_mean_pct": rh.resample(valid_time="1D").mean(),
            "rh_min_pct": rh.resample(valid_time="1D").min(),
            "wind_mean_ms": wspd.resample(valid_time="1D").mean(),
            "wind_max_ms": wspd.resample(valid_time="1D").max(),
            "swvl1": ds["swvl1"].resample(valid_time="1D").mean(),
        }
    ).rename({"valid_time": "date"})
    counts = ds["t2m"].resample(valid_time="1D").count().rename({"valid_time": "date"})
    return daily.where(counts == steps_per_day)


def daily_precip_from_hourly(tp: xr.DataArray, time_dim: str = "valid_time") -> xr.DataArray:
    """Daily totals (mm) from hourly accumulations: total(D) = sum over (D 00, D+1 00] UTC."""
    shifted = tp.assign_coords(
        {time_dim: pd.DatetimeIndex(tp[time_dim].values) - pd.Timedelta(hours=1)}
    )
    out = shifted.resample({time_dim: "1D"}).sum(min_count=24) * 1000.0
    return out.rename({time_dim: "date"}).clip(min=0.0)


def daily_fields_from_files(
    files: list[Path],
    first_day: pd.Timestamp,
    last_day: pd.Timestamp,
    precip_convention: str = "daily_reset",
    steps_per_day: int = 24,
) -> xr.Dataset:
    """Daily fields for observation days [first_day, last_day], processed file by file.

    Only one file (typically one month of hourly data) is held in memory at a time, which
    keeps national-extent processing within workstation memory. Files must contain whole UTC
    days (as delivered by monthly CDS requests).
    """
    if not files:
        raise FileNotFoundError("no ERA5-Land files registered")
    lo = first_day
    hi = last_day + pd.Timedelta(days=1)  # the 00 UTC step of last_day+1 holds tp(last_day)
    dailies, tp00 = [], []
    for f in sorted(files):
        with _open_one(f) as ds:
            t = pd.DatetimeIndex(ds["valid_time"].values)
            if t.max() < lo or t.min() > hi:
                continue
            sub = ds.sel(valid_time=slice(lo, hi + pd.Timedelta(hours=23))).load()
        st = pd.DatetimeIndex(sub["valid_time"].values)
        inst = sub.sel(valid_time=st[st < hi])
        if inst.sizes["valid_time"]:
            dailies.append(_instantaneous_daily(inst, steps_per_day))
        if precip_convention == "hourly":
            tp00.append(sub["tp"].sel(valid_time=st[(st > lo) & (st <= hi)]))
        else:
            tp00.append(sub["tp"].sel(valid_time=st[(st.hour == 0) & (st > lo) & (st <= hi)]))
    if not dailies:
        raise FileNotFoundError(
            f"no ERA5-Land data cover {first_day:%Y-%m-%d}..{last_day:%Y-%m-%d}"
        )
    daily = xr.concat(dailies, dim="date")
    if pd.Index(daily["date"].values).duplicated().any():
        raise ValueError("ERA5-Land files overlap or split UTC days; provide whole-day files")
    tp_all = xr.concat(tp00, dim="valid_time")
    tp_all = tp_all.isel(valid_time=~pd.Index(tp_all["valid_time"].values).duplicated())
    precip = (
        daily_precip_from_hourly(tp_all)
        if precip_convention == "hourly"
        else daily_precip_from_accumulated(tp_all)
    )
    daily["precip_mm"] = precip.reindex(date=daily["date"])
    days = pd.date_range(first_day, last_day, freq="D")
    return daily.reindex(date=days)


def to_cells(
    daily: xr.Dataset, lon: np.ndarray, lat: np.ndarray, method: Literal["linear", "nearest"]
) -> xr.Dataset:
    """Interpolate native-grid daily fields to cell centroids (nearest fallback at edges)."""
    pts_lon = xr.DataArray(lon, dims="cell")
    pts_lat = xr.DataArray(lat, dims="cell")
    out = daily.interp(longitude=pts_lon, latitude=pts_lat, method=method)
    if method != "nearest":
        near = daily.sel(longitude=pts_lon, latitude=pts_lat, method="nearest")
        out = out.fillna(near)
    return out.drop_vars(["longitude", "latitude"], errors="ignore")


def fosberg_ffwi(t_c: np.ndarray, rh: np.ndarray, wind_ms: np.ndarray) -> np.ndarray:
    """Fosberg fire-weather index (Fosberg 1978) from temperature, RH and wind."""
    tf = t_c * 9 / 5 + 32
    h = np.clip(rh, 0, 100)
    m = np.where(
        h < 10,
        0.03229 + 0.281073 * h - 0.000578 * h * tf,
        np.where(
            h < 50,
            2.22749 + 0.160107 * h - 0.01478 * tf,
            21.0606 + 0.005565 * h**2 - 0.00035 * h * tf - 0.483199 * h,
        ),
    )
    r = m / 30.0
    eta = 1 - 2 * r + 1.5 * r**2 - 0.5 * r**3
    u = wind_ms * 2.23694
    return np.asarray(eta * np.sqrt(1 + u**2) / 0.3002)


def _window_sum(a: np.ndarray, pos: np.ndarray, w: int) -> np.ndarray:
    """Sum of ``a[d-w+1 .. d]`` along axis 0 for every ``d`` in ``pos``.

    NaN when the window starts before the series, ``d`` is unknown (-1) or any day in the
    window is missing (equivalent to ``rolling(w, min_periods=w).sum()``).
    """
    filled = np.nan_to_num(a.astype(np.float64), nan=0.0)
    csum = np.vstack([np.zeros((1, a.shape[1])), np.cumsum(filled, axis=0)])
    cnan = np.vstack(
        [np.zeros((1, a.shape[1]), dtype=np.int32), np.cumsum(np.isnan(a), axis=0, dtype=np.int32)]
    )
    lo = pos - w + 1
    ok = (pos >= 0) & (lo >= 0)
    hi_i, lo_i = np.where(ok, pos + 1, 0), np.where(ok, lo, 0)
    out = (csum[hi_i] - csum[lo_i]).astype(np.float32)
    out[(cnan[hi_i] - cnan[lo_i]) > 0] = np.nan
    out[~ok] = np.nan
    return out


def weather_feature_cube(
    cfg: Config, files: list[Path], year: int, lon: np.ndarray, lat: np.ndarray
) -> xr.Dataset:
    """Features indexed by TARGET date t (all of ``year``) x cell, built from days <= t-1."""
    wcfg = cfg.features.weather
    wmax = max(wcfg.antecedent_windows_days)
    t_first = pd.Timestamp(year, 1, 1)
    t_last = pd.Timestamp(year, 12, 31)
    obs_first = t_first - pd.Timedelta(days=wmax)
    src = cfg.sources.era5_land
    daily = daily_fields_from_files(
        files,
        obs_first,
        t_last - pd.Timedelta(days=1),
        src.precip_convention,
        src.instantaneous_steps_per_day,
    )
    dtype = cfg.features.float_dtype
    targets = pd.date_range(t_first, t_last, freq="D")
    obs_days = pd.DatetimeIndex(daily["date"].values)
    # observation day t-1 for every target t (position in the daily series)
    pos = obs_days.get_indexer(targets - pd.Timedelta(days=1))
    method = cfg.sources.era5_land.interpolation
    # one variable at a time in float32: a national 5 km grid has ~1e5 cells, so a full
    # float64 dataset of every variable would not fit in workstation memory
    cells: dict[str, np.ndarray] = {}
    for v in daily.data_vars:
        da = to_cells(daily[[v]], lon, lat, method)[v].transpose("date", "cell")
        cells[str(v)] = np.asarray(da.values, dtype=np.float32)
    out: dict[str, tuple[tuple[str, str], np.ndarray]] = {}
    for v in (
        "t2m_max_c",
        "t2m_min_c",
        "t2m_mean_c",
        "d2m_mean_c",
        "rh_mean_pct",
        "rh_min_pct",
        "wind_mean_ms",
        "wind_max_ms",
        "precip_mm",
        "swvl1",
    ):
        out[v] = (("date", "cell"), cells[v][pos])
    # antecedent windows ending at t-1 (all w days must be present)
    for w in wcfg.antecedent_windows_days:
        out[f"precip_sum_{w}d_mm"] = (("date", "cell"), _window_sum(cells["precip_mm"], pos, w))
        out[f"t2m_max_mean_{w}d_c"] = (
            ("date", "cell"),
            _window_sum(cells["t2m_max_c"], pos, w) / w,
        )
        out[f"rh_mean_{w}d_pct"] = (("date", "cell"), _window_sum(cells["rh_mean_pct"], pos, w) / w)
    p = cells["precip_mm"]
    dry = np.where(np.isnan(p), np.nan, (p < wcfg.rain_day_threshold_mm).astype(np.float32))
    out[f"dry_days_{wmax}d"] = (("date", "cell"), _window_sum(dry, pos, wmax))
    del cells
    if wcfg.include_fire_weather_index:
        out["ffwi_fosberg"] = (
            ("date", "cell"),
            fosberg_ffwi(out["t2m_max_c"][1], out["rh_min_pct"][1], out["wind_mean_ms"][1]),
        )
    cube = xr.Dataset(
        {k: (dims, np.asarray(v, dtype=dtype)) for k, (dims, v) in out.items()},
        coords={"date": targets, "cell": np.arange(len(lon))},
    )
    cube["asof_weather"] = ("date", (targets - pd.Timedelta(days=1)).values)
    return cube
