"""Daily forecast of frozen v6 and frozen v7 for one UTC day, kept in a hash-chained log.

Usage: forecast_daily.py [--day YYYY-MM-DD] [--replay]   (default: the UTC day 12 hours ahead)

Inputs are what exists at issue time: S-NPP detections from NASA GIBS (D-1 up to 21 UTC, as v7
was trained), ERA5 through D-7 (v6's lag), NDVI through D-12, the GFS 18 UTC run of D-1 and the
two runs before it. Run after about 23:00 UTC of D-1. An entry counts for the prospective test
(2027-03-01..2027-10-31) only if it is issued before 06:00 UTC of D, before the first S-NPP pass
over Kazakhstan. One entry per day: the first issue stands, a second run for the same day stops.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import struct
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
import develop_model_v7 as v7  # noqa: E402
import test_2026 as t26  # noqa: E402

from wildfire_kz import forecast_log as fl  # noqa: E402
from wildfire_kz import model_upgrade as mu  # noqa: E402
from wildfire_kz.data import checksum, dump_json, gfs_forecasts  # noqa: E402
from wildfire_kz.data import public_predictors as pp  # noqa: E402
from wildfire_kz.data import public_study as study  # noqa: E402
from wildfire_kz.data.gibs_fires import fetch_day  # noqa: E402

LIVE = ROOT / "runs/forecast_live"
LOG = LIVE / "log.jsonl"
TEST = (date(2027, 3, 1), date(2027, 10, 31))
# Sealed inputs of the 2026 test end here; later days come only from the live feeds.
SEALED_DETECTIONS, SEALED_NDVI = t26.END.date(), (t26.END - pd.Timedelta(days=12)).date()
EPOCH = v7.EPOCH
WEATHER_NAMES = ["tmax", "tmin", "temperature", "rh", "wind", "precip", "soil_moisture"]
ERA5_VARIABLES = [
    "temperature_2m",
    "dew_point_2m",
    "wind_u_component_10m",
    "wind_v_component_10m",
    "precipitation",
    "soil_moisture_0_to_7cm",
]


def log(message: str) -> None:
    print(f"{datetime.now(UTC).isoformat(timespec='seconds')} {message}", flush=True)


# ---------- releases ----------
def verify_v7() -> dict:
    release = json.loads((v7.RUN / "release.json").read_text())
    for name, digest in release["artifacts"].items():
        if checksum(v7.RUN / name) != digest:
            raise PermissionError(f"v7 artifact changed: {name}")
    for name, digest in release["code"].items():
        if checksum(ROOT / name) != digest:
            raise PermissionError(f"v7 code changed: {name}")
    return release


# ---------- detections ----------
FIRMS_7D = (
    "https://firms.modaps.eosdis.nasa.gov/data/active_fire/suomi-npp-viirs-c2/csv/"
    "SUOMI_VIIRS_C2_Russia_Asia_7d.csv"
)
FIRMS_CONFIDENCE = {"n": "nominal", "h": "high", "l": "low"}


def firms_day(day: date) -> pd.DataFrame:
    """The same S-NPP NRT points from the public seven-day FIRMS file, in GIBS columns."""
    path = LIVE / f"firms/{datetime.now(UTC):%Y%m%dT%H}.csv"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        pp.download(FIRMS_7D, path, timeout=120)
    raw = pd.read_csv(path, dtype={"acq_time": str, "confidence": str, "version": str})
    west, south, east, north = t26.BBOX
    raw = raw[
        (raw.acq_date == str(day))
        & raw.longitude.between(west, east)
        & raw.latitude.between(south, north)
    ]
    out = pd.DataFrame(
        {
            "LATITUDE": raw.latitude,
            "LONGITUDE": raw.longitude,
            "ACQ_DATE": raw.acq_date,
            "ACQ_TIME": raw.acq_time.str.zfill(4),
            "CONFIDENCE": raw.confidence.map(FIRMS_CONFIDENCE),
            "SATELLITE": raw.satellite,
            "VERSION": raw.version,
        }
    ).astype(str)
    return out.drop_duplicates(["LATITUDE", "LONGITUDE", "ACQ_TIME"]).reset_index(drop=True)


def detections_day(day: date) -> tuple[pd.DataFrame, str]:
    """Raw points of one UTC day and their source; refetched until complete (D+1 06 UTC)."""
    path = LIVE / f"gibs/{day}.parquet"
    complete_after = fl.midnight(day + timedelta(days=1)) + fl.DEADLINE_AFTER_MIDNIGHT
    if path.exists() and datetime.fromtimestamp(path.stat().st_mtime, UTC) >= complete_after:
        return pd.read_parquet(path), "gibs"
    try:
        raw, source = fetch_day(str(day), t26.BBOX), "gibs"
        if len(raw):
            raw = raw.astype(str).drop_duplicates(["LATITUDE", "LONGITUDE", "ACQ_TIME"])
    except Exception as error:  # noqa: BLE001 - any GIBS failure falls back to FIRMS
        log(f"GIBS {day} failed ({error}); FIRMS seven-day file")
        raw, source = pd.DataFrame(), "firms"
    if not len(raw) and day >= datetime.now(UTC).date() - timedelta(days=6):
        raw, source = firms_day(day), "firms"
    if source == "gibs":
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".working")
        raw.to_parquet(temporary, index=False)
        temporary.replace(path)
    return raw, source


def live_detections(last: date) -> tuple[pd.DataFrame, dict]:
    """2026 sealed detections, then GIBS for every later day through `last`."""
    sealed = pd.read_parquet(t26.RUN / "detections_2026.parquet")
    days = [
        SEALED_DETECTIONS + timedelta(days=k) for k in range(1, (last - SEALED_DETECTIONS).days + 1)
    ]
    from concurrent.futures import ThreadPoolExecutor

    # Days are independent HTTP work; each is written atomically.
    with ThreadPoolExecutor(max_workers=6) as pool:
        fetched = list(pool.map(detections_day, days))
    frames = [f for f, _ in fetched]
    points = (
        pd.concat([f for f in frames if len(f)], ignore_index=True)
        if any(len(f) for f in frames)
        else None
    )
    if points is not None and not points.SATELLITE.isin(["N"]).all():
        raise ValueError("Only S-NPP points are permitted")
    live = t26.normalise(points) if points is not None else sealed.iloc[:0]
    both = pd.concat([sealed, live], ignore_index=True)
    meta = {
        "live_days": [str(days[0]), str(days[-1])] if days else None,
        "live_points": 0 if points is None else len(points),
        "points_last_day": len(frames[-1]) if frames else None,
        "firms_days": [str(d) for d, (_, src) in zip(days, fetched, strict=True) if src == "firms"],
        "last_detection_utc": str(both.timestamp.max()),
    }
    return both, meta


# ---------- ERA5 through the latest published day ----------
def live_weather_path(year: int) -> Path:
    return LIVE / f"weather/{year}.npz"


def extend_weather(year: int, until: date) -> date | None:
    """Sealed year (if any) plus every later complete ERA5 day up to `until`; returns last day."""
    path, sealed = live_weather_path(year), pp.PUBLIC / f"weather/{year}.npz"
    if path.exists():
        with np.load(path) as z:
            arrays = {n: z[n] for n in WEATHER_NAMES}
            meta = {k: z[k] for k in ["first_day", "native_cell_y", "native_cell_x", "y0", "x0"]}
    elif pp.complete(sealed):
        with np.load(sealed) as z:
            arrays = {n: z[n] for n in WEATHER_NAMES}
            meta = {k: z[k] for k in ["first_day", "native_cell_y", "native_cell_x", "y0", "x0"]}
    else:
        _, lon, lat = pp.geography()
        iy, ix = np.rint((lat + 90) / 0.25).astype(int), np.rint((lon + 180) / 0.25).astype(int)
        y0, x0 = int(iy.min()), int(ix.min())
        shape = (int(iy.max()) + 1 - y0, int(ix.max()) + 1 - x0, 0)
        arrays = {n: np.zeros(shape, dtype="float32") for n in WEATHER_NAMES}
        meta = {
            "first_day": np.array(f"{year}-01-01"),
            "native_cell_y": (iy - y0).astype("uint16"),
            "native_cell_x": (ix - x0).astype("uint16"),
            "y0": y0,
            "x0": x0,
        }
    first = date(year, 1, 1)
    have = arrays["tmax"].shape[2]
    start, stop = have, min((until - first).days + 1, (date(year, 12, 31) - first).days + 1)
    if stop <= start:
        if not path.exists() and have:
            pp.save_npz(path, **arrays, **meta)
        return first + timedelta(days=have - 1) if have else None
    ny, nx, _ = arrays["tmax"].shape
    y0, x0 = int(meta["y0"]), int(meta["x0"])
    cy, cx = meta["native_cell_y"].astype(int), meta["native_cell_x"].astype(int)
    h0, h1 = start * 24, stop * 24 + 1
    provenance: list[dict] = []

    async def acquire() -> list[np.ndarray]:
        fs = pp.RangeCachedS3(anon=True, asynchronous=True, skip_instance_cache=True)
        readers = {}
        try:
            for v in ERA5_VARIABLES:
                readers[v] = await pp.open_weather_series(
                    fs, v, year, provenance, first_hour=h0, stop_hour=h1
                )
            sel = (slice(y0, y0 + ny), slice(x0, x0 + nx), slice(h0, h1))
            return list(await asyncio.gather(*(readers[v].read_array(sel) for v in ERA5_VARIABLES)))
        finally:
            for r in readers.values():
                r.close()
            if fs._s3creator is not None:
                await fs._s3creator.__aexit__(None, None, None)

    t, dew, u, vv, rain, soil = [a.astype("float32", copy=False) for a in asyncio.run(acquire())]
    nday = stop - start
    # A day counts only when all its hours (and the closing midnight) exist at every grid cell.
    hourly_ok = np.all(np.isfinite(t[cy, cx]) & np.isfinite(rain[cy, cx]), axis=0)
    good = 0
    while good < nday and hourly_ok[good * 24 : good * 24 + 25].all():
        good += 1
    if good == 0:
        return first + timedelta(days=have - 1) if have else None

    def daily(a: np.ndarray, op: str = "mean") -> np.ndarray:
        return getattr(np, op)(a[:, :, : good * 24].reshape(ny, nx, good, 24), axis=-1).astype(
            "float32"
        )

    # The original daily equations of test_2026.weather().
    rh = 100 * np.exp(17.625 * dew / (243.04 + dew) - 17.625 * t / (243.04 + t))
    new = {
        "tmax": daily(t, "max"),
        "tmin": daily(t, "min"),
        "temperature": daily(t),
        "rh": daily(np.clip(rh, 0, 100)),
        "wind": daily(np.hypot(u, vv)),
        "precip": daily(rain[:, :, 1:], "sum"),
        "soil_moisture": daily(soil),
    }
    arrays = {n: np.concatenate([arrays[n], new[n]], axis=2) for n in WEATHER_NAMES}
    pp.save_npz(path, **arrays, **meta)
    dump_json(
        path.with_suffix(".provenance.json"),
        {"sources": provenance, "days": arrays["tmax"].shape[2]},
    )
    return first + timedelta(days=arrays["tmax"].shape[2] - 1)


def live_weather_arrays(
    year: int,
) -> tuple[dict[str, np.ndarray], pd.Timestamp, np.ndarray, np.ndarray]:
    path = live_weather_path(year)
    if not pp.complete(path):
        raise FileNotFoundError(f"Live weather incomplete for {year}")
    with np.load(path) as data:
        return (
            {n: data[n].copy() for n in study.WEATHER + ["temperature"]},
            pd.Timestamp(str(data["first_day"]), tz="UTC"),
            data["native_cell_y"].copy(),
            data["native_cell_x"].copy(),
        )


# ---------- NDVI ----------
def ndvi(day: date) -> str | None:
    """Weekly NDVI through D-12; a week not yet published is retried on every run."""
    weeks = [
        d.date()
        for d in pd.date_range("2014-11-01", str(day - timedelta(days=12)), freq="7D")
        if d.date() > SEALED_NDVI and d.date() >= day - timedelta(days=60)
    ]
    for w in weeks:
        marker = pp.PUBLIC / f"vegetation/{w}.unavailable.json"
        if marker.exists():
            marker.unlink()
        pp.vegetation_day(str(w))
    present = [w for w in weeks if pp.complete(pp.PUBLIC / f"vegetation/{w}.npz")]
    return str(present[-1]) if present else None


# ---------- GFS ----------
def gfs_day(day: date) -> None:
    """One day from the 18 UTC run of the day before, as gfs_forecasts.build writes it.

    Sequential on purpose: eccodes loads its definitions unsafely when the first messages
    are decoded in several threads at once.
    """
    path = v7.GFS / f"{day}.npz"
    if path.exists():
        return
    values = gfs_forecasts.daily(day)
    temporary = path.with_suffix(".working.npz")
    np.savez_compressed(temporary, **{k: np.asarray(v) for k, v in values.items()})  # type: ignore[arg-type]
    temporary.replace(path)


# ---------- features ----------
class CellHistory(t26.CellHistory):
    """v6's cell features with the equations of test_2026.CellHistory; the monthly climatology
    runs over every year from 2014 to the year before the target, as in development."""

    def __init__(self, history: pd.DataFrame, n_cells: int, last_year: int):
        from scipy.ndimage import maximum_filter

        h = history.assign(day_no=(history.day - EPOCH).dt.days)
        self.n, self.years = n_cells, range(2014, last_year + 1)
        self.active = {
            int(d): g.cell.to_numpy(dtype=np.int64)  # type: ignore[arg-type]
            for d, g in h.groupby("day_no")
        }
        self.first = int(h.day_no.min())
        self.month_cell = {}
        _, gr, gc, shape = t26._grid()
        for y in self.years:
            for m in range(1, 13):
                sel = h[(h.day.dt.year == y) & (h.day.dt.month == m)].cell.to_numpy(dtype=np.int64)
                v = np.zeros(n_cells, dtype=np.float32)
                v[np.unique(sel)] = 1
                img = np.zeros(shape, dtype=np.float32)
                img[gr, gc] = v
                self.month_cell[(y, m)] = (v, maximum_filter(img, size=3, mode="constant")[gr, gc])

    def features(self, keys: pd.DataFrame) -> dict[str, np.ndarray]:
        target = (keys.day - EPOCH).dt.days.to_numpy()
        ci = keys.cell_index.to_numpy()
        names = ["cell_fire_30d", "cell_fire_365d", "cell_days_since_fire"]
        out = {k: np.zeros(len(keys), dtype=np.float32) for k in names}
        out |= {
            k: np.zeros(len(keys), dtype=np.float32)
            for k in ["cell_month_climatology", "nbr15_month_climatology"]
        }
        for t in np.unique(target):
            idx = np.flatnonzero(target == t)
            end = t - 2
            c30, c365 = np.zeros(self.n, np.int32), np.zeros(self.n, np.int32)
            last = np.full(self.n, -(10**6), dtype=np.int64)
            for d in range(max(self.first, end - 3650), end + 1):
                a = self.active.get(d)
                if a is None:
                    continue
                last[a] = d
                if d > end - 365:
                    c365[a] += 1
                if d > end - 30:
                    c30[a] += 1
            cells = ci[idx]
            out["cell_fire_30d"][idx] = np.log1p(c30[cells])
            out["cell_fire_365d"][idx] = np.log1p(c365[cells])
            out["cell_days_since_fire"][idx] = np.minimum(t - last[cells], 3650)
            when = EPOCH + pd.Timedelta(days=int(t))
            prior = [y for y in self.years if y < when.year]
            out["cell_month_climatology"][idx] = np.mean(
                [self.month_cell[(y, when.month)][0][cells] for y in prior], axis=0
            )
            out["nbr15_month_climatology"][idx] = np.mean(
                [self.month_cell[(y, when.month)][1][cells] for y in prior], axis=0
            )
        return out


def cover_override(year: int, release: Path | None = None) -> dict:
    # MODIS MCD12Q1 after 2024 is not used: the 2026 protocol fixed 2024 cover, kept for 2027.
    return study.cover_year(min(year, t26.COVER_YEAR), release)


def h3_h2(day: pd.Timestamp, detections: pd.DataFrame, cells: pd.Series) -> pd.DataFrame:
    """v7's H3 and H2 inputs for every grid cell, with the equations of develop_model_v7."""
    from scipy.ndimage import distance_transform_edt, uniform_filter

    _, gr, gc, shape = t26._grid()
    n = len(cells)
    d = detections.assign(cell=detections.cell_id.map(cells)).dropna(subset=["cell"])
    stamp = d.timestamp
    day_no = (stamp.dt.floor("D") - EPOCH).dt.days.to_numpy()
    cell = d.cell.to_numpy(dtype=np.int64)
    t = int((day - EPOCH).days)
    early = stamp.dt.hour.to_numpy() < v7.YDAY_CUTOFF_HOUR

    def image(sel: np.ndarray) -> np.ndarray:
        img = np.zeros(shape, dtype=np.float32)
        c = np.unique(cell[sel])
        img[gr[c], gc[c]] = 1
        return img

    out = {c: np.zeros(n, dtype=np.float32) for c in v7.H3}
    one, two = image((day_no == t - 1) & early), image(day_no == t - 2)
    for img, tag in [(one, "yday"), (two, "d2")]:
        for size, km in [(3, 15), (11, 55)]:
            total = uniform_filter(img, size=size, mode="constant") * size * size
            out[f"h3_{tag}_{km}km"] = np.rint(total[gr, gc])
    out["h3_yday_distance_km"] = (
        np.minimum(distance_transform_edt(one == 0)[gr, gc] * 5, 200).astype(np.float32)
        if one.any()
        else np.full(n, 200, dtype=np.float32)
    )
    weather = v7.Weather("gfs")
    y, x = weather.ny, weather.nx
    today, yesterday, before = (weather.day(day - pd.Timedelta(days=k)) for k in (0, 1, 2))
    if today is None or yesterday is None or before is None:
        raise FileNotFoundError("GFS for D, D-1 or D-2 is missing")
    h2 = {c: np.full(n, np.nan, dtype=np.float32) for c in v7.H2}
    for v in v7.DAILY:
        h2[f"h2_{v}_d0"] = today[v][y, x]
    tmax, rh = today["tmax"][y, x], today["rh"][y, x]
    h2["h2_vpd_d0"] = 0.6108 * np.exp(17.27 * tmax / (tmax + 237.3)) * (1 - rh / 100)
    for v in ["tmax", "rh", "wind", "precip"]:
        h2[f"h2_{v}_d1"] = yesterday[v][y, x]
    h2["h2_precip_3d"] = today["precip"][y, x] + yesterday["precip"][y, x] + before["precip"][y, x]
    return pd.DataFrame({**out, **h2})


# ---------- output ----------
def write_payload(path: Path, p: np.ndarray) -> str:
    payload = fl.encode(p)
    if not np.array_equal(fl.decode(payload), p, equal_nan=True):
        raise ValueError("Payload does not round-trip")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return checksum(path)


def strong_detections(live: pd.DataFrame) -> pd.DataFrame:
    """Nominal/high active cell-days from 2014 on, for the H1 heat-source rule."""
    columns = ["cell_id", "timestamp", "confidence"]
    frames = [
        pd.read_parquet(ROOT / f"data/real/normalized/detections_{y}.parquet", columns=columns)
        for y in range(2014, 2025)
    ]
    frames += [pd.read_parquet(v7.IND / "detections_2025.parquet", columns=columns), live[columns]]
    both = pd.concat(frames, ignore_index=True)
    both = both[both.confidence.isin(["n", "h"])]
    return both.assign(day=both.timestamp.dt.floor("D"))[["cell_id", "day"]].drop_duplicates()


def forecast(target: date, replay: bool = False) -> None:
    issued = datetime.now(UTC)
    if not replay and any(e["target_day"] == str(target) for e in fl.read(LOG)):
        log(f"{target}: already in the log, the first entry stands")
        return
    earliest, deadline = fl.window(target)
    if not replay and issued < earliest:
        raise RuntimeError(
            f"Too early: D-1 detections to 21 UTC and GFS 18 UTC exist after {earliest}"
        )
    t26.verify_v6()
    mu.verify_release(t26.V5 / "release.json")
    v7_release = verify_v7()

    log(f"{target}: inputs")
    detections, det_meta = live_detections(target - timedelta(days=1))
    # The 14-day windows run D-20..D-7; each year they touch must reach as far as they need.
    lasts = {
        y: extend_weather(y, target - timedelta(days=7))
        for y in sorted({(target - timedelta(days=20)).year, (target - timedelta(days=7)).year})
    }
    era5_last = lasts[(target - timedelta(days=7)).year]
    if era5_last is None or era5_last < target - timedelta(days=7):
        raise FileNotFoundError(f"ERA5 published only through {era5_last}; v6 needs D-7")
    ndvi_last = ndvi(target)
    gfs_days = [target - timedelta(days=k) for k in (2, 1, 0)]
    for d in gfs_days:
        gfs_day(d)

    log(f"{target}: features")
    study.weather_arrays = live_weather_arrays
    t26.cover_override = cover_override
    grid = pp.geography()[0]
    ids = pd.Index(grid.cell_id)
    n = len(ids)
    cells = pd.Series(np.arange(n), index=ids)
    binary = (ROOT / "platform/dist/assets/cells.bin").read_bytes()
    order = ids.get_indexer(
        pd.Index([f"g5000_{r[0]}_{r[1]}" for r in struct.iter_unpack("<hhfffH8H", binary)])
    )
    industrial = ids.isin(json.loads((mu.OLD / "industrial_cells.json").read_text())["cell_ids"])
    history = mu.load_history(2024, t26.V5 / "release.json")
    raw25 = pd.read_parquet(
        t26.independent.RUN / "detections_2025.parquet", columns=["cell_id", "timestamp"]
    )
    extra = pd.concat([raw25, detections[["cell_id", "timestamp"]]], ignore_index=True)
    extra["day"] = extra.timestamp.dt.floor("D")
    history = pd.concat([history, extra[["cell_id", "day"]]], ignore_index=True).drop_duplicates()
    day = pd.Timestamp(target, tz="UTC")
    keys = pd.DataFrame({"cell_index": np.arange(n, dtype="int32"), "day": day})
    f = t26.feature_frame(keys)
    f = mu.augment(f, mu.FireHistory(history), t26.V5 / "release.json")
    history_cells = CellHistory(
        history.assign(cell=history.cell_id.map(cells))
        .dropna(subset=["cell"])
        .astype({"cell": np.int64}),
        n,
        target.year - 1,
    )
    for name, values in history_cells.features(f).items():
        f[name] = values
    recent = set(
        detections.loc[
            (detections.timestamp >= day - pd.Timedelta(hours=48)) & (detections.timestamp < day),
            "cell_id",
        ]
    )
    eligible = f.required_features_valid.to_numpy() & ~industrial & ~ids.isin(recent)
    extras = h3_h2(day, detections, cells)
    for c in extras:
        f[c] = extras[c].to_numpy()
    # H1 persistent heat sources as known before D: the 2027 test's primary risk set.
    heat = v7.HeatRule(strong_detections(detections), cells).flag(keys)

    log(f"{target}: scoring")
    out_dir = LIVE / (f"replay/{target}" if replay else f"forecasts/{target}")
    models = {}
    for name, folder in [("v6", t26.V6), ("v7", v7.RUN)]:
        model = joblib.load(folder / "model.joblib")
        model["estimator"].set_params(n_jobs=2)
        calibration = joblib.load(folder / "calibrator.joblib")
        frozen = json.loads((folder / "frozen.json").read_text())
        p = np.full(n, np.nan, dtype="float32")
        raw = model["estimator"].predict_proba(f.loc[eligible, model["features"]])[:, 1]
        p[eligible] = mu.published_probability(calibration.predict(raw))
        alert = p >= frozen["threshold"]
        models[name] = {
            "release_sha256": checksum(folder / "release.json"),
            "payload": f"forecasts/{target}/{name}.f16.gz",
            "payload_sha256": write_payload(out_dir / f"{name}.f16.gz", p[order]),
            "format": fl.FORMAT,
            "finite_cells": int(np.isfinite(p).sum()),
            "threshold": frozen["threshold"],
            "alert_cells": int(alert.sum()),
            "alert_cells_outside_heat_sources": int((alert & ~heat).sum()),
            "mean_probability": float(np.nanmean(p)),
        }
    # Heat sources in cells.bin order, as the map indexes cells.
    heat_cells = np.flatnonzero(heat[order]).astype(int).tolist()
    (out_dir / "heat_cells.json").write_text(json.dumps(heat_cells))
    if replay:
        check(target, out_dir, f)
        return
    entry = fl.append(
        LOG,
        {
            "target_day": str(target),
            "status": "issued",
            "issued_utc": issued.isoformat(timespec="seconds"),
            "on_time": issued < deadline,
            "prospective_test_day": TEST[0] <= target <= TEST[1],
            "models": models,
            "heat_cells": len(heat_cells),
            "heat_cells_sha256": checksum(out_dir / "heat_cells.json"),
            "inputs": {
                "detections": det_meta,
                "era5_last_day": str(era5_last),
                "ndvi_last_week": ndvi_last,
                "gfs": {str(d): checksum(v7.GFS / f"{d}.npz") for d in gfs_days},
                "land_cover_year": t26.COVER_YEAR,
                "v7_frozen_utc": v7_release["frozen_utc"],
            },
            "code_sha256": checksum(Path(__file__)),
        },
    )
    log(
        f"{target}: issued, on time {entry['on_time']}; alerts v6 {models['v6']['alert_cells']}, "
        f"v7 {models['v7']['alert_cells']} of {models['v6']['finite_cells']} cells"
    )
    import publish_forecasts

    publish_forecasts.publish()


def missed(target: date, error: BaseException) -> None:
    """After the last scheduled attempt a failure is a missed day, and is logged as one."""
    if any(e["target_day"] == str(target) for e in fl.read(LOG)):
        return
    fl.append(
        LOG,
        {
            "target_day": str(target),
            "status": "missed",
            "issued_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "on_time": False,
            "prospective_test_day": TEST[0] <= target <= TEST[1],
            "reason": f"{type(error).__name__}: {error}"[:500],
            "code_sha256": checksum(Path(__file__)),
        },
    )
    log(f"{target}: recorded as missed ({error})")


def check(target: date, out_dir: Path, f: pd.DataFrame) -> None:
    """A replayed day must equal the registered v6 map and v7's development H3 rows."""
    registered = t26.V6 / f"site_assets/predictions/{target}.f16.gz"
    if registered.exists():
        same = registered.read_bytes() == (out_dir / "v6.f16.gz").read_bytes()
        log(f"replay {target}: v6 payload equals the registered map: {same}")
    rows = v7.sample("2026_reassessment")
    sel = (rows.day == pd.Timestamp(target, tz="UTC")).to_numpy()
    if sel.any():
        h3 = pd.read_parquet(v7.RUN / "features_h3/2026_reassessment.parquet")[sel]
        mine = f.loc[rows.cell_index[sel].to_numpy(), v7.H3].to_numpy()
        log(
            f"replay {target}: H3 equals development on {sel.sum()} rows: {np.array_equal(mine, h3.to_numpy())}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", default=str(fl.target_day(datetime.now(UTC))))
    parser.add_argument("--replay", action="store_true", help="recompute a past day, no log entry")
    parser.add_argument("--status", action="store_true", help="print the log summary and stop")
    args = parser.parse_args()
    if args.status:
        print(json.dumps(fl.summary(fl.read(LOG), TEST), indent=2))
        sys.exit(0)
    target = date.fromisoformat(args.day)
    try:
        forecast(target, args.replay)
    except Exception as error:
        if not args.replay and fl.last_attempt(target, datetime.now(UTC)):
            missed(target, error)
        raise
