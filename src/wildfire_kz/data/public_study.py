"""Compact, real-data hindcast tables; no national cell-day Cartesian DataFrame."""

from __future__ import annotations

import calendar
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from wildfire_kz.config import load_config
from wildfire_kz.data import checksum, dump_json
from wildfire_kz.data.public_predictors import (
    PUBLIC,
    ROOT,
    complete,
    geography,
    log,
    permitted,
    reserve,
)
from wildfire_kz.data.real import normalize_detection_archive
from wildfire_kz.events import link_events

RUN = ROOT / "runs/public_hindcast"
FEATURE_CODE_HASH = checksum(Path(__file__))
COVER = ["forest", "grassland", "shrubland", "cropland", "other"]
WEATHER = ["tmax", "tmin", "wind", "rh", "precip", "soil_moisture"]
FEATURES = (
    WEATHER
    + [f"{v}_{n}d" for v in ["precip", "temperature"] for n in [7, 14]]
    + [
        "ndvi",
        "ndvi_missing",
        "ndvi_age_days",
        *COVER,
        "elevation",
        "slope",
        "aspect_sin",
        "aspect_cos",
        "population_density",
        "settlement_distance",
        "month_sin",
        "month_cos",
    ]
)


def record_table(path: Path, frame: pd.DataFrame, metadata: dict[str, Any]) -> None:
    reserve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".working")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)
    dump_json(path.with_suffix(".sha256.json"), {"sha256": checksum(path), **metadata})


def outcomes(end_year: int, release: Path | None = None) -> Path:
    """Freeze development event linkage independently of calibration/test labels."""
    permitted([end_year], release)
    path = RUN / f"outcomes/events_through_{end_year}.parquet"
    if complete(path):
        return path
    frames = []
    cfg = load_config(ROOT / "configs/real_public.yaml")
    grid, _, _ = geography()
    source_hashes = {}
    for year in range(2014, end_year + 1):
        normalized = ROOT / f"data/real/normalized/detections_{year}.parquet"
        if year >= 2023:
            # The guard is checked before opening either normalized or source rows.
            permitted([year], release)
            source = cfg.data.sealed_detection_archives[year]
            if checksum(source.path) != source.sha256:
                raise ValueError("Held-out detection archive changed")
            if not normalized.is_file():
                frame = normalize_detection_archive(source.path, grid, year, cfg, final=True)
                record_table(normalized, frame, {"final_evaluation_release": str(release)})
        source_hashes[str(year)] = checksum(normalized)
        frames.append(pd.read_parquet(normalized))
    log(f"outcomes: linking {sum(map(len, frames)):,} records through {end_year}")
    linked = link_events(pd.concat(frames, ignore_index=True))
    record_table(
        path,
        linked,
        {
            "synthetic": False,
            "radius_m": 2000,
            "window_hours": 48,
            "source_hashes": source_hashes,
            "first_detections": int(linked.is_first.sum()),
        },
    )
    log(f"outcomes: {linked.is_first.sum():,} events through {end_year}")
    return path


def cover_year(year: int, release: Path | None = None) -> dict[str, np.ndarray]:
    permitted([year + 1], release)
    return _cover_year(year)


@lru_cache(maxsize=3)
def _cover_year(year: int) -> dict[str, np.ndarray]:
    paths = sorted((PUBLIC / "landcover").glob("annual_*.npz"))
    for path in paths:
        with np.load(path) as data:
            if f"forest_{year}" in data:
                if not complete(path):
                    raise ValueError(f"Land-cover checksum mismatch: {path}")
                return {n: data[f"{n}_{year}"].copy() for n in COVER + ["nonvegetated"]}
    raise FileNotFoundError(f"No verified land cover for observation year {year}")


def industrial_cells(end_year: int = 2021) -> set[str]:
    if end_year > 2021:
        raise PermissionError("Industrial exclusions must use development labels only")
    path = RUN / (
        "industrial_cells.json" if end_year == 2021 else f"industrial_cells_{end_year}.json"
    )
    if path.is_file():
        return set(json.loads(path.read_text())["cell_ids"])
    frame = pd.read_parquet(outcomes(2021), columns=["cell_id", "timestamp"])
    frame = frame[frame.timestamp.dt.year.between(2015, end_year)]
    counts = frame.assign(day=frame.timestamp.dt.floor("D")).groupby("cell_id").day.nunique()
    grid, _, _ = geography()
    nonveg = pd.Series(cover_year(2014)["nonvegetated"] >= 0.8, index=grid.cell_id)
    cells = set(counts[(counts >= 30) & nonveg.reindex(counts.index).fillna(False)].index)
    dump_json(
        path,
        {
            "development_end": end_year,
            "prior_mask_year": 2014,
            "minimum_active_days": 30,
            "nonvegetated_fraction": 0.8,
            "cell_ids": sorted(cells),
            "outcomes_sha256": checksum(outcomes(2021)),
        },
    )
    return cells


def year_keys(year: int, *, training: bool, release: Path | None = None) -> pd.DataFrame:
    """Keep every eligible positive; sample negatives with exact inclusion weights."""
    permitted([year], release)
    grid, _, _ = geography()
    ncell, nday = len(grid), 366 if calendar.isleap(year) else 365
    dates = pd.date_range(f"{year}-01-01", periods=nday, tz="UTC")
    cells = pd.Index(grid.cell_id)
    cover = cover_year(year - 1, release)
    fractions = np.stack([cover[n] for n in COVER])
    # Exclusions are applied AFTER this probability sample, separately for each
    # rolling fold using its training years. q remains valid after filtering.
    valid = np.isfinite(fractions).all(axis=0)
    with np.load(PUBLIC / "terrain/national.npz") as terrain:
        valid &= np.isfinite(terrain["elevation"])
    broad = np.argmax(np.nan_to_num(fractions, nan=-1), axis=0)
    eligible = np.broadcast_to(valid[:, None], (ncell, nday)).copy()
    positive = np.zeros((ncell, nday), dtype=bool)
    end_year = 2021 if year <= 2021 else (2022 if year == 2022 else 2024)
    events = pd.read_parquet(outcomes(end_year, release), columns=["cell_id", "day", "is_first"])
    offsets = (events.day - dates[0]).dt.days.to_numpy()
    ids = cells.get_indexer(events.cell_id)
    for lag in [1, 2]:
        day = offsets + lag
        good = (ids >= 0) & (day >= 0) & (day < nday)
        eligible[ids[good], day[good]] = False
    first = events.is_first.to_numpy() & (ids >= 0) & (offsets >= 0) & (offsets < nday)
    positive[ids[first], offsets[first]] = True
    excluded_positive = int((positive & ~eligible).sum())
    rng = np.random.default_rng(42 + year + (0 if training else 100000))
    pieces, audit = [], []
    for month in range(1, 13):
        ds = np.flatnonzero(dates.month == month)
        for cls, name in enumerate(COVER):
            cs = np.flatnonzero(valid & (broad == cls))
            mask = eligible[np.ix_(cs, ds)]
            labels = positive[np.ix_(cs, ds)]
            p = np.flatnonzero(mask & labels)
            negatives = np.flatnonzero(mask & ~labels)
            count = min(len(negatives), max(20 if training else 2000, 10 * len(p)))
            sampled = (
                rng.choice(negatives, count, replace=False) if count else np.array([], dtype=int)
            )
            q = count / len(negatives) if len(negatives) else 1.0
            for flat, label, probability in [(p, 1, 1.0), (sampled, 0, q)]:
                if not len(flat):
                    continue
                ci, di = cs[flat // len(ds)], ds[flat % len(ds)]
                pieces.append(
                    pd.DataFrame(
                        {
                            "cell_index": ci.astype("int32"),
                            "day": dates[di],
                            "label": np.int8(label),
                            "landcover": name,
                            "q": probability,
                            "weight": 1 / probability,
                        }
                    )
                )
            audit.append(
                {
                    "month": month,
                    "cover": name,
                    "positive": len(p),
                    "eligible_negatives": len(negatives),
                    "sampled_negatives": count,
                    "q": q,
                }
            )
    frame = (
        pd.concat(pieces, ignore_index=True)
        .sort_values(["day", "cell_index"])
        .reset_index(drop=True)
    )
    dump_json(
        RUN / f"sampling/{year}_{'train' if training else 'evaluation'}.json",
        {
            "year": year,
            "strata": audit,
            "excluded_positive_cell_days": excluded_positive,
            "eligible_cell_days": int(eligible.sum()),
            "valid_cells": int(valid.sum()),
            "sampled_rows": len(frame),
            "positive_rows": int(frame.label.sum()),
            "weight_mass": float(frame.weight.sum()),
            "synthetic": False,
        },
    )
    return frame


@lru_cache(maxsize=2)
def weather_arrays(year: int) -> tuple[dict[str, np.ndarray], pd.Timestamp, np.ndarray, np.ndarray]:
    """At most two years in memory, enough for every antecedent window."""
    path = PUBLIC / f"weather/{year}.npz"
    if not complete(path):
        raise FileNotFoundError(f"Weather incomplete for {year}")
    with np.load(path) as data:
        return (
            {n: data[n].copy() for n in WEATHER + ["temperature"]},
            pd.Timestamp(str(data["first_day"]), tz="UTC"),
            data["native_cell_y"].copy(),
            data["native_cell_x"].copy(),
        )


def meteorology(
    indices: np.ndarray, dates: pd.DatetimeIndex, release: Path | None = None
) -> dict[str, np.ndarray]:
    # Observation end + five days must be STRICTLY before target midnight.
    source_days = dates - pd.Timedelta(days=7)
    result = {
        n: np.full(len(indices), np.nan, dtype="float32")
        for n in WEATHER + [f"{v}_{w}d" for v in ["precip", "temperature"] for w in [7, 14]]
    }
    for year in sorted(set(source_days.year)):
        permitted([int(year)], release)
        selected = np.flatnonzero(source_days.year == year)
        arrays, start, iy, ix = weather_arrays(int(year))
        ci = indices[selected]
        d = ((source_days[selected] - start).days).to_numpy()
        for name in WEATHER:
            result[name][selected] = arrays[name][iy[ci], ix[ci], d]
    for window in [7, 14]:
        for name in ["precip", "temperature"]:
            accumulator = np.zeros(len(indices), dtype="float32")
            missing = np.zeros(len(indices), dtype=bool)
            for lag in range(window):
                lagged = source_days - pd.Timedelta(days=lag)
                for year in sorted(set(lagged.year)):
                    permitted([int(year)], release)
                    selected = np.flatnonzero(lagged.year == year)
                    arrays, start, iy, ix = weather_arrays(int(year))
                    ci = indices[selected]
                    d = (lagged[selected] - start).days.to_numpy()
                    values = arrays[name][iy[ci], ix[ci], d]
                    accumulator[selected] += np.nan_to_num(values)
                    missing[selected] |= ~np.isfinite(values)
            if name == "temperature":
                accumulator /= window
            accumulator[missing] = np.nan
            result[f"{name}_{window}d"] = accumulator
    return result


def vegetation_features(
    indices: np.ndarray, dates: pd.DatetimeIndex, release: Path | None = None
) -> dict[str, np.ndarray]:
    permitted(sorted(set(dates.year)), release)
    ncell = len(geography()[0])
    value = np.full(ncell, np.nan, dtype="float32")
    observation = np.full(ncell, -100000, dtype="int32")
    result = np.full(len(indices), np.nan, dtype="float32")
    age = np.full(len(indices), np.nan, dtype="float32")
    first, last = dates.min() - pd.Timedelta(days=32), dates.max() - pd.Timedelta(days=12)
    records = sorted(
        p
        for p in (PUBLIC / "vegetation").glob("????-??-??.npz")
        if first <= pd.Timestamp(p.stem, tz="UTC") <= last
    )
    expected = [
        d
        for d in pd.date_range("2014-11-01", "2024-12-31", freq="7D", tz="UTC")
        if first <= d <= last
    ]
    missing = [
        d.strftime("%Y-%m-%d")
        for d in expected
        if not complete(PUBLIC / f"vegetation/{d:%Y-%m-%d}.npz")
        and not (PUBLIC / f"vegetation/{d:%Y-%m-%d}.unavailable.json").is_file()
    ]
    if missing:
        raise FileNotFoundError(
            f"NDVI acquisition incomplete: {len(missing)} snapshots; first {missing[:3]}"
        )
    cursor = 0
    for day in sorted(dates.unique()):
        # D+1+10 < target => D <= target-12.
        while cursor < len(records) and pd.Timestamp(
            records[cursor].stem, tz="UTC"
        ) <= day - pd.Timedelta(days=12):
            path = records[cursor]
            if not complete(path):
                raise ValueError(f"NDVI checksum mismatch: {path}")
            with np.load(path) as data:
                a = data["ndvi"]
                valid = np.isfinite(a)
                value[valid] = a[valid]
                observation[valid] = int(pd.Timestamp(path.stem, tz="UTC").value // 86400000000000)
            cursor += 1
        selected = np.flatnonzero(dates == day)
        ci = indices[selected]
        elapsed = int(day.value // 86400000000000) - observation[ci]
        fresh = elapsed <= 32
        result[selected[fresh]] = value[ci[fresh]]
        age[selected[fresh]] = elapsed[fresh]
    return {
        "ndvi": result,
        "ndvi_missing": (~np.isfinite(result)).astype("float32"),
        "ndvi_age_days": age,
    }


def feature_frame(keys: pd.DataFrame, release: Path | None = None) -> pd.DataFrame:
    dates = pd.DatetimeIndex(keys.day)
    permitted(sorted(set(dates.year)), release)
    if len(set(dates.year)) != 1:
        raise ValueError("Materialise one target year at a time")
    year = int(dates.year[0])
    indices = keys.cell_index.to_numpy()
    grid, _, _ = geography()
    result = keys.copy()
    for column in ["cell_id", "x", "y_coord", "area_km2"]:
        result[column] = grid[column].to_numpy()[indices]
    values = meteorology(indices, dates, release)
    values.update(vegetation_features(indices, dates, release))
    cover = cover_year(year - 1, release)
    if "landcover" not in result:
        broad = np.argmax(
            np.nan_to_num(np.stack([cover[n][indices] for n in COVER]), nan=-1), axis=0
        )
        result["landcover"] = np.array(COVER)[broad]
    values.update({n: cover[n][indices] for n in COVER})
    for group, columns in [
        ("terrain", ["elevation", "slope", "aspect_sin", "aspect_cos"]),
        ("human", ["population_density", "settlement_distance"]),
    ]:
        path = PUBLIC / f"{group}/national.npz"
        if not complete(path):
            raise ValueError(f"Unverified static source: {path}")
        with np.load(path) as data:
            values.update({n: data[n][indices].astype("float32") for n in columns})
    phase = 2 * np.pi * (dates.month - 1) / 12
    values["month_sin"], values["month_cos"] = np.sin(phase), np.cos(phase)
    for name, a in values.items():
        result[name] = a.astype("float32")
    # Nearest native ERA5 cells can be water at the coast (missing soil moisture).
    # Do not impute these mandatory-source gaps and present them as map forecasts.
    result["required_features_valid"] = np.isfinite(
        result[WEATHER + COVER + ["elevation", "slope", "aspect_sin", "aspect_cos"]].to_numpy()
    ).all(axis=1)
    return result


def table(year: int, *, training: bool, release: Path | None = None) -> Path:
    permitted([year], release)
    path = RUN / f"features/{year}_{'train' if training else 'evaluation'}.parquet"
    code_hash = FEATURE_CODE_HASH
    if (
        complete(path)
        and json.loads(path.with_suffix(".sha256.json").read_text()).get("feature_code_sha256")
        == code_hash
    ):
        return path
    keys = year_keys(year, training=training, release=release)
    frame = feature_frame(keys, release)
    invalid = ~frame.required_features_valid
    invalid_rows, invalid_positives = int(invalid.sum()), int(frame.loc[invalid, "label"].sum())
    frame = frame.loc[~invalid].reset_index(drop=True)
    if len(frame) == 0 or frame.label.nunique() != 2:
        raise ValueError("Verified sources produced no usable two-class study sample")
    record_table(
        path,
        frame,
        {
            "synthetic": False,
            "year": year,
            "features": FEATURES,
            "rows": len(frame),
            "positives": int(frame.label.sum()),
            "variant": "public_reprocessed_hindcast",
            "feature_code_sha256": code_hash,
            "missing_required_source_rows_excluded": invalid_rows,
            "missing_required_source_positives_excluded": invalid_positives,
        },
    )
    log(f"features {year}: {len(frame):,} rows; {frame.label.sum():,} positives")
    return path
