"""Final 2026 test of frozen model v6 against frozen release v5, with keyless GIBS labels.

Commands, in order:
  protocol  - register the test before any 2026 label is read
  weather   - ERA5 2026 through the last day the test needs, same source and equations
  ndvi      - weekly NOAA VIIRS NDVI for 2026, same calendar and QA
  labels    - first label access: S-NPP detections from NASA GIBS, normalised and linked
  predict   - sampled risk set, features, frozen v5 and v6 scores
  evaluate  - metrics, daily capture and paired cluster bootstrap
No estimator is fitted or tuned here.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import struct
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import FunctionType

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from wildfire_kz import independent  # noqa: E402
from wildfire_kz import model_upgrade as mu  # noqa: E402
from wildfire_kz.data import checksum, dump_json  # noqa: E402
from wildfire_kz.data import public_predictors as pp  # noqa: E402
from wildfire_kz.data import public_study as study  # noqa: E402
from wildfire_kz.data.gibs_fires import fetch_day  # noqa: E402
from wildfire_kz.evaluation import cluster_draws, metrics  # noqa: E402
from wildfire_kz.events import link_events  # noqa: E402

RUN = ROOT / "runs/test_2026"
V5 = ROOT / "runs/model_stack_v5"
V6 = ROOT / "runs/model_v6"
RELEASE = mu.OLD / "release.json"
START, END = pd.Timestamp("2026-01-01", tz="UTC"), pd.Timestamp("2026-10-15", tz="UTC")
GIBS_GAPS = ["2026-04-29"] + [f"2026-07-{d}" for d in range(11, 16)]
EXCLUDED = ["2026-04-29", "2026-04-30", "2026-05-01"] + [f"2026-07-{d}" for d in range(11, 18)]
BBOX = (46.0, 40.0, 88.0, 56.0)
COVER_YEAR = 2024
SEED = 20260401


def log(message: str) -> None:
    print(datetime.now(UTC).isoformat(), message, flush=True)


def verify_v6() -> dict:
    record = json.loads((V6 / "release.json").read_text())
    for name, digest in record["artifacts"].items():
        if checksum(V6 / name) != digest:
            raise PermissionError(f"Frozen v6 changed: {name}")
    for path, digest in record["code"].items():
        if checksum(ROOT / path) != digest:
            raise PermissionError(f"Frozen v6 code changed: {path}")
    return record


def protocol() -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    path = RUN / "protocol.json"
    if path.exists():
        raise FileExistsError("The 2026 protocol is registered and immutable")
    mu.verify_release(V5 / "release.json")
    verify_v6()
    dump_json(
        path,
        {
            "registered_utc": datetime.now(UTC).isoformat(),
            "synthetic": False,
            "labels_accessed": False,
            "test_period": [str(START.date()), str(END.date())],
            "excluded_target_days": EXCLUDED,
            "excluded_reason": "GIBS has no S-NPP layer on 2026-04-29 and 2026-07-11..15; a target day also needs the two previous days for the 48 h risk set",
            "models": {
                "v6": {
                    "release_sha256": checksum(V6 / "release.json"),
                    "threshold": json.loads((V6 / "frozen.json").read_text())["threshold"],
                },
                "v5": {
                    "release_sha256": checksum(V5 / "release.json"),
                    "threshold": json.loads((V5 / "frozen.json").read_text())["threshold"],
                },
            },
            "retraining_or_tuning_permitted": False,
            "labels": "NASA GIBS VIIRS_SNPP_Thermal_Anomalies_375m_All vector tiles, tile matrix 500m level 5, Kazakhstan bounding box 46-88E 40-56N; FIRMS NRT records (version 2.0NRT), confidence nominal/high for labels, all confidences for history features as in the frozen models; duplicates on tile seams removed by latitude, longitude and time",
            "label_source_check": "On seven 2025 days GIBS NRT contained 582 of 583 standard-archive fire cell-days and about 7% extra cell-days; both models are scored on the same labels",
            "deviation_from_2025_test": "NRT instead of standard processing, because FIRMS has not published a 2026 country archive and no API key is used",
            "events": "link_events, 2 km and 48 h, continuing from the 2025 standard archive; positive = first detection of a new event in an eligible cell",
            "risk_set": "2024 vegetated cover (MODIS 2025 is not published), finite terrain, frozen industrial exclusions, no nominal/high detection in the previous 48 h",
            "sampling": f"all positives; 300 negatives per day and region, seed {SEED}, inverse inclusion weights",
            "weather": "same Open-Meteo ERA5 0.25 degree source and daily equations, target minus 7 days",
            "vegetation": "same NOAA VIIRS NDVI weekly calendar and QA, target minus 12, maximum age 32 days",
            "metrics": [
                "precision and recall at each frozen threshold",
                "F1",
                "average precision",
                "ROC-AUC",
                "estimated daily capture in the top 0.1% and 1% of eligible cells",
            ],
            "uncertainty": "1000 paired 100 km x 30 day cluster bootstrap draws, seed 42, for precision, recall and v6 minus v5 differences",
            "interpretation": "One new temporal assessment of two frozen models; not a prospective as-issued trial or a spatial holdout",
        },
    )
    dump_json(RUN / "protocol.sha256.json", {"sha256": checksum(path)})
    log(f"protocol {checksum(path)}")


def check_protocol() -> dict:
    proof = json.loads((RUN / "protocol.sha256.json").read_text())
    if checksum(RUN / "protocol.json") != proof["sha256"]:
        raise PermissionError("2026 protocol changed")
    mu.verify_release(V5 / "release.json")
    verify_v6()
    return json.loads((RUN / "protocol.json").read_text())


def weather() -> None:
    """ERA5 2026 through END minus 7 days, with the original daily equations."""
    check_protocol()
    year, last = 2026, END - pd.Timedelta(days=7)
    path = pp.PUBLIC / f"weather/{year}.npz"
    if pp.complete(path):
        log("weather 2026: verified cache")
        return
    _, lon, lat = pp.geography()
    iy, ix = np.rint((lat + 90) / 0.25).astype(int), np.rint((lon + 180) / 0.25).astype(int)
    y0, y1, x0, x1 = int(iy.min()), int(iy.max()) + 1, int(ix.min()), int(ix.max()) + 1
    nday = (last - pd.Timestamp(f"{year}-01-01", tz="UTC")).days + 1
    names = ["tmax", "tmin", "temperature", "rh", "wind", "precip", "soil_moisture"]
    provenance: list[dict] = []
    variables = [
        "temperature_2m",
        "dew_point_2m",
        "wind_u_component_10m",
        "wind_v_component_10m",
        "precipitation",
        "soil_moisture_0_to_7cm",
    ]

    async def acquire() -> None:
        fs = pp.RangeCachedS3(
            anon=True,
            asynchronous=True,
            skip_instance_cache=True,
            config_kwargs={"max_pool_connections": 8},
        )
        readers = {}
        try:
            for v in variables:
                # One extra hour so the last day's precipitation includes its closing midnight.
                readers[v] = await pp.open_weather_series(
                    fs, v, year, provenance, stop_hour=nday * 24 + 1
                )
            for row in range(y0, y1):
                checkpoint = pp.PUBLIC / f"weather/rows_{year}/{row}.npz"
                if pp.complete(checkpoint):
                    continue
                used = ix[iy == row]
                if len(used) == 0:
                    pp.save_npz(
                        checkpoint,
                        **{n: np.full((x1 - x0, nday), np.nan, dtype="float32") for n in names},
                    )
                    continue
                left, right = int(used.min()), int(used.max()) + 1
                sel = (row, slice(left, right), slice(0, nday * 24 + 1))
                decoded = await asyncio.gather(*(readers[v].read_array(sel) for v in variables))
                t, dew, u, vv, rain, soil = [a.astype("float32", copy=False) for a in decoded]

                def daily(a: np.ndarray, op: str = "mean", width: int = right - left) -> np.ndarray:
                    return getattr(np, op)(
                        a[:, : nday * 24].reshape(width, nday, 24), axis=-1
                    ).astype("float32")

                rh = 100 * np.exp(17.625 * dew / (243.04 + dew) - 17.625 * t / (243.04 + t))
                values = {
                    "tmax": daily(t, "max"),
                    "tmin": daily(t, "min"),
                    "temperature": daily(t),
                    "rh": daily(np.clip(rh, 0, 100)),
                    "wind": daily(np.hypot(u, vv)),
                    "precip": daily(rain[:, 1:], "sum"),
                    "soil_moisture": daily(soil),
                }
                padded = {}
                for name, a in values.items():
                    padded[name] = np.full((x1 - x0, nday), np.nan, dtype="float32")
                    padded[name][left - x0 : right - x0] = a
                pp.save_npz(checkpoint, **padded)
                log(f"weather 2026: latitude {row - y0 + 1}/{y1 - y0}")
        finally:
            for reader in readers.values():
                reader.close()
            if fs._s3creator is not None:
                await fs._s3creator.__aexit__(None, None, None)

    asyncio.run(acquire())
    output = {n: np.full((y1 - y0, x1 - x0, nday), np.nan, dtype="float32") for n in names}
    for row in range(y0, y1):
        with np.load(pp.PUBLIC / f"weather/rows_{year}/{row}.npz") as chunk:
            for n in names:
                output[n][row - y0] = chunk[n]
    if np.nanmin(output["precip"]) < -1e-5:
        raise ValueError("Negative deaccumulated precipitation")
    pp.save_npz(
        path,
        **output,
        first_day=np.array(f"{year}-01-01"),
        native_cell_y=(iy - y0).astype("uint16"),
        native_cell_x=(ix - x0).astype("uint16"),
        y0=y0,
        x0=x0,
    )
    dump_json(
        path.with_suffix(".provenance.json"),
        {
            "sources": provenance,
            "provider": pp.SOURCES["weather"],
            "resolution_deg": 0.25,
            "weather_release_lag_days": 5,
            "partial_year_last_day": str(last.date()),
            "units": {
                "tmax": "C",
                "tmin": "C",
                "wind": "m/s",
                "rh": "%",
                "precip": "mm/calendar UTC day",
                "soil_moisture": "m3/m3",
            },
        },
    )
    log(f"weather 2026: {nday} days written")


def ndvi() -> None:
    check_protocol()
    days = [
        d.strftime("%Y-%m-%d")
        for d in pd.date_range("2014-11-01", str((END - pd.Timedelta(days=12)).date()), freq="7D")
        if d >= pd.Timestamp("2025-12-01")
    ]
    pp.permitted([2026], RELEASE)
    pp.parallel(pp.vegetation_day, days, 2)
    log(f"ndvi: {len(days)} weeks checked")


def predictors_ready() -> None:
    if not pp.complete(pp.PUBLIC / "weather/2026.npz"):
        raise FileNotFoundError("2026 weather incomplete; labels stay sealed")
    for d in pd.date_range("2014-11-01", str((END - pd.Timedelta(days=12)).date()), freq="7D"):
        if d >= pd.Timestamp("2025-12-01"):
            p = pp.PUBLIC / f"vegetation/{d:%Y-%m-%d}.npz"
            if not pp.complete(p) and not p.with_suffix(".unavailable.json").exists():
                raise FileNotFoundError(f"NDVI {d.date()} incomplete; labels stay sealed")


def normalise(points: pd.DataFrame) -> pd.DataFrame:
    """Same projection, cell join and fields as the FIRMS adapter, for NRT records."""
    import geopandas as gpd
    from pyproj import Transformer

    grid = pp.geography()[0]
    raw = points.copy()
    raw["timestamp"] = pd.to_datetime(
        raw.ACQ_DATE
        + "T"
        + raw.ACQ_TIME.str.replace(":", "").str.zfill(4).str[:2]
        + ":"
        + raw.ACQ_TIME.str.replace(":", "").str.zfill(4).str[2:]
        + ":00Z",
        utc=True,
    )
    raw["confidence"] = raw.CONFIDENCE.map({"nominal": "n", "high": "h", "low": "l"})
    if raw.confidence.isna().any():
        raise ValueError("Unexpected GIBS confidence value")
    transform = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
    raw["x"], raw["y_coord"] = transform.transform(
        raw.LONGITUDE.astype(float).to_numpy(), raw.LATITUDE.astype(float).to_numpy()
    )
    pts = gpd.GeoDataFrame(raw, geometry=gpd.points_from_xy(raw.x, raw.y_coord), crs=grid.crs)
    joined = gpd.sjoin(pts, grid[["cell_id", "geometry"]], predicate="intersects")
    joined = joined.reset_index().sort_values("cell_id").drop_duplicates("index")
    result = pd.DataFrame(joined[["cell_id", "timestamp", "x", "y_coord", "confidence"]])
    result["satellite"] = "N"
    result["product_version"] = joined.VERSION.astype(str).to_numpy()
    result["year"] = result.timestamp.dt.year
    return result.reset_index(drop=True)


def labels() -> pd.DataFrame:
    check_protocol()
    predictors_ready()
    events_path = RUN / "events.parquet"
    if events_path.exists():
        if (
            checksum(events_path)
            != json.loads(events_path.with_suffix(".sha256.json").read_text())["sha256"]
        ):
            raise ValueError("2026 labels changed")
        return pd.read_parquet(events_path)
    if not (RUN / "label_access.json").exists():
        dump_json(
            RUN / "label_access.json",
            {
                "first_access_utc": datetime.now(UTC).isoformat(),
                "protocol_sha256": checksum(RUN / "protocol.json"),
                "source": "NASA GIBS WMTS vector tiles",
            },
        )
    (RUN / "gibs").mkdir(exist_ok=True)
    from concurrent.futures import ThreadPoolExecutor

    keys = [
        str(d.date())
        for d in pd.date_range("2026-01-01", str(END.date()), tz="UTC")
        if str(d.date()) not in GIBS_GAPS
    ]

    def fetch(key: str) -> None:
        path = RUN / f"gibs/{key}.parquet"
        if path.exists():
            return
        raw = fetch_day(key, BBOX)
        raw = (
            raw.astype(str).drop_duplicates(["LATITUDE", "LONGITUDE", "ACQ_TIME"])
            if len(raw)
            else raw
        )
        temporary = path.with_suffix(".working")
        raw.to_parquet(temporary, index=False)
        temporary.replace(path)

    # Days are independent, so they download in parallel; each day is written atomically.
    with ThreadPoolExecutor(max_workers=8) as pool:
        for done, _ in enumerate(pool.map(fetch, keys), 1):
            if done % 30 == 0:
                log(f"gibs {done}/{len(keys)} days")
    frames = [pd.read_parquet(RUN / f"gibs/{key}.parquet") for key in keys]
    points = pd.concat([f for f in frames if len(f)], ignore_index=True)
    if not points.SATELLITE.isin(["N"]).all():
        raise ValueError("Only S-NPP points are permitted")
    detections = normalise(points)
    detections.to_parquet(RUN / "detections_2026.parquet", index=False)
    dump_json(
        RUN / "detections_2026.sha256.json",
        {"sha256": checksum(RUN / "detections_2026.parquet"), "points": len(points)},
    )
    previous = pd.read_parquet(independent.RUN / "detections_2025.parquet")
    linked = link_events(pd.concat([previous, detections], ignore_index=True))
    linked.to_parquet(events_path, index=False)
    dump_json(events_path.with_suffix(".sha256.json"), {"sha256": checksum(events_path)})
    return linked


def cover_override(year: int, release: Path | None = None) -> dict:
    # MODIS MCD12Q1 2025 is unpublished; the protocol fixes 2024 cover for 2026 targets.
    return study.cover_year(COVER_YEAR if year == 2025 else year, release)


def feature_frame(keys: pd.DataFrame) -> pd.DataFrame:
    env = dict(study.__dict__)
    env.update(
        permitted=independent.cached_guard,
        vegetation_features=independent.vegetation_features,
        cover_year=cover_override,
    )
    env["meteorology"] = FunctionType(
        study.meteorology.__code__, env, "meteorology", study.meteorology.__defaults__
    )
    adapted = FunctionType(
        study.feature_frame.__code__, env, "feature_frame", study.feature_frame.__defaults__
    )
    return adapted(keys, RELEASE)


class CellHistory:
    """v6's cell-level features, with the same windows and lag as development."""

    def __init__(self, history: pd.DataFrame, n_cells: int):
        epoch = pd.Timestamp("1970-01-01", tz="UTC")
        self.n = n_cells
        h = history.assign(day_no=(history.day - epoch).dt.days)
        self.active = {int(d): g.cell.to_numpy(dtype=np.int64) for d, g in h.groupby("day_no")}
        self.first = int(h.day_no.min())
        self.month_cell = {}
        cell_ids, gr, gc, shape = _grid()
        from scipy.ndimage import maximum_filter

        for y in range(2014, 2026):
            for m in range(1, 13):
                sel = h[(h.day.dt.year == y) & (h.day.dt.month == m)].cell.to_numpy(dtype=np.int64)
                v = np.zeros(n_cells, dtype=np.float32)
                v[np.unique(sel)] = 1
                img = np.zeros(shape, dtype=np.float32)
                img[gr, gc] = v
                self.month_cell[(y, m)] = (v, maximum_filter(img, size=3, mode="constant")[gr, gc])

    def features(self, keys: pd.DataFrame) -> dict[str, np.ndarray]:
        epoch = pd.Timestamp("1970-01-01", tz="UTC")
        target = (keys.day - epoch).dt.days.to_numpy()
        ci = keys.cell_index.to_numpy()
        out = {
            k: np.zeros(len(keys), dtype=np.float32)
            for k in [
                "cell_fire_30d",
                "cell_fire_365d",
                "cell_days_since_fire",
                "cell_month_climatology",
                "nbr15_month_climatology",
            ]
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
            date = epoch + pd.Timedelta(days=int(t))
            prior = [y for y in range(2014, 2026) if y < date.year]
            out["cell_month_climatology"][idx] = np.mean(
                [self.month_cell[(y, date.month)][0][cells] for y in prior], axis=0
            )
            out["nbr15_month_climatology"][idx] = np.mean(
                [self.month_cell[(y, date.month)][1][cells] for y in prior], axis=0
            )
        return out


def _grid():
    g = pd.read_parquet(ROOT / "data/real/normalized/grid_5km.parquet", columns=["cell_id"])
    parts = g.cell_id.str.split("_", expand=True)
    rows, cols = parts[1].astype(int).to_numpy(), parts[2].astype(int).to_numpy()
    return (
        g.cell_id,
        rows - rows.min(),
        cols - cols.min(),
        (rows.max() - rows.min() + 1, cols.max() - cols.min() + 1),
    )


def predict() -> None:
    check_protocol()
    events = labels()
    grid = pp.geography()[0]
    ids = pd.Index(grid.cell_id)
    n = len(ids)
    rows = list(
        struct.iter_unpack("<hhfffH8H", (ROOT / "platform/dist/assets/cells.bin").read_bytes())
    )
    region = pd.Series({f"g5000_{r[0]}_{r[1]}": r[5] for r in rows}).reindex(ids).to_numpy()
    cover = study.cover_year(COVER_YEAR, RELEASE)
    valid = np.isfinite(np.stack([cover[k] for k in study.COVER])).all(axis=0)
    with np.load(pp.PUBLIC / "terrain/national.npz") as terrain:
        valid &= np.isfinite(terrain["elevation"])
    valid &= ~ids.isin(json.loads((mu.OLD / "industrial_cells.json").read_text())["cell_ids"])

    # History features use all confidence categories, as the frozen models were trained.
    raw25 = pd.read_parquet(
        independent.RUN / "detections_2025.parquet", columns=["cell_id", "timestamp"]
    )
    raw26 = pd.read_parquet(RUN / "detections_2026.parquet", columns=["cell_id", "timestamp"])
    extra = pd.concat([raw25, raw26], ignore_index=True)
    extra["day"] = extra.timestamp.dt.floor("D")
    history_data = pd.concat(
        [mu.load_history(2024, V5 / "release.json"), extra[["cell_id", "day"]]], ignore_index=True
    ).drop_duplicates()
    fire_history = mu.FireHistory(history_data)
    cell_history = CellHistory(
        history_data.assign(cell=history_data.cell_id.map(pd.Series(np.arange(n), index=ids)))
        .dropna(subset=["cell"])
        .astype({"cell": np.int64}),
        n,
    )

    v5 = joblib.load(V5 / "model.joblib")
    v5_cal = joblib.load(V5 / "calibrator.joblib")
    v6 = joblib.load(V6 / "model.joblib")
    v6_cal = joblib.load(V6 / "calibrator.joblib")
    rng = np.random.default_rng(SEED)
    first = events[events.is_first].groupby("day").cell_id.apply(set).to_dict()
    recent_by_day = events.groupby("day").cell_id.apply(set).to_dict()
    (RUN / "months").mkdir(exist_ok=True)
    audit = []
    for month in range(START.month, END.month + 1):
        target = RUN / f"months/{month:02}.parquet"
        keys = []
        last_day = min(END, pd.Timestamp(f"2026-{month:02}-01", tz="UTC") + pd.offsets.MonthEnd(0))
        for day in pd.date_range(f"2026-{month:02}-01", str(last_day.date()), tz="UTC"):
            if str(day.date()) in EXCLUDED:
                continue
            recent = recent_by_day.get(day - pd.Timedelta(days=1), set()) | recent_by_day.get(
                day - pd.Timedelta(days=2), set()
            )
            eligible = valid & ~ids.isin(recent)
            positive = ids.isin(first.get(day, set())) & eligible
            for r in sorted(set(region)):
                neg = np.flatnonzero(eligible & ~positive & (region == r))
                pos = np.flatnonzero(positive & (region == r))
                count = min(300, len(neg))
                q = count / len(neg) if len(neg) else 1
                sampled = rng.choice(neg, count, replace=False)
                for ci, label, prob in [(pos, 1, 1.0), (sampled, 0, q)]:
                    if len(ci):
                        keys.append(
                            pd.DataFrame(
                                {
                                    "cell_index": ci,
                                    "day": day,
                                    "label": label,
                                    "q": prob,
                                    "weight": 1 / prob,
                                    "region": r,
                                }
                            )
                        )
                audit.append(
                    {
                        "day": str(day.date()),
                        "region": int(r),
                        "positive": len(pos),
                        "negative_population": len(neg),
                        "sampled_negatives": count,
                        "q": q,
                    }
                )
        if target.exists():
            log(f"2026 month {month}: cached")
            continue
        frame = feature_frame(pd.concat(keys, ignore_index=True))
        frame = mu.augment(frame, fire_history, V5 / "release.json")
        missing = ~frame.required_features_valid
        log(
            f"2026 month {month}: {len(frame)} rows, {int(missing.sum())} with missing mandatory inputs ({int(frame.loc[missing, 'label'].sum())} positives)"
        )
        frame = frame[~missing].reset_index(drop=True)
        for name, values in cell_history.features(frame).items():
            frame[name] = values
        raw5 = v5["estimator"].predict_proba(frame[v5["features"]])[:, 1]
        frame["p_v5"] = mu.published_probability(v5_cal.predict(raw5))
        raw6 = v6["estimator"].predict_proba(frame[v6["features"]])[:, 1]
        frame["p_v6"] = mu.published_probability(v6_cal.predict(raw6))
        keep = [
            "cell_id",
            "day",
            "label",
            "weight",
            "q",
            "x",
            "y_coord",
            "region",
            "ndvi_missing",
            "p_v5",
            "p_v6",
        ]
        frame[keep].to_parquet(target, index=False)
        dump_json(
            target.with_suffix(".sha256.json"),
            {"sha256": checksum(target), "excluded_missing_rows": int(missing.sum())},
        )
    pd.DataFrame(audit).to_csv(RUN / "sampling.csv", index=False)
    log("predict done")


def capture(frame: pd.DataFrame, score: np.ndarray) -> dict[str, float]:
    out = {}
    f = frame[["day", "label", "weight"]].assign(score=score)
    for name, share in {"top_0.1pct": 0.001, "top_1pct": 0.01}.items():
        hit = 0.0
        for _, g in f.groupby("day"):
            g = g.sort_values("score", ascending=False)
            inside = g.weight.cumsum().to_numpy() <= share * g.weight.sum()
            hit += g.label.to_numpy()[inside].sum()
        out[name] = float(hit / f.label.sum())
    return out


def evaluate() -> None:
    p = check_protocol()
    if (RUN / "evaluation.json").exists():
        raise FileExistsError("2026 evaluation completed; no retuning")
    frame = pd.concat(
        [pd.read_parquet(path) for path in sorted((RUN / "months").glob("*.parquet"))],
        ignore_index=True,
    )
    y, w = frame.label.to_numpy(), frame.weight.to_numpy()
    prevalence = np.full(
        len(frame),
        json.loads((V5 / "frozen.json").read_text())["original_2022_metrics"]["prevalence"],
    )
    result = {}
    for name in ["v6", "v5"]:
        score = frame[f"p_{name}"].to_numpy()
        result[name] = {
            **metrics(y, score, w, p["models"][name]["threshold"], prevalence),
            **capture(frame, score),
        }
    draws = cluster_draws(frame, 1000, 100000, 30, 42)
    codes = draws.codes
    boot = {}
    for name in ["v6", "v5"]:
        pred = frame[f"p_{name}"].to_numpy() >= p["models"][name]["threshold"]
        tp = draws.multiplicities @ np.bincount(codes, weights=w * y * pred)
        fp = draws.multiplicities @ np.bincount(codes, weights=w * (1 - y) * pred)
        pos = draws.multiplicities @ np.bincount(codes, weights=w * y)
        boot[name] = {"precision": tp / np.maximum(tp + fp, 1), "recall": tp / np.maximum(pos, 1)}
    ci = {
        m: {
            k: [float(v) for v in np.quantile(boot[m][k], [0.025, 0.975])]
            for k in ["precision", "recall"]
        }
        for m in boot
    }
    diff = {
        k: [float(v) for v in np.quantile(boot["v6"][k] - boot["v5"][k], [0.025, 0.975])]
        for k in ["precision", "recall"]
    }
    dump_json(
        RUN / "evaluation.json",
        {
            "synthetic": False,
            "protocol_sha256": checksum(RUN / "protocol.json"),
            "rows": len(frame),
            "positive_cell_days": int(y.sum()),
            "weighted_cell_days": float(w.sum()),
            "metrics": result,
            "confidence_intervals_95": ci,
            "paired_difference_v6_minus_v5_95": diff,
            "models_updated_after_test": False,
            "label_source": "GIBS NRT S-NPP",
        },
    )
    print(json.dumps({"metrics": result, "ci": ci, "diff": diff}, indent=1), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    commands = {
        "protocol": protocol,
        "weather": weather,
        "ndvi": ndvi,
        "labels": labels,
        "predict": predict,
        "evaluate": evaluate,
    }
    parser.add_argument("command", choices=list(commands))
    commands[parser.parse_args().command]()
