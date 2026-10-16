"""MOD13A2 v061 16-day NDVI/EVI: QA masking, aggregation and lag-aware as-of lookup.

Availability rule: a composite covering [start, end] becomes *available* on
``end + 1 day + publication_lag_days`` and may be used for target day t only if
``available <= t - 1``. Gap rule: when the newest usable composite is invalid (QA/fill) for a
cell, the last valid value is carried forward only while its composite end lies within
``max_gap_fill_days`` of the newest usable composite's end; afterwards the value is NaN
(missingness is preserved, never interpolated from the future).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd
from rasterio.enums import Resampling

from wildfire_kz.config.schema import Config, ModisVISource
from wildfire_kz.data.rasters import GridAggregator, raster_catalog
from wildfire_kz.grid.grid import GridMeta
from wildfire_kz.utils.runtime import get_logger

log = get_logger("features.modis")


@dataclass(frozen=True)
class Composite:
    start: dt.date
    end: dt.date
    available: dt.date


def composite_dates(year: int, doy: int, src: ModisVISource) -> Composite:
    start = dt.date(year, 1, 1) + dt.timedelta(days=doy - 1)
    end = min(start + dt.timedelta(days=src.composite_length_days - 1), dt.date(year, 12, 31))
    available = end + dt.timedelta(days=1 + src.publication_lag_days)
    return Composite(start=start, end=end, available=available)


def aggregate_composites(cfg: Config, grid: pd.DataFrame, meta: GridMeta,
                         first_needed: dt.date, last_needed: dt.date) -> pd.DataFrame:
    """Per-composite cell means of QA-valid NDVI/EVI (long table)."""
    src = cfg.sources.mod13a2
    agg = GridAggregator(grid, meta)
    rows = []

    def pixel_fn(bands: list[np.ndarray], res: float) -> dict[str, np.ndarray]:
        ndvi, evi, qa = bands
        ok = np.isfinite(qa) & np.isin(qa, src.valid_qa_values)
        ok_n = ok & np.isfinite(ndvi) & (ndvi != src.fill_value)
        ok_e = ok & np.isfinite(evi) & (evi != src.fill_value)
        return {"ndvi": np.where(ok_n, ndvi * src.scale_factor, np.nan),
                "evi": np.where(ok_e, evi * src.scale_factor, np.nan)}

    for entry in raster_catalog(cfg, src):
        if entry.year is None or entry.doy is None:
            continue
        comp = composite_dates(entry.year, entry.doy, src)
        if comp.available > last_needed or comp.end < first_needed:
            continue
        res = agg.aggregate([entry.path], src.working_resolution_m, src.window_size_km,
                            Resampling.nearest, pixel_fn=pixel_fn,
                            bands=(src.ndvi_band, src.evi_band, src.qa_band))
        rows.append(pd.DataFrame({
            "cell_idx": np.arange(len(grid)), "start": pd.Timestamp(comp.start),
            "end": pd.Timestamp(comp.end), "available": pd.Timestamp(comp.available),
            "ndvi": res.get("ndvi", np.full(len(grid), np.nan)),
            "evi": res.get("evi", np.full(len(grid), np.nan)),
        }))
    if not rows:
        raise FileNotFoundError("no MOD13A2 composites cover the requested period")
    return pd.concat(rows, ignore_index=True)


def vegetation_regimes(comp: pd.DataFrame, n_cells: int, max_gap_days: int
                       ) -> dict[str, np.ndarray]:
    """State after each composite becomes available (regime k = composite k newest usable).

    Returns arrays (n_composites, n_cells) for value/end-date of the last valid composite and
    the NDVI change versus the previous valid composite, plus the availability date vector.
    """
    order = comp[["start", "end", "available"]].drop_duplicates().sort_values("available")
    k = len(order)
    ndvi = comp.pivot(index="end", columns="cell_idx", values="ndvi").reindex(order["end"])
    evi = comp.pivot(index="end", columns="cell_idx", values="evi").reindex(order["end"])
    nd = ndvi.reindex(columns=range(n_cells)).to_numpy(dtype=float)
    ev = evi.reindex(columns=range(n_cells)).to_numpy(dtype=float)
    ends = order["end"].to_numpy(dtype="datetime64[D]")
    last_n = np.full(n_cells, np.nan)
    last_e = np.full(n_cells, np.nan)
    last_end = np.full(n_cells, np.datetime64("NaT"), dtype="datetime64[D]")
    prev_n = np.full(n_cells, np.nan)
    prev_end = np.full(n_cells, np.datetime64("NaT"), dtype="datetime64[D]")
    out = {k_: np.full((k, n_cells), np.nan) for k_ in ("ndvi", "evi", "ndvi_delta")}
    out_end = np.full((k, n_cells), np.datetime64("NaT"), dtype="datetime64[D]")
    for i in range(k):
        valid = np.isfinite(nd[i])
        prev_n = np.where(valid, last_n, prev_n)
        prev_end = np.where(valid, last_end, prev_end)
        last_n = np.where(valid, nd[i], last_n)
        last_e = np.where(valid, np.where(np.isfinite(ev[i]), ev[i], np.nan), last_e)
        last_end = np.where(valid, ends[i], last_end)
        stale = (ends[i] - last_end).astype("timedelta64[D]").astype(float)
        fresh = np.isfinite(stale) & (stale <= max_gap_days)
        out["ndvi"][i] = np.where(fresh, last_n, np.nan)
        out["evi"][i] = np.where(fresh, last_e, np.nan)
        gap_prev = (last_end - prev_end).astype("timedelta64[D]").astype(float)
        ok_delta = fresh & np.isfinite(gap_prev) & (gap_prev <= max_gap_days)
        out["ndvi_delta"][i] = np.where(ok_delta, last_n - prev_n, np.nan)
        out_end[i] = np.where(fresh, last_end, np.datetime64("NaT"))
    return {**out, "value_end": out_end,
            "available": order["available"].to_numpy(dtype="datetime64[D]")}


def vegetation_features(regimes: dict[str, np.ndarray], cell_idx: np.ndarray,
                        dates: np.ndarray) -> pd.DataFrame:
    """Look up vegetation features for (cell, target date) pairs."""
    t = np.asarray(dates, dtype="datetime64[D]")
    avail = regimes["available"]
    # newest composite with available <= t - 1
    k = np.searchsorted(avail, t - np.timedelta64(1, "D"), side="right") - 1
    ok = k >= 0
    kk = np.where(ok, k, 0)
    res = {}
    for name in ("ndvi", "evi", "ndvi_delta"):
        res[name] = np.where(ok, regimes[name][kk, cell_idx], np.nan)
    vend = np.where(ok, regimes["value_end"][kk, cell_idx], np.datetime64("NaT"))
    res["veg_age_days"] = ((t - np.timedelta64(1, "D")) - vend).astype("timedelta64[D]").astype(
        float)
    asof = np.where(ok, avail[kk], np.datetime64("NaT"))
    res["asof_vegetation"] = asof.astype("datetime64[ns]")
    return pd.DataFrame(res)
